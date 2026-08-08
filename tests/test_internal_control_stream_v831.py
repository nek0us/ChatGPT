from __future__ import annotations

import unittest

from ChatGPTWeb.agent import AgentService
from ChatGPTWeb.api import ChatStreamEvent
from ChatGPTWeb.service import ChatRequest, ChatService


class _PlannerBackend:
    def __init__(self):
        self.buffered_calls = 0
        self.stream_calls = 0

    async def continue_chat(self, msg_data):
        self.buffered_calls += 1
        raise AssertionError("planner must keep the streaming backend transport")

    async def continue_chat_stream(self, msg_data):
        self.stream_calls += 1
        yield ChatStreamEvent(type="status", metadata={"phase": "planner"})
        yield ChatStreamEvent(
            type="delta",
            text='{"type":"final","answer":"wrong-prefix',
        )
        yield ChatStreamEvent(
            type="reconcile",
            text='{"type":"final","answer":"different-snapshot"}',
            metadata={"stream_replacement": True},
        )
        yield ChatStreamEvent(
            type="final",
            text='{"type":"final","answer":"canonical"}',
            conversation_id="planner-conversation",
            message_id="planner-message",
            model="gpt-5-5-mini",
        )


class InternalControlStreamV831Tests(unittest.IsolatedAsyncioTestCase):
    async def test_service_uses_only_planner_canonical_final(self):
        backend = _PlannerBackend()
        service = ChatService(backend)
        observed = []

        async def callback(event):
            observed.append((event.type, event.text))

        result = await service.stream_to_callback(
            ChatRequest(
                prompt="planner",
                internal_control_stream=True,
            ),
            callback,
        )

        self.assertTrue(result.ok)
        self.assertEqual(
            result.text,
            '{"type":"final","answer":"canonical"}',
        )
        self.assertEqual(
            observed,
            [
                ("status", ""),
                ("final", '{"type":"final","answer":"canonical"}'),
            ],
        )
        self.assertEqual(backend.buffered_calls, 0)
        self.assertEqual(backend.stream_calls, 1)

    async def test_agent_marks_primary_planner_as_internal_control(self):
        class FakeService:
            def __init__(self):
                self.sent = []
                self.streamed = []

            async def send(self, request):
                self.sent.append(request)
                raise AssertionError("primary planner must not use buffered send")

            async def stream_to_callback(self, request, callback):
                self.streamed.append(request)
                return object()

        service = FakeService()
        attempts = []

        async def callback(event):
            return None

        async def begin_attempt(attempt):
            attempts.append(attempt)

        agent = AgentService(
            service,
            stream_callback=callback,
            stream_attempt_callback=begin_attempt,
        )
        result = await agent._send_request(
            ChatRequest(prompt="planner"),
            stream_attempt="primary",
        )

        self.assertIsNotNone(result)
        self.assertEqual(service.sent, [])
        self.assertEqual(len(service.streamed), 1)
        self.assertTrue(service.streamed[0].internal_control_stream)
        self.assertEqual(attempts, ["primary"])
