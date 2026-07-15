import datetime
import tempfile
import unittest
from unittest.mock import AsyncMock, patch
from pathlib import Path

from ChatGPTWeb.api import Auth, classify_login_failure, login_failure_cooldown, restore_session_state, save_session_state
from ChatGPTWeb.config import LoginFailureKind, Session, Status
from ChatGPTWeb.storage import RuntimeStorage


class _Logger:
    def __init__(self):
        self.messages = []

    def debug(self, message):
        self.messages.append(message)

    def warning(self, message):
        self.messages.append(message)


class _NoopLogger:
    def warning(self, _message):
        pass


class LoginFailureClassificationTests(unittest.TestCase):
    def test_known_provider_failures_are_classified(self):
        cases = [
            ("Your account has been locked.", "microsoft", LoginFailureKind.AccountLocked.value),
            ("OpenAI account blocked: Your account has been deactivated.", "microsoft", LoginFailureKind.AccountLocked.value),
            ("Authentication Error: You do not have an account because it has been deleted or deactivated.", "microsoft", LoginFailureKind.AccountLocked.value),
            ("Incorrect password.", "microsoft", LoginFailureKind.BadCredentials.value),
            ("Help us protect your account with a security code.", "microsoft", LoginFailureKind.NeedVerification.value),
            ("Too many attempts, try again later.", "microsoft", LoginFailureKind.RateLimited.value),
            ("net::ERR_CONNECTION_RESET", "microsoft", LoginFailureKind.Transient.value),
            ("Page.goto: NS_ERROR_NET_INTERRUPT\nSecure Connection Failed", "microsoft", LoginFailureKind.Transient.value),
            ("Couldn't sign you in", "google", LoginFailureKind.RiskBlocked.value),
            ("This browser or app may not be secure", "google", LoginFailureKind.RiskBlocked.value),
            ("Verify it's you", "google", LoginFailureKind.NeedVerification.value),
            ("OpenAI login requires an email verification code", "openai", LoginFailureKind.NeedVerification.value),
            ("Check your inbox to continue", "openai", LoginFailureKind.NeedVerification.value),
            ("Locator.wait_for: Timeout 30000ms exceeded", "google", LoginFailureKind.Transient.value),
            ("Oops, an error occurred!\nOperation timed out", "openai", LoginFailureKind.Transient.value),
            ("url=https://accounts.google.com/v3/signin/identifier\nEmail or phone", "google", LoginFailureKind.Unknown.value),
        ]
        for details, mode, expected in cases:
            with self.subTest(details=details, mode=mode):
                self.assertEqual(classify_login_failure(details, mode), expected)

    def test_cooldowns_are_specific_to_temporary_failure_kind(self):
        self.assertEqual(login_failure_cooldown(LoginFailureKind.RateLimited.value), 1800)
        self.assertEqual(login_failure_cooldown(LoginFailureKind.RiskBlocked.value), 3600)
        self.assertEqual(login_failure_cooldown(LoginFailureKind.Transient.value), 300)
        self.assertEqual(login_failure_cooldown(LoginFailureKind.Unknown.value), 600)


