"""Optional MCP tools backed only by the stable :mod:`service` facade.

The adapter intentionally has no access to Playwright pages, stored session
tokens, passwords, or browser contexts. This keeps the agent boundary small
and makes the core behavior testable without installing the MCP SDK.
"""

from __future__ import annotations

import base64

from typing import Any, Awaitable, Callable, Dict, List

from .agent import AgentAnchorPolicy, AgentSafetyPolicy, AgentService, AgentState, AgentTool, AgentToolResult
from .api import ChatStreamEvent
from .input_files import InputFileError, InputFileLimits, input_files_from_attachments
from .remote_files import RemoteFileDownloader, RemoteFilePolicy, resolve_remote_input_payload
from .service import ChatRequest, ChatResult, ChatService


_SENSITIVE_KEY_PARTS = ("token", "cookie", "password", "secret", "authorization")
StreamProgressCallback = Callable[[ChatStreamEvent], Awaitable[None]]


def _redact_sensitive(value: Any) -> Any:
    """Recursively drop accidental credential-shaped fields from tool output."""
    if isinstance(value, dict):
        return {
            str(key): _redact_sensitive(item)
            for key, item in value.items()
            if not any(part in str(key).lower() for part in _SENSITIVE_KEY_PARTS)
        }
    if isinstance(value, list):
        return [_redact_sensitive(item) for item in value]
    return value


def _result_to_dict(result: ChatResult) -> Dict[str, Any]:
    return _redact_sensitive(
        {
            "ok": result.ok,
            "text": result.text,
            "conversation_id": result.conversation_id,
            "message_id": result.message_id,
            "requested_model": result.requested_model,
            "used_model": result.used_model,
            "image_urls": result.image_urls,
            "files": [
                {
                    "name": file.name,
                    "mime_type": file.mime_type,
                    "content_base64": base64.b64encode(file.content).decode("ascii"),
                }
                for file in result.files
            ],
            "usage": result.usage,
            "metadata": result.metadata,
            "errors": result.errors,
            "account": result.account,
            "content": result.content.to_dict(),
        }
    )


