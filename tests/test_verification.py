import asyncio
import unittest

from ChatGPTWeb.verification import (
    VerificationBroker,
    VerificationCancelledError,
    VerificationExpiredError,
)
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
