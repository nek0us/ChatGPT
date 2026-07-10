import asyncio
import json
import os
import sys
from pathlib import Path

from ChatGPTWeb import chatgpt
from ChatGPTWeb.config import MsgData


SESSIONS_FILE = Path(os.getenv("CHATGPTWEB_SESSIONS_FILE", "example/local_sessions.json"))
SESSION_MODE = os.getenv("CHATGPTWEB_SESSION_MODE", "").strip().lower()
SESSION_EMAIL = os.getenv("CHATGPTWEB_SESSION_EMAIL", "").strip().lower()
PROMPT = os.getenv("CHATGPTWEB_SMOKE_PROMPT", "Say hello in one short sentence.")
PROMPTS = json.loads(os.getenv("CHATGPTWEB_SMOKE_PROMPTS", "null") or "null")
HEADLESS = os.getenv("CHATGPTWEB_HEADLESS", "false").lower() in ("1", "true", "yes")
TIMEOUT = int(os.getenv("CHATGPTWEB_SMOKE_TIMEOUT", "600"))
STREAM = os.getenv("CHATGPTWEB_SMOKE_STREAM", "false").lower() in ("1", "true", "yes")
DELAY = float(os.getenv("CHATGPTWEB_SMOKE_DELAY", "3"))
PROBE = os.getenv("CHATGPTWEB_SMOKE_PROBE", "false").lower() in ("1", "true", "yes")
PROBE_FETCH = os.getenv("CHATGPTWEB_SMOKE_PROBE_FETCH", "false").lower() in ("1", "true", "yes")
PROBE_AFTER = os.getenv("CHATGPTWEB_SMOKE_PROBE_AFTER", "false").lower() in ("1", "true", "yes")
MODELS = os.getenv("CHATGPTWEB_SMOKE_MODELS", "false").lower() in ("1", "true", "yes")
WEB_SEARCH = os.getenv("CHATGPTWEB_SMOKE_WEB_SEARCH", "false").lower() in ("1", "true", "yes")
STREAM_IDLE_TIMEOUT = int(os.getenv("CHATGPTWEB_SMOKE_STREAM_IDLE_TIMEOUT", "0"))
STREAM_STATUS_INTERVAL = int(os.getenv("CHATGPTWEB_SMOKE_STREAM_STATUS_INTERVAL", "15"))
SAVE_SCREEN = os.getenv("CHATGPTWEB_SMOKE_SAVE_SCREEN", "false").lower() in ("1", "true", "yes")


def load_sessions() -> list[dict]:
    if not SESSIONS_FILE.exists():
        raise FileNotFoundError(f"Missing local sessions file: {SESSIONS_FILE}")
    sessions = json.loads(SESSIONS_FILE.read_text("utf8"))
    if SESSION_MODE:
        sessions = [session for session in sessions if str(session.get("mode", "openai")).lower() == SESSION_MODE]
    if SESSION_EMAIL:
        sessions = [session for session in sessions if str(session.get("email", "")).lower() == SESSION_EMAIL]
    if not sessions:
        raise ValueError(f"{SESSIONS_FILE} does not contain a session matching the requested filter")
    return sessions


def get_prompts() -> list[str]:
    if isinstance(PROMPTS, list) and PROMPTS:
        return [str(prompt) for prompt in PROMPTS]
    second_prompt = os.getenv("CHATGPTWEB_SMOKE_SECOND_PROMPT", "")
    if second_prompt:
        return [PROMPT, second_prompt]
    return [PROMPT]