class McpServiceAdapter:
    """Small, confirmation-aware agent facade over :class:`ChatService`."""

    def __init__(
        self,
        service: ChatService,
        *,
        agent_safety_policy: AgentSafetyPolicy | None = None,
        agent_anchor_policy: AgentAnchorPolicy | None = None,
        max_attachment_bytes: int = 20 * 1024 * 1024,
        max_attachment_count: int = 8,
        remote_input_enabled: bool = True,
        remote_input_timeout_seconds: float = 15.0,
        remote_input_max_redirects: int = 3,
        remote_file_downloader: RemoteFileDownloader | None = None,
    ):
        self._service = service
        self._agent_safety_policy = agent_safety_policy
        self._agent_anchor_policy = agent_anchor_policy
        self._input_file_limits = InputFileLimits(
            max_files=max_attachment_count,
            max_file_bytes=max_attachment_bytes,
            max_total_bytes=max_attachment_bytes,
        )
        self._input_file_limits.validate()
        policy = RemoteFilePolicy(
            enabled=remote_input_enabled,
            timeout_seconds=remote_input_timeout_seconds,
            max_redirects=remote_input_max_redirects,
        )
        policy.validate()
        self._remote_file_downloader = remote_file_downloader or RemoteFileDownloader(policy)

    async def _input_files(self, attachments: List[Dict[str, Any]] | None):
        payload = await resolve_remote_input_payload(
            {"attachments": attachments},
            mode="custom",
            limits=self._input_file_limits,
            downloader=self._remote_file_downloader,
        )
        return input_files_from_attachments(
            payload.get("attachments"),
            limits=self._input_file_limits,
        )

    async def chat_send(
        self,
        prompt: str,
        *,
        model: str = "auto",
        conversation_id: str = "",
        parent_message_id: str = "",
        web_search: bool = False,
        attachments: List[Dict[str, Any]] | None = None,
        confirm: bool = False,
    ) -> Dict[str, Any]:
        """Send one buffered chat request after the caller explicitly confirms it."""
        if not prompt.strip():
            return {"ok": False, "error": "prompt must not be empty"}
        if not confirm:
            return {
                "ok": False,
                "error": "This action can consume account quota. Call again with confirm=true to send it.",
                "requires_confirmation": True,
            }
        try:
            files = await self._input_files(attachments)
        except InputFileError as error:
            return {"ok": False, "error": str(error)}
        result = await self._service.send(
            ChatRequest(
                prompt=prompt,
                model=model,
                conversation_id=conversation_id,
                parent_message_id=parent_message_id,
                files=files,
                web_search=web_search,
            )
        )
        return _result_to_dict(result)

    async def list_accounts(self) -> Dict[str, Any]:
        """Return account availability diagnostics without credentials."""
        status = await self._service.get_account_status()
        accounts = status.get("accounts")
        if not isinstance(accounts, list):
            accounts = [{"email": email} for email in status.get("account", []) if isinstance(email, str)]
        allowed = {
            "email", "status", "login_state", "available", "disabled", "disabled_until",
            "chat_rate_limited", "chat_rate_limited_until", "chat_rate_limit_source",
            "gptplus", "conversation_count", "login_failure_kind", "runtime",
            "operational_state", "operational_guidance", "recommended_action",
            "capability_quota",
        }
        return {
            "accounts": [
                _redact_sensitive({key: value for key, value in account.items() if key in allowed})
                for account in accounts
                if isinstance(account, dict)
            ]
        }

    async def chat_stream(
        self,
        prompt: str,
        *,
        model: str = "auto",
        conversation_id: str = "",
        parent_message_id: str = "",
        web_search: bool = False,
        attachments: List[Dict[str, Any]] | None = None,
        confirm: bool = False,
        progress_callback: StreamProgressCallback | None = None,
    ) -> Dict[str, Any]:
        """Stream a request through a callback and return its final normalized result."""
        if not prompt.strip():
            return {"ok": False, "error": "prompt must not be empty"}
        if not confirm:
            return {
                "ok": False,
                "error": "This action can consume account quota. Call again with confirm=true to send it.",
                "requires_confirmation": True,
            }

        try:
            files = await self._input_files(attachments)
        except InputFileError as error:
            return {"ok": False, "error": str(error)}

        async def on_event(event: ChatStreamEvent) -> None:
            if progress_callback:
                await progress_callback(event)

        result = await self._service.stream_to_callback(
            ChatRequest(
                prompt=prompt,
                model=model,
                conversation_id=conversation_id,
                parent_message_id=parent_message_id,
                files=files,
                web_search=web_search,
            ),
            on_event,
        )
        return _result_to_dict(result)

    async def list_models(self, fetch_remote: bool = False) -> Dict[str, Any]:
        """Return cached models, or explicitly request an authenticated refresh."""
        return _redact_sensitive(await self._service.get_model_catalog(fetch_remote=fetch_remote))

    async def get_conversation(self, conversation_id: str) -> List[Dict[str, str]]:
        """Return locally stored history for a known conversation identifier."""
        if not conversation_id.strip():
            return []
        return _redact_sensitive(await self._service.get_history(conversation_id))

    async def agent_turn(
        self,
        task: str,
        tools: List[Dict[str, Any]],
        *,
        state: Dict[str, Any] | None = None,
        tool_result: Dict[str, Any] | None = None,
        model: str = "auto",
        attachments: List[Dict[str, Any]] | None = None,
    ) -> Dict[str, Any]:
        """Return one agent decision; the MCP host executes requested tools itself."""
        try:
            registered = [AgentTool.from_dict(item) for item in tools]
            files = await self._input_files(attachments)
            turn = await AgentService(
                self._service,
                safety_policy=self._agent_safety_policy,
                anchor_policy=self._agent_anchor_policy,
            ).turn(
                task,
                registered,
                state=AgentState.from_dict(state),
                tool_result=AgentToolResult.from_dict(tool_result),
                model=model,
                files=files,
            )
        except ValueError as error:
            return {"ok": False, "error": str(error)}
        return _redact_sensitive(turn.to_dict())


