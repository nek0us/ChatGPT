"""Secret-free MCP subprocess used by the stdio integration test."""

from ChatGPTWeb import ChatService, create_mcp_server
from ChatGPTWeb.api import ChatStreamEvent


class _Backend:
    async def continue_chat(self, msg_data):
        msg_data.status = True
        msg_data.msg_recv = "stdio response"
        return msg_data

    async def continue_chat_stream(self, _msg_data):
        yield ChatStreamEvent(type="status", metadata={"phase": "waiting_for_upstream"})
        yield ChatStreamEvent(type="delta", text="stdio ")
        yield ChatStreamEvent(
            type="final",
            text="stdio response",
            conversation_id="stdio-conversation",
            message_id="stdio-message",
            model="stdio-model",
        )

    async def show_chat_history(self, msg_data):
        return [{"Q": "saved question", "A": msg_data.conversation_id}]

    async def token_status(self):
        return {"accounts": [{"email": "stdio@example.com", "available": True}]}

    async def get_model_catalog(self, fetch_remote=True):
        return {"source": "stdio-test", "fetch_remote": fetch_remote}


if __name__ == "__main__":
    create_mcp_server(ChatService(_Backend())).run(transport="stdio")
