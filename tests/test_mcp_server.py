import unittest
import json
import sys

from ChatGPTWeb.api import ChatStreamEvent
from ChatGPTWeb.mcp_server import McpServiceAdapter, create_mcp_server
from ChatGPTWeb.service import ChatService


class _FakeBackend:
    def __init__(self):
        self.sent = []

    async def continue_chat(self, msg_data):
        self.sent.append(msg_data)
        msg_data.status = True
        msg_data.msg_recv = "agent response"
        msg_data.conversation_id = "conversation-agent"
        msg_data.next_msg_id = "message-agent"
        msg_data.model_requested = msg_data.gpt_model
        msg_data.model_used = "gpt-5-mini"
        msg_data.response_metadata = {"safe": True, "access_token": "must-not-leak"}
        return msg_data

    async def continue_chat_stream(self, _msg_data):
        yield ChatStreamEvent(type="delta", text="stream ")
        yield ChatStreamEvent(type="final", text="stream response", model="gpt-5-mini")

    async def show_chat_history(self, msg_data):
        return [{"Q": "question", "A": msg_data.conversation_id}]

    async def token_status(self):
        return {
            "account": ["legacy@example.com"],
            "accounts": [
                {
                    "email": "account@example.com",
                    "available": True,
                    "session_token": "must-not-leak",
                    "runtime": {"page_ready": True},
                }
            ],
        }

    async def get_model_catalog(self, fetch_remote=True):
        return {"fetch_remote": fetch_remote, "access_token": "must-not-leak"}


class McpServiceAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.backend = _FakeBackend()
        self.adapter = McpServiceAdapter(ChatService(self.backend))

    async def test_send_requires_explicit_confirmation(self):
        result = await self.adapter.chat_send("hello")

        self.assertFalse(result["ok"])
        self.assertTrue(result["requires_confirmation"])
        self.assertEqual(self.backend.sent, [])

    async def test_confirmed_send_returns_normalized_redacted_result(self):
        result = await self.adapter.chat_send("hello", model="gpt-5-mini", confirm=True)

        self.assertTrue(result["ok"])
        self.assertEqual(self.backend.sent[0].msg_send, "hello")
        self.assertEqual(result["used_model"], "gpt-5-mini")
        self.assertNotIn("access_token", result["metadata"])

    async def test_read_tools_keep_credentials_out_of_responses(self):
        accounts = await self.adapter.list_accounts()
        models = await self.adapter.list_models(fetch_remote=True)
        history = await self.adapter.get_conversation("conversation-history")

        self.assertEqual(accounts["accounts"][0]["email"], "account@example.com")
        self.assertNotIn("session_token", accounts["accounts"][0])
        self.assertNotIn("access_token", models)
        self.assertEqual(history[0]["A"], "conversation-history")

    async def test_factory_registers_the_minimum_tool_set_when_sdk_is_installed(self):
        try:
            import mcp  # noqa: F401
        except ImportError:
            self.skipTest("optional MCP SDK is not installed")

        server = create_mcp_server(ChatService(self.backend))
        names = {tool.name for tool in await server.list_tools()}

        self.assertEqual(names, {"chat_send", "chat_stream", "list_accounts", "list_models", "get_conversation", "agent_turn"})

    async def test_agent_turn_returns_a_host_executed_tool_request(self):
        self.backend.sent = []
        self.backend.continue_chat = self._agent_reply
        result = await self.adapter.agent_turn(
            "create a note",
            [{
                "name": "workspace.write_text",
                "description": "write a workspace text file",
                "input_schema": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                    "additionalProperties": False,
                },
            }],
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["decision"]["tool"], "workspace.write_text")
        self.assertEqual(result["decision"]["arguments"]["path"], "note.txt")

    async def _agent_reply(self, msg_data):
        self.backend.sent.append(msg_data)
        msg_data.status = True
        msg_data.msg_recv = (
            '{"blocked":false}'
            if "ChatGPTWeb Agent Safety Review" in msg_data.msg_send
            else '{"type":"tool_call","tool":"workspace.write_text","arguments":{"path":"note.txt"},"summary":"create note"}'
        )
        msg_data.conversation_id = "conversation-agent"
        msg_data.next_msg_id = "message-agent"
        msg_data.model_requested = msg_data.gpt_model
        msg_data.model_used = "gpt-5-mini"
        return msg_data

    async def test_stream_forwards_delta_events_and_returns_final_result(self):
        events = []

        async def on_event(event):
            events.append(event)

        result = await self.adapter.chat_stream("hello", confirm=True, progress_callback=on_event)

        self.assertEqual([event.type for event in events], ["delta", "final"])
        self.assertEqual(result["text"], "stream response")
        self.assertTrue(result["ok"])

    async def test_stdio_client_initializes_and_calls_a_real_tool(self):
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except ImportError:
            self.skipTest("optional MCP SDK is not installed")

        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "tests.mcp_stdio_server"],
        )
        async with stdio_client(parameters) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as client:
                await client.initialize()
                tools = await client.list_tools()
                progress_messages = []

                async def on_progress(_progress, _total, message):
                    progress_messages.append(message)

                result = await client.call_tool(
                    "chat_stream",
                    {"prompt": "stdio", "confirm": True},
                    progress_callback=on_progress,
                )

        self.assertEqual({tool.name for tool in tools.tools}, {"chat_send", "chat_stream", "list_accounts", "list_models", "get_conversation", "agent_turn"})
        self.assertFalse(result.isError)
        self.assertEqual(json.loads(result.content[0].text)["text"], "stdio response")
        self.assertEqual(progress_messages, ["[waiting_for_upstream]", "stdio "])
