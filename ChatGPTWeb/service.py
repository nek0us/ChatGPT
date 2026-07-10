"""Stable, transport-neutral service API for bot, HTTP, and agent adapters."""

from dataclasses import dataclass, field, replace
import inspect

from typing import Any, AsyncIterator, Awaitable, Callable, Dict, List, Protocol, Union

from .api import ChatStreamEvent
from .content import ChatContent, UpstreamMarkupNormalizer, build_chat_content
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
    content: ChatContent = field(default_factory=ChatContent)


class ChatBackend(Protocol):
    async def continue_chat(self, msg_data: MsgData) -> MsgData: ...

    def continue_chat_stream(self, msg_data: MsgData) -> AsyncIterator[ChatStreamEvent]: ...

    async def show_chat_history(self, msg_data: MsgData) -> List[Dict[str, str]]: ...

    async def token_status(self) -> Dict[str, Any]: ...

    async def get_model_catalog(self, fetch_remote: bool = True) -> Dict[str, Any]: ...


StreamCallback = Callable[[ChatStreamEvent], Union[None, Awaitable[None]]]


class ChatService:
    """Small public facade over the legacy ``chatgpt`` runtime.

    It deliberately owns no browser/session state. Adapters can depend on this
    class while the runtime remains free to change its Playwright internals.
    """

    def __init__(self, backend: ChatBackend):
        self._backend = backend

    @staticmethod
    def _result_from_msg_data(msg_data: MsgData) -> ChatResult:
        metadata = dict(msg_data.response_metadata)
        image_urls = list(msg_data.img_list)
        content = build_chat_content(msg_data.msg_recv, image_urls, metadata)
        return ChatResult(
            ok=bool(msg_data.status and not msg_data.error_list),
            text=content.markdown,
            conversation_id=msg_data.conversation_id,
            message_id=msg_data.next_msg_id,
            requested_model=msg_data.model_requested or msg_data.gpt_model,
            used_model=msg_data.model_used,
            image_urls=image_urls,
            usage=dict(msg_data.usage),
            metadata=metadata,
            errors=list(msg_data.error_list),
            account=msg_data.from_email,
            content=content,
        )

    async def send(self, request: ChatRequest) -> ChatResult:
        """Send a buffered request and return a normalized result."""
        msg_data = await self._backend.continue_chat(request.to_msg_data())
        return self._result_from_msg_data(msg_data)

    async def stream(self, request: ChatRequest) -> AsyncIterator[ChatStreamEvent]:
        """Yield upstream stream events without exposing Playwright objects."""
        upstream = self._backend.continue_chat_stream(request.to_msg_data())
        normalizer = UpstreamMarkupNormalizer()
        try:
            async for event in upstream:
                if event.type == "delta":
                    text = normalizer.feed(event.text)
                    if not text:
                        continue
                    yield replace(event, text=text, raw_text=event.text)
                    continue
                if event.type == "final":
                    content = build_chat_content(event.text, event.image_urls, event.metadata)
                    yield replace(event, text=content.markdown, raw_text=event.text)
                    continue
                yield event
        finally:
            close = getattr(upstream, "aclose", None)
            if close:
                await close()

    async def stream_to_callback(self, request: ChatRequest, callback: StreamCallback) -> ChatResult:
        """Deliver stream events in order and return the final normalized result.

        The callback may be synchronous or asynchronous. Callback failures are
        intentionally propagated so callers can decide how to recover.
        """
        chunks: List[str] = []
        image_urls: List[str] = []
        final_event: ChatStreamEvent | None = None
        errors: List[Dict[str, Any]] = []
        last_event: ChatStreamEvent | None = None

        async for event in self.stream(request):
            last_event = event
            if event.type == "delta":
                chunks.append(event.text)
            elif event.type == "image":
                image_urls = event.image_urls.copy()
            elif event.type == "final":
                final_event = event
                if event.image_urls:
                    image_urls = event.image_urls.copy()
            elif event.type == "error":
                errors.append({"kind": "stream_error", "message": event.text, "retryable": False})

            callback_result = callback(event)
            if inspect.isawaitable(callback_result):
                await callback_result

        terminal = final_event or last_event
        text = final_event.text if final_event and final_event.text else "".join(chunks)
        metadata = dict(terminal.metadata) if terminal else {}
        raw_text = final_event.raw_text if final_event and final_event.raw_text else text
        content = build_chat_content(raw_text, image_urls, metadata)
        return ChatResult(
            ok=bool(final_event and not errors),
            text=text,
            conversation_id=terminal.conversation_id if terminal else request.conversation_id,
            message_id=terminal.message_id if terminal else "",
            requested_model=request.model,
            used_model=terminal.model if terminal else "",
            image_urls=image_urls,
            usage=dict(terminal.usage) if terminal else {},
            metadata=metadata,
            errors=errors,
            content=content,
        )

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
