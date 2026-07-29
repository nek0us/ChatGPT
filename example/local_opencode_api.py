"""Run ChatGPTWeb as a local OpenAI-compatible endpoint for OpenCode."""

import asyncio
import json
import os
from pathlib import Path

from aiohttp import web

from ChatGPTWeb import ChatService, chatgpt, create_http_app


SESSIONS_FILE = Path(os.getenv("CHATGPTWEB_SESSIONS_FILE", "example/local_sessions.json"))
STORAGE_DIR = Path(os.getenv("CHATGPTWEB_STORAGE_DIR", "data/chatgptweb"))
HOST = os.getenv("CHATGPTWEB_HTTP_HOST", "127.0.0.1")
PORT = int(os.getenv("CHATGPTWEB_HTTP_PORT", "8000"))
API_KEY = os.getenv("CHATGPTWEB_HTTP_API_KEY", "")
CONTROL_HOST = os.getenv("CHATGPTWEB_CONTROL_HOST", "127.0.0.1")
CONTROL_PORT = int(os.getenv("CHATGPTWEB_CONTROL_PORT", "8765"))
CONTROL_API_KEY = os.getenv("CHATGPTWEB_CONTROL_API_KEY", API_KEY)


def _enabled(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def load_sessions() -> list[dict]:
    if not SESSIONS_FILE.is_file():
        raise FileNotFoundError(f"Missing local sessions file: {SESSIONS_FILE}")
    sessions = json.loads(SESSIONS_FILE.read_text("utf8"))
    if not isinstance(sessions, list) or not sessions:
        raise ValueError(f"{SESSIONS_FILE} must contain at least one account")
    return sessions


def main() -> None:
    if not API_KEY:
        raise ValueError(
            "Set CHATGPTWEB_HTTP_API_KEY to a local administrator secret before starting the API"
        )

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    runtime = chatgpt(
        sessions=load_sessions(),
        storage_dir=STORAGE_DIR,
        begin_sleep_time=False,
        headless=_enabled("CHATGPTWEB_HEADLESS", False),
        logger_level=os.getenv("CHATGPTWEB_LOG_LEVEL", "INFO"),
        stdout_flush=True,
        local_js=_enabled("CHATGPTWEB_LOCAL_JS", False),
        control_host=CONTROL_HOST,
        control_port=CONTROL_PORT,
        control_api_key=CONTROL_API_KEY,
    )
    app = create_http_app(
        ChatService(runtime),
        api_key=API_KEY,
        api_key_store=runtime.api_key_store,
    )

    async def start_runtime(_: web.Application) -> None:
        # chatgpt(plugin=False) schedules its browser startup on the current
        # event loop. Pass that same loop to aiohttp below; otherwise aiohttp
        # creates a second loop and the startup future never gets CPU time.
        if runtime._start_task is not None:
            print("Starting ChatGPTWeb browser runtime before accepting API requests...")
            await asyncio.wrap_future(runtime._start_task)
        if not runtime.manage.get("start"):
            raise RuntimeError("ChatGPTWeb browser runtime did not finish starting")
        health = await ChatService(runtime).get_runtime_health()
        if health["readiness"] != "ready":
            print(
                "ChatGPTWeb runtime started in degraded mode: no account is ready yet. "
                "The HTTP API stays online while login recovery continues."
            )

    async def close_runtime(_: web.Application) -> None:
        await runtime.close()

    app.on_startup.append(start_runtime)
    app.on_cleanup.append(close_runtime)
    web.run_app(app, host=HOST, port=PORT, loop=loop)


if __name__ == "__main__":
    main()
