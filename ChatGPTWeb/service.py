"""Stable, transport-neutral service API for bot, HTTP, and agent adapters."""

from dataclasses import dataclass, field, replace
from enum import Enum
import inspect
import math

from typing import Any, AsyncIterator, Awaitable, Callable, Dict, List, Protocol, Union

from .api import ChatStreamEvent
from .content import ChatContent, UpstreamMarkupNormalizer, build_chat_content
from .config import IOFile, MsgData


class ConversationOperation(str, Enum):
    """Explicit conversation operations supported by the public service API."""

    SEND = "send"
    START_PERSONA = "start_persona"
    REWIND = "rewind"
    RESET_TO_PERSONA = "reset_to_persona"


@dataclass
class ChatRequest:
    """A caller-owned chat request with no browser or storage details."""

    prompt: str
    conversation_id: str = ""
    parent_message_id: str = ""
    model: str = "auto"
    files: List[IOFile] = field(default_factory=list)
    required_capabilities: List[str] = field(default_factory=list)
    web_search: bool = False
    deep_research: bool = False
    prefer_paid_account: bool = False
    # Internal adapters may pin a known conversation owner without persisting a
    # full transcript. It is intentionally not accepted by public HTTP payloads.
    account_hint: str = ""
    persist_history: bool = True
    stream_idle_timeout_seconds: int = 0
    stream_status_interval_seconds: int = 15
    # Trusted adapters set these values. Public HTTP payloads deliberately do
    # not expose them, so a client cannot jump the shared runtime queue.
    client_id: str = ""
    request_priority: int = 50
    enforce_client_ownership: bool = False
    operation: ConversationOperation = ConversationOperation.SEND
    reference: str = ""

    def to_msg_data(self) -> MsgData:
        msg_data = MsgData(
            msg_send=self.prompt,
            conversation_id=self.conversation_id,
            p_msg_id=self.parent_message_id,
            gpt_model=self.model,
            upload_file=self.files.copy(),
            required_capabilities=self.required_capabilities.copy(),
            web_search=self.web_search,
            deep_research=self.deep_research,
            gpt_plus=self.prefer_paid_account,
            account_hint=self.account_hint,
            persist_history=self.persist_history,
            stream_idle_timeout_seconds=max(0, self.stream_idle_timeout_seconds),
            stream_status_interval_seconds=max(0, self.stream_status_interval_seconds),
            client_id=self.client_id,
            request_priority=max(0, self.request_priority),
            enforce_client_ownership=self.enforce_client_ownership,
        )
        if self.operation is ConversationOperation.REWIND:
            msg_data.msg_send = self.reference
            msg_data.msg_type = "back_loop"
        return msg_data


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
    files: List[IOFile] = field(default_factory=list)


@dataclass(frozen=True)
class ConversationContextEstimate:
    """A conservative local estimate, not an upstream context-window report."""

    conversation_id: str
    message_count: int
    character_count: int
    estimated_tokens: int
    model: str = ""
    context_window_tokens: int | None = None
    estimated_utilization: float | None = None
    context_window_source: str = "unavailable"
    source: str = "local_history_heuristic"


class ChatBackend(Protocol):
    async def continue_chat(self, msg_data: MsgData) -> MsgData: ...

    async def init_personality(self, msg_data: MsgData) -> MsgData: ...

    async def get_persona_prompt(self, name: str) -> str: ...

    async def back_chat_from_input(self, msg_data: MsgData) -> MsgData: ...

    async def back_init_personality(self, msg_data: MsgData) -> MsgData: ...

    def continue_chat_stream(self, msg_data: MsgData) -> AsyncIterator[ChatStreamEvent]: ...

    async def show_chat_history(self, msg_data: MsgData) -> List[Dict[str, Any]]: ...

    async def token_status(self) -> Dict[str, Any]: ...

    async def get_model_catalog(self, fetch_remote: bool = True) -> Dict[str, Any]: ...

    async def control_account(self, account: str, action: str) -> Dict[str, Any]: ...

    async def get_activity(self, limit: int = 50) -> Dict[str, Any]: ...

    async def get_runtime_logs(self, limit: int = 160) -> Dict[str, Any]: ...

    async def add_personality(self, personality: Dict[str, str]) -> None: ...

    async def del_personality(self, name: str) -> str: ...

    async def list_personas(self) -> List[Dict[str, str]]: ...


StreamCallback = Callable[[ChatStreamEvent], Union[None, Awaitable[None]]]


