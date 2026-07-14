"""Interactive local ChatService console with the optional WebUI enabled."""

import asyncio
import json
import os
from pathlib import Path

import aioconsole

from ChatGPTWeb import ChatRequest, ChatService, chatgpt


SESSIONS_FILE = Path(os.getenv("CHATGPTWEB_SESSIONS_FILE", "example/local_sessions.json"))
STORAGE_DIR = Path(os.getenv("CHATGPTWEB_STORAGE_DIR", "data/chatgptweb"))
CONTROL_PORT = int(os.getenv("CHATGPTWEB_CONTROL_PORT", "8765"))
CONTROL_API_KEY = os.getenv("CHATGPTWEB_CONTROL_API_KEY") or None
MODEL = os.getenv("CHATGPTWEB_MODEL", "auto")


def load_sessions() -> list[dict]:
    if not SESSIONS_FILE.is_file():
        raise FileNotFoundError(f"Missing local sessions file: {SESSIONS_FILE}")
    sessions = json.loads(SESSIONS_FILE.read_text("utf8"))
    if not isinstance(sessions, list) or not sessions:
        raise ValueError(f"{SESSIONS_FILE} must contain at least one account")
    return sessions


async def main():
    runtime = chatgpt(
        sessions=load_sessions(),
        storage_dir=STORAGE_DIR,
        begin_sleep_time=False,
        headless=False,
        logger_level="INFO",
        stdout_flush=True,
        local_js=True,
        control_host="127.0.0.1",
        control_port=CONTROL_PORT,
        control_api_key=CONTROL_API_KEY,
    )
    service = ChatService(runtime)
    conversation_id = ""
    parent_message_id = ""
    print("Local console ready. Commands: :new, :status, :quit")
    try:
        while True:
            prompt = (await aioconsole.ainput("you> ")).strip()
            if prompt == ":quit":
                return
            if prompt == ":new":
                conversation_id = ""
                parent_message_id = ""
                print("Started a new conversation.")
                continue
            if prompt == ":status":
                status = await service.get_account_status()
                print(json.dumps(status.get("accounts", []), ensure_ascii=False, indent=2))
                continue
            if not prompt:
                continue

            request = ChatRequest(
                prompt=prompt,
                conversation_id=conversation_id,
                parent_message_id=parent_message_id,
                model=MODEL,
            )
            printed = False
            async for event in service.stream(request):
                if event.type == "delta":
                    print(event.text, end="", flush=True)
                    printed = True
                elif event.type == "status":
                    state = event.metadata.get("message", "working") if isinstance(event.metadata, dict) else "working"
                    print(f"\n[{state}]", flush=True)
                elif event.type == "error":
                    print(f"\nerror: {event.text}")
                elif event.type == "final":
                    if not printed and event.text:
                        print(event.text, end="")
                    conversation_id = event.conversation_id or conversation_id
                    parent_message_id = event.message_id or parent_message_id
                    print()
                    if conversation_id:
                        print(f"conversation: {conversation_id}")
    finally:
        await runtime.close()


asyncio.run(main())
