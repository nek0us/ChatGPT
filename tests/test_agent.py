import unittest

from aiohttp.test_utils import TestClient, TestServer

from ChatGPTWeb.agent import AgentSafetyPolicy, AgentService, AgentState, AgentTool, AgentToolResult, parse_agent_decision
from ChatGPTWeb.http_api import agent_turn_from_payload, create_http_app
from ChatGPTWeb.service import ChatService


class _Backend:
    def __init__(self, replies, safety_replies=None):
        self.replies = list(replies)
        self.safety_replies = list(safety_replies or [])
        self.requests = []
        self.received_conversation_ids = []
        self.received_parent_message_ids = []

    async def continue_chat(self, msg_data):
        self.requests.append(msg_data)
        self.received_conversation_ids.append(msg_data.conversation_id)
        self.received_parent_message_ids.append(msg_data.p_msg_id)
        msg_data.status = True
        if "ChatGPTWeb Agent Safety Review" in msg_data.msg_send:
            msg_data.msg_recv = (
                '{"ready":true}'
                if "Static classifier root" in msg_data.msg_send
                else self.safety_replies.pop(0) if self.safety_replies else '{"blocked":false}'
            )
        elif "Static protocol root" in msg_data.msg_send and "Agent task data follows." not in msg_data.msg_send:
            msg_data.msg_recv = '{"ready":true}'
        else:
            msg_data.msg_recv = self.replies.pop(0)
        msg_data.conversation_id = "agent-conversation"
        msg_data.next_msg_id = f"message-{len(self.requests)}"
        msg_data.model_requested = msg_data.gpt_model
        msg_data.model_used = "gpt-agent"
        msg_data.from_email = "agent@example.com"
        return msg_data


def _tools():
    return [AgentTool(
        "workspace.write_text",
        "Write one UTF-8 text file inside the configured workspace.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string", "maxLength": 120},
                "content": {"type": "string", "maxLength": 1000},
            },
            "required": ["path", "content"],
            "additionalProperties": False,
        },
    )]


class AgentDecisionTests(unittest.TestCase):
    def test_visual_task_protocol_forbids_product_native_tools(self):
        prompt = AgentService._initial_task_prompt("create a visual card", _tools())

        self.assertIn("product-native image generation", prompt)
        self.assertIn("registered host tools", prompt)

    def test_registered_tool_call_is_validated(self):
        decision = parse_agent_decision(
            '{"type":"tool_call","tool":"workspace.write_text","arguments":{"path":"note.txt","content":"hello"},"summary":"create note"}',
            _tools(),
        )

        self.assertEqual(decision.kind, "tool_call")
        self.assertEqual(decision.arguments["path"], "note.txt")

    def test_unknown_tool_and_bad_arguments_fail_closed(self):
        unknown = parse_agent_decision('{"type":"tool_call","tool":"shell","arguments":{}}', _tools())
        malformed = parse_agent_decision(
            '{"type":"tool_call","tool":"workspace.write_text","arguments":{"path":"note.txt"}}',
            _tools(),
        )

        self.assertEqual(unknown.kind, "error")
        self.assertEqual(malformed.kind, "error")


class AgentServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_tool_result_continues_same_conversation_to_a_final_answer(self):
        backend = _Backend([
            '{"type":"tool_call","tool":"workspace.write_text","arguments":{"path":"note.txt","content":"hello"},"summary":"create note"}',
            '{"type":"final","answer":"已在工作区创建 note.txt。"}',
        ])
        service = AgentService(ChatService(backend))

        first = await service.turn("创建一个 hello 文件", _tools())
        second = await service.turn(
            "",
            _tools(),
            state=first.state,
            tool_result=AgentToolResult("workspace.write_text", "created note.txt"),
        )

        self.assertTrue(first.ok)
        self.assertEqual(first.decision.kind, "tool_call")
        self.assertIn("【ChatGPTWeb Agent Protocol】", backend.requests[3].msg_send)
        self.assertTrue(second.ok)
        self.assertEqual(second.decision.kind, "final")
        self.assertEqual(second.decision.answer, "已在工作区创建 note.txt。")
        self.assertEqual(backend.requests[3].conversation_id, "agent-conversation")
        self.assertIn("created note.txt", backend.requests[4].msg_send)

    async def test_malformed_decision_is_repaired_once_before_failing(self):
        backend = _Backend([
            "I can inspect that for you.",
            '{"type":"tool_call","tool":"workspace.write_text","arguments":{"path":"note.txt","content":"hello"},"summary":"create note"}',
        ])

        result = await AgentService(ChatService(backend)).turn("create a note", _tools())

        self.assertTrue(result.ok)
        self.assertEqual(result.decision.kind, "tool_call")
        self.assertEqual(len(backend.requests), 5)
        self.assertIn("previous response was not a valid agent decision", backend.requests[-1].msg_send)
        self.assertEqual(backend.requests[-1].conversation_id, "agent-conversation")
        self.assertEqual(backend.requests[-1].p_msg_id, "message-4")

    async def test_continuation_without_result_is_rejected_before_model_call(self):
        backend = _Backend([])
        result = await AgentService(ChatService(backend)).turn(
            "",
            _tools(),
            state=AgentState(conversation_id="existing", parent_message_id="message"),
        )

        self.assertFalse(result.ok)
        self.assertEqual(backend.requests, [])

    async def test_sensitive_agent_task_is_refused_before_model_call(self):
        backend = _Backend([])

        result = await AgentService(ChatService(backend)).turn(
            "请分析一份法律诉讼材料，并生成后续行动计划",
            _tools(),
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.decision.kind, "final")
        self.assertIn("不处理法律、政治", result.decision.answer)
        self.assertEqual(backend.requests, [])

    async def test_host_can_extend_sensitive_agent_task_deny_list(self):
        backend = _Backend([])
        result = await AgentService(
            ChatService(backend),
            safety_policy=AgentSafetyPolicy(extra_blocked_terms=("内部密钥轮换",)),
        ).turn("请安排内部密钥轮换", _tools())

        self.assertTrue(result.ok)
        self.assertEqual(result.decision.kind, "final")
        self.assertEqual(backend.requests, [])

    async def test_semantic_review_blocks_obfuscated_sensitive_task_before_agent_plan(self):
        backend = _Backend([], safety_replies=['{"blocked":true}'])

        result = await AgentService(ChatService(backend)).turn(
            "请处理一个经过改写的敏感主题任务",
            _tools(),
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.decision.kind, "final")
        self.assertEqual(len(backend.requests), 2)
        self.assertIn("Agent Safety Review", backend.requests[0].msg_send)

    async def test_host_can_explicitly_disable_sensitive_task_guard(self):
        backend = _Backend(['{"type":"final","answer":"completed"}'])

        result = await AgentService(
            ChatService(backend),
            safety_policy=AgentSafetyPolicy(enabled=False),
        ).turn("请分析一份法律材料", _tools())

        self.assertTrue(result.ok)
        self.assertEqual(result.decision.answer, "completed")
        self.assertEqual(len(backend.requests), 2)
        self.assertNotIn("Agent Safety Review", backend.requests[0].msg_send)

    async def test_initial_agent_turn_can_explicitly_continue_a_persona_conversation(self):
        backend = _Backend([
            '{"type":"final","answer":"我会记住这件事。"}',
        ])
        result = await AgentService(ChatService(backend)).turn(
            "ten minutes later remind me",
            _tools(),
            state=AgentState(conversation_id="persona-conversation", parent_message_id="persona-message"),
            continue_existing=True,
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.decision.kind, "final")
        self.assertEqual(backend.received_conversation_ids[2], "persona-conversation")
        self.assertEqual(backend.received_parent_message_ids[2], "persona-message")

    async def test_independent_tasks_reuse_only_isolated_protocol_anchors(self):
        backend = _Backend([
            '{"type":"final","answer":"first"}',
            '{"type":"final","answer":"second"}',
        ])
        service = ChatService(backend)

        first = await AgentService(service).turn("first task", _tools())
        second = await AgentService(service).turn("second task", _tools())

        self.assertEqual(first.decision.answer, "first")
        self.assertEqual(second.decision.answer, "second")
        self.assertEqual(len(backend.requests), 6)
        self.assertIn("Static classifier root", backend.requests[0].msg_send)
        self.assertIn("Static protocol root", backend.requests[2].msg_send)
        self.assertNotIn("Static classifier root", backend.requests[4].msg_send)
        self.assertNotIn("Static protocol root", backend.requests[5].msg_send)
        self.assertEqual(backend.requests[4].conversation_id, "agent-conversation")
        self.assertEqual(backend.requests[5].conversation_id, "agent-conversation")
        self.assertEqual(backend.requests[4].p_msg_id, "message-1")
        self.assertEqual(backend.requests[5].p_msg_id, "message-3")
        self.assertTrue(all(not request.persist_history for request in backend.requests))
        self.assertEqual(backend.requests[4].account_hint, "agent@example.com")
        self.assertEqual(backend.requests[5].account_hint, "agent@example.com")

    async def test_http_agent_payload_keeps_state_for_a_remote_host_loop(self):
        backend = _Backend([
            '{"type":"tool_call","tool":"workspace.write_text","arguments":{"path":"note.txt","content":"hello"}}',
        ])
        payload = await agent_turn_from_payload(ChatService(backend), {
            "task": "create a note",
            "tools": [tool.to_dict() for tool in _tools()],
        })

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["decision"]["type"], "tool_call")
        self.assertEqual(payload["state"]["conversation_id"], "agent-conversation")


class OpenAICompatibleAgentTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.backend = _Backend([
            '{"type":"tool_call","tool":"workspace.write_text","arguments":{"path":"note.txt","content":"hello"}}',
            '{"type":"final","answer":"created note.txt"}',
        ])
        self.client = TestClient(TestServer(create_http_app(ChatService(self.backend))))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()

    async def test_standard_openai_tool_call_round_trip_without_private_cursor_fields(self):
        tools = [{
            "type": "function",
            "function": {
                "name": "workspace.write_text",
                "description": "Write a workspace file.",
                "parameters": _tools()[0].input_schema,
            },
        }]
        first = await self.client.post("/v1/chat/completions", json={
            "model": "auto",
            "messages": [{"role": "user", "content": "create note.txt"}],
            "tools": tools,
        })
        first_payload = await first.json()

        self.assertEqual(first.status, 200)
        self.assertEqual(first_payload["choices"][0]["finish_reason"], "tool_calls")
        call = first_payload["choices"][0]["message"]["tool_calls"][0]
        self.assertEqual(call["function"]["name"], "workspace.write_text")

        second = await self.client.post("/v1/chat/completions", json={
            "model": "auto",
            "messages": [
                first_payload["choices"][0]["message"],
                {"role": "tool", "tool_call_id": call["id"], "content": "created note.txt"},
            ],
        })
        second_payload = await second.json()

        self.assertEqual(second.status, 200)
        self.assertEqual(second_payload["choices"][0]["finish_reason"], "stop")
        self.assertEqual(second_payload["choices"][0]["message"]["content"], "created note.txt")
