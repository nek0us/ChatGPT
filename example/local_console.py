"""Run the local ChatGPTWeb operations console on loopback only."""

import asyncio
import json
import os
import secrets
from pathlib import Path

from aiohttp import web

from ChatGPTWeb import ChatService, chatgpt, create_control_app


SESSIONS_FILE = Path(os.getenv("CHATGPTWEB_SESSIONS_FILE", "example/local_sessions.json"))
HOST = "127.0.0.1"
PORT = int(os.getenv("CHATGPTWEB_CONSOLE_PORT", "8765"))
HEADLESS = os.getenv("CHATGPTWEB_HEADLESS", "false").lower() in ("1", "true", "yes")
API_KEY = os.getenv("CHATGPTWEB_CONSOLE_KEY") or secrets.token_urlsafe(24)


def load_sessions() -> list[dict]:
    if not SESSIONS_FILE.exists():
        raise FileNotFoundError(f"Missing local sessions file: {SESSIONS_FILE}")
    sessions = json.loads(SESSIONS_FILE.read_text("utf8"))
    if not sessions:
        raise ValueError("sessions file must contain at least one session")
    return sessions


async def main() -> None:
    runtime = chatgpt(
        sessions=load_sessions(),
        headless=HEADLESS,
        httpx_status=False,
        logger_level="INFO",
        stdout_flush=True,
        local_js=True,
    )
    app = create_control_app(
        ChatService(runtime),
        runtime.verification_broker,
        api_key=API_KEY,
    )
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, HOST, PORT)
    await site.start()
    print(f"ChatGPTWeb control: http://{HOST}:{PORT}")
    print(f"Control API key: {API_KEY}")
    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()
        await runtime.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