class SessionLoginStateTests(unittest.TestCase):
    def test_permanent_failure_stops_account_without_retry_cooldown(self):
        session = Session(email="locked@example.com")

        session.mark_login_failure(
            kind=LoginFailureKind.AccountLocked.value,
            details="account locked",
            cooldown_seconds=600,
        )

        self.assertEqual(session.status, Status.Stop.value)
        self.assertTrue(session.is_login_disabled())
        self.assertIsNone(session.disabled_until)
        self.assertEqual(session.login_fail_count, 1)

    def test_temporary_failure_cools_down_then_success_resets_state(self):
        session = Session(email="limited@example.com")

        session.mark_login_failure(
            kind=LoginFailureKind.RateLimited.value,
            details="too many attempts",
            cooldown_seconds=login_failure_cooldown(LoginFailureKind.RateLimited.value),
        )

        self.assertEqual(session.status, Status.Update.value)
        self.assertTrue(session.is_login_disabled())
        self.assertIsNotNone(session.disabled_until)
        self.assertEqual(session.login_fail_count, 1)

        session.mark_login_success()

        self.assertEqual(session.status, Status.Ready.value)
        self.assertTrue(session.login_state)
        self.assertFalse(session.is_login_disabled())
        self.assertEqual(session.login_fail_count, 0)
        self.assertEqual(session.login_failure_kind, "")
        self.assertEqual(session.last_login_error, "")

    def test_unknown_failure_stops_after_configured_threshold(self):
        session = Session(email="flaky@example.com", max_login_failures=2)

        session.mark_login_failure(kind=LoginFailureKind.Unknown.value, cooldown_seconds=1)
        self.assertEqual(session.status, Status.Update.value)
        session.mark_login_failure(kind=LoginFailureKind.Unknown.value, cooldown_seconds=1)

        self.assertEqual(session.status, Status.Stop.value)
        self.assertTrue(session.is_login_disabled())

    def test_permanent_failure_is_not_overwritten_by_later_transient_error(self):
        session = Session(email="locked@example.com")
        session.mark_login_failure(kind=LoginFailureKind.AccountLocked.value, details="deactivated")

        session.mark_login_failure(kind=LoginFailureKind.Transient.value, details="browser timeout")

        self.assertEqual(session.status, Status.Stop.value)
        self.assertEqual(session.login_failure_kind, LoginFailureKind.AccountLocked.value)
        self.assertEqual(session.login_fail_count, 1)

    def test_stopped_account_remains_stopped_after_session_restore(self):
        session = Session(email="locked@example.com")
        session.mark_login_failure(kind=LoginFailureKind.AccountLocked.value, details="locked")
        logger = _NoopLogger()

        with tempfile.TemporaryDirectory() as directory:
            storage = RuntimeStorage(Path(directory))
            save_session_state(session, storage, logger)
            restored = restore_session_state(Session(email="locked@example.com"), storage, logger)
            persisted = storage.session_path("locked@example.com")

        self.assertEqual(restored.status, Status.Stop.value)
        self.assertEqual(restored.login_failure_kind, LoginFailureKind.AccountLocked.value)
        self.assertTrue(restored.is_login_disabled())
        self.assertEqual(persisted.suffix, ".json")
        self.assertNotIn("locked@example.com", persisted.name)

    def test_ready_state_is_not_restored_as_a_stale_runtime_state(self):
        session = Session(email="ready@example.com")
        session.mark_login_success()
        logger = _NoopLogger()

        with tempfile.TemporaryDirectory() as directory:
            storage = RuntimeStorage(Path(directory))
            save_session_state(session, storage, logger)
            restored = restore_session_state(Session(email="ready@example.com"), storage, logger)

        self.assertEqual(restored.status, "")
        self.assertFalse(restored.login_state)


class AuthStateIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_auth_records_locked_account_and_does_not_leave_it_retryable(self):
        session = Session(email="locked@example.com", password="not-a-real-password", mode="microsoft")
        logger = _Logger()
        auth = AsyncMock()
        auth.get_session_token.return_value = (None, None, "Your account has been locked.")

        with patch("ChatGPTWeb.api.AsyncAuth0", return_value=auth):
            await Auth(session, logger)

        self.assertEqual(session.status, Status.Stop.value)
        self.assertEqual(session.login_failure_kind, LoginFailureKind.AccountLocked.value)
        self.assertTrue(session.is_login_disabled())
        self.assertEqual(session.login_fail_count, 1)

    async def test_auth_success_resets_previous_failure_metadata(self):
        session = Session(email="ready@example.com", password="not-a-real-password")
        session.mark_login_failure(kind=LoginFailureKind.Transient.value, cooldown_seconds=300)
        session.disabled_until = datetime.datetime.now() - datetime.timedelta(seconds=1)
        logger = _Logger()
        auth = AsyncMock()
        auth.get_session_token.return_value = ({"name": "session"}, "access-token", "")

        with patch("ChatGPTWeb.api.AsyncAuth0", return_value=auth):
            await Auth(session, logger)

        self.assertEqual(session.status, Status.Ready.value)
        self.assertEqual(session.access_token, "access-token")
        self.assertEqual(session.login_fail_count, 0)
        self.assertFalse(session.is_login_disabled())

    async def test_auth_skips_provider_during_cooldown(self):
        session = Session(email="limited@example.com", password="not-a-real-password")
        session.mark_login_failure(kind=LoginFailureKind.RateLimited.value, cooldown_seconds=1800)
        logger = _Logger()
        auth = AsyncMock()

        with patch("ChatGPTWeb.api.AsyncAuth0", return_value=auth):
            await Auth(session, logger)

        auth.get_session_token.assert_not_awaited()
        self.assertEqual(session.status, Status.Update.value)
        self.assertTrue(session.is_login_disabled())

    async def test_google_timeout_uses_transient_cooldown_not_risk_cooldown(self):
        session = Session(email="google@example.com", password="not-a-real-password", mode="google")
        logger = _Logger()
        auth = AsyncMock()
        auth.get_session_token.return_value = (None, None, "Locator.wait_for: Timeout 30000ms exceeded")

        with patch("ChatGPTWeb.api.AsyncAuth0", return_value=auth):
            await Auth(session, logger)

        self.assertEqual(session.login_failure_kind, LoginFailureKind.Transient.value)
        self.assertEqual((session.disabled_until - datetime.datetime.now()).total_seconds() // 60, 4)


if __name__ == "__main__":
    unittest.main()