class ChatService:
    """Small public facade over the legacy ``chatgpt`` runtime.

    It deliberately owns no browser/session state. Adapters can depend on this
    class while the runtime remains free to change its Playwright internals.
    """

    def __init__(self, backend: ChatBackend):
        self._backend = backend

    async def _execute_buffered_request(self, request: ChatRequest) -> MsgData:
        """Route explicit operations through the legacy runtime behind this facade."""
        msg_data = request.to_msg_data()
        if request.operation is ConversationOperation.SEND:
            return await self._backend.continue_chat(msg_data)
        if request.operation is ConversationOperation.START_PERSONA:
            return await self._backend.init_personality(msg_data)
        if request.operation is ConversationOperation.REWIND:
            return await self._backend.back_chat_from_input(msg_data)
        if request.operation is ConversationOperation.RESET_TO_PERSONA:
            return await self._backend.back_init_personality(msg_data)
        raise ValueError(f"Unsupported conversation operation: {request.operation}")

    @staticmethod
    def _result_from_msg_data(msg_data: MsgData) -> ChatResult:
        metadata = dict(msg_data.response_metadata)
        if msg_data.title:
            metadata.setdefault("conversation_title", msg_data.title)
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
            files=msg_data.download_file.copy(),
        )

    async def send(self, request: ChatRequest) -> ChatResult:
        """Send a buffered request and return a normalized result."""
        msg_data = await self._execute_buffered_request(request)
        return self._result_from_msg_data(msg_data)

    async def stream(self, request: ChatRequest) -> AsyncIterator[ChatStreamEvent]:
        """Yield upstream stream events without exposing Playwright objects."""
        if request.operation is not ConversationOperation.SEND:
            raise ValueError("Only the send operation supports streaming")
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
                # The reconciled final event may replace an earlier private URL
                # with a downloadable image file, so it is authoritative even
                # when its URL list is intentionally empty.
                image_urls = event.image_urls.copy()
            elif event.type == "error":
                error = {
                    "kind": str(event.metadata.get("error_kind") or "stream_error"),
                    "message": event.text,
                    "retryable": bool(event.metadata.get("retryable", False)),
                }
                if event.metadata.get("capability"):
                    error["capability"] = str(event.metadata["capability"])
                errors.append(error)

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
            files=terminal.files.copy() if terminal else [],
        )

    async def get_history(self, conversation_id: str) -> List[Dict[str, Any]]:
        """Return the repository-backed history for a known conversation."""
        return await self._backend.show_chat_history(MsgData(conversation_id=conversation_id))

    async def assert_conversation_access(self, conversation_id: str, client_id: str) -> None:
        """Ask capable backends to enforce a remote client's conversation boundary."""
        checker = getattr(self._backend, "assert_conversation_client_access", None)
        if checker is not None:
            result = checker(conversation_id, client_id)
            if inspect.isawaitable(result):
                await result

    async def get_persona_prompt(self, name: str) -> str:
        """Return a stored persona prompt without exposing backend storage objects."""
        return await self._backend.get_persona_prompt(name)

    async def estimate_context(
        self,
        conversation_id: str,
        *,
        model: str = "",
        account: str = "",
    ) -> ConversationContextEstimate:
        """Estimate locally retained conversation text without claiming upstream quota."""
        history = await self.get_history(conversation_id)
        parts: List[str] = []
        for item in history:
            if not isinstance(item, dict):
                continue
            for field_name in ("Q", "A", "input", "output"):
                value = item.get(field_name)
                if isinstance(value, str):
                    parts.append(value)
        text = "".join(parts)
        ascii_count = sum(character.isascii() for character in text)
        non_ascii_count = len(text) - ascii_count
        estimated_tokens = math.ceil(ascii_count / 4 + non_ascii_count / 1.5)
        context_window_tokens, context_window_source = await self._find_context_window(model, account)
        return ConversationContextEstimate(
            conversation_id=conversation_id,
            message_count=len(history),
            character_count=len(text),
            estimated_tokens=estimated_tokens,
            model=model,
            context_window_tokens=context_window_tokens,
            estimated_utilization=(estimated_tokens / context_window_tokens) if context_window_tokens else None,
            context_window_source=context_window_source,
        )

    async def _find_context_window(self, model: str, account: str) -> tuple[int | None, str]:
        if not model:
            return None, "model_unavailable"
        catalog = await self.get_model_catalog(fetch_remote=False)
        accounts = catalog.get("accounts") if isinstance(catalog, dict) else None
        if not isinstance(accounts, list):
            return None, "catalog_unavailable"
        ordered_accounts = sorted(
            (item for item in accounts if isinstance(item, dict)),
            key=lambda item: 0 if account and item.get("email") == account else 1,
        )
        for item in ordered_accounts:
            for catalog_name, catalog_value in (("remote", item.get("remote")), *(
                ("cached", value) for value in item.get("cached", []) if isinstance(item.get("cached"), list)
            )):
                if not isinstance(catalog_value, dict):
                    continue
                for candidate in catalog_value.get("models", []):
                    if not isinstance(candidate, dict) or candidate.get("slug") != model:
                        continue
                    value = candidate.get("contextWindow")
                    if isinstance(value, int) and value > 0:
                        return value, f"{catalog_name}:{catalog_value.get('source', 'catalog')}"
        return None, "context_window_unavailable"

    async def get_account_status(self) -> Dict[str, Any]:
        """Return sanitized account diagnostics; it never includes credentials."""
        return await self._backend.token_status()

    async def get_runtime_health(self) -> Dict[str, Any]:
        """Return coarse readiness data suitable for an unauthenticated health probe."""
        status = await self.get_account_status()
        raw_accounts = status.get("accounts")
        accounts = raw_accounts if isinstance(raw_accounts, list) else []
        configured = len(accounts)
        if not accounts:
            configured = len(status.get("account", [])) if isinstance(status.get("account"), list) else 0

        available = sum(1 for account in accounts if isinstance(account, dict) and account.get("available"))
        login_in_progress = sum(
            1 for account in accounts if isinstance(account, dict) and account.get("login_retry_pending")
        )
        backend_manage = getattr(self._backend, "manage", None)
        start_task = getattr(self._backend, "_start_task", None)
        if isinstance(backend_manage, dict) and backend_manage.get("start"):
            runtime_state = "ready" if available else "degraded"
        elif start_task is not None and not start_task.done():
            runtime_state = "starting"
        elif start_task is not None and start_task.done():
            runtime_state = "not_ready"
        else:
            runtime_state = "unknown"

        ready = available > 0
        scheduler_status = getattr(self._backend, "request_scheduler_status", None)
        scheduler = await scheduler_status() if scheduler_status else None
        capability_names = ("image_upload", "file_upload", "image_generation")
        capability_availability = {
            capability: sum(
                1
                for account in accounts
                if (
                    isinstance(account, dict)
                    and isinstance(account.get("capability_quota"), dict)
                    and isinstance(
                        account["capability_quota"].get(capability),
                        dict,
                    )
                    and account["capability_quota"][capability].get("available")
                )
            )
            for capability in capability_names
        }
        return {
            "status": "ok" if ready else "degraded",
            "liveness": "ok",
            "readiness": "ready" if ready else "not_ready",
            "runtime": {"state": runtime_state},
            "accounts": {
                "configured": configured,
                "available": available,
                "login_in_progress": login_in_progress,
            },
            "capability_quota": {
                "policy": (
                    status.get("capability_quota")
                    if isinstance(status.get("capability_quota"), dict) else {}
                ),
                "available_accounts": capability_availability,
            },
            **({"request_queue": scheduler} if isinstance(scheduler, dict) else {}),
        }

    async def get_model_catalog(self, fetch_remote: bool = True) -> Dict[str, Any]:
        return await self._backend.get_model_catalog(fetch_remote=fetch_remote)

    async def control_account(self, account: str, action: str) -> Dict[str, Any]:
        """Apply an explicit local operator action to one account."""
        return await self._backend.control_account(account, action)

    async def get_activity(self, limit: int = 50) -> Dict[str, Any]:
        """Return bounded local runtime activity without browser internals."""
        return await self._backend.get_activity(limit=limit)

    async def get_runtime_logs(self, limit: int = 160) -> Dict[str, Any]:
        """Return a current-process log tail when the backend supports it."""
        getter = getattr(self._backend, "get_runtime_logs", None)
        if getter is None:
            return {
                "available": False,
                "source": "unavailable",
                "message": "runtime log is not available",
                "entries": [],
                "lines": [],
            }
        return await getter(limit=limit)

    async def get_usage_status(self) -> Dict[str, Any]:
        """Expose the current honest state: quota is unknown until upstream reports it."""
        status = await self.get_account_status()
        account_statuses = status.get("accounts")
        if not isinstance(account_statuses, list):
            account_statuses = [
                {"email": email, "usage": None}
                for email in status.get("account", [])
            ]
        accounts = [
            {
                "email": account.get("email", ""),
                "usage": account.get("usage"),
                "state": (account.get("usage") or {}).get("source", "unavailable"),
                "quota": None,
                "reason": "Observed token fields are process-local; ChatGPT has not reported live remaining quota.",
            }
            for account in account_statuses
        ]
        return {"source": "observed_upstream", "accounts": accounts}

    async def upsert_persona(self, name: str, value: str) -> None:
        """Store one persona for a trusted adapter namespace."""
        await self._backend.add_personality({"name": name, "value": value})

    async def delete_persona(self, name: str) -> None:
        """Remove one persona belonging to a trusted adapter namespace."""
        await self._backend.del_personality(name)

    async def list_personas(self) -> List[Dict[str, str]]:
        """Return stored persona definitions for a trusted adapter namespace."""
        return await self._backend.list_personas()
