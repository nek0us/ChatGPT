"""Stable, transport-neutral service API for bot, HTTP, and agent adapters."""

from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List, Protocol

from .api import ChatStreamEvent
from .config import IOFile, MsgData


@dataclass
class ChatRequest:
    """A caller-owned chat request with no browser or storage details."""

    prompt: str
    conversation_id: str = ""
    parent_message_id: str = ""
    model: str = "auto"
    files: List[IOFile] = field(default_factory=list)
    web_search: bool = False
    deep_research: bool = False

    def to_msg_data(self) -> MsgData:
        return MsgData(
            msg_send=self.prompt,
            conversation_id=self.conversation_id,
            p_msg_id=self.parent_message_id,
            gpt_model=self.model,
            upload_file=self.files.copy(),
            web_search=self.web_search,
            deep_research=self.deep_research,
        )


@dataclass
class ChatResult:
    """The normalized result returned by :meth:`ChatService.send`."""

    ok: bool
    text: str
    conversation_id: str
    message_id: str
    requested_model: str = ""
    used_model: str = ""
    image_urls: List[str] = field(default_factory=list)
    usage: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    errors: List[Dict[str, Any]] = field(default_factory=list)
    account: str = ""


class ChatBackend(Protocol):
    async def continue_chat(self, msg_data: MsgData) -> MsgData: ...

    async def continue_chat_stream(self, msg_data: MsgData) -> AsyncIterator[ChatStreamEvent]: ...

    async def show_chat_history(self, msg_data: MsgData) -> List[Dict[str, str]]: ...

    async def token_status(self) -> Dict[str, Any]: ...

    async def get_model_catalog(self, fetch_remote: bool = True) -> Dict[str, Any]: ...


class ChatService:
    """Small public facade over the legacy ``chatgpt`` runtime.

    It deliberately owns no browser/session state. Adapters can depend on this
    class while the runtime remains free to change its Playwright internals.
    """

    def __init__(self, backend: ChatBackend):
        self._backend = backend

    @staticmethod
    def _result_from_msg_data(msg_data: MsgData) -> ChatResult:
        return ChatResult(
            ok=bool(msg_data.status and not msg_data.error_list),
            text=msg_data.msg_recv,
            conversation_id=msg_data.conversation_id,
            message_id=msg_data.next_msg_id,
            requested_model=msg_data.model_requested or msg_data.gpt_model,
            used_model=msg_data.model_used,
            image_urls=list(msg_data.img_list),
            usage=dict(msg_data.usage),
            metadata=dict(msg_data.response_metadata),
            errors=list(msg_data.error_list),
            account=msg_data.from_email,
        )

    async def send(self, request: ChatRequest) -> ChatResult:
        """Send a buffered request and return a normalized result."""
        msg_data = await self._backend.continue_chat(request.to_msg_data())
        return self._result_from_msg_data(msg_data)

    async def stream(self, request: ChatRequest) -> AsyncIterator[ChatStreamEvent]:
        """Yield upstream stream events without exposing Playwright objects."""
        async for event in self._backend.continue_chat_stream(request.to_msg_data()):
            yield event

    async def get_history(self, conversation_id: str) -> List[Dict[str, str]]:
        """Return the repository-backed history for a known conversation."""
        return await self._backend.show_chat_history(MsgData(conversation_id=conversation_id))

    async def get_account_status(self) -> Dict[str, Any]:
        """Return sanitized account diagnostics; it never includes credentials."""
        return await self._backend.token_status()

    async def get_model_catalog(self, fetch_remote: bool = True) -> Dict[str, Any]:
        return await self._backend.get_model_catalog(fetch_remote=fetch_remote)

    async def get_usage_status(self) -> Dict[str, Any]:
        """Expose the current honest state: quota is unknown until upstream reports it."""
        status = await self.get_account_status()
        accounts = [
            {
                "email": email,
                "usage": None,
                "state": "unknown",
                "reason": "ChatGPT has not reported a live usage value for this account.",
            }
            for email in status.get("account", [])
        ]
        return {"source": "unavailable", "accounts": accounts}
