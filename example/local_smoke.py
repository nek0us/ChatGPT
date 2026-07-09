import asyncio
import json
import os
from pathlib import Path

from ChatGPTWeb import chatgpt
from ChatGPTWeb.config import MsgData


SESSIONS_FILE = Path(os.getenv("CHATGPTWEB_SESSIONS_FILE", "example/local_sessions.json"))
PROMPT = os.getenv("CHATGPTWEB_SMOKE_PROMPT", "Say hello in one short sentence.")
HEADLESS = os.getenv("CHATGPTWEB_HEADLESS", "false").lower() in ("1", "true", "yes")
TIMEOUT = int(os.getenv("CHATGPTWEB_SMOKE_TIMEOUT", "600"))


def load_sessions() -> list[dict]:
    if not SESSIONS_FILE.exists():
        raise FileNotFoundError(f"Missing local sessions file: {SESSIONS_FILE}")
    sessions = json.loads(SESSIONS_FILE.read_text("utf8"))
    if not sessions:
        raise ValueError(f"{SESSIONS_FILE} does not contain any sessions")
    return sessions


async def main():
    chat = chatgpt(
        sessions=load_sessions(),
        begin_sleep_time=False,
        headless=HEADLESS,
        httpx_status=False,
        logger_level="DEBUG",
        stdout_flush=True,
        local_js=True,
        ready_timeout=TIMEOUT,
    )
    data = MsgData(msg_send=PROMPT)
    try:
        data = await asyncio.wait_for(chat.continue_chat(data), timeout=TIMEOUT)
    except TimeoutError:
        data.add_error(
            kind="local_smoke_timeout",
            message=f"local smoke timed out after {TIMEOUT} seconds",
        )
    print(
        json.dumps(
            {
                "status": data.status,
                "from_email": data.from_email,
                "conversation_id": data.conversation_id,
                "next_msg_id": data.next_msg_id,
                "msg_recv": data.msg_recv,
                "error_info": data.error_info,
                "error_list": data.error_list,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


asyncio.run(main())
