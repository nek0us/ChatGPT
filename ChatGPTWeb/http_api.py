"""Optional aiohttp adapter over :mod:`ChatGPTWeb.service`."""

import base64
import binascii
import asyncio
import hmac
import json
import logging
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

from aiohttp import web

from .agent import AgentAnchorPolicy, AgentSafetyPolicy, AgentService, AgentState, AgentTool, AgentToolResult
from .api_keys import ApiKeyStore
from .api import ChatStreamEvent
from .config import IOFile
from .control_ui import CONTROL_HTML
from .service import ChatRequest, ChatResult, ChatService, ConversationOperation
from .verification import VerificationBroker

SERVICE_KEY: web.AppKey[ChatService] = web.AppKey("chatgptweb_service", ChatService)
API_KEY_STORE: web.AppKey[ApiKeyStore] = web.AppKey("chatgptweb_api_key_store", ApiKeyStore)
API_PRINCIPAL: web.RequestKey[Any] = web.RequestKey("chatgptweb_api_principal", object)
logger = logging.getLogger(__name__)


@dataclass
class _OpenAIAgentCursor:
    state: AgentState
    tools: list[AgentTool]
    tool_name: str
    expires_at: float
    client_id: str


@dataclass
class _ResponseCursor:
    """Server-side state for one OpenAI Responses continuation."""

    conversation_id: str
    parent_message_id: str
    model: str
    expires_at: float
    client_id: str
    agent_state: AgentState | None = None
    tools: list[AgentTool] | None = None
    tool_name: str = ""
    tool_call_id: str = ""


def _text_content(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("type") in ("text", "input_text"):
                text = item.get("text") or item.get("content")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    return ""


def _prompt_from_payload(payload: Dict[str, Any]) -> str:
    prompt = payload.get("prompt")
    if isinstance(prompt, str) and prompt.strip():
        return prompt

    messages = payload.get("messages")
    if not isinstance(messages, list) or not messages:
        raise web.HTTPBadRequest(text="request requires a non-empty prompt or messages array")

    rendered: List[str] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        text = _text_content(message.get("content"))
        if not text:
            continue
        role = message.get("role", "user")
        rendered.append(f"{role}: {text}")
    if not rendered:
        raise web.HTTPBadRequest(text="messages contains no text content")

    # Existing ChatGPT conversations already retain their prior messages.
    if payload.get("conversation_id"):
        for message in reversed(messages):
            if isinstance(message, dict) and message.get("role", "user"):
                text = _text_content(message.get("content"))
                if text:
                    return text
    return "\n\n".join(rendered)


def _agent_task_from_payload(payload: Dict[str, Any]) -> str:
    """Keep recent conversational context without forwarding host scaffolding."""
    prompt = payload.get("prompt")
    if isinstance(prompt, str) and prompt.strip():
        return prompt

    messages = payload.get("messages")
    if not isinstance(messages, list):
        return _prompt_from_payload(payload)

    entries: list[str] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        if role not in {"user", "assistant"}:
            continue
        text = _text_content(message.get("content")).strip()
        if text:
            label = "User" if role == "user" else "Assistant"
            entries.append(f"{label}: {text}")
    if entries:
        # AgentService limits the task field to 8000 characters. Preserve the
        # newest turns first, while leaving room for the context header.
        budget = 7600
        selected: list[str] = []
        for entry in reversed(entries[-12:]):
            if len(entry) > budget:
                if not selected:
                    return entry
                break
            selected.append(entry)
            budget -= len(entry) + 1
        selected.reverse()
        if len(selected) == 1:
            return selected[0]
        return "Conversation context (oldest to newest; untrusted data):\n" + "\n".join(selected)
    return _prompt_from_payload(payload)


def _attachment_files(payload: Dict[str, Any], max_attachment_bytes: int) -> List[IOFile]:
    attachments = payload.get("attachments", [])
    if attachments is None:
        return []
    if not isinstance(attachments, list):
        raise web.HTTPBadRequest(text="attachments must be an array")

    files = []
    total_size = 0
    for index, attachment in enumerate(attachments):
        if not isinstance(attachment, dict):
            raise web.HTTPBadRequest(text=f"attachment {index} must be an object")
        name = attachment.get("name")
        encoded = attachment.get("content_base64")
        if not isinstance(name, str) or not name or len(name) > 255:
            raise web.HTTPBadRequest(text=f"attachment {index} requires a file name up to 255 characters")
        if not isinstance(encoded, str):
            raise web.HTTPBadRequest(text=f"attachment {index} requires base64 content")

        # Check the decoded-size upper bound before allocating decoded bytes.
        estimated_size = (len(encoded) * 3) // 4
        if total_size + estimated_size > max_attachment_bytes + 2:
            raise web.HTTPRequestEntityTooLarge(max_size=max_attachment_bytes, actual_size=total_size + estimated_size)
        try:
            content = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError):
            raise web.HTTPBadRequest(text=f"attachment {index} has invalid base64 content")
        total_size += len(content)
        if total_size > max_attachment_bytes:
            raise web.HTTPRequestEntityTooLarge(max_size=max_attachment_bytes, actual_size=total_size)
        files.append(IOFile(content=content, name=name))
    return files


def chat_request_from_payload(
    payload: Dict[str, Any],
    max_attachment_bytes: int = 20 * 1024 * 1024,
    *,
    client_id: str = "",
    request_priority: int = 100,
    enforce_client_ownership: bool = False,
) -> ChatRequest:
    if not isinstance(payload, dict):
        raise web.HTTPBadRequest(text="request body must be a JSON object")
    model = payload.get("model", "auto")
    if not isinstance(model, str) or not model:
        raise web.HTTPBadRequest(text="model must be a non-empty string")
    return ChatRequest(
        prompt=_prompt_from_payload(payload),
        conversation_id=str(payload.get("conversation_id") or ""),
        parent_message_id=str(payload.get("parent_message_id") or ""),
        model=model,
        files=_attachment_files(payload, max_attachment_bytes),
        web_search=bool(payload.get("web_search", False)),
        deep_research=bool(payload.get("deep_research", False)),
        stream_idle_timeout_seconds=max(0, int(payload.get("stream_idle_timeout_seconds", 0) or 0)),
        stream_status_interval_seconds=max(0, int(payload.get("stream_status_interval_seconds", 15) or 0)),
        client_id=client_id,
        request_priority=request_priority,
        enforce_client_ownership=enforce_client_ownership,
    )


def _bot_chat_request_from_payload(
    payload: Dict[str, Any],
    *,
    max_attachment_bytes: int,
    client_id: str,
) -> ChatRequest:
    request = chat_request_from_payload(
        payload,
        max_attachment_bytes=max_attachment_bytes,
        client_id=client_id,
        request_priority=10,
        enforce_client_ownership=True,
    )
    request.prefer_paid_account = bool(payload.get("prefer_paid_account", False))
    raw_operation = payload.get("operation", ConversationOperation.SEND.value)
    try:
        request.operation = ConversationOperation(raw_operation)
    except (TypeError, ValueError) as error:
        raise web.HTTPBadRequest(text="unsupported bot conversation operation") from error
    reference = payload.get("reference", "")
    if not isinstance(reference, str):
        raise web.HTTPBadRequest(text="bot reference must be a string")
    request.reference = reference
    if request.operation is ConversationOperation.START_PERSONA:
        persona_name = request.prompt.strip()
        if not persona_name:
            raise web.HTTPBadRequest(text="bot persona name must not be empty")
        request.prompt = f"__bot_persona__:{client_id}:{persona_name}"
    return request


