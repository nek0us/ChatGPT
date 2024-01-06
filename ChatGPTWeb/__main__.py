import asyncio
from ChatGPTWeb import chatgpt
from ChatGPTWeb.config import Personality, MsgData
import aioconsole

sessions = [
    {
        "session_token": ""

    },
    {
        "email": "xxx@hotmail.com",
        "password": "",
        # "mode":"openai" ,
        "session_token": "",
    },
    {
        "email": "xxx@outlook.com",
        "password": "",
        "mode":"microsoft"
    },
    {
        "email": "xxx@gmail.com",
        "password": "",
        "mode":"google"
    }
]
# please remove account if u don't have 

personality_definition = Personality(
    [
        {
            "name": "Programmer",
            'value': 'You are python Programmer'
        },
    ])

chat = chatgpt(sessions=sessions, begin_sleep_time=False, headless=True,log_status=False)
# if u need,u can "log_status=True"
# "begin_sleep_time=False" for testing only
# Make sure "headless=True" when using

async def main():
    c_id = await aioconsole.ainput("your conversation_id if you have:")
    # if u don't have,pleases enter empty
    p_id = await aioconsole.ainput("your parent_message_id if you have:")
    # if u don't have,pleases enter empty
    data:MsgData = MsgData(conversation_id=c_id,p_msg_id=p_id)
    while 1:
        print("\n------------------------------")
        data.msg_send = await aioconsole.ainput("input：")
        print("------------------------------\n")
        if data.msg_send == "quit":
            break
        elif data.msg_send == "re":
            data.msg_type = "back_loop"
            data.p_msg_id = await aioconsole.ainput("your parent_message_id if you go back:")
        elif data.msg_send == "reset":
            data = await chat.back_init_personality(data)
            print(f"ChatGPT:{data.msg_recv}")
            continue
        elif data.msg_send == "init_personality":
            data.msg_send = "your ..."
            data = await chat.init_personality(data)
            print(f"ChatGPT:{data.msg_recv}")
            continue
        elif data.msg_send == "history":
            print(await chat.show_chat_history(data))
            continue
        elif data.msg_send == "status":
            print(await chat.token_status())
            continue
        data = await chat.continue_chat(data)
        print(f"ChatGPT:{data.msg_recv}")
        
        
loop = asyncio.get_event_loop()
loop.run_until_complete(main())           
    
