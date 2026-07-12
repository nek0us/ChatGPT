import asyncio
import unittest

from ChatGPTWeb.verification import (
    VerificationBroker,
    VerificationCancelledError,
    VerificationExpiredError,
)


class _ImmediateCodeProvider:
    name = "immediate-test"

    async def wait_for_code(self, _challenge):
        return "654321"


class _WaitingCodeProvider:
    name = "waiting-test"

    def __init__(self):
        self.cancelled = False
        self.release = asyncio.Event()

    async def wait_for_code(self, _challenge):
        try:
            await self.release.wait()
            return None
        except asyncio.CancelledError:
            self.cancelled = True
            raise
from ChatGPTWeb.OpenAIAuth import AsyncAuth0


class _Logger:
    def info(self, _message):
        pass


class _OtpInput:
    async def count(self):
        return 1

    async def fill(self, value):
        self.value = value


class _Keyboard:
    def __init__(self):
        self.presses = []

    async def press(self, value):
        self.presses.append(value)


class _OtpPage:
    def __init__(self):
        self.otp = _OtpInput()
        self.keyboard = _Keyboard()

    def locator(self, selector):
        if selector == "input[autocomplete='one-time-code']":
            return self.otp
        raise AssertionError(f"unexpected selector: {selector}")


class _MissingInput:
    async def count(self):
        return 0


class _MicrosoftOtpPage:
    def __init__(self):
        self.inputs = [_OtpInput() for _ in range(6)]
        self.keyboard = _Keyboard()

    def locator(self, selector):
        if selector.startswith('input[id="codeEntry-') and selector.endswith('"]'):
            index = int(selector.removeprefix('input[id="codeEntry-').removesuffix('"]'))
            return self.inputs[index] if index < len(self.inputs) else _MissingInput()
        if selector in (
            'input[aria-label="Enter your security code"]',
            "input[aria-label='New password']",
        ):
            return _MissingInput()
        raise AssertionError(f"unexpected selector: {selector}")

    async def wait_for_load_state(self):
        pass

    async def wait_for_timeout(self, _milliseconds):
        pass


class VerificationBrokerTests(unittest.IsolatedAsyncioTestCase):
    async def _pending_challenge(self, broker: VerificationBroker, account: str = "account@example.com"):
        task = asyncio.create_task(broker.request_code(account, "openai", timeout_seconds=1))
        for _ in range(10):
            snapshot = await broker.snapshot()
            if snapshot:
                return task, snapshot[0]
            await asyncio.sleep(0)
        self.fail("verification challenge was not registered")

    async def test_submitted_code_unblocks_waiter_without_leaking_into_snapshot(self):
        broker = VerificationBroker()
        task, challenge = await self._pending_challenge(broker)

        self.assertTrue(await broker.submit(challenge["id"], "12 34 56"))
        self.assertEqual(await task, "123456")
        self.assertEqual(await broker.snapshot(), [])
        self.assertNotIn("123456", str(challenge))

    async def test_provider_can_submit_a_code_without_persisting_it(self):
        broker = VerificationBroker(code_providers=[_ImmediateCodeProvider()])

        code = await broker.request_code("account@example.com", "openai")

        self.assertEqual(code, "654321")
        self.assertEqual(await broker.snapshot(), [])

    async def test_manual_submission_cancels_a_waiting_provider(self):
        provider = _WaitingCodeProvider()
        broker = VerificationBroker(code_providers=[provider])
        task, challenge = await self._pending_challenge(broker)
        for _ in range(10):
            snapshot = await broker.snapshot()
            if snapshot[0]["automation"]:
                break
            await asyncio.sleep(0)
        else:
            self.fail("provider did not start for the verification challenge")

        self.assertEqual(snapshot[0]["automation"][0]["provider"], "waiting-test")
        self.assertEqual(snapshot[0]["automation"][0]["state"], "waiting")
        self.assertTrue(await broker.submit(challenge["id"], "123456"))
        self.assertEqual(await task, "123456")
        self.assertTrue(provider.cancelled)

    async def test_cancel_unblocks_waiter_and_removes_challenge(self):
        broker = VerificationBroker()
        task, challenge = await self._pending_challenge(broker)

        self.assertTrue(await broker.cancel(challenge["id"]))
        with self.assertRaises(VerificationCancelledError):
            await task
        self.assertEqual(await broker.snapshot(), [])

    async def test_expired_challenge_is_removed(self):
        broker = VerificationBroker()

        with self.assertRaises(VerificationExpiredError):
            await broker.request_code("account@example.com", "openai", timeout_seconds=0.01)
        self.assertEqual(await broker.snapshot(), [])

    async def test_rejects_invalid_codes_and_stale_challenge_ids(self):
        broker = VerificationBroker()
        task, challenge = await self._pending_challenge(broker)

        with self.assertRaises(ValueError):
            await broker.submit(challenge["id"], "abc")
        self.assertFalse(await broker.submit("missing", "123456"))
        await broker.cancel(challenge["id"])
        with self.assertRaises(VerificationCancelledError):
            await task

    async def test_openai_auth_fills_code_submitted_through_broker(self):
        broker = VerificationBroker()
        page = _OtpPage()
        auth = AsyncAuth0(
            "account@example.com",
            "password",
            page,
            _Logger(),
            browser_contexts=None,
            verification_broker=broker,
        )
        auth.login_page = page
        task = asyncio.create_task(auth._submit_openai_verification_code())
        for _ in range(10):
            snapshot = await broker.snapshot()
            if snapshot:
                break
            await asyncio.sleep(0)
        else:
            self.fail("OpenAI auth did not request verification")

        self.assertTrue(await broker.submit(snapshot[0]["id"], "123456"))
        await task
        self.assertEqual(page.otp.value, "123456")
        self.assertEqual(page.keyboard.presses, ["Enter"])

    async def test_microsoft_auth_fills_broker_code_without_a_local_file(self):
        broker = VerificationBroker()
        page = _MicrosoftOtpPage()
        auth = AsyncAuth0(
            "account@example.com",
            "password",
            page,
            _Logger(),
            browser_contexts=None,
            mode="microsoft",
            verification_broker=broker,
        )
        auth.login_page = page
        task = asyncio.create_task(auth._submit_microsoft_help_email_code())
        for _ in range(10):
            snapshot = await broker.snapshot()
            if snapshot:
                break
            await asyncio.sleep(0)
        else:
            self.fail("Microsoft auth did not request verification")

        self.assertEqual(snapshot[0]["provider"], "microsoft")
        self.assertEqual(snapshot[0]["kind"], "help_email_otp")
        self.assertTrue(await broker.submit(snapshot[0]["id"], "123456"))
        await task

        self.assertEqual([field.value for field in page.inputs], list("123456"))
        self.assertEqual(page.keyboard.presses, ["Enter"])