def _chat_result_payload(result: ChatResult) -> Dict[str, Any]:
    return {
        "ok": result.ok,
        "text": result.text,
        "conversation_id": result.conversation_id,
        "message_id": result.message_id,
        "requested_model": result.requested_model,
        "used_model": result.used_model,
        "image_urls": result.image_urls,
        "usage": result.usage,
        "metadata": result.metadata,
        "errors": result.errors,
        "account": result.account,
        "content": result.content.to_dict(),
    }


def _stream_event_payload(event: ChatStreamEvent) -> Dict[str, Any]:
    return {
        "type": event.type,
        "text": event.text,
        "raw_text": event.raw_text,
        "message_id": event.message_id,
        "conversation_id": event.conversation_id,
        "image_urls": event.image_urls,
        "model": event.model,
        "usage": event.usage,
        "metadata": event.metadata,
    }


def _agent_tools_from_payload(payload: Dict[str, Any]) -> List[AgentTool]:
    tools = payload.get("tools")
    if not isinstance(tools, list) or not tools:
        raise web.HTTPBadRequest(text="agent request requires a non-empty tools array")
    if len(tools) > 64:
        raise web.HTTPBadRequest(text="agent request supports at most 64 tools")
    if not all(isinstance(item, dict) for item in tools):
        raise web.HTTPBadRequest(text="every agent tool must be an object")
    try:
        return [AgentTool.from_dict(item) for item in tools]
    except ValueError as error:
        raise web.HTTPBadRequest(text=str(error)) from error


async def agent_turn_from_payload(
    service: ChatService,
    payload: Dict[str, Any],
    *,
    agent_safety_policy: AgentSafetyPolicy | None = None,
    agent_anchor_policy: AgentAnchorPolicy | None = None,
    client_id: str = "",
    request_priority: int = 120,
) -> Dict[str, Any]:
    """Translate an external host's agent turn without executing host tools."""
    if not isinstance(payload, dict):
        raise web.HTTPBadRequest(text="request body must be a JSON object")
    task = payload.get("task", "")
    if not isinstance(task, str):
        raise web.HTTPBadRequest(text="agent task must be a string")
    try:
        state = AgentState.from_dict(payload.get("state"))
        tool_result = AgentToolResult.from_dict(payload.get("tool_result"))
    except ValueError as error:
        raise web.HTTPBadRequest(text=str(error)) from error
    model = payload.get("model", state.model or "auto")
    if not isinstance(model, str) or not model.strip():
        raise web.HTTPBadRequest(text="agent model must be a non-empty string")
    turn = await AgentService(
        service,
        safety_policy=agent_safety_policy,
        anchor_policy=agent_anchor_policy,
        client_id=client_id,
        request_priority=request_priority,
        enforce_client_ownership=bool(client_id),
    ).turn(
        task,
        _agent_tools_from_payload(payload),
        state=state,
        tool_result=tool_result,
        model=model,
    )
    return turn.to_dict()


def _openai_agent_tools(payload: Dict[str, Any]) -> list[AgentTool]:
    raw_tools = payload.get("tools")
    if not isinstance(raw_tools, list) or not raw_tools:
        raise web.HTTPBadRequest(text="tools must be a non-empty array")
    converted: list[dict[str, Any]] = []
    for item in raw_tools:
        if not isinstance(item, dict):
            raise web.HTTPBadRequest(text="every tool must be an object")
        function = item.get("function") if item.get("type") == "function" else item
        if not isinstance(function, dict):
            raise web.HTTPBadRequest(text="OpenAI tool requires a function object")
        converted.append({
            "name": function.get("name"),
            "description": function.get("description"),
            "input_schema": function.get("parameters", {"type": "object", "properties": {}}),
        })
    try:
        tools = [AgentTool.from_dict(item) for item in converted]
    except ValueError as error:
        raise web.HTTPBadRequest(text=str(error)) from error
    logger.debug(
        "OpenAI-compatible agent request received %d host tools: %s",
        len(tools),
        ", ".join(tool.name for tool in tools),
    )
    return tools


def _latest_openai_tool_call_id(payload: Dict[str, Any]) -> str:
    """Return the most recent standard OpenAI tool-call identifier, if any."""
    messages = payload.get("messages")
    if not isinstance(messages, list):
        return ""
    for message in reversed(messages):
        if not isinstance(message, dict) or message.get("role") != "tool":
            continue
        tool_call_id = message.get("tool_call_id")
        if isinstance(tool_call_id, str) and tool_call_id:
            return tool_call_id
    return ""


def _tool_result_from_openai_messages(
    payload: Dict[str, Any], cursor: _OpenAIAgentCursor, tool_call_id: str,
) -> AgentToolResult:
    messages = payload.get("messages")
    if not isinstance(messages, list):
        raise web.HTTPBadRequest(text="tool continuation requires messages")
    for message in reversed(messages):
        if not isinstance(message, dict) or message.get("role") != "tool":
            continue
        if message.get("tool_call_id") != tool_call_id:
            continue
        content = _text_content(message.get("content"))
        return AgentToolResult(cursor.tool_name, content[:12000], ok=True)
    raise web.HTTPBadRequest(text="tool continuation requires the matching role=tool result")


def _response_input_text(payload: Dict[str, Any]) -> str:
    """Extract only this Responses turn; previous state stays server-side."""
    value = payload.get("input")
    if isinstance(value, str):
        text = value.strip()
        if text:
            return text
    elif isinstance(value, list):
        entries: list[str] = []
        for item in value:
            if not isinstance(item, dict) or item.get("type") == "function_call_output":
                continue
            role = item.get("role") if isinstance(item.get("role"), str) else "user"
            text = _text_content(item.get("content")).strip()
            if text:
                entries.append(f"{role}: {text}" if role != "user" else text)
        if entries:
            return "\n\n".join(entries)
    raise web.HTTPBadRequest(text="responses request requires non-empty text input")


def _response_instructions(payload: Dict[str, Any]) -> str:
    value = payload.get("instructions")
    if value is None:
        return ""
    if not isinstance(value, str):
        raise web.HTTPBadRequest(text="responses instructions must be a string")
    return value.strip()


def _response_model(payload: Dict[str, Any], cursor: _ResponseCursor | None = None) -> str:
    value = payload.get("model", cursor.model if cursor else "auto")
    if not isinstance(value, str) or not value.strip():
        raise web.HTTPBadRequest(text="responses model must be a non-empty string")
    return value.strip()


def _response_tool_result(payload: Dict[str, Any], cursor: _ResponseCursor) -> AgentToolResult:
    if not cursor.tool_call_id or not cursor.tool_name:
        raise web.HTTPBadRequest(text="previous response is not awaiting a function result")
    value = payload.get("input")
    if not isinstance(value, list):
        raise web.HTTPBadRequest(text="function continuation requires input items")
    for item in value:
        if not isinstance(item, dict) or item.get("type") != "function_call_output":
            continue
        if item.get("call_id") != cursor.tool_call_id:
            continue
        output = item.get("output")
        if isinstance(output, str):
            return AgentToolResult(cursor.tool_name, output[:12000], ok=True)
        return AgentToolResult(cursor.tool_name, json.dumps(output, ensure_ascii=False)[:12000], ok=True)
    raise web.HTTPBadRequest(text="function continuation requires matching function_call_output")


