import unittest

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

        self.assertEqual(names, {"chat_send", "list_accounts", "list_models", "get_conversation"})
