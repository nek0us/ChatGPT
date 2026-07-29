import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from ChatGPTWeb.api import retry_keep_alive
from ChatGPTWeb.config import LoginFailureKind, Session, Status


class _Logger:
    def debug(self, _message):
        pass

    def warning(self, _message):
        pass

    def error(self, _message):
        pass


class _Expectation:
    def __init__(self, response):
        self.value = asyncio.get_running_loop().create_future()
        self.value.set_result(response)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False


class _ProbePage:
    def __init__(self, response=None, error=None):
        self._response = response
        self._error = error
        self.goto = AsyncMock(side_effect=error) if error else AsyncMock(return_value=response)
        self.close = AsyncMock()
        self.expect_response = self._expect_response

    def _expect_response(self, _url, timeout):
        self.timeout = timeout
        return _Expectation(self._response)


class SessionRefreshTests(unittest.IsolatedAsyncioTestCase):
    async def test_session_probe_waits_only_until_response_commit(self):
        response = type("Response", (), {"status": 302, "url": "https://chatgpt.com/api/auth/session"})()
        probe_page = _ProbePage(response=response)
        context = type("Context", (), {"new_page": AsyncMock(return_value=probe_page)})()
        session = Session(email="probe@example.com", page=object(), browser_contexts=context)

        await retry_keep_alive(
            session,
            "https://chatgpt.com/api/auth/session",
            storage=object(),
            js=(),
            js_num=0,
            save_screen_status=False,
            logger=_Logger(),
        )

        probe_page.goto.assert_awaited_once_with(
            "https://chatgpt.com/api/auth/session", timeout=40000, wait_until="commit"
        )
        probe_page.close.assert_awaited_once()

    async def test_exhausted_session_probe_requests_context_recovery(self):
        first = _ProbePage(error=TimeoutError("navigation stalled"))
        second = _ProbePage(error=TimeoutError("navigation stalled"))
        context = type("Context", (), {"new_page": AsyncMock(side_effect=[first, second])})()
        session = Session(email="probe@example.com", page=object(), browser_contexts=context)

        with patch("ChatGPTWeb.api.save_screen", new=AsyncMock()):
            await retry_keep_alive(
                session,
                "https://chatgpt.com/api/auth/session",
                storage=object(),
                js=(),
                js_num=0,
                save_screen_status=False,
                logger=_Logger(),
            )

        self.assertEqual(session.status, Status.Update.value)
        self.assertEqual(session.login_failure_kind, LoginFailureKind.Transient.value)
        self.assertTrue(session.session_refresh_recovery_needed)
        self.assertFalse(session.login_state)

