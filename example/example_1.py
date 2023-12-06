from ChatGPTWeb import chatgpt
from ChatGPTWeb.config import Personality, MsgData

sessions = [
    {
        "session_token": "Your session_token"

    },
    {
        "email": "Your email",
        "password": "Your Password"
    }
]
personality_definition = Personality(
    [
        {
            "name": "Programmer",
            'value': 'You are python Programmer'
        },
    ])

chat = chatgpt(sessions=sessions, headless=False, begin_sleep_time=False)

data: MsgData = MsgData()
data.msg_send = "hello"

data = chat.ask(data)
# data = chat.browser_event_loop.run_until_complete(chat.continue_chat(data))

print(f"ChatGPT:{data.msg_recv}")
