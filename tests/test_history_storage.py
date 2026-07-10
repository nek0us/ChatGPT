import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from ChatGPTWeb.ChatGPTWeb import chatgpt
from ChatGPTWeb.config import MsgData


def _storage_runtime(path: Path):
    runtime = chatgpt.__new__(chatgpt)
    runtime.chat_file = path
    runtime._conversation_locks = {}
    runtime._conversation_locks_guard = asyncio.Lock()
    runtime._conversation_map_lock = asyncio.Lock()
    runtime.set_chat_file()
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
            account_map = json.loads(runtime.cc_map.read_text("utf8"))

        self.assertEqual(len(history["message"]), 12)
        self.assertEqual({item["input"] for item in history["message"]}, {message.msg_send for message in messages})
        self.assertEqual(account_map["account@example.com"], ["conversation-1"])

    async def test_invalid_conversation_id_cannot_escape_history_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = _storage_runtime(root)
            message = MsgData(conversation_id="../outside", msg_send="question", msg_recv="answer", status=True)

            with self.assertRaises(ValueError):
                await runtime.save_chat(message, "account@example.com")

        self.assertFalse((root / "outside").exists())
