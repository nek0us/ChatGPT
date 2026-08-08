from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace

from aiohttp import web

if not hasattr(web, "RequestKey"):
    class _RequestKey:
        def __init__(self, name, type_):
            self.name = name
            self.type = type_

        @classmethod
        def __class_getitem__(cls, item):
            return cls

    web.RequestKey = _RequestKey

from ChatGPTWeb.ChatGPTWeb import chatgpt
from ChatGPTWeb.api import ChatStreamDecoder
from ChatGPTWeb.config import MsgData


class StreamCompletionDecoderV861Tests(unittest.TestCase):
    def test_message_stream_complete_sets_semantic_completion(self):
        decoder = ChatStreamDecoder()
        events = decoder.feed(
            'data: {"type":"message_stream_complete","conversation_id":"conv-1"}\n\n'
        )
        self.assertEqual(events, [])
        self.assertTrue(decoder.semantic_complete)
        self.assertFalse(decoder.done)

    def test_fragmented_terminal_event_is_detected_only_after_full_sse_block(self):
        decoder = ChatStreamDecoder()
        decoder.feed('data: {"type":"message_stream_')
        self.assertFalse(decoder.semantic_complete)
        decoder.feed('complete","conversation_id":"conv-1"}\n\n')
        self.assertTrue(decoder.semantic_complete)

    def test_done_marker_is_also_semantic_completion(self):
        decoder = ChatStreamDecoder()
        decoder.feed('data: [DONE]\n\n')
        self.assertTrue(decoder.done)
        self.assertTrue(decoder.semantic_complete)


class _Logger:
    def debug(self, *args, **kwargs):
        pass


class _FakePage:
    def __init__(self, stream_text: str):
        self.stream_text = stream_text
        self.binding = None
        self.cleanup_calls = []
        self.release = asyncio.Event()

    async def expose_binding(self, name, callback):
        self.binding = callback

    async def evaluate(self, script, options):
        if isinstance(options, dict) and "abort" in options:
            self.cleanup_calls.append(options["abort"])
            self.release.set()
            return True

        self.binding(
            None,
            {
                "type": "meta",
                "url": "/conversation",
                "status": 200,
                "contentType": "text/event-stream",
            },
        )
        self.binding(None, {"type": "chunk", "text": self.stream_text})
        await self.release.wait()
        return {"ok": True}


class BrowserStreamCompletionIntegrationV861Tests(unittest.IsolatedAsyncioTestCase):
    async def test_semantic_completion_ends_without_waiting_for_http_eof(self):
        stream_text = (
            'data: {"conversation_id":"conv-1","message_id":"msg-1",'
            '"p":"/message/content/parts/0","o":"append","v":"Hello"}\n\n'
            'data: {"type":"message_stream_complete","conversation_id":"conv-1"}\n\n'
        )
        page = _FakePage(stream_text)
        session = SimpleNamespace(
            page=page,
            email="test@example.com",
            access_token="token",
            device_id="device",
        )
        instance = object.__new__(chatgpt)
        instance.logger = _Logger()

        async def resolve(msg_data, active_session):
            return None

        async def reconcile(active_session, event, settle=False):
            return event

        instance._resolve_conversation_project = resolve
        instance._build_conversation_payload = lambda msg_data: "{}"
        instance._reconcile_stream_final = reconcile

        msg_data = MsgData(persist_history=False)

        async def collect():
            return [
                event
                async for event in instance._stream_msg_by_browser_fetch(
                    msg_data,
                    session,
                )
            ]

        events = await asyncio.wait_for(collect(), timeout=1.0)
        self.assertIn(True, page.cleanup_calls)
        self.assertEqual(
            [event.text for event in events if event.type == "delta"],
            ["Hello"],
        )
        final = next(event for event in events if event.type == "final")
        self.assertEqual(final.text, "Hello")
        self.assertEqual(final.conversation_id, "conv-1")


if __name__ == "__main__":
    unittest.main()