def _response_payload(
    response_id: str,
    *,
    model: str,
    previous_response_id: str = "",
    result: ChatResult | None = None,
    turn: Any = None,
    tool_call_id: str = "",
) -> Dict[str, Any]:
    output: list[dict[str, Any]]
    output_text = ""
    status = "completed"
    usage: dict[str, Any] = {}
    if turn is not None:
        decision = turn.decision
        if decision.kind == "tool_call":
            output = [{
                "type": "function_call",
                "id": f"fc_{uuid.uuid4().hex}",
                "call_id": tool_call_id,
                "name": decision.tool,
                "arguments": json.dumps(decision.arguments, ensure_ascii=False),
                "status": "completed",
            }]
        elif decision.kind == "final":
            output_text = decision.answer
            output = [{
                "type": "message",
                "id": f"msg_{uuid.uuid4().hex}",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": output_text, "annotations": []}],
            }]
        else:
            status = "failed"
            output_text = decision.error
            output = []
    elif result is not None:
        status = "completed" if result.ok else "failed"
        output_text = result.text
        usage = dict(result.usage)
        output = [{
            "type": "message",
            "id": result.message_id or f"msg_{uuid.uuid4().hex}",
            "role": "assistant",
            "status": "completed" if result.ok else "incomplete",
            "content": [{"type": "output_text", "text": output_text, "annotations": []}],
        }] if output_text else []
    else:
        raise ValueError("response requires a chat result or agent turn")
    return {
        "id": response_id,
        "object": "response",
        "created_at": int(time.time()),
        "status": status,
        "model": model,
        "output": output,
        "output_text": output_text,
        "previous_response_id": previous_response_id or None,
        "usage": usage,
    }


def _result_payload(result: ChatResult, request_id: str) -> Dict[str, Any]:
    return {
        "id": request_id,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": result.used_model or result.requested_model,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": result.text},
            "finish_reason": "stop" if result.ok else "error",
        }],
        "chatgptweb": {
            "ok": result.ok,
            "conversation_id": result.conversation_id,
            "message_id": result.message_id,
            "requested_model": result.requested_model,
            "used_model": result.used_model,
            "image_urls": result.image_urls,
            "usage": result.usage,
            "metadata": result.metadata,
            "errors": result.errors,
            "content": result.content.to_dict(),
        },
    }


def _agent_completion_payload(turn, request_id: str, model: str, tool_call_id: str = "") -> Dict[str, Any]:
    decision = turn.decision
    if decision.kind == "tool_call":
        message: dict[str, Any] = {
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": tool_call_id,
                "type": "function",
                "function": {
                    "name": decision.tool,
                    "arguments": json.dumps(decision.arguments, ensure_ascii=False),
                },
            }],
        }
        finish_reason = "tool_calls"
    elif decision.kind == "final":
        message = {"role": "assistant", "content": decision.answer}
        finish_reason = "stop"
    else:
        message = {"role": "assistant", "content": decision.error}
        finish_reason = "error"
    return {
        "id": request_id,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": turn.used_model or model,
        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
        "chatgptweb": {
            "ok": turn.ok,
            "agent": turn.to_dict(),
            "tool_call_id": tool_call_id,
        },
    }


def _agent_chunk_payload(
    request_id: str,
    model: str,
    delta: Dict[str, Any],
    finish_reason: str | None = None,
) -> Dict[str, Any]:
    """Build one OpenAI-compatible SSE chunk for a buffered agent decision."""
    return {
        "id": request_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{
            "index": 0,
            "delta": delta,
            "finish_reason": finish_reason,
        }],
    }


async def _stream_agent_completion(
    request: web.Request,
    turn,
    request_id: str,
    model: str,
    tool_call_id: str,
) -> web.StreamResponse:
    """Expose one buffered agent turn through OpenAI's streamed tool-call shape.

    The model-decision request remains deliberately buffered: a tool call must
    be schema-validated before any bytes can invite a host to execute it.  The
    OpenAI-compatible client nevertheless receives normal SSE chunks, which is
    required by coding agents such as OpenCode.
    """
    response = web.StreamResponse(headers={
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
    })
    await response.prepare(request)
    decision = turn.decision
    try:
        if decision.kind == "tool_call":
            arguments = json.dumps(decision.arguments, ensure_ascii=False, separators=(",", ":"))
            await response.write(_sse(None, _agent_chunk_payload(request_id, model, {
                "role": "assistant",
                "tool_calls": [{
                    "index": 0,
                    "id": tool_call_id,
                    "type": "function",
                    "function": {"name": decision.tool, "arguments": ""},
                }],
            })))
            await response.write(_sse(None, _agent_chunk_payload(request_id, model, {
                "tool_calls": [{
                    "index": 0,
                    "function": {"arguments": arguments},
                }],
            })))
            finish_reason = "tool_calls"
        else:
            answer = decision.answer if decision.kind == "final" else decision.error
            await response.write(_sse(None, _agent_chunk_payload(
                request_id,
                model,
                {"role": "assistant", "content": answer},
            )))
            finish_reason = "stop"
        await response.write(_sse(None, _agent_chunk_payload(request_id, model, {}, finish_reason)))
        await response.write(_sse(None, "[DONE]"))
        await response.write_eof()
    except ConnectionResetError:
        return response
    return response


def _sse(event: str | None, payload: Any) -> bytes:
    prefix = f"event: {event}\n" if event else ""
    data = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    return f"{prefix}data: {data}\n\n".encode("utf-8")


def _chunk_payload(event: ChatStreamEvent, request_id: str, model: str, finish_reason: str | None = None) -> Dict[str, Any]:
    return {
        "id": request_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": event.model or model,
        "choices": [{
            "index": 0,
            "delta": {"content": event.text} if event.text else {},
            "finish_reason": finish_reason,
        }],
    }


