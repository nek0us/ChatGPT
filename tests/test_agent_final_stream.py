"""v5 coverage for planner-isolated OpenAI tool streaming.

OpenAI-compatible routes never expose Agent protocol JSON.  A validated
``tool_call`` is emitted only after schema validation.  A validated ``final``
decision starts a fresh ordinary chat turn from the original user task, whose
plain text is streamed directly to the client.
"""

from __future__ import annotations

import asyncio
import json
import unittest

from aiohttp.test_utils import TestClient, TestServer

from ChatGPTWeb.agent import AgentAnchorPolicy, AgentSafetyPolicy
from ChatGPTWeb.api import ChatStreamEvent
from ChatGPTWeb.http_api import create_http_app
from ChatGPTWeb.service import ChatService


LONG_ANSWER = "\n\n".join(
    f"【第{index}段】" + (f"这是用于验证完整用户答案的第{index}段内容。" * 5)
    for index in range(1, 11)
)
PLANNER_NOTE = "planner-only-note-that-must-never-be-visible"
ANCHOR_NOTE = "anchor-ready-that-must-never-be-visible"


async def _next_sse_block(response, timeout: float = 3.0) -> bytes:
    return await asyncio.wait_for(response.content.readuntil(b"\n\n"), timeout=timeout)


def _event_payload(block: bytes) -> tuple[str, object | None]:
    event = ""
    data = None
    for raw_line in block.decode("utf-8").splitlines():
        if raw_line.startswith("event: "):
            event = raw_line[7:]
        elif raw_line.startswith("data: "):
            value = raw_line[6:]
            data = value if value == "[DONE]" else json.loads(value)
    return event, data


