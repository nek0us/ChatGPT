import asyncio
import json
import os
from pathlib import Path

import aioconsole

from ChatGPTWeb import chatgpt
from ChatGPTWeb.config import IOFile, MsgData


SESSIONS_FILE = Path(os.getenv("CHATGPTWEB_SESSIONS_FILE", "example/local_sessions.json"))


def load_sessions() -> list[dict]:
    if not SESSIONS_FILE.exists():
        raise FileNotFoundError(
            f"Missing {SESSIONS_FILE}. Copy example/local_sessions.example.json "
            f"to {SESSIONS_FILE} and fill it with local test accounts."
        )
    sessions = json.loads(SESSIONS_FILE.read_text("utf8"))
    if not sessions:
        raise ValueError(f"{SESSIONS_FILE} does not contain any sessions")
    return sessions


chat = chatgpt(
    sessions=load_sessions(),
    begin_sleep_time=False,
    headless=False,
    httpx_status=False,
    logger_level="DEBUG",
    stdout_flush=True,
    local_js=True,
)


async def main():
    c_id = await aioconsole.ainput("your conversation_id if you have:")
    p_id = await aioconsole.ainput("your parent_message_id if you have:")
    data = MsgData(conversation_id=c_id, p_msg_id=p_id)
    while True:
        print("------------------------------")
        data.msg_send = await aioconsole.ainput("input:")
        print("------------------------------")
        if data.msg_send == "quit":
            break
        if data.msg_send == "gpt4o":
            if data.gpt_model != "gpt-4o":
                data.gpt_model = "gpt-4o"
                data.conversation_id = ""
                data.p_msg_id = ""
            data.msg_send = await aioconsole.ainput("reinput:")
            if data.msg_send == "what's the png":
                with open("1.png", "rb") as f:
                    data.upload_file.append(IOFile(content=f.read(), name="1.png"))
        elif data.msg_send == "gpt3.5":
            if data.gpt_model != "text-davinci-002-render-sha":
                data.gpt_model = "text-davinci-002-render-sha"
                data.conversation_id = ""
                data.p_msg_id = ""
            data.msg_send = await aioconsole.ainput("reinput:")
        elif data.msg_send == "re":
            data.msg_type = "back_loop"
            data.p_msg_id = await aioconsole.ainput("your parent_message_id if you go back:")
        elif data.msg_send == "history":
            print(await chat.show_chat_history(data))
            continue
        elif data.msg_send == "status":
            print(await chat.token_status())
            continue

        data = await chat.continue_chat(data)
        if data.msg_recv == "":
            print(f"error:{data.error_info}")
            if data.error_list:
                print(f"error_list:{data.error_list}")
        else:
            print(f"ChatGPT:{data.msg_recv}")
        data.error_info = ""
        data.error_list.clear()
        data.msg_recv = ""
        data.p_msg_id = ""


asyncio.run(main())