def create_http_app(
    service: ChatService,
    api_key: str | None = None,
    api_key_store: ApiKeyStore | None = None,
    max_attachment_bytes: int = 20 * 1024 * 1024,
    verification_broker: VerificationBroker | None = None,
    agent_safety_policy: AgentSafetyPolicy | None = None,
    agent_anchor_policy: AgentAnchorPolicy | None = None,
    runtime_log_path: Path | str | None = None,
) -> web.Application:
    """Create an opt-in local API application without opening a listening port."""
    if max_attachment_bytes <= 0:
        raise ValueError("max_attachment_bytes must be positive")
    agent_cursors: dict[str, _OpenAIAgentCursor] = {}
    response_cursors: dict[str, _ResponseCursor] = {}
    # A host such as OpenCode can create independent subagent sessions. Do not
    # pin all of them to one shared protocol root: a fresh task should enter
    # the runtime's account pool, while its cursor still pins every follow-up
    # tool round to the selected account. Callers may opt back into anchors.
    openai_agent_anchor_policy = agent_anchor_policy or AgentAnchorPolicy(control_enabled=False)
    log_path = Path(runtime_log_path).expanduser() if runtime_log_path else None

    def discard_agent_cursors() -> None:
        now = time.monotonic()
        for token, cursor in tuple(agent_cursors.items()):
            if cursor.expires_at <= now:
                agent_cursors.pop(token, None)

    def discard_response_cursors() -> None:
        now = time.monotonic()
        for token, cursor in tuple(response_cursors.items()):
            if cursor.expires_at <= now:
                response_cursors.pop(token, None)

    def supplied_bearer(request: web.Request) -> str:
        return request.headers.get("Authorization", "").removeprefix("Bearer ").strip()

    def client_identity(request: web.Request) -> str:
        principal = request.get(API_PRINCIPAL)
        if isinstance(principal, dict):
            key_id = principal.get("id")
            if isinstance(key_id, str) and key_id:
                return f"api:{key_id}"
        return "api:admin"

    def bot_persona_name(request: web.Request, name: Any) -> str:
        if not isinstance(name, str) or not name.strip():
            raise web.HTTPBadRequest(text="bot persona requires a non-empty name")
        normalized = name.strip()
        if len(normalized) > 128:
            raise web.HTTPBadRequest(text="bot persona name is too long")
        # Store each Bot client's prompts in a separate namespace.  This keeps
        # a shared core from accidentally exposing or overwriting another
        # plugin instance's persona definitions.
        return f"__bot_persona__:{client_identity(request)}:{normalized}"

    def require_admin(request: web.Request) -> None:
        if request.get(API_PRINCIPAL) != "admin":
            raise web.HTTPForbidden(text="administrator API key required")

    @web.middleware
    async def auth_middleware(request: web.Request, handler):
        if request.path in ("/", "/health"):
            return await handler(request)
        # Keep the original no-auth local application behavior for callers
        # that intentionally create an app without either key mechanism.
        if not api_key and not api_key_store:
            request[API_PRINCIPAL] = "admin"
            return await handler(request)
        supplied = supplied_bearer(request)
        if api_key and hmac.compare_digest(supplied, api_key):
            request[API_PRINCIPAL] = "admin"
            return await handler(request)
        record = api_key_store.authenticate(supplied) if api_key_store else None
        if record is None:
            raise web.HTTPUnauthorized(text="invalid API key")
        if request.path == "/v1/models":
            permitted = "chat" in record["scopes"]
        elif request.path in {"/v1/chat/completions", "/v1/responses"}:
            permitted = "chat" in record["scopes"]
        elif request.path == "/v1/agent/turn":
            permitted = "agent" in record["scopes"]
        elif request.path.startswith("/v1/bot/"):
            permitted = "bot" in record["scopes"]
        else:
            permitted = False
        if not permitted:
            raise web.HTTPForbidden(text="API key is not permitted for this endpoint")
        if not api_key_store.acquire(record):
            raise web.HTTPTooManyRequests(text="API key concurrency limit reached")
        request[API_PRINCIPAL] = record
        try:
            return await handler(request)
        finally:
            api_key_store.release(record)

    async def health(_: web.Request) -> web.Response:
        payload = await service.get_runtime_health()
        payload["api"] = {
            "version": "2026-07-29",
            "capabilities": ["chat_completions", "responses", "agent_turn", "bot_bridge"],
        }
        return web.json_response(payload)

    async def models(_: web.Request) -> web.Response:
        return web.json_response(await service.get_model_catalog(fetch_remote=False))

    async def account_status(_: web.Request) -> web.Response:
        return web.json_response(await service.get_account_status())

    async def usage_status(_: web.Request) -> web.Response:
        return web.json_response(await service.get_usage_status())

    async def activity(request: web.Request) -> web.Response:
        try:
            limit = int(request.query.get("limit", "50"))
        except ValueError as error:
            raise web.HTTPBadRequest(text="limit must be an integer") from error
        return web.json_response(await service.get_activity(limit=limit))

    async def runtime_logs(request: web.Request) -> web.Response:
        """Return a bounded tail of this runtime's own log to administrators."""
        require_admin(request)
        if not log_path:
            return web.json_response({"available": False, "message": "runtime log is not configured", "lines": []})
        try:
            lines = max(20, min(int(request.query.get("lines", "160")), 800))
        except ValueError as error:
            raise web.HTTPBadRequest(text="lines must be an integer") from error
        try:
            with log_path.open("rb") as handle:
                handle.seek(0, 2)
                size = handle.tell()
                handle.seek(max(0, size - 256 * 1024))
                text = handle.read().decode("utf8", errors="replace")
        except FileNotFoundError:
            return web.json_response({"available": False, "message": "runtime log does not exist yet", "lines": []})
        except OSError as error:
            logger.warning("could not read runtime log %s: %s", log_path, error)
            return web.json_response({"available": False, "message": "runtime log cannot be read", "lines": []})
        return web.json_response({"available": True, "message": "", "lines": text.splitlines()[-lines:]})

    async def control_account(request: web.Request) -> web.Response:
        require_admin(request)
        try:
            payload = await request.json()
        except (json.JSONDecodeError, ValueError):
            raise web.HTTPBadRequest(text="request body must be valid JSON")
        action = payload.get("action") if isinstance(payload, dict) else None
        if not isinstance(action, str):
            raise web.HTTPBadRequest(text="request requires an account action")
        try:
            account = await service.control_account(request.match_info["account"], action)
        except KeyError as error:
            raise web.HTTPNotFound(text=str(error)) from error
        except ValueError as error:
            raise web.HTTPBadRequest(text=str(error)) from error
        return web.json_response({"account": account})

    def require_verification_broker() -> VerificationBroker:
        if not verification_broker:
            raise web.HTTPNotImplemented(text="verification control is not enabled")
        return verification_broker

    async def verification_status(_: web.Request) -> web.Response:
        require_admin(_)
        return web.json_response({"challenges": await require_verification_broker().snapshot()})

    async def submit_verification(request: web.Request) -> web.Response:
        require_admin(request)
        try:
            payload = await request.json()
        except (json.JSONDecodeError, ValueError):
            raise web.HTTPBadRequest(text="request body must be valid JSON")
        code = payload.get("code") if isinstance(payload, dict) else None
        if not isinstance(code, str):
            raise web.HTTPBadRequest(text="request requires a verification code")
        try:
            accepted = await require_verification_broker().submit(request.match_info["challenge_id"], code)
        except ValueError as error:
            raise web.HTTPBadRequest(text=str(error)) from error
        if not accepted:
            raise web.HTTPNotFound(text="verification challenge is no longer pending")
        return web.json_response({"accepted": True})

    async def cancel_verification(request: web.Request) -> web.Response:
        require_admin(request)
        cancelled = await require_verification_broker().cancel(request.match_info["challenge_id"])
        if not cancelled:
            raise web.HTTPNotFound(text="verification challenge is no longer pending")
        return web.json_response({"cancelled": True})

    async def bot_capabilities(request: web.Request) -> web.Response:
        return web.json_response({
            "protocol_version": 1,
            "client_id": client_identity(request),
            "capabilities": [
                "chat", "stream", "history", "persona", "persona_sync", "context_estimate",
            ],
            "runtime": await service.get_runtime_health(),
        })

    async def bot_payload(request: web.Request) -> Dict[str, Any]:
        try:
            payload = await request.json()
        except (json.JSONDecodeError, ValueError):
            raise web.HTTPBadRequest(text="request body must be valid JSON")
        if not isinstance(payload, dict):
            raise web.HTTPBadRequest(text="request body must be a JSON object")
        return payload

    async def bot_chat(request: web.Request) -> web.Response:
        chat_request = _bot_chat_request_from_payload(
            await bot_payload(request),
            max_attachment_bytes=max_attachment_bytes,
            client_id=client_identity(request),
        )
        return web.json_response(_chat_result_payload(await service.send(chat_request)))

    async def bot_chat_stream(request: web.Request) -> web.StreamResponse:
        chat_request = _bot_chat_request_from_payload(
            await bot_payload(request),
            max_attachment_bytes=max_attachment_bytes,
            client_id=client_identity(request),
        )
        if chat_request.operation is not ConversationOperation.SEND:
            raise web.HTTPBadRequest(text="bot streaming supports only normal send operations")
        response = web.StreamResponse(headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        })
        await response.prepare(request)
        stream = service.stream(chat_request)
        try:
            async for event in stream:
                await response.write(_sse("chatgptweb.event", _stream_event_payload(event)))
            await response.write(_sse("chatgptweb.done", {"ok": True}))
            await response.write_eof()
        except ConnectionResetError:
            return response
        finally:
            await stream.aclose()
        return response

    async def bot_history(request: web.Request) -> web.Response:
        payload = await bot_payload(request)
        conversation_id = payload.get("conversation_id")
        if not isinstance(conversation_id, str) or not conversation_id:
            raise web.HTTPBadRequest(text="bot history requires conversation_id")
        try:
            await service.assert_conversation_access(conversation_id, client_identity(request))
        except PermissionError as error:
            raise web.HTTPForbidden(text=str(error)) from error
        return web.json_response({"history": await service.get_history(conversation_id)})

    async def bot_persona(request: web.Request) -> web.Response:
        payload = await bot_payload(request)
        name = bot_persona_name(request, payload.get("name"))
        return web.json_response({"prompt": await service.get_persona_prompt(name)})

    async def bot_personas(request: web.Request) -> web.Response:
        prefix = f"__bot_persona__:{client_identity(request)}:"
        personas = await service.list_personas()
        return web.json_response({"personas": [
            {"name": item["name"][len(prefix):], "value": item["value"]}
            for item in personas
            if item.get("name", "").startswith(prefix)
        ]})

    async def bot_upsert_persona(request: web.Request) -> web.Response:
        payload = await bot_payload(request)
        value = payload.get("value")
        if not isinstance(value, str):
            raise web.HTTPBadRequest(text="bot persona value must be a string")
        name = bot_persona_name(request, payload.get("name"))
        await service.upsert_persona(name, value)
        return web.json_response({"ok": True})

    async def bot_delete_persona(request: web.Request) -> web.Response:
        payload = await bot_payload(request)
        name = bot_persona_name(request, payload.get("name"))
        await service.delete_persona(name)
        return web.json_response({"ok": True})

    async def bot_context_estimate(request: web.Request) -> web.Response:
        payload = await bot_payload(request)
        conversation_id = payload.get("conversation_id")
        if not isinstance(conversation_id, str) or not conversation_id:
            raise web.HTTPBadRequest(text="bot context estimate requires conversation_id")
        try:
            await service.assert_conversation_access(conversation_id, client_identity(request))
        except PermissionError as error:
            raise web.HTTPForbidden(text=str(error)) from error
        model = payload.get("model", "")
        account = payload.get("account", "")
        if not isinstance(model, str) or not isinstance(account, str):
            raise web.HTTPBadRequest(text="bot context model and account must be strings")
        estimate = await service.estimate_context(conversation_id, model=model, account=account)
        return web.json_response({"estimate": dict(estimate.__dict__)})

    async def chat_completions(request: web.Request) -> web.StreamResponse:
        try:
            payload = await request.json()
        except (json.JSONDecodeError, ValueError):
            raise web.HTTPBadRequest(text="request body must be valid JSON")
        request_id = f"chatcmpl-{uuid.uuid4().hex}"
        client_id = client_identity(request)
        supplied_call_id = payload.get("chatgptweb_tool_call_id")
        if supplied_call_id is not None and not isinstance(supplied_call_id, str):
            raise web.HTTPBadRequest(text="chatgptweb_tool_call_id must be a string")
        discard_agent_cursors()
        tool_call_id = supplied_call_id or _latest_openai_tool_call_id(payload)
        cursor = agent_cursors.get(tool_call_id) if tool_call_id else None
        if cursor is not None and cursor.client_id != client_id:
            raise web.HTTPForbidden(text="tool-call cursor belongs to another API client")
        if tool_call_id and cursor is None and payload.get("tools") is None:
            raise web.HTTPBadRequest(text="tool-call cursor is unknown or expired; restart the agent request")
        if payload.get("tools") is not None or cursor is not None:
            if cursor is None:
                tools = _openai_agent_tools(payload)
            else:
                tools = cursor.tools
            try:
                if cursor is None:
                    turn = await AgentService(
                        service,
                        safety_policy=agent_safety_policy,
                        anchor_policy=openai_agent_anchor_policy,
                        client_id=client_id,
                        request_priority=120,
                        enforce_client_ownership=True,
                    ).turn(
                        _agent_task_from_payload(payload), tools, model=str(payload.get("model") or "auto"),
                    )
                else:
                    # Keep the stored tool set instead of trusting a continuation to broaden it.
                    result = _tool_result_from_openai_messages(payload, cursor, tool_call_id)
                    agent_cursors.pop(tool_call_id, None)
                    turn = await AgentService(
                        service,
                        safety_policy=agent_safety_policy,
                        anchor_policy=openai_agent_anchor_policy,
                        client_id=client_id,
                        request_priority=120,
                        enforce_client_ownership=True,
                    ).turn(
                        "", cursor.tools, state=cursor.state, tool_result=result, model=cursor.state.model,
                    )
            except ValueError as error:
                raise web.HTTPBadRequest(text=str(error)) from error
            call_id = ""
            if turn.ok and turn.decision.kind == "tool_call":
                call_id = f"call_{uuid.uuid4().hex}"
                agent_cursors[call_id] = _OpenAIAgentCursor(
                    state=turn.state,
                    tools=tools if cursor is None else cursor.tools,
                    tool_name=turn.decision.tool,
                    expires_at=time.monotonic() + 600,
                    client_id=client_id,
                )
            if payload.get("stream", False):
                return await _stream_agent_completion(
                    request,
                    turn,
                    request_id,
                    str(payload.get("model") or "auto"),
                    call_id,
                )
            return web.json_response(_agent_completion_payload(turn, request_id, str(payload.get("model") or "auto"), call_id))

        chat_request = chat_request_from_payload(
            payload,
            max_attachment_bytes=max_attachment_bytes,
            client_id=client_id,
            request_priority=100,
            enforce_client_ownership=True,
        )
        if not payload.get("stream", False):
            result = await service.send(chat_request)
            return web.json_response(_result_payload(result, request_id))

        response = web.StreamResponse(headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        })
        await response.prepare(request)
        emitted_text = ""
        stream = service.stream(chat_request)
        try:
            async for event in stream:
                if event.type == "delta":
                    emitted_text += event.text
                    await response.write(_sse(None, _chunk_payload(event, request_id, chat_request.model)))
                elif event.type == "final":
                    # A final full-text event can include a suffix that no delta carried.
                    suffix = event.text[len(emitted_text):] if event.text.startswith(emitted_text) else ""
                    if suffix:
                        suffix_event = ChatStreamEvent(type="delta", text=suffix, model=event.model)
                        await response.write(_sse(None, _chunk_payload(suffix_event, request_id, chat_request.model)))
                    await response.write(_sse(None, _chunk_payload(event, request_id, chat_request.model, "stop")))
                    await response.write(_sse("chatgptweb.final", {
                        "conversation_id": event.conversation_id,
                        "message_id": event.message_id,
                        "model": event.model,
                        "usage": event.usage,
                        "metadata": event.metadata,
                        "image_urls": event.image_urls,
                    }))
                elif event.type in ("image", "image_pending"):
                    await response.write(_sse(f"chatgptweb.{event.type}", {
                        "image_urls": event.image_urls,
                        "metadata": event.metadata,
                    }))
                elif event.type == "status":
                    await response.write(_sse("chatgptweb.status", event.metadata))
                elif event.type == "error":
                    await response.write(_sse("error", {"message": event.text}))
            await response.write(_sse(None, "[DONE]"))
            await response.write_eof()
        except ConnectionResetError:
            # The generator's close path aborts the matching browser fetch.
            return response
        finally:
            await stream.aclose()
        return response

    async def stream_response_object(
        request: web.Request,
        response_object: Dict[str, Any],
    ) -> web.StreamResponse:
        """Emit the small Responses SSE subset needed for text and tool turns."""
        response = web.StreamResponse(headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        })
        await response.prepare(request)
        try:
            await response.write(_sse("response.created", {"type": "response.created", "response": response_object}))
            for output_index, item in enumerate(response_object.get("output", [])):
                if item.get("type") == "message":
                    content = item.get("content") or []
                    if content:
                        text = str(content[0].get("text") or "")
                        if text:
                            await response.write(_sse("response.output_text.delta", {
                                "type": "response.output_text.delta",
                                "response_id": response_object["id"],
                                "item_id": item["id"],
                                "output_index": output_index,
                                "content_index": 0,
                                "delta": text,
                            }))
                        await response.write(_sse("response.output_text.done", {
                            "type": "response.output_text.done",
                            "response_id": response_object["id"],
                            "item_id": item["id"],
                            "output_index": output_index,
                            "content_index": 0,
                            "text": text,
                        }))
                elif item.get("type") == "function_call":
                    await response.write(_sse("response.function_call_arguments.done", {
                        "type": "response.function_call_arguments.done",
                        "response_id": response_object["id"],
                        "item_id": item["id"],
                        "output_index": output_index,
                        "call_id": item["call_id"],
                        "name": item["name"],
                        "arguments": item["arguments"],
                    }))
            event_type = "response.completed" if response_object["status"] == "completed" else "response.failed"
            await response.write(_sse(event_type, {"type": event_type, "response": response_object}))
            await response.write_eof()
        except ConnectionResetError:
            return response
        return response

    async def responses(request: web.Request) -> web.StreamResponse:
        try:
            payload = await request.json()
        except (json.JSONDecodeError, ValueError):
            raise web.HTTPBadRequest(text="request body must be valid JSON")
        if not isinstance(payload, dict):
            raise web.HTTPBadRequest(text="request body must be a JSON object")
        discard_response_cursors()
        client_id = client_identity(request)
        previous_response_id = payload.get("previous_response_id") or ""
        if not isinstance(previous_response_id, str):
            raise web.HTTPBadRequest(text="previous_response_id must be a string")
        cursor = response_cursors.get(previous_response_id) if previous_response_id else None
        if previous_response_id and cursor is None:
            raise web.HTTPNotFound(text="previous response was not found or has expired")
        if cursor is not None and cursor.client_id != client_id:
            raise web.HTTPForbidden(text="previous response belongs to another API client")

        model = _response_model(payload, cursor)
        instructions = _response_instructions(payload)
        tool_payload = payload.get("tools")
        tools = cursor.tools if cursor and cursor.agent_state is not None else None
        if isinstance(tool_payload, list) and tool_payload:
            tools = _openai_agent_tools(payload)
        response_id = f"resp_{uuid.uuid4().hex}"
        tool_call_id = ""

        if tools is not None:
            tool_result = _response_tool_result(payload, cursor) if cursor and cursor.agent_state else None
            task = _response_input_text(payload) if tool_result is None else ""
            if instructions:
                task = f"{instructions}\n\n{task}".strip()
            turn = await AgentService(
                service,
                safety_policy=agent_safety_policy,
                anchor_policy=openai_agent_anchor_policy,
                client_id=client_id,
                request_priority=120,
                enforce_client_ownership=True,
            ).turn(
                task,
                tools,
                state=cursor.agent_state if cursor else None,
                tool_result=tool_result,
                model=model,
                continue_existing=bool(cursor),
            )
            if turn.ok and turn.decision.kind == "tool_call":
                tool_call_id = f"call_{uuid.uuid4().hex}"
            response_object = _response_payload(
                response_id,
                model=turn.used_model or model,
                previous_response_id=previous_response_id,
                turn=turn,
                tool_call_id=tool_call_id,
            )
            response_cursors[response_id] = _ResponseCursor(
                conversation_id=turn.state.conversation_id,
                parent_message_id=turn.state.parent_message_id,
                model=turn.used_model or model,
                expires_at=time.monotonic() + 600,
                client_id=client_id,
                agent_state=turn.state,
                tools=tools,
                tool_name=turn.decision.tool if turn.decision.kind == "tool_call" else "",
                tool_call_id=tool_call_id,
            )
        else:
            prompt = _response_input_text(payload)
            if instructions:
                prompt = f"{instructions}\n\n{prompt}"
            chat_request = ChatRequest(
                prompt=prompt,
                conversation_id=cursor.conversation_id if cursor else "",
                parent_message_id=cursor.parent_message_id if cursor else "",
                model=model,
                client_id=client_id,
                request_priority=100,
                enforce_client_ownership=True,
            )
            result = await service.send(chat_request)
            response_object = _response_payload(
                response_id,
                model=result.used_model or model,
                previous_response_id=previous_response_id,
                result=result,
            )
            if result.ok and result.conversation_id and result.message_id:
                response_cursors[response_id] = _ResponseCursor(
                    conversation_id=result.conversation_id,
                    parent_message_id=result.message_id,
                    model=result.used_model or model,
                    expires_at=time.monotonic() + 600,
                    client_id=client_id,
                )

        if payload.get("stream", False):
            return await stream_response_object(request, response_object)
        return web.json_response(response_object)

    async def agent_turn(request: web.Request) -> web.Response:
        try:
            payload = await request.json()
        except (json.JSONDecodeError, ValueError):
            raise web.HTTPBadRequest(text="request body must be valid JSON")
        return web.json_response(await agent_turn_from_payload(
            service,
            payload,
            agent_safety_policy=agent_safety_policy,
            agent_anchor_policy=agent_anchor_policy,
            client_id=client_identity(request),
            request_priority=120,
        ))

    def require_api_key_store() -> ApiKeyStore:
        if not api_key_store:
            raise web.HTTPNotImplemented(text="dynamic API key management is not enabled")
        return api_key_store

    async def list_api_keys(request: web.Request) -> web.Response:
        require_admin(request)
        include_revoked = request.query.get("include_revoked", "false").lower() == "true"
        return web.json_response({"keys": require_api_key_store().list(include_revoked=include_revoked)})

    async def create_api_key(request: web.Request) -> web.Response:
        require_admin(request)
        try:
            payload = await request.json()
        except (json.JSONDecodeError, ValueError):
            raise web.HTTPBadRequest(text="request body must be valid JSON")
        if not isinstance(payload, dict):
            raise web.HTTPBadRequest(text="request body must be a JSON object")
        try:
            metadata, secret = require_api_key_store().create(
                label=payload.get("label"),
                scopes=payload.get("scopes"),
                max_concurrency=payload.get("max_concurrency"),
            )
        except ValueError as error:
            raise web.HTTPBadRequest(text=str(error)) from error
        return web.json_response({"key": metadata, "secret": secret}, status=201)

    async def revoke_api_key(request: web.Request) -> web.Response:
        require_admin(request)
        value = require_api_key_store().revoke(request.match_info["key_id"])
        if value is None:
            raise web.HTTPNotFound(text="API key was not found")
        return web.json_response({"key": value})

    async def rotate_api_key(request: web.Request) -> web.Response:
        require_admin(request)
        value = require_api_key_store().rotate(request.match_info["key_id"])
        if value is None:
            raise web.HTTPNotFound(text="API key was not found or is revoked")
        metadata, secret = value
        return web.json_response({"key": metadata, "secret": secret})

    # JSON base64 is larger than decoded attachment bytes.
    app = web.Application(
        middlewares=[auth_middleware],
        client_max_size=(max_attachment_bytes * 4 // 3) + 1024 * 1024,
    )
    app[SERVICE_KEY] = service
    if api_key_store:
        app[API_KEY_STORE] = api_key_store
    app.router.add_get("/health", health)
    app.router.add_get("/v1/models", models)
    app.router.add_get("/v1/account/status", account_status)
    app.router.add_post("/v1/accounts/{account}/control", control_account)
    app.router.add_get("/v1/usage", usage_status)
    app.router.add_get("/v1/activity", activity)
    app.router.add_get("/v1/runtime/logs", runtime_logs)
    app.router.add_get("/v1/verification", verification_status)
    app.router.add_post("/v1/verification/{challenge_id}", submit_verification)
    app.router.add_delete("/v1/verification/{challenge_id}", cancel_verification)
    app.router.add_get("/v1/bot/capabilities", bot_capabilities)
    app.router.add_post("/v1/bot/chat", bot_chat)
    app.router.add_post("/v1/bot/chat/stream", bot_chat_stream)
    app.router.add_post("/v1/bot/history", bot_history)
    app.router.add_post("/v1/bot/persona", bot_persona)
    app.router.add_get("/v1/bot/personas", bot_personas)
    app.router.add_put("/v1/bot/personas", bot_upsert_persona)
    app.router.add_delete("/v1/bot/personas", bot_delete_persona)
    app.router.add_post("/v1/bot/context-estimate", bot_context_estimate)
    app.router.add_post("/v1/chat/completions", chat_completions)
    app.router.add_post("/v1/responses", responses)
    app.router.add_post("/v1/agent/turn", agent_turn)
    app.router.add_get("/v1/keys", list_api_keys)
    app.router.add_post("/v1/keys", create_api_key)
    app.router.add_post("/v1/keys/{key_id}/rotate", rotate_api_key)
    app.router.add_delete("/v1/keys/{key_id}", revoke_api_key)
    return app


def create_control_app(
    service: ChatService,
    verification_broker: VerificationBroker,
    api_key: str | None = None,
    api_key_store: ApiKeyStore | None = None,
    runtime_log_path: Path | str | None = None,
) -> web.Application:
    """Create the opt-in local operations console over the existing API."""
    app = create_http_app(
        service,
        api_key=api_key,
        api_key_store=api_key_store,
        verification_broker=verification_broker,
        runtime_log_path=runtime_log_path,
    )

    async def dashboard(_: web.Request) -> web.Response:
        return web.Response(text=CONTROL_HTML, content_type="text/html")

    app.router.add_get("/", dashboard)
    return app


_CONTROL_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ChatGPTWeb Control</title><style>
:root{color-scheme:light;font-family:Arial,sans-serif;color:#172033;background:#f4f6f8}.shell{max-width:1240px;margin:32px auto;padding:0 20px}.top{display:flex;justify-content:space-between;gap:16px;align-items:center;border-bottom:1px solid #cbd2d9;padding-bottom:18px}.top h1{font-size:22px;margin:0}.key{display:flex;gap:8px}.key input{width:210px}.panel{margin-top:22px}.panel h2{font-size:15px;margin:0 0 10px}.table-wrap{overflow-x:auto}.table{width:100%;min-width:1030px;border-collapse:collapse;background:#fff}.table th,.table td{padding:11px 12px;border-bottom:1px solid #e2e6ea;text-align:left;font-size:13px;vertical-align:top}.table th{color:#53606e;font-weight:600}.details{max-width:210px;line-height:1.45}.challenge{display:grid;grid-template-columns:minmax(180px,1fr) 160px 112px 82px;gap:8px;align-items:center;background:#fff;border:1px solid #d7dde3;padding:12px;margin-bottom:8px}.key-form{display:flex;flex-wrap:wrap;gap:8px;align-items:center;background:#fff;border:1px solid #d7dde3;padding:12px}.key-form label{font-size:13px}.key-form input[type=checkbox]{margin-right:4px}.key-list{background:#fff;border:1px solid #d7dde3;border-top:0}.key-row{display:grid;grid-template-columns:minmax(180px,1fr) minmax(130px,1fr) 100px 150px;gap:8px;align-items:center;padding:10px 12px;border-top:1px solid #e2e6ea;font-size:13px}.secret{display:block;overflow-wrap:anywhere;background:#fff8db;border:1px solid #f0d88a;padding:10px;margin:8px 0;font-family:ui-monospace,monospace;font-size:12px}.muted{color:#66717d;font-size:13px}.error{color:#b42318;font-size:13px;min-height:18px}input{box-sizing:border-box;border:1px solid #aeb8c2;border-radius:4px;padding:8px 10px;font:inherit}button{border:1px solid #254d70;background:#fff;color:#173b58;border-radius:4px;padding:8px 11px;font:inherit;cursor:pointer;margin-right:6px}button.primary{background:#176b87;border-color:#176b87;color:#fff}button.danger{color:#9b1c1c;border-color:#d9aaaa}@media(max-width:700px){.top{align-items:flex-start;flex-direction:column}.challenge{grid-template-columns:1fr}.key-row{grid-template-columns:1fr}.key input{width:min(260px,65vw)}}
</style></head><body><main class="shell"><header class="top"><h1>ChatGPTWeb Control</h1><div class="key"><input id="key" type="password" autocomplete="off" placeholder="API key"><button id="refresh">Refresh</button></div></header><p id="error" class="error"></p><section class="panel"><h2>Accounts</h2><div class="table-wrap"><table class="table"><thead><tr><th>Account</th><th>State</th><th>Sessions</th><th>Usage</th><th>Details</th><th>Control</th></tr></thead><tbody id="accounts"></tbody></table></div></section><section class="panel"><h2>Verification</h2><div id="challenges" class="muted">No pending verification.</div></section><section class="panel"><h2>Client API Keys</h2><form id="key-form" class="key-form"><input id="key-label" placeholder="Key label" required><label><input type="checkbox" name="key-scope" value="chat" checked>Chat / Responses</label><label><input type="checkbox" name="key-scope" value="agent">Agent protocol</label><label><input type="checkbox" name="key-scope" value="bot">Bot bridge</label><input id="key-concurrency" type="number" min="1" max="16" value="2" title="Maximum concurrent requests"><button class="primary">Create key</button></form><code id="key-secret" class="secret" hidden></code><div id="client-keys" class="key-list muted">No client keys loaded.</div></section><section class="panel"><h2>Recent Activity</h2><div class="table-wrap"><table class="table"><thead><tr><th>Time</th><th>Account</th><th>Event</th><th>Detail</th></tr></thead><tbody id="activity"></tbody></table></div></section></main><script>
const key=document.querySelector('#key'),error=document.querySelector('#error'),accounts=document.querySelector('#accounts'),challenges=document.querySelector('#challenges'),activity=document.querySelector('#activity'),keyForm=document.querySelector('#key-form'),keyLabel=document.querySelector('#key-label'),keyConcurrency=document.querySelector('#key-concurrency'),keySecret=document.querySelector('#key-secret'),clientKeys=document.querySelector('#client-keys'),drafts=new Map(),submitting=new Set();key.value=sessionStorage.getItem('chatgptweb-control-key')||'';
function headers(){const value=key.value.trim();return value?{Authorization:'Bearer '+value,'Content-Type':'application/json'}:{'Content-Type':'application/json'}}
async function call(path,options={}){const response=await fetch(path,{...options,headers:{...headers(),...(options.headers||{})}});if(!response.ok)throw new Error(response.status===401?'Enter a valid API key':await response.text());return response.status===204?null:response.json()}
function cell(row,value){const td=document.createElement('td');td.textContent=value||'--';row.append(td)}
async function changeAccount(account,action,button){button.disabled=true;try{await call('/v1/accounts/'+encodeURIComponent(account)+'/control',{method:'POST',body:JSON.stringify({action})});await refresh(true)}catch(e){error.textContent=e.message;button.disabled=false}}
function accountButton(control,item,label,action,danger=false){const button=document.createElement('button');button.textContent=label;if(danger)button.className='danger';button.addEventListener('click',()=>changeAccount(item.email,action,button));control.append(button)}
function formatUsage(usage){if(!usage||!usage.requests)return 'No upstream usage observed';const models=Object.entries(usage.models||{}).map(([name,value])=>{const tokens=['input_tokens','output_tokens','total_tokens'].filter(key=>typeof value[key]==='number').map(key=>key.replace('_tokens','')+': '+value[key]).join(', ');return name+' ('+value.requests+' req'+(tokens?', '+tokens:'')+')'});return models.join(' | ')||usage.requests+' request(s)'}
function retryTime(item){if(!item.retry_after_seconds)return '';const seconds=item.retry_after_seconds;if(seconds<60)return seconds+'s remaining';const minutes=Math.ceil(seconds/60);return minutes+'m remaining'}
function details(item){const plan=item.account_plan&&item.account_plan!=='unknown'?item.account_plan+' ('+(item.account_plan_source||'observed')+')':'unknown (legacy '+(item.gptplus?'plus':'free')+')';const bits=['mode: '+(item.mode||'--'),'plan: '+plan,'models: '+(item.observed_model_count||0)+' ('+(item.observed_models_source||'unavailable')+')','login: '+(item.login_state?'ready':'not ready')];if(item.login_guidance)bits.push('status: '+item.login_guidance);if(item.login_failure_kind)bits.push('failure: '+item.login_failure_kind+' ('+(item.login_fail_count||0)+'/'+(item.max_login_failures||'--')+')');const wait=retryTime(item);if(wait)bits.push('cooldown: '+wait);if(item.persist_auth_state)bits.push('auth state: '+(item.auth_state_loaded?'restored':'enabled'));if(item.runtime&&item.runtime.recovery_count)bits.push('recovery: '+item.runtime.recovery_count);return bits.join('\\n')}
function retryLabel(item){return item.retry_mode==='manual'?'Retry manually':item.retry_mode==='cooldown'?'Retry now':item.retry_mode==='wait'?'Login in progress':'Retry login'}
function renderAccounts(data){accounts.replaceChildren();for(const item of data.accounts||[]){const row=document.createElement('tr');cell(row,item.email);cell(row,item.login_retry_pending?'login in progress':item.manual_disabled?'manually disabled':item.status);cell(row,String(item.conversation_count||0));cell(row,formatUsage(item.usage));const diagnostic=document.createElement('td');diagnostic.className='details';diagnostic.textContent=details(item);row.append(diagnostic);const control=document.createElement('td');if(item.manual_disabled)accountButton(control,item,'Enable','enable');else{accountButton(control,item,'Disable','disable',true);if(!item.login_state&&item.can_retry_login&&!item.login_retry_pending)accountButton(control,item,retryLabel(item),'retry_login')}accountButton(control,item,'Refresh plan','refresh_capabilities');row.append(control);accounts.append(row)}}
function renderActivity(data){activity.replaceChildren();const events=data.events||[];if(!events.length){const row=document.createElement('tr');const empty=document.createElement('td');empty.colSpan=4;empty.className='muted';empty.textContent='No local activity yet.';row.append(empty);activity.append(row);return}for(const item of events){const row=document.createElement('tr');cell(row,item.at);cell(row,item.account);cell(row,item.event);cell(row,item.message);activity.append(row)}}
function renderChallenges(data){challenges.replaceChildren();const list=data.challenges||[];if(!list.length){challenges.textContent='No pending verification.';return}for(const item of list){const card=document.createElement('form');card.className='challenge';const label=document.createElement('div');label.textContent=item.account+' · '+item.provider;const input=document.createElement('input');input.inputMode='numeric';input.autocomplete='one-time-code';input.maxLength=12;input.placeholder='Verification code';input.value=drafts.get(item.id)||'';input.addEventListener('input',()=>drafts.set(item.id,input.value));const submit=document.createElement('button');submit.className='primary';submit.textContent='Submit';const cancel=document.createElement('button');cancel.type='button';cancel.className='danger';cancel.textContent='Cancel';const busy=submitting.has(item.id);submit.disabled=busy;cancel.disabled=busy;card.append(label,input,submit,cancel);card.addEventListener('submit',async event=>{event.preventDefault();const code=input.value.trim();if(!code){error.textContent='Enter the verification code.';return}submitting.add(item.id);submit.disabled=true;cancel.disabled=true;try{await call('/v1/verification/'+item.id,{method:'POST',body:JSON.stringify({code})});drafts.delete(item.id);await refresh(true)}catch(e){error.textContent=e.message}finally{submitting.delete(item.id);submit.disabled=false;cancel.disabled=false}});cancel.addEventListener('click',async()=>{submitting.add(item.id);submit.disabled=true;cancel.disabled=true;try{await call('/v1/verification/'+item.id,{method:'DELETE'});drafts.delete(item.id);await refresh(true)}catch(e){error.textContent=e.message}finally{submitting.delete(item.id);submit.disabled=false;cancel.disabled=false}});challenges.append(card)}}
function showSecret(secret){keySecret.hidden=!secret;keySecret.textContent=secret?'Copy this secret now. It is shown only once: '+secret:''}
function renderKeys(data){clientKeys.replaceChildren();const list=data.keys||[];if(!list.length){clientKeys.textContent='No active client keys.';return}for(const item of list){const row=document.createElement('div');row.className='key-row';const label=document.createElement('strong');label.textContent=item.label;const scope=document.createElement('span');scope.textContent=(item.scopes||[]).join(', ');const limit=document.createElement('span');limit.textContent='active '+(item.active_requests||0)+' / '+item.max_concurrency;const controls=document.createElement('span');const rotate=document.createElement('button');rotate.textContent='Rotate';rotate.addEventListener('click',async()=>{try{const data=await call('/v1/keys/'+encodeURIComponent(item.id)+'/rotate',{method:'POST'});showSecret(data.secret);await refresh(true)}catch(e){error.textContent=e.message}});const revoke=document.createElement('button');revoke.className='danger';revoke.textContent='Revoke';revoke.addEventListener('click',async()=>{if(!confirm('Revoke '+item.label+'?'))return;try{await call('/v1/keys/'+encodeURIComponent(item.id),{method:'DELETE'});await refresh(true)}catch(e){error.textContent=e.message}});controls.append(rotate,revoke);row.append(label,scope,limit,controls);clientKeys.append(row)}}
keyForm.addEventListener('submit',async event=>{event.preventDefault();const scopes=[...document.querySelectorAll('input[name=key-scope]:checked')].map(item=>item.value);if(!scopes.length){error.textContent='Choose at least one scope.';return}try{const data=await call('/v1/keys',{method:'POST',body:JSON.stringify({label:keyLabel.value,scopes,max_concurrency:Number(keyConcurrency.value)})});showSecret(data.secret);keyLabel.value='';await refresh(true)}catch(e){error.textContent=e.message}})
async function refresh(force=false){if(!force&&(submitting.size||challenges.contains(document.activeElement)))return;error.textContent='';sessionStorage.setItem('chatgptweb-control-key',key.value.trim());try{const [status,verification,events,keys]=await Promise.all([call('/v1/account/status'),call('/v1/verification'),call('/v1/activity'),call('/v1/keys')]);renderAccounts(status);renderChallenges(verification);renderActivity(events);renderKeys(keys)}catch(e){error.textContent=e.message}}
document.querySelector('#refresh').addEventListener('click',refresh);refresh();setInterval(refresh,5000);
</script></body></html>"""