def _agent_json(answer: str) -> str:
    return json.dumps(
        {"type": "final", "answer": answer},
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _response_deltas(body: bytes) -> tuple[str, str]:
    deltas: list[str] = []
    terminal = ""
    for part in [item + b"\n\n" for item in body.split(b"\n\n") if item]:
        event, payload = _event_payload(part)
        if event == "response.output_text.delta" and isinstance(payload, dict):
            deltas.append(str(payload.get("delta") or ""))
        if event in {"response.completed", "response.failed"}:
            terminal = event
    return "".join(deltas), terminal


def _response_function_call(body: bytes) -> dict[str, object]:
    for part in [item + b"\n\n" for item in body.split(b"\n\n") if item]:
        event, payload = _event_payload(part)
        if event != "response.output_item.done" or not isinstance(payload, dict):
            continue
        item = payload.get("item")
        if isinstance(item, dict) and item.get("type") == "function_call":
            return item
    raise AssertionError("response did not contain a function call")


def _chat_deltas(body: bytes) -> str:
    output: list[str] = []
    for part in [item + b"\n\n" for item in body.split(b"\n\n") if item]:
        _, payload = _event_payload(part)
        if not isinstance(payload, dict):
            continue
        choices = payload.get("choices") or []
        if not choices or not isinstance(choices[0], dict):
            continue
        delta = choices[0].get("delta") or {}
        if isinstance(delta, dict) and delta.get("content"):
            output.append(str(delta["content"]))
    return "".join(output)


class _PlannerRenderBackend:
    def __init__(self) -> None:
        self.buffered_calls = 0
        self.planner_calls = 0
        self.render_calls = 0
        self.prompts: list[str] = []
        self.render_requests = []
        self.planner_requests = []
        self.hold_render = False
        self.fail_render_stream = False
        self.render_started = asyncio.Event()
        self.release_render = asyncio.Event()

    async def continue_chat(self, msg_data):
        self.buffered_calls += 1
        prompt = msg_data.msg_send
        self.prompts.append(prompt)
        if "[Agent decision schema]" not in prompt:
            msg_data.status = True
            msg_data.msg_recv = LONG_ANSWER
            msg_data.conversation_id = "render-buffered-conversation"
            msg_data.next_msg_id = "render-buffered-message"
            msg_data.model_used = "gpt-5-5-mini"
            return msg_data
        if "Static protocol root" not in prompt:
            raise AssertionError(f"unexpected buffered request: {prompt[:120]}")
        msg_data.status = True
        msg_data.msg_recv = _agent_json(ANCHOR_NOTE)
        msg_data.conversation_id = "anchor-conversation"
        msg_data.next_msg_id = "anchor-message"
        msg_data.model_used = "gpt-5-5-mini"
        return msg_data

    async def continue_chat_stream(self, msg_data):
        prompt = msg_data.msg_send
        self.prompts.append(prompt)

        if "[Agent decision schema]" not in prompt:
            self.render_calls += 1
            self.render_requests.append(msg_data)
            self.render_started.set()
            if self.fail_render_stream:
                yield ChatStreamEvent(
                    type="error",
                    text="upstream stream failed before text",
                    model="gpt-5-5-mini",
                )
                return
            if "Replacement snapshot" in prompt:
                yield ChatStreamEvent(type="delta", text="stable streamed answer", model="gpt-5-5-mini")
                yield ChatStreamEvent(
                    type="final",
                    text="different reconciled snapshot",
                    conversation_id="render-replacement",
                    message_id="render-replacement-message",
                    model="gpt-5-5-mini",
                )
                return
            split = max(1, len(LONG_ANSWER) // 3)
            yield ChatStreamEvent(type="delta", text=LONG_ANSWER[:split], model="gpt-5-5-mini")
            if self.hold_render:
                await self.release_render.wait()
            yield ChatStreamEvent(type="delta", text=LONG_ANSWER[split:], model="gpt-5-5-mini")
            yield ChatStreamEvent(
                type="final",
                text=LONG_ANSWER,
                conversation_id="render-conversation",
                message_id="render-message",
                model="gpt-5-5-mini",
            )
            return

        self.planner_calls += 1
        self.planner_requests.append(msg_data)
        if "The host has executed the previous tool call" in prompt:
            full = _agent_json("tool result verified")
        elif "A final answer is forbidden in this turn" in prompt:
            full = json.dumps({
                "type": "tool_call",
                "tool": "workspace.read_text",
                "arguments": {"path": "Downloads/requirements.txt"},
                "summary": "Read the requested file",
            }, ensure_ascii=False, separators=(",", ":"))
        elif "Your previous response was not a valid agent decision" in prompt:
            full = _agent_json("repaired-planner-note")
        elif "Read README.md" in prompt:
            full = json.dumps({
                "type": "tool_call",
                "tool": "workspace.read_text",
                "arguments": {"path": "README.md"},
                "summary": "Read it",
            }, ensure_ascii=False, separators=(",", ":"))
        elif "Repair before answer" in prompt:
            full = '{"type":"bogus"}'
        else:
            full = _agent_json(PLANNER_NOTE)

        midpoint = max(1, len(full) // 2)
        yield ChatStreamEvent(type="status", metadata={"phase": "planner"})
        yield ChatStreamEvent(type="delta", text=full[:midpoint], model="gpt-5-5-mini")
        yield ChatStreamEvent(type="delta", text=full[midpoint:], model="gpt-5-5-mini")
        yield ChatStreamEvent(
            type="final",
            text=full,
            conversation_id=f"planner-conversation-{self.planner_calls}",
            message_id=f"planner-message-{self.planner_calls}",
            model="gpt-5-5-mini",
        )


class PlannerIsolatedAgentHTTPTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.backend = _PlannerRenderBackend()
        app = create_http_app(
            ChatService(self.backend),
            api_key="test-key",
            agent_safety_policy=AgentSafetyPolicy(enabled=False),
            agent_anchor_policy=AgentAnchorPolicy(enabled=False),
        )
        self.client = TestClient(TestServer(app))
        await self.client.start_server()
        self.headers = {"Authorization": "Bearer test-key"}
        self.tool = {
            "type": "function",
            "name": "workspace.read_text",
            "description": "Read one text file.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
                "additionalProperties": False,
            },
        }

    async def asyncTearDown(self):
        self.backend.release_render.set()
        await self.client.close()

    async def _responses_request(self, prompt: str):
        response = await self.client.post(
            "/v1/responses",
            json={
                "model": "gpt-5-5-mini",
                "stream": True,
                "input": prompt,
                "tools": [self.tool],
            },
            headers=self.headers,
        )
        self.assertEqual(response.status, 200)
        return response

    async def test_responses_direct_answer_streams_before_completion(self):
        self.backend.hold_render = True
        response = await self._responses_request("Long exact answer")
        deltas: list[str] = []
        while not deltas:
            event, payload = _event_payload(await _next_sse_block(response))
            if event == "response.output_text.delta" and isinstance(payload, dict):
                deltas.append(str(payload.get("delta") or ""))
        self.assertTrue(self.backend.render_started.is_set())
        self.assertFalse(self.backend.release_render.is_set())
        self.assertTrue("".join(deltas).startswith("【第1段】"))
        self.backend.release_render.set()
        remaining = await asyncio.wait_for(response.read(), timeout=3)
        text, terminal = _response_deltas(remaining)
        deltas.append(text)
        joined = "".join(deltas)
        self.assertEqual(joined, LONG_ANSWER)
        self.assertEqual(terminal, "response.completed")
        self.assertNotIn(PLANNER_NOTE, joined)
        self.assertEqual(self.backend.planner_calls, 1)
        self.assertEqual(self.backend.render_calls, 1)

    async def test_responses_recovers_visible_answer_when_render_stream_fails_early(self):
        self.backend.fail_render_stream = True
        response = await self._responses_request("Recover from an early render stream failure")
        body = await asyncio.wait_for(response.read(), timeout=3)

        text, terminal = _response_deltas(body)
        self.assertEqual(text, LONG_ANSWER)
        self.assertEqual(terminal, "response.completed")
        self.assertEqual(self.backend.render_calls, 1)
        self.assertEqual(self.backend.buffered_calls, 1)

    async def test_opencode_session_reuses_presentation_conversation_for_tool_turns(self):
        headers = {
            **self.headers,
            "User-Agent": "opencode/1.18.15 ai-sdk/provider-utils/4.0.38",
            "X-Session-Id": "ses_agent_presentation",
        }
        first = await self.client.post(
            "/v1/responses",
            json={
                "model": "gpt-5-5-mini",
                "stream": True,
                "input": [{
                    "role": "user",
                    "content": [{"type": "input_text", "text": "解析滕王阁序"}],
                }],
                "tools": [self.tool],
            },
            headers=headers,
        )
        await first.read()
        second = await self.client.post(
            "/v1/responses",
            json={
                "model": "gpt-5-5-mini",
                "stream": True,
                "instructions": "[Agent decision schema] host-only protocol",
                "input": [
                    {"role": "user", "content": [{"type": "input_text", "text": "解析滕王阁序"}]},
                    {"role": "assistant", "content": [{"type": "output_text", "text": LONG_ANSWER}]},
                    {"role": "user", "content": [{"type": "input_text", "text": "再解析下赤壁赋"}]},
                ],
                "tools": [self.tool],
            },
            headers=headers,
        )
        await second.read()

        self.assertEqual(first.status, 200)
        self.assertEqual(second.status, 200)
        self.assertEqual(self.backend.planner_calls, 0)
        self.assertEqual(len(self.backend.render_requests), 2)
        self.assertEqual(self.backend.render_requests[1].conversation_id, "render-conversation")
        self.assertIn("再解析下赤壁赋", self.backend.render_requests[1].msg_send)
        self.assertNotIn("解析滕王阁序", self.backend.render_requests[1].msg_send)
        planner_prompts = [
            prompt for prompt in self.backend.prompts
            if not prompt.startswith("Answer the user's request directly as the user-facing assistant.")
        ]
        self.assertEqual(len(planner_prompts), 2)
        self.assertIn("再解析下赤壁赋", planner_prompts[-1])
        self.assertNotIn("解析滕王阁序", planner_prompts[-1])
        self.assertNotIn(self.tool["description"], planner_prompts[-1])

    async def test_opencode_knowledge_turns_bypass_planner_and_keep_latest_input(self):
        headers = {
            **self.headers,
            "User-Agent": "opencode/1.18.15 ai-sdk/provider-utils/4.0.38",
            "X-Session-Id": "ses_knowledge_direct",
        }
        title = await self.client.post(
            "/v1/responses",
            json={
                "model": "gpt-5-5-mini",
                "stream": True,
                "input": [
                    {
                        "role": "system",
                        "content": "You are a title generator. You output ONLY a thread title.",
                    },
                    {
                        "role": "user",
                        "content": "Generate a title for this conversation:\n",
                    },
                    {
                        "role": "user",
                        "content": "Explain the literary passage one.",
                    },
                ],
            },
            headers=headers,
        )
        await title.read()
        first = await self.client.post(
            "/v1/responses",
            json={
                "model": "gpt-5-5-mini",
                "stream": True,
                "instructions": "[Agent decision schema] host-only protocol",
                "input": [
                    {"role": "developer", "content": [{"type": "input_text", "text": "large host instructions"}]},
                    {"role": "user", "content": [{"type": "input_text", "text": "Explain the literary passage one."}]},
                ],
                "tools": [self.tool],
            },
            headers=headers,
        )
        await first.read()
        second = await self.client.post(
            "/v1/responses",
            json={
                "model": "gpt-5-5-mini",
                "stream": True,
                "input": [
                    {"role": "user", "content": [{"type": "input_text", "text": "Explain the literary passage one."}]},
                    {"role": "assistant", "content": [{"type": "output_text", "text": LONG_ANSWER}]},
                    {"role": "user", "content": [{"type": "input_text", "text": "Explain the literary passage two."}]},
                ],
                "tools": [self.tool],
            },
            headers=headers,
        )
        await second.read()

        self.assertEqual(title.status, 200)
        self.assertEqual(first.status, 200)
        self.assertEqual(second.status, 200)
        self.assertEqual(self.backend.planner_calls, 0)
        self.assertEqual(self.backend.render_calls, 2)
        self.assertEqual(self.backend.render_requests[0].msg_send, "Explain the literary passage one.")
        self.assertEqual(self.backend.render_requests[1].msg_send, "Explain the literary passage two.")
        self.assertEqual(self.backend.render_requests[1].conversation_id, "render-conversation")

    async def test_opencode_title_is_completed_locally_without_browser_request(self):
        response = await self.client.post(
            "/v1/responses",
            json={
                "model": "gpt-5-5-mini",
                "stream": True,
                "input": [
                    {
                        "role": "system",
                        "content": "You are a title generator. You output ONLY a thread title.",
                    },
                    {
                        "role": "user",
                        "content": [{"type": "input_text", "text": "Generate a title for this conversation:\n"}],
                    },
                    {
                        "role": "user",
                        "content": [{"type": "input_text", "text": "Explain the number one"}],
                    },
                ],
            },
            headers={
                **self.headers,
                "User-Agent": "opencode/1.18.15 ai-sdk/provider-utils/4.0.38",
                "X-Session-Id": "ses_local_title",
            },
        )
        body = await response.read()

        text, terminal = _response_deltas(body)
        self.assertEqual(response.status, 200)
        self.assertEqual(text, "Explain the number one")
        self.assertEqual(terminal, "response.completed")
        self.assertEqual(self.backend.planner_calls, 0)
        self.assertEqual(self.backend.render_calls, 0)
        self.assertEqual(self.backend.buffered_calls, 0)

    async def test_opencode_host_task_cannot_finalize_before_a_tool_call(self):
        response = await self.client.post(
            "/v1/responses",
            json={
                "model": "gpt-5-5-mini",
                "stream": True,
                "input": [{
                    "role": "user",
                    "content": "Read Downloads/requirements.txt and explain it",
                }],
                "tools": [self.tool],
            },
            headers={
                **self.headers,
                "User-Agent": "opencode/1.18.15 ai-sdk/provider-utils/4.0.38",
                "X-Session-Id": "ses_required_tool",
            },
        )
        body = await response.read()
        function_call = _response_function_call(body)

        self.assertEqual(response.status, 200)
        self.assertEqual(function_call["name"], "workspace.read_text")
        self.assertEqual(
            json.loads(str(function_call["arguments"])),
            {"path": "Downloads/requirements.txt"},
        )
        self.assertEqual(self.backend.planner_calls, 2)
        self.assertEqual(self.backend.render_calls, 0)
        repair = self.backend.planner_requests[-1]
        self.assertIn("Current registered tools JSON", repair.msg_send)
        self.assertNotEqual(repair.p_msg_id, "planner-message-1")

    async def test_opencode_title_accepts_developer_instruction_shape(self):
        response = await self.client.post(
            "/v1/responses",
            json={
                "model": "gpt-5-5-mini",
                "stream": True,
                "input": [
                    {
                        "role": "developer",
                        "content": "You are a title generator. You output ONLY a thread title.",
                    },
                    {
                        "role": "user",
                        "content": "Generate a title for this conversation:\nExplain the number eleven",
                    },
                ],
            },
            headers={
                **self.headers,
                "User-Agent": "opencode/1.18.15 ai-sdk/provider-utils/4.0.38",
                "X-Session-Id": "ses_local_title_developer",
            },
        )
        body = await response.read()

        text, terminal = _response_deltas(body)
        self.assertEqual(response.status, 200)
        self.assertEqual(text, "Explain the number eleven")
        self.assertEqual(terminal, "response.completed")
        self.assertEqual(self.backend.render_calls, 0)
        self.assertEqual(self.backend.buffered_calls, 0)

    async def test_opencode_title_accepts_prompt_pair_without_system_item(self):
        response = await self.client.post(
            "/v1/responses",
            json={
                "model": "gpt-5-5-mini",
                "stream": True,
                "input": [
                    {"role": "user", "content": "Generate a title for this conversation:\n"},
                    {"role": "user", "content": "Explain the number twelve"},
                ],
            },
            headers={
                **self.headers,
                "User-Agent": "opencode/1.18.15 ai-sdk/provider-utils/4.0.38",
                "X-Session-Id": "ses_local_title_prompt_pair",
            },
        )
        body = await response.read()

        text, terminal = _response_deltas(body)
        self.assertEqual(response.status, 200)
        self.assertEqual(text, "Explain the number twelve")
        self.assertEqual(terminal, "response.completed")
        self.assertEqual(self.backend.render_calls, 0)
        self.assertEqual(self.backend.buffered_calls, 0)

    async def test_opencode_plain_turn_preserves_the_reusable_tool_planner(self):
        headers = {
            **self.headers,
            "User-Agent": "opencode/1.18.15 ai-sdk/provider-utils/4.0.38",
            "X-Session-Id": "ses_tool_plain_tool",
        }
        first = await self.client.post(
            "/v1/responses",
            json={
                "model": "gpt-5-5-mini",
                "stream": True,
                "input": [{"role": "user", "content": "Read README.md"}],
                "tools": [self.tool],
            },
            headers=headers,
        )
        first_body = await first.read()
        function_call = _response_function_call(first_body)
        continuation = await self.client.post(
            "/v1/responses",
            json={
                "model": "gpt-5-5-mini",
                "stream": True,
                "input": [{
                    "type": "function_call_output",
                    "call_id": function_call["call_id"],
                    "output": "README contents",
                }],
                "tools": [self.tool],
            },
            headers=headers,
        )
        await continuation.read()
        plain = await self.client.post(
            "/v1/responses",
            json={
                "model": "gpt-5-5-mini",
                "stream": True,
                "input": [{"role": "user", "content": "Explain the result briefly"}],
                "tools": [self.tool],
            },
            headers=headers,
        )
        await plain.read()
        later_tool = await self.client.post(
            "/v1/responses",
            json={
                "model": "gpt-5-5-mini",
                "stream": True,
                "input": [{"role": "user", "content": "Read pyproject.toml"}],
                "tools": [self.tool],
            },
            headers=headers,
        )
        await later_tool.read()

        self.assertEqual(first.status, 200)
        self.assertEqual(continuation.status, 200)
        self.assertEqual(plain.status, 200)
        self.assertEqual(later_tool.status, 200)
        self.assertEqual(self.backend.planner_calls, 4)
        self.assertEqual(
            self.backend.planner_requests[-2].conversation_id,
            "planner-conversation-2",
        )
        self.assertIn(
            "A new user request has arrived in the same host session.",
            self.backend.planner_requests[-2].msg_send,
        )
        self.assertIn(
            "A final answer is forbidden in this turn",
            self.backend.planner_requests[-1].msg_send,
        )

    async def test_chat_completions_direct_answer_streams_once(self):
        self.backend.hold_render = True
        response = await self.client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-5-5-mini",
                "stream": True,
                "messages": [{"role": "user", "content": "Long exact answer"}],
                "tools": [{
                    "type": "function",
                    "function": {
                        "name": self.tool["name"],
                        "description": self.tool["description"],
                        "parameters": self.tool["parameters"],
                    },
                }],
            },
            headers=self.headers,
        )
        self.assertEqual(response.status, 200)
        initial = b""
        while not _chat_deltas(initial):
            initial += await _next_sse_block(response)
        self.assertFalse(self.backend.release_render.is_set())
        self.backend.release_render.set()
        body = initial + await asyncio.wait_for(response.read(), timeout=3)
        self.assertEqual(_chat_deltas(body), LONG_ANSWER)
        self.assertNotIn(PLANNER_NOTE.encode(), body)
        self.assertEqual(self.backend.planner_calls, 1)
        self.assertEqual(self.backend.render_calls, 1)

    async def test_repair_protocol_is_hidden_before_direct_answer(self):
        self.backend.release_render.set()
        response = await self._responses_request("Repair before answer")
        body = await asyncio.wait_for(response.read(), timeout=3)
        text, terminal = _response_deltas(body)
        self.assertEqual(text, LONG_ANSWER)
        self.assertEqual(terminal, "response.completed")
        self.assertNotIn("bogus", body.decode("utf-8"))
        self.assertNotIn("repaired-planner-note", body.decode("utf-8"))
        self.assertEqual(self.backend.planner_calls, 2)
        self.assertEqual(self.backend.render_calls, 1)

    async def test_tool_call_is_validated_and_does_not_render_answer(self):
        response = await self._responses_request("Read README.md")
        body = await asyncio.wait_for(response.read(), timeout=3)
        self.assertNotIn(b"response.output_text.delta", body)
        self.assertIn(b"response.function_call_arguments.delta", body)
        self.assertIn(b"workspace.read_text", body)
        self.assertEqual(self.backend.planner_calls, 1)
        self.assertEqual(self.backend.render_calls, 0)

    async def test_direct_stream_fails_honestly_on_unannounced_final_replacement(self):
        response = await self._responses_request("Replacement snapshot")
        body = await asyncio.wait_for(response.read(), timeout=3)
        text, terminal = _response_deltas(body)
        self.assertEqual(text, "stable streamed answer")
        self.assertEqual(terminal, "response.failed")
        self.assertNotIn("different reconciled snapshot", body.decode("utf-8"))
        self.assertIn("does not extend", body.decode("utf-8"))


