"""Regression coverage for realtime Responses/OpenCode streaming.

These tests fail against the pre-fix implementation because the HTTP response
headers and response.created event are not available until the buffered browser
turn has completed.
"""

from __future__ import annotations

import asyncio
import json
import unittest

from aiohttp.test_utils import TestClient, TestServer

from ChatGPTWeb.api import ChatStreamEvent, ChatStreamParser
from ChatGPTWeb.http_api import create_http_app
from ChatGPTWeb.service import ChatService


class _RealtimeBackend:
    def __init__(self) -> None:
        self.text_release = asyncio.Event()
        self.agent_release = asyncio.Event()
        self.buffered_calls = 0
        self.stream_calls = 0
        self.sent = []

    async def continue_chat(self, msg_data):
        self.buffered_calls += 1
        raise AssertionError("streamed OpenCode paths must not call buffered continue_chat")

    async def continue_chat_stream(self, msg_data):
        self.stream_calls += 1
        self.sent.append(msg_data)
        is_agent = "[Agent decision schema]" in msg_data.msg_send
        release = self.agent_release if is_agent else self.text_release
        yield ChatStreamEvent(
            type="status",
            metadata={"phase": "waiting_for_upstream"},
        )
        await release.wait()
        if is_agent:
            text = json.dumps({
                "type": "tool_call",
                "tool": "workspace.read_text",
                "arguments": {"path": "README.md"},
                "summary": "Read the requested file",
            })
        else:
            text = "hello from realtime stream"
        midpoint = max(1, len(text) // 2)
        yield ChatStreamEvent(type="delta", text=text[:midpoint], model="gpt-5-5-mini")
        yield ChatStreamEvent(type="delta", text=text[midpoint:], model="gpt-5-5-mini")
        yield ChatStreamEvent(
            type="final",
            text=text,
            conversation_id="conversation-realtime",
            message_id="message-realtime",
            model="gpt-5-5-mini",
            usage={"output_tokens": 3},
        )


async def _read_event_block(response) -> bytes:
    return await asyncio.wait_for(response.content.readuntil(b"\n\n"), timeout=1)


class RealtimeResponsesTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.backend = _RealtimeBackend()
        self.client = TestClient(TestServer(create_http_app(
            ChatService(self.backend),
            api_key="test-key",
        )))
        await self.client.start_server()
        self.headers = {"Authorization": "Bearer test-key"}

    async def asyncTearDown(self):
        backend = getattr(self, "backend", None)
        if backend is not None:
            backend.text_release.set()
            backend.agent_release.set()
        client = getattr(self, "client", None)
        if client is not None:
            await client.close()

    async def test_responses_created_arrives_before_text_backend_finishes(self):
        post = asyncio.create_task(self.client.post(
            "/v1/responses",
            json={"model": "gpt-5-5-mini", "input": "hello", "stream": True},
            headers=self.headers,
        ))
        response = await asyncio.wait_for(post, timeout=1)
        first = await _read_event_block(response)

        self.assertEqual(response.status, 200)
        self.assertEqual(response.headers.get("X-Accel-Buffering"), "no")
        self.assertIn(b"event: response.created", first)
        self.assertFalse(self.backend.text_release.is_set())
        self.assertEqual(self.backend.buffered_calls, 0)

        self.backend.text_release.set()
        body = first + await asyncio.wait_for(response.read(), timeout=2)
        self.assertIn(b"event: response.output_text.delta", body)
        self.assertIn(b"hello from realtime stream", body)
        self.assertIn(b"event: response.completed", body)
        self.assertEqual(self.backend.buffered_calls, 0)

    async def test_responses_agent_opens_stream_before_validated_tool_decision(self):
        post = asyncio.create_task(self.client.post(
            "/v1/responses",
            json={
                "model": "gpt-5-5-mini",
                "stream": True,
                "input": [{
                    "role": "user",
                    "content": [{"type": "input_text", "text": "Read README.md"}],
                }],
                "tools": [{
                    "type": "function",
                    "name": "workspace.read_text",
                    "description": "Read one workspace text file.",
                    "parameters": {
                        "type": "object",
                        "properties": {"path": {"type": "string"}},
                        "required": ["path"],
                    },
                }],
            },
            headers=self.headers,
        ))
        response = await asyncio.wait_for(post, timeout=1)
        first = await _read_event_block(response)

        self.assertIn(b"event: response.created", first)
        self.assertFalse(self.backend.agent_release.is_set())
        self.assertEqual(self.backend.buffered_calls, 0)

        self.backend.agent_release.set()
        body = first + await asyncio.wait_for(response.read(), timeout=2)
        self.assertIn(b"event: response.function_call_arguments.delta", body)
        self.assertIn(b'"name"', body)
        self.assertIn(b'workspace.read_text', body)
        self.assertIn(b"event: response.completed", body)
        self.assertEqual(self.backend.buffered_calls, 0)
        self.assertEqual(self.backend.stream_calls, 1)

    async def test_chat_completions_tool_stream_sends_headers_before_agent_finishes(self):
        post = asyncio.create_task(self.client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-5-5-mini",
                "stream": True,
                "messages": [{"role": "user", "content": "Read README.md"}],
                "tools": [{
                    "type": "function",
                    "function": {
                        "name": "workspace.read_text",
                        "description": "Read one workspace text file.",
                        "parameters": {
                            "type": "object",
                            "properties": {"path": {"type": "string"}},
                            "required": ["path"],
                        },
                    },
                }],
            },
            headers=self.headers,
        ))
        response = await asyncio.wait_for(post, timeout=1)
        first = await _read_event_block(response)

        self.assertEqual(response.headers.get("X-Accel-Buffering"), "no")
        self.assertIn(b'"role": "assistant"', first)
        self.assertFalse(self.backend.agent_release.is_set())

        self.backend.agent_release.set()
        body = first + await asyncio.wait_for(response.read(), timeout=2)
        self.assertIn(b'"tool_calls"', body)
        self.assertIn(b'"finish_reason": "tool_calls"', body)
        self.assertTrue(body.endswith(b"data: [DONE]\n\n"))
        self.assertEqual(self.backend.buffered_calls, 0)

    async def test_anonymous_internal_message_is_not_assistant_output(self):
        parser = ChatStreamParser()
        events = parser.feed({
            "message": {
                "id": "internal-title-node",
                "content": {"parts": ["问候交流"]},
            },
        })

        self.assertEqual(events, [])
        self.assertEqual(parser.text, "")
        self.assertEqual(parser.message_id, "")


if __name__ == "__main__":
    unittest.main()
