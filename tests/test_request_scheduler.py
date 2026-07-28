import asyncio
import tempfile
import unittest
from pathlib import Path

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