class AnchorIsolationTests(unittest.IsolatedAsyncioTestCase):
    async def test_control_anchor_ack_is_never_user_visible(self):
        backend = _PlannerRenderBackend()
        backend.release_render.set()
        app = create_http_app(
            ChatService(backend),
            api_key="test-key",
            agent_safety_policy=AgentSafetyPolicy(enabled=False),
            agent_anchor_policy=AgentAnchorPolicy(enabled=True, control_enabled=True),
        )
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            response = await client.post(
                "/v1/responses",
                json={
                    "model": "gpt-5-5-mini",
                    "stream": True,
                    "input": "Long exact answer",
                    "tools": [{
                        "type": "function",
                        "name": "workspace.read_text",
                        "description": "Read one text file.",
                        "parameters": {
                            "type": "object",
                            "properties": {"path": {"type": "string"}},
                            "required": ["path"],
                            "additionalProperties": False,
                        },
                    }],
                },
                headers={"Authorization": "Bearer test-key"},
            )
            body = await asyncio.wait_for(response.read(), timeout=3)
            text, terminal = _response_deltas(body)
            self.assertEqual(text, LONG_ANSWER)
            self.assertEqual(terminal, "response.completed")
            decoded = body.decode("utf-8")
            self.assertNotIn(ANCHOR_NOTE, decoded)
            self.assertNotIn(PLANNER_NOTE, decoded)
            self.assertEqual(backend.buffered_calls, 1)
            self.assertEqual(backend.planner_calls, 1)
            self.assertEqual(backend.render_calls, 1)
        finally:
            await client.close()

    async def test_chat_completions_anchor_ack_is_never_user_visible(self):
        backend = _PlannerRenderBackend()
        backend.release_render.set()
        app = create_http_app(
            ChatService(backend),
            api_key="test-key",
            agent_safety_policy=AgentSafetyPolicy(enabled=False),
            agent_anchor_policy=AgentAnchorPolicy(enabled=True, control_enabled=True),
        )
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            response = await client.post(
                "/v1/chat/completions",
                json={
                    "model": "gpt-5-5-mini",
                    "stream": True,
                    "messages": [{"role": "user", "content": "Long exact answer"}],
                    "tools": [{
                        "type": "function",
                        "function": {
                            "name": "workspace.read_text",
                            "description": "Read one text file.",
                            "parameters": {
                                "type": "object",
                                "properties": {"path": {"type": "string"}},
                                "required": ["path"],
                                "additionalProperties": False,
                            },
                        },
                    }],
                },
                headers={"Authorization": "Bearer test-key"},
            )
            body = await asyncio.wait_for(response.read(), timeout=3)
            text = _chat_deltas(body)
            self.assertEqual(text, LONG_ANSWER)
            decoded = body.decode("utf-8")
            self.assertNotIn(ANCHOR_NOTE, decoded)
            self.assertNotIn(PLANNER_NOTE, decoded)
            self.assertEqual(backend.buffered_calls, 1)
            self.assertEqual(backend.planner_calls, 1)
            self.assertEqual(backend.render_calls, 1)
        finally:
            await client.close()



if __name__ == "__main__":
    unittest.main()
