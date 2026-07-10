"""Optional aiohttp adapter over :mod:`ChatGPTWeb.service`."""

import base64
import binascii
import asyncio
import hmac
import json
import time
import uuid
from typing import Any, Dict, List

from aiohttp import web

from .api import ChatStreamEvent
from .config import IOFile
from .service import ChatRequest, ChatResult, ChatService

SERVICE_KEY: web.AppKey[ChatService] = web.AppKey("chatgptweb_service", ChatService)


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
) -> web.Application:
    """Create an opt-in local API application without opening a listening port."""
    if max_attachment_bytes <= 0:
        raise ValueError("max_attachment_bytes must be positive")

    @web.middleware
    async def auth_middleware(request: web.Request, handler):
        if request.path == "/health" or not api_key:
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

    async def chat_completions(request: web.Request) -> web.StreamResponse:
        try:
            payload = await request.json()
        except (json.JSONDecodeError, ValueError):
            raise web.HTTPBadRequest(text="request body must be valid JSON")
        chat_request = chat_request_from_payload(payload, max_attachment_bytes=max_attachment_bytes)
        request_id = f"chatcmpl-{uuid.uuid4().hex}"
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

    # JSON base64 is larger than decoded attachment bytes.
    app = web.Application(
        middlewares=[auth_middleware],
        client_max_size=(max_attachment_bytes * 4 // 3) + 1024 * 1024,
    )
    app[SERVICE_KEY] = service
    app.router.add_get("/health", health)
    app.router.add_get("/v1/models", models)
    app.router.add_get("/v1/account/status", account_status)
    app.router.add_get("/v1/usage", usage_status)
    app.router.add_post("/v1/chat/completions", chat_completions)
    return app
