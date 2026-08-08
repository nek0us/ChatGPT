import asyncio
import tempfile
import time
import unittest
from pathlib import Path

from ChatGPTWeb.ChatGPTWeb import chatgpt
from ChatGPTWeb.config import MsgData, Session
from ChatGPTWeb.request_scheduler import RequestScheduler
from ChatGPTWeb.storage import RuntimeStorage


class RequestSchedulerTests(unittest.IsolatedAsyncioTestCase):
    async def test_higher_priority_waiter_runs_before_earlier_normal_waiter(self):
        scheduler = RequestScheduler(lambda: 1)
        first = await scheduler.acquire(priority=100, client_id="api:first", timeout_seconds=1)
        order: list[str] = []

        async def wait_for_lease(name: str, priority: int) -> None:
            lease = await scheduler.acquire(priority=priority, client_id=name, timeout_seconds=1)
            order.append(name)
            await lease.release()

        normal = asyncio.create_task(wait_for_lease("api:normal", 100))
        interactive = asyncio.create_task(wait_for_lease("bot", 10))
        await asyncio.sleep(0)
        await first.release()
        await asyncio.gather(normal, interactive)

        self.assertEqual(order, ["bot", "api:normal"])

    async def test_timeout_does_not_consume_a_future_slot(self):
        scheduler = RequestScheduler(lambda: 1)
        first = await scheduler.acquire(priority=100, client_id="api:first", timeout_seconds=1)
        with self.assertRaises(TimeoutError):
            await scheduler.acquire(priority=100, client_id="api:timed-out", timeout_seconds=0.01)
        await first.release()
        next_lease = await scheduler.acquire(priority=100, client_id="api:next", timeout_seconds=1)
        await next_lease.release()


class RequestAdmissionActivityTests(unittest.TestCase):
    def setUp(self):
        self.runtime = chatgpt.__new__(chatgpt)
        self.runtime._activity = []
        self.runtime.api_key_store = None

    @staticmethod
    def _request(wait_seconds: float) -> MsgData:
        return MsgData(
            msg_send="hello",
            client_id="api:test-key",
            request_queued_at=time.monotonic() - wait_seconds,
        )

    def test_fast_admission_removes_the_transient_queue_item(self):
        request = self._request(0.1)
        item = self.runtime._begin_request_admission(request)

        self.runtime._finish_request_admission(
            item,
            request,
            Session(email="fast@example.com"),
        )

        self.assertEqual(self.runtime._activity, [])
        self.assertLess(request.request_admission_ms, 1000)

    def test_pending_admission_does_not_present_account_hint_as_assignment(self):
        request = self._request(1.0)
        request.account_hint = "preferred@example.com"

        item = self.runtime._begin_request_admission(request)

        self.assertEqual(item["account"], "")
        self.assertEqual(item["details"]["requested_account"], "preferred@example.com")
        self.assertTrue(item["details"]["pending"])

    def test_slow_admission_keeps_wait_duration_and_assigned_account(self):
        request = self._request(2.0)
        item = self.runtime._begin_request_admission(request)

        self.runtime._finish_request_admission(
            item,
            request,
            Session(email="ready@example.com"),
        )

        self.assertEqual(len(self.runtime._activity), 1)
        self.assertEqual(item["event"], "chat_queued")
        self.assertEqual(item["account"], "ready@example.com")
        self.assertEqual(item["details"]["pending"], False)
        self.assertEqual(item["details"]["outcome"], "admitted")
        self.assertGreaterEqual(item["details"]["admission_ms"], 2000)

    def test_failed_slow_admission_remains_visible(self):
        request = self._request(1.5)
        item = self.runtime._begin_request_admission(request)

        self.runtime._finish_request_admission(
            item,
            request,
            None,
            outcome="request_queue_timeout",
        )

        self.assertEqual(len(self.runtime._activity), 1)
        self.assertEqual(item["account"], "")
        self.assertEqual(item["details"]["pending"], False)
        self.assertEqual(item["details"]["outcome"], "request_queue_timeout")


class ConversationClientOwnershipTests(unittest.TestCase):
    def test_index_retains_and_exposes_client_owner(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = RuntimeStorage(Path(directory))
            storage.update_conversation_index(
                "conversation-1", "account@example.com", "created", "updated", 1,
                client_id="api:key-one",
            )
            storage.update_conversation_index(
                "conversation-1", "account@example.com", "created", "later", 2,
            )
            self.assertEqual(storage.conversation_client_id("conversation-1"), "api:key-one")
            storage.bind_conversation_client("conversation-agent", "api:key-two", "account@example.com")
            self.assertTrue(storage.conversation_exists("conversation-agent"))
            self.assertEqual(storage.conversation_client_id("conversation-agent"), "api:key-two")
            self.assertFalse(storage.bind_conversation_client(
                "conversation-agent", "api:key-three", "account@example.com",
            ))
            self.assertEqual(storage.conversation_client_id("conversation-agent"), "api:key-two")


if __name__ == "__main__":
    unittest.main()
