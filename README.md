# ChatGPT
a ChatGPT api,no web ui

一个不怎么使用网页的ChatGPT api
[![PyPi](https://img.shields.io/pypi/v/ChatGPTWeb.svg)](https://pypi.python.org/pypi/ChatGPTWeb)

# 安装/Install
Ubuntu & Windows

```bash
pip install ChatGPTWeb

sudo playwright install-deps

playwright install firefox
```


### MsgData() 数据类型
```bash 
class MsgData(): 
    status: bool = False,
    msg_type: typing.Optional[typing.Literal["old_session","back_loop","new_session"]] = "new_session",
    msg_send: str = "hi",
    # your msg 
    msg_recv: str = "",
    # gpt's msg
    conversation_id: str = "",
    p_msg_id: str = "",
    # p_msg_id : the message's parent_message_id in this conversation id / 这个会话里某条消息的 parent_message_id
    next_msg_id: str = "",
    post_data: str = ""


from ChatGPTWeb.config import MsgData
data:MsgData = MsgData(conversation_id=c_id,p_msg_id=p_id)
```
# 使用/Used
just simple to use

简单使用

### copy __main__.py or this code to start / 复制 __main__.py 或者以下code来开始
```bash
from ChatGPTWeb.ChatGPTWeb import chatgpt
from ChatGPTWeb.config import MsgData
import asyncio
import aioconsole

session_token=""
person = "hello,my name is 'pig'."
chat = chatgpt(session_token=session_token,personality=person,log_status=False)

async def main():
    
    c_id = await aioconsole.ainput("your conversation_id if you have:")
    p_id = await aioconsole.ainput("your parent_message_id if you have:")
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
            data = await chat.init_personality(data)
            print(f"ChatGPT:{data.msg_recv}")
            continue
        elif data.msg_send == "history":
            print(await chat.show_chat_history(data))
            continue
        data = await chat.continue_chat(data)
        print(f"ChatGPT:{data.msg_recv}")
        
        
loop = asyncio.get_event_loop()
loop.run_until_complete(main())           
    
```