def create_mcp_server(
    service: ChatService,
    *,
    agent_safety_policy: AgentSafetyPolicy | None = None,
    agent_anchor_policy: AgentAnchorPolicy | None = None,
    max_attachment_bytes: int = 20 * 1024 * 1024,
    max_attachment_count: int = 8,
    remote_input_enabled: bool = True,
    remote_input_timeout_seconds: float = 15.0,
    remote_input_max_redirects: int = 3,
    remote_file_downloader: RemoteFileDownloader | None = None,
):
    """Create a FastMCP server without importing the optional SDK at package import time."""
    try:
        from mcp.server.fastmcp import Context, FastMCP
    except ImportError as exc:
        raise RuntimeError("MCP support is optional. Install it with: pip install 'ChatGPTWeb[mcp]'") from exc

    # FastMCP evaluates nested tool annotations against this module's globals.
    globals()["Context"] = Context

    adapter = McpServiceAdapter(
        service,
        agent_safety_policy=agent_safety_policy,
        agent_anchor_policy=agent_anchor_policy,
        max_attachment_bytes=max_attachment_bytes,
        max_attachment_count=max_attachment_count,
        remote_input_enabled=remote_input_enabled,
        remote_input_timeout_seconds=remote_input_timeout_seconds,
        remote_input_max_redirects=remote_input_max_redirects,
        remote_file_downloader=remote_file_downloader,
    )
    server = FastMCP(
        "ChatGPTWeb",
        instructions=(
            "ChatGPTWeb tools use an existing logged-in browser runtime. "
            "chat_send requires confirm=true because it can consume account quota. "
            "agent_turn returns one validated decision only; the MCP host owns tool execution "
            "and must provide the next tool_result explicitly."
        ),
    )

    @server.tool()
    async def chat_send(
        prompt: str,
        model: str = "auto",
        conversation_id: str = "",
        parent_message_id: str = "",
        web_search: bool = False,
        attachments: List[Dict[str, Any]] | None = None,
        confirm: bool = False,
    ) -> Dict[str, Any]:
        """Send a ChatGPT request. Set confirm=true only after approving the quota spend."""
        return await adapter.chat_send(
            prompt,
            model=model,
            conversation_id=conversation_id,
            parent_message_id=parent_message_id,
            web_search=web_search,
            attachments=attachments,
            confirm=confirm,
        )

    @server.tool()
    async def chat_stream(
        prompt: str,
        ctx: Context,
        model: str = "auto",
        conversation_id: str = "",
        parent_message_id: str = "",
        web_search: bool = False,
        attachments: List[Dict[str, Any]] | None = None,
        confirm: bool = False,
    ) -> Dict[str, Any]:
        """Stream text deltas as MCP progress notifications, then return the complete result."""
        progress = 0

        async def report_event(event: ChatStreamEvent) -> None:
            nonlocal progress
            if event.type == "delta":
                progress += 1
                await ctx.report_progress(progress, message=event.text)
            elif event.type == "status":
                phase = event.metadata.get("phase", "waiting")
                await ctx.report_progress(progress, message=f"[{phase}]")

        return await adapter.chat_stream(
            prompt,
            model=model,
            conversation_id=conversation_id,
            parent_message_id=parent_message_id,
            web_search=web_search,
            attachments=attachments,
            confirm=confirm,
            progress_callback=report_event,
        )

    @server.tool()
    async def list_accounts() -> Dict[str, Any]:
        """List account availability and runtime diagnostics without credentials."""
        return await adapter.list_accounts()

    @server.tool()
    async def list_models(fetch_remote: bool = False) -> Dict[str, Any]:
        """List model capabilities; remote refresh is opt-in because it uses the browser runtime."""
        return await adapter.list_models(fetch_remote=fetch_remote)

    @server.tool()
    async def get_conversation(conversation_id: str) -> List[Dict[str, str]]:
        """Read locally stored history for one conversation."""
        return await adapter.get_conversation(conversation_id)

    @server.tool()
    async def agent_turn(
        task: str,
        tools: List[Dict[str, Any]],
        state: Dict[str, Any] | None = None,
        tool_result: Dict[str, Any] | None = None,
        model: str = "auto",
        attachments: List[Dict[str, Any]] | None = None,
    ) -> Dict[str, Any]:
        """Get one validated agent tool-call/final decision; execute tools in the host, then call again with tool_result."""
        return await adapter.agent_turn(
            task,
            tools,
            state=state,
            tool_result=tool_result,
            model=model,
            attachments=attachments,
        )

    return server