async def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")

    chat = chatgpt(
        sessions=load_sessions(),
        begin_sleep_time=False,
        headless=HEADLESS,
        httpx_status=False,
        logger_level="DEBUG",
        stdout_flush=True,
        save_screen=SAVE_SCREEN,
        local_js=True,
        ready_timeout=TIMEOUT,
    )
    data = MsgData(
        msg_send=get_prompts()[0],
        web_search=WEB_SEARCH,
        stream_idle_timeout_seconds=STREAM_IDLE_TIMEOUT,
        stream_status_interval_seconds=STREAM_STATUS_INTERVAL,
    )
    stream_events = []
    results = []
    probe = []
    post_probe = []
    model_catalog = {}
    try:
        if MODELS:
            model_catalog = await chat.get_model_catalog(fetch_remote=PROBE_FETCH)
        elif PROBE:
            startup_wait = 0
            while not chat.manage["start"] and startup_wait < TIMEOUT:
                await asyncio.sleep(0.5)
                startup_wait += 0.5
            probe = await chat.probe_browser_runtime(fetch_capabilities=PROBE_FETCH)
        else:
            for index, prompt in enumerate(get_prompts()):
                if index > 0:
                    data = MsgData(
                        msg_send=prompt,
                        conversation_id=data.conversation_id,
                        p_msg_id=data.next_msg_id,
                        web_search=WEB_SEARCH,
                        stream_idle_timeout_seconds=STREAM_IDLE_TIMEOUT,
                        stream_status_interval_seconds=STREAM_STATUS_INTERVAL,
                    )
                else:
                    data.msg_send = prompt

                if STREAM:
                    async def run_stream():
                        events = []
                        async for event in chat.continue_chat_stream(data):
                            events.append(
                                {
                                    "type": event.type,
                                    "text": event.text,
                                    "conversation_id": event.conversation_id,
                                    "message_id": event.message_id,
                                    "image_urls": event.image_urls,
                                    "model": event.model,
                                    "usage": event.usage,
                                    "metadata": event.metadata,
                                }
                            )
                        return events

                    stream_events = await asyncio.wait_for(run_stream(), timeout=TIMEOUT)
                else:
                    data = await asyncio.wait_for(chat.continue_chat(data), timeout=TIMEOUT)

                results.append(
                    {
                        "prompt": prompt,
                        "status": data.status,
                        "from_email": data.from_email,
                        "conversation_id": data.conversation_id,
                        "next_msg_id": data.next_msg_id,
                        "model_requested": data.model_requested,
                        "model_used": data.model_used,
                        "usage": data.usage,
                        "response_metadata": data.response_metadata,
                        "msg_recv": data.msg_recv,
                        "error_info": data.error_info,
                        "error_list": data.error_list,
                        "stream_events": stream_events,
                    }
                )
                if not data.status:
                    break
                if index < len(get_prompts()) - 1 and DELAY > 0:
                    await asyncio.sleep(DELAY)
    except TimeoutError:
        data.add_error(
            kind="local_smoke_timeout",
            message=f"local smoke timed out after {TIMEOUT} seconds",
        )
    finally:
        if PROBE_AFTER and not PROBE and not MODELS:
            try:
                post_probe = await chat.probe_browser_runtime(fetch_capabilities=False)
            except Exception as error:
                post_probe = [{"error": str(error)}]
        await chat.close()
    print(
        json.dumps(
            {
                "status": data.status,
                "from_email": data.from_email,
                "conversation_id": data.conversation_id,
                "next_msg_id": data.next_msg_id,
                "model_requested": data.model_requested,
                "model_used": data.model_used,
                "usage": data.usage,
                "response_metadata": data.response_metadata,
                "msg_recv": data.msg_recv,
                "error_info": data.error_info,
                "error_list": data.error_list,
                "stream": STREAM,
                "probe_mode": PROBE,
                "probe_fetch": PROBE_FETCH,
                "probe_after": PROBE_AFTER,
                "model_catalog_mode": MODELS,
                "web_search": WEB_SEARCH,
                "stream_idle_timeout_seconds": STREAM_IDLE_TIMEOUT,
                "session_mode_filter": SESSION_MODE,
                "session_email_filter": bool(SESSION_EMAIL),
                "save_screen": SAVE_SCREEN,
                "model_catalog": model_catalog,
                "probe": probe,
                "post_probe": post_probe,
                "stream_events": stream_events,
                "results": results,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


asyncio.run(main())
