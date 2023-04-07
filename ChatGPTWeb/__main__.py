from contextlib import asynccontextmanager,contextmanager
from GPT import chatgpt
from config import MsgData
import asyncio
import aioconsole

session_token=""

a = chatgpt(session_token=session_token)

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
        elif data.msg_send == "history":
            print(await a.show_chat_history(data))
            continue
        await a.simple_example(data)
        
        
loop = asyncio.get_event_loop()
loop.run_until_complete(main())           
    


