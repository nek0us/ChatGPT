import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from ChatGPTWeb.ChatGPTWeb import chatgpt
from ChatGPTWeb.config import MsgData, Personality
from ChatGPTWeb.storage import RuntimeStorage


def _storage_runtime(path: Path):
    runtime = chatgpt.__new__(chatgpt)
    runtime.storage = RuntimeStorage(path)
    runtime._conversation_locks = {}
    runtime._conversation_locks_guard = asyncio.Lock()
    return runtime


class HistoryStorageTests(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_saves_preserve_all_messages_and_map_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = _storage_runtime(Path(directory))
            messages = [
                MsgData(
                    conversation_id="conversation-1",
                    msg_send=f"question-{index}",
                    msg_recv=f"answer-{index}",
                    next_msg_id=f"message-{index}",
                    status=True,
                )
                for index in range(12)
            ]

            await asyncio.gather(*(runtime.save_chat(message, "account@example.com") for message in messages))
            history = await runtime.load_chat(MsgData(conversation_id="conversation-1"))
            index = json.loads(runtime.storage.index_path.read_text("utf8"))

        self.assertEqual(len(history["message"]), 12)
        self.assertEqual({item["input"] for item in history["message"]}, {message.msg_send for message in messages})
        self.assertEqual(index["version"], 2)
        self.assertEqual(index["conversations"]["conversation-1"]["account"], "account@example.com")
        self.assertTrue(runtime.storage.conversation_path("conversation-1").suffix == ".json")
        self.assertNotEqual(runtime.storage.conversation_path("conversation-1").name, "conversation-1")

    async def test_invalid_conversation_id_cannot_escape_history_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = _storage_runtime(root)
            message = MsgData(conversation_id="../outside", msg_send="question", msg_recv="answer", status=True)

            with self.assertRaises(ValueError):
                await runtime.save_chat(message, "account@example.com")

        self.assertFalse((root / "outside").exists())

    async def test_personas_use_the_shared_versioned_storage(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = _storage_runtime(Path(directory))
            runtime.personality = Personality()

            await runtime.add_personality({"name": "helper", "value": "Be concise."})

            self.assertEqual(runtime.storage.load_personas(), [{"name": "helper", "value": "Be concise."}])
            stored = json.loads(runtime.storage.personas_path.read_text("utf8"))

        self.assertEqual(stored["version"], 2)
