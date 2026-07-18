"""Optional aiohttp adapter over :mod:`ChatGPTWeb.service`."""

import base64
import binascii
import asyncio
import hmac
import json
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List

from aiohttp import web

from .agent import AgentAnchorPolicy, AgentSafetyPolicy, AgentService, AgentState, AgentTool, AgentToolResult
from .api import ChatStreamEvent
from .config import IOFile
from .control_ui import CONTROL_HTML
from .service import ChatRequest, ChatResult, ChatService
from .verification import VerificationBroker

SERVICE_KEY: web.AppKey[ChatService] = web.AppKey("chatgptweb_service", ChatService)


@dataclass
class _OpenAIAgentCursor:
    state: AgentState
    tools: list[AgentTool]
    tool_name: str
    expires_at: float


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


def chat_request_from_payload(payload: Dict[str, Any], max_attachment_bytes: int = 20 * 1024 * 1024) -> ChatRequest:
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
    )


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
        return [AgentTool.from_dict(item) for item in converted]
    except ValueError as error:
        raise web.HTTPBadRequest(text=str(error)) from error


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
        message = {"role": "assistant", "content": ""}
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
    max_attachment_bytes: int = 20 * 1024 * 1024,
    verification_broker: VerificationBroker | None = None,
    agent_safety_policy: AgentSafetyPolicy | None = None,
    agent_anchor_policy: AgentAnchorPolicy | None = None,
) -> web.Application:
    """Create an opt-in local API application without opening a listening port."""
    if max_attachment_bytes <= 0:
        raise ValueError("max_attachment_bytes must be positive")
    agent_cursors: dict[str, _OpenAIAgentCursor] = {}

    def discard_agent_cursors() -> None:
        now = time.monotonic()
        for token, cursor in tuple(agent_cursors.items()):
            if cursor.expires_at <= now:
                agent_cursors.pop(token, None)

    @web.middleware
    async def auth_middleware(request: web.Request, handler):
        if request.path in ("/", "/health") or not api_key:
            return await handler(request)
        authorization = request.headers.get("Authorization", "")
        supplied = authorization.removeprefix("Bearer ").strip()
        if not hmac.compare_digest(supplied, api_key):
            raise web.HTTPUnauthorized(text="invalid API key")
        return await handler(request)

    async def health(_: web.Request) -> web.Response:
        return web.json_response({"status": "ok"})

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

    async def control_account(request: web.Request) -> web.Response:
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
        return web.json_response({"challenges": await require_verification_broker().snapshot()})

    async def submit_verification(request: web.Request) -> web.Response:
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
        cancelled = await require_verification_broker().cancel(request.match_info["challenge_id"])
        if not cancelled:
            raise web.HTTPNotFound(text="verification challenge is no longer pending")
        return web.json_response({"cancelled": True})

    async def chat_completions(request: web.Request) -> web.StreamResponse:
        try:
            payload = await request.json()
        except (json.JSONDecodeError, ValueError):
            raise web.HTTPBadRequest(text="request body must be valid JSON")
        request_id = f"chatcmpl-{uuid.uuid4().hex}"
        supplied_call_id = payload.get("chatgptweb_tool_call_id")
        if supplied_call_id is not None and not isinstance(supplied_call_id, str):
            raise web.HTTPBadRequest(text="chatgptweb_tool_call_id must be a string")
        discard_agent_cursors()
        tool_call_id = supplied_call_id or _latest_openai_tool_call_id(payload)
        cursor = agent_cursors.get(tool_call_id) if tool_call_id else None
        if tool_call_id and cursor is None and payload.get("tools") is None:
            raise web.HTTPBadRequest(text="tool-call cursor is unknown or expired; restart the agent request")
        if payload.get("tools") is not None or cursor is not None:
            if payload.get("stream", False):
                raise web.HTTPBadRequest(text="streaming tool calls are not supported; use non-streaming tool rounds")
            if cursor is None:
                tools = _openai_agent_tools(payload)
            else:
                tools = cursor.tools
            try:
                if cursor is None:
                    turn = await AgentService(
                        service,
                        safety_policy=agent_safety_policy,
                        anchor_policy=agent_anchor_policy,
                    ).turn(
                        _prompt_from_payload(payload), tools, model=str(payload.get("model") or "auto"),
                    )
                else:
                    # Keep the stored tool set instead of trusting a continuation to broaden it.
                    result = _tool_result_from_openai_messages(payload, cursor, tool_call_id)
                    agent_cursors.pop(tool_call_id, None)
                    turn = await AgentService(
                        service,
                        safety_policy=agent_safety_policy,
                        anchor_policy=agent_anchor_policy,
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
                )
            return web.json_response(_agent_completion_payload(turn, request_id, str(payload.get("model") or "auto"), call_id))

        chat_request = chat_request_from_payload(payload, max_attachment_bytes=max_attachment_bytes)
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
        ))

    # JSON base64 is larger than decoded attachment bytes.
    app = web.Application(
        middlewares=[auth_middleware],
        client_max_size=(max_attachment_bytes * 4 // 3) + 1024 * 1024,
    )
    app[SERVICE_KEY] = service
    app.router.add_get("/health", health)
    app.router.add_get("/v1/models", models)
    app.router.add_get("/v1/account/status", account_status)
    app.router.add_post("/v1/accounts/{account}/control", control_account)
    app.router.add_get("/v1/usage", usage_status)
    app.router.add_get("/v1/activity", activity)
    app.router.add_get("/v1/verification", verification_status)
    app.router.add_post("/v1/verification/{challenge_id}", submit_verification)
    app.router.add_delete("/v1/verification/{challenge_id}", cancel_verification)
    app.router.add_post("/v1/chat/completions", chat_completions)
    app.router.add_post("/v1/agent/turn", agent_turn)
    return app


def create_control_app(
    service: ChatService,
    verification_broker: VerificationBroker,
    api_key: str | None = None,
) -> web.Application:
    """Create the opt-in local operations console over the existing API."""
    app = create_http_app(service, api_key=api_key, verification_broker=verification_broker)

    async def dashboard(_: web.Request) -> web.Response:
        return web.Response(text=CONTROL_HTML, content_type="text/html")

    app.router.add_get("/", dashboard)
    return app


_CONTROL_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ChatGPTWeb Control</title><style>
:root{color-scheme:light;font-family:Arial,sans-serif;color:#172033;background:#f4f6f8}.shell{max-width:1240px;margin:32px auto;padding:0 20px}.top{display:flex;justify-content:space-between;gap:16px;align-items:center;border-bottom:1px solid #cbd2d9;padding-bottom:18px}.top h1{font-size:22px;margin:0}.key{display:flex;gap:8px}.key input{width:210px}.panel{margin-top:22px}.panel h2{font-size:15px;margin:0 0 10px}.table-wrap{overflow-x:auto}.table{width:100%;min-width:1030px;border-collapse:collapse;background:#fff}.table th,.table td{padding:11px 12px;border-bottom:1px solid #e2e6ea;text-align:left;font-size:13px;vertical-align:top}.table th{color:#53606e;font-weight:600}.details{max-width:210px;line-height:1.45}.challenge{display:grid;grid-template-columns:minmax(180px,1fr) 160px 112px 82px;gap:8px;align-items:center;background:#fff;border:1px solid #d7dde3;padding:12px;margin-bottom:8px}.muted{color:#66717d;font-size:13px}.error{color:#b42318;font-size:13px;min-height:18px}input{box-sizing:border-box;border:1px solid #aeb8c2;border-radius:4px;padding:8px 10px;font:inherit}button{border:1px solid #254d70;background:#fff;color:#173b58;border-radius:4px;padding:8px 11px;font:inherit;cursor:pointer;margin-right:6px}button.primary{background:#176b87;border-color:#176b87;color:#fff}button.danger{color:#9b1c1c;border-color:#d9aaaa}@media(max-width:700px){.top{align-items:flex-start;flex-direction:column}.challenge{grid-template-columns:1fr}.key input{width:min(260px,65vw)}}
</style></head><body><main class="shell"><header class="top"><h1>ChatGPTWeb Control</h1><div class="key"><input id="key" type="password" autocomplete="off" placeholder="API key"><button id="refresh">Refresh</button></div></header><p id="error" class="error"></p><section class="panel"><h2>Accounts</h2><div class="table-wrap"><table class="table"><thead><tr><th>Account</th><th>State</th><th>Sessions</th><th>Usage</th><th>Details</th><th>Control</th></tr></thead><tbody id="accounts"></tbody></table></div></section><section class="panel"><h2>Verification</h2><div id="challenges" class="muted">No pending verification.</div></section><section class="panel"><h2>Recent Activity</h2><div class="table-wrap"><table class="table"><thead><tr><th>Time</th><th>Account</th><th>Event</th><th>Detail</th></tr></thead><tbody id="activity"></tbody></table></div></section></main><script>
const key=document.querySelector('#key'),error=document.querySelector('#error'),accounts=document.querySelector('#accounts'),challenges=document.querySelector('#challenges'),activity=document.querySelector('#activity'),drafts=new Map(),submitting=new Set();key.value=sessionStorage.getItem('chatgptweb-control-key')||'';
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
async function refresh(force=false){if(!force&&(submitting.size||challenges.contains(document.activeElement)))return;error.textContent='';sessionStorage.setItem('chatgptweb-control-key',key.value.trim());try{const [status,verification,events]=await Promise.all([call('/v1/account/status'),call('/v1/verification'),call('/v1/activity')]);renderAccounts(status);renderChallenges(verification);renderActivity(events)}catch(e){error.textContent=e.message}}
document.querySelector('#refresh').addEventListener('click',refresh);refresh();setInterval(refresh,5000);
</script></body></html>"""
