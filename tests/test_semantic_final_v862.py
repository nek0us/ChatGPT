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
from ChatGPTWeb.capability_quota import IMAGE_GENERATION
from ChatGPTWeb.config import MsgData


class _Logger:
    def debug(self, *args, **kwargs):
        pass


class _FakePage:
    def __init__(self, payloads):
        self.payloads = payloads
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

        for payload in self.payloads:
            self.binding(None, payload)
        await self.release.wait()
        return {"ok": True}


class SemanticFinalV862Tests(unittest.IsolatedAsyncioTestCase):
    def runtime(self, page):
        runtime = object.__new__(chatgpt)
        runtime.logger = _Logger()

        async def resolve(msg_data, active_session):
            return None

        runtime._resolve_conversation_project = resolve
        runtime._build_conversation_payload = lambda msg_data: "{}"
        return runtime

    def session(self, page):
        return SimpleNamespace(
            page=page,
            email="test@example.com",
            access_token="token",
            device_id="device",
        )

    @staticmethod
    def semantic_payloads():
        text = (
            'data: {"conversation_id":"conv-1","message_id":"msg-1",'
            '"p":"/message/content/parts/0","o":"append","v":"Hello"}\n\n'
            'data: {"type":"message_stream_complete","conversation_id":"conv-1"}\n\n'
        )
        return [
            {
                "type": "meta",
                "url": "/conversation",
                "status": 200,
                "contentType": "text/event-stream",
            },
            {"type": "chunk", "text": text},
        ]

    async def test_semantic_text_final_skips_blocking_conversation_fetch(self):
        page = _FakePage(self.semantic_payloads())
        runtime = self.runtime(page)
        reconcile_calls = 0

        async def reconcile(active_session, event, settle=False):
            nonlocal reconcile_calls
            reconcile_calls += 1
            await asyncio.sleep(5)
            return event

        runtime._reconcile_stream_final = reconcile
        msg_data = MsgData(persist_history=False)

        async def collect():
            return [
                event
                async for event in runtime._stream_msg_by_browser_fetch(
                    msg_data,
                    self.session(page),
                )
            ]

        events = await asyncio.wait_for(collect(), timeout=1.0)
        self.assertEqual(reconcile_calls, 0)
        self.assertIn(True, page.cleanup_calls)
        final = next(event for event in events if event.type == "final")
        self.assertEqual(final.text, "Hello")
        self.assertTrue(final.metadata.get("semantic_stream_complete"))

    async def test_semantic_image_turn_keeps_conversation_reconciliation(self):
        page = _FakePage(self.semantic_payloads())
        runtime = self.runtime(page)
        reconcile_calls = 0

        async def reconcile(active_session, event, settle=False):
            nonlocal reconcile_calls
            reconcile_calls += 1
            self.assertTrue(settle)
            return event

        runtime._reconcile_stream_final = reconcile
        msg_data = MsgData(persist_history=False)
        msg_data.required_capabilities.append(IMAGE_GENERATION)

        events = [
            event
            async for event in runtime._stream_msg_by_browser_fetch(
                msg_data,
                self.session(page),
            )
        ]
        self.assertEqual(reconcile_calls, 1)
        self.assertTrue(any(event.type == "final" for event in events))

    async def test_ordinary_stream_end_still_uses_reconciliation(self):
        chunk = (
            'data: {"conversation_id":"conv-1","message_id":"msg-1",'
            '"p":"/message/content/parts/0","o":"append","v":"Hello"}\n\n'
        )
        page = _FakePage([
            {
                "type": "meta",
                "url": "/conversation",
                "status": 200,
                "contentType": "text/event-stream",
            },
            {"type": "chunk", "text": chunk},
            {"type": "done", "tail": ""},
        ])
        page.release.set()
        runtime = self.runtime(page)
        reconcile_calls = 0

        async def reconcile(active_session, event, settle=False):
            nonlocal reconcile_calls
            reconcile_calls += 1
            return event

        runtime._reconcile_stream_final = reconcile
        msg_data = MsgData(persist_history=False)
        events = [
            event
            async for event in runtime._stream_msg_by_browser_fetch(
                msg_data,
                self.session(page),
            )
        ]
        self.assertEqual(reconcile_calls, 1)
        self.assertTrue(any(event.type == "final" for event in events))


if __name__ == "__main__":
    unittest.main()
