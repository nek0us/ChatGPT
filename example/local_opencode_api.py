"""Run ChatGPTWeb as a local OpenAI-compatible endpoint for OpenCode."""

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
        raise ValueError("Set CHATGPTWEB_HTTP_API_KEY to a local secret before starting the API")

    runtime = chatgpt(
        sessions=load_sessions(),
        storage_dir=STORAGE_DIR,
        begin_sleep_time=False,
        headless=_enabled("CHATGPTWEB_HEADLESS", False),
        logger_level=os.getenv("CHATGPTWEB_LOG_LEVEL", "INFO"),
        stdout_flush=True,
        local_js=_enabled("CHATGPTWEB_LOCAL_JS", True),
    )
    app = create_http_app(ChatService(runtime), api_key=API_KEY)

    async def close_runtime(_: web.Application) -> None:
        await runtime.close()

    app.on_cleanup.append(close_runtime)
    print(f"ChatGPTWeb OpenAI-compatible API: http://{HOST}:{PORT}/v1")
    web.run_app(app, host=HOST, port=PORT)


if __name__ == "__main__":
    main()
