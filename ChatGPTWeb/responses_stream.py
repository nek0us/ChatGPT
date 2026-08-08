"""Realtime OpenAI Responses SSE transport serialization."""

from __future__ import annotations

import asyncio
import json
import time
from contextlib import suppress
from typing import Any

from aiohttp import web


def sse_headers() -> dict[str, str]:
    """Headers that keep SSE unbuffered through aiohttp and common proxies."""
    return {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache, no-transform",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }


def pending_response(
    response_id: str,
    *,
    model: str,
    previous_response_id: str = "",
    created_at: int | None = None,
) -> dict[str, Any]:
    return {
        "id": response_id,
        "object": "response",
        "created_at": int(time.time()) if created_at is None else created_at,
        "status": "in_progress",
        "model": model,
        "output": [],
        "output_text": "",
        "previous_response_id": previous_response_id or None,
        "usage": {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
        },
    }


def failed_response(
    response_id: str,
    *,
    model: str,
    previous_response_id: str = "",
    error: BaseException | str,
    created_at: int | None = None,
) -> dict[str, Any]:
    if isinstance(error, BaseException):
        message = str(error)[:2000] or error.__class__.__name__
    else:
        message = str(error)[:2000]
    response = pending_response(
        response_id,
        model=model,
        previous_response_id=previous_response_id,
        created_at=created_at,
    )
    response.update({
        "status": "failed",
        "error": {
            "code": "chatgptweb_stream_error",
            "message": message,
        },
    })
    return response


def _sse(event: str, payload: dict[str, Any]) -> bytes:
    return (
        f"event: {event}\n"
        f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
    ).encode("utf-8")


class ResponsesSSEWriter:
    """Serialize one Responses API event stream with strict item ordering."""

    def __init__(
        self,
        request: web.Request,
        *,
        response_id: str,
        model: str,
        previous_response_id: str = "",
    ) -> None:
        self.request = request
        self.response_id = response_id
        self.model = model
        self.previous_response_id = previous_response_id
        self.created_at = int(time.time())
        self.response = web.StreamResponse(headers=sse_headers())
        self.sequence = 0
        self.started = False
        self.closed = False
        self.disconnected = False
        self._disconnect_event = asyncio.Event()
        self._write_lock = asyncio.Lock()
        self._text_item_id = ""
        self._text_started = False

    @property
    def text_started(self) -> bool:
        return self._text_started

    @property
    def text_item_id(self) -> str:
        return self._text_item_id

    async def _write(self, data: bytes) -> None:
        if self.closed:
            return
        if self.disconnected:
            raise ConnectionResetError("Responses client disconnected")
        async with self._write_lock:
            try:
                await self.response.write(data)
            except (ConnectionResetError, BrokenPipeError, RuntimeError):
                self.disconnected = True
                self._disconnect_event.set()
                raise ConnectionResetError("Responses client disconnected")

    async def emit(self, event: str, payload: dict[str, Any]) -> None:
        self.sequence += 1
        await self._write(_sse(event, {
            "type": event,
            "sequence_number": self.sequence,
            **payload,
        }))

    async def start(self) -> web.StreamResponse:
        if self.started:
            return self.response
        await self.response.prepare(self.request)
        self.started = True
        pending = pending_response(
            self.response_id,
            model=self.model,
            previous_response_id=self.previous_response_id,
            created_at=self.created_at,
        )
        await self.emit("response.created", {"response": pending})
        await self.emit("response.in_progress", {"response": pending})
        return self.response

    async def heartbeat(self, label: str = "ping") -> None:
        """Send an SSE comment; SDK parsers ignore it while proxies flush it."""
        safe = "".join(character for character in label if character not in "\r\n")[:120]
        await self._write(f": {safe or 'ping'}\n\n".encode("utf-8"))

    async def keepalive(self, stop: asyncio.Event, interval: float = 10.0) -> None:
        try:
            while not stop.is_set() and not self.closed:
                try:
                    await asyncio.wait_for(stop.wait(), timeout=max(1.0, interval))
                except asyncio.TimeoutError:
                    await self.heartbeat("chatgptweb waiting for validated agent decision")
        except ConnectionResetError:
            return

    async def wait_disconnected(self) -> None:
        await self._disconnect_event.wait()

    def ensure_connected(self) -> None:
        if self.disconnected:
            raise ConnectionResetError("Responses client disconnected")

    async def begin_text(self, item_id: str) -> None:
        if self._text_started:
            return
        self._text_item_id = item_id
        self._text_started = True
        await self.emit("response.output_item.added", {
            "output_index": 0,
            "item": {
                "type": "message",
                "id": item_id,
                "role": "assistant",
                "status": "in_progress",
                "phase": "final_answer",
                "content": [],
            },
        })
        await self.emit("response.content_part.added", {
            "item_id": item_id,
            "output_index": 0,
            "content_index": 0,
            "part": {"type": "output_text", "text": "", "annotations": []},
        })

    async def text_delta(self, delta: str) -> None:
        if not delta:
            return
        if not self._text_started:
            raise RuntimeError("begin_text must be called before text_delta")
        await self.emit("response.output_text.delta", {
            "response_id": self.response_id,
            "item_id": self._text_item_id,
            "output_index": 0,
            "content_index": 0,
            "delta": delta,
        })

    async def finish_text(self, item: dict[str, Any], text: str) -> None:
        if not self._text_started:
            await self.begin_text(str(item.get("id") or f"msg_{self.response_id}"))
        final_item = dict(item)
        final_item["id"] = self._text_item_id
        final_item["status"] = str(item.get("status") or "completed")
        final_item["phase"] = "final_answer"
        final_item["content"] = [{
            "type": "output_text",
            "text": text,
            "annotations": [],
        }]
        await self.emit("response.output_text.done", {
            "response_id": self.response_id,
            "item_id": self._text_item_id,
            "output_index": 0,
            "content_index": 0,
            "text": text,
        })
        await self.emit("response.content_part.done", {
            "item_id": self._text_item_id,
            "output_index": 0,
            "content_index": 0,
            "part": final_item["content"][0],
        })
        await self.emit("response.output_item.done", {
            "output_index": 0,
            "item": final_item,
        })

    async def emit_buffered_output(self, response_object: dict[str, Any]) -> None:
        """Emit validated final text or function calls on an already-open stream."""
        for output_index, item in enumerate(response_object.get("output", [])):
            if not isinstance(item, dict):
                continue
            added = dict(item)
            added["status"] = "in_progress"
            if item.get("type") == "message":
                added["phase"] = "final_answer"
                added["content"] = []
            elif item.get("type") == "function_call":
                added["arguments"] = ""
            await self.emit("response.output_item.added", {
                "output_index": output_index,
                "item": added,
            })
            if item.get("type") == "message":
                content = item.get("content") or []
                text = str(content[0].get("text") or "") if content and isinstance(content[0], dict) else ""
                await self.emit("response.content_part.added", {
                    "item_id": item["id"],
                    "output_index": output_index,
                    "content_index": 0,
                    "part": {"type": "output_text", "text": "", "annotations": []},
                })
                if text:
                    await self.emit("response.output_text.delta", {
                        "response_id": self.response_id,
                        "item_id": item["id"],
                        "output_index": output_index,
                        "content_index": 0,
                        "delta": text,
                    })
                await self.emit("response.output_text.done", {
                    "response_id": self.response_id,
                    "item_id": item["id"],
                    "output_index": output_index,
                    "content_index": 0,
                    "text": text,
                })
                await self.emit("response.content_part.done", {
                    "item_id": item["id"],
                    "output_index": output_index,
                    "content_index": 0,
                    "part": {"type": "output_text", "text": text, "annotations": []},
                })
            elif item.get("type") == "function_call":
                arguments = str(item.get("arguments") or "")
                if arguments:
                    await self.emit("response.function_call_arguments.delta", {
                        "item_id": item["id"],
                        "output_index": output_index,
                        "delta": arguments,
                    })
                await self.emit("response.function_call_arguments.done", {
                    "response_id": self.response_id,
                    "item_id": item["id"],
                    "output_index": output_index,
                    "call_id": item["call_id"],
                    "name": item["name"],
                    "arguments": arguments,
                })
            completed_item = (
                {**item, "phase": "final_answer"}
                if item.get("type") == "message"
                else item
            )
            await self.emit("response.output_item.done", {
                "output_index": output_index,
                "item": completed_item,
            })

    async def finish(self, response_object: dict[str, Any]) -> web.StreamResponse:
        if self.closed:
            return self.response
        event = "response.completed" if response_object.get("status") == "completed" else "response.failed"
        await self.emit(event, {"response": response_object})
        self.closed = True
        with suppress(ConnectionResetError, BrokenPipeError, RuntimeError):
            await self.response.write_eof()
        return self.response

    async def abort(self) -> None:
        self.closed = True
        with suppress(ConnectionResetError, BrokenPipeError, RuntimeError):
            await self.response.write_eof()
