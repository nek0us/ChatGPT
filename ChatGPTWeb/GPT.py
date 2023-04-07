import json
from playwright.async_api import async_playwright, Route, Request
import asyncio
import typing
import threading
from config import *
import logging
from contextlib import asynccontextmanager
import re
from pathlib import Path



class chatgpt():
    def __init__(self,
                 proxy: typing.Optional[ProxySettings] = None,
                 session_token: str = "",
                 chat_file: Path = Path()/"data"/"chat_history") -> None:
        self.data = MsgData()
        self.status = False
        self.proxy = proxy
        self.chat_file = chat_file
        self.set_chat_file()
        self.logger = logging.getLogger("logger")
        self.logger.setLevel(logging.INFO)
        sh = logging.StreamHandler()
        sh.setFormatter(formator)
        self.logger.addHandler(sh)
        self.cookie: typing.List[SetCookieParam] = [{
            "url": "https://chat.openai.com",
            "name": "__Secure-next-auth.session-token",
            "value": session_token
        }]
        self.browser_event_loop = asyncio.get_event_loop()
        #threading.Thread(target=lambda: self.run_loop(self.browser_event_loop),
        #                 daemon=True).start()
        asyncio.run_coroutine_threadsafe(self.__start__(),
                                         self.browser_event_loop)
    
    def set_chat_file(self):
        self.chat_file.mkdir(parents=True,exist_ok=True)  
          
    
    def run_loop(self, loop):
        asyncio.set_event_loop(loop)
        loop.run_forever()

    async def __start__(self):
        self.ap = await async_playwright().start()
        self.browser = await self.ap.firefox.launch(
            #headless=False,
            slow_mo=50,proxy=self.proxy)
        self.context = await self.browser.new_context(service_workers="block")
        await self.context.add_cookies(self.cookie)
        self.page = await self.context.new_page()
        #self.logger.info("browser started")
        #self.logger.info("begin goto get session")
        #res = await self.page.goto(url_session, timeout=60000)
        while 1:
            async with self.page.expect_response(url_session,timeout=20000) as a:
                
                res = await self.page.goto(url_session, timeout=20000)
                res = await a.value
                if res.status == 403 and res.url == url_session:
                    async with self.page.expect_response(url_session,timeout=20000) as b:
                        resb = await b.value
                        if resb.status == 200 and resb.url == url_session:
                            await self.page.wait_for_timeout(1000)
                            break
                elif res.status == 200 and res.url == url_session:
                    await self.page.wait_for_timeout(1000)
                    break
            #res = await self.page.goto(url_session, timeout=20000)
            await self.page.wait_for_timeout(20000)

        try:
            json_data = await self.page.evaluate(
                '() => JSON.parse(document.querySelector("body").innerText)')
            access_token = json_data['accessToken']
        except:
            access_token = None

        if access_token:
            self.access_token = access_token
            self.status = True
            while 1:
                async with self.page.expect_response(url_session,timeout=20000) as a:
                    res = await self.page.goto(url_session, timeout=20000)
                    res = await a.value
                    if res.status == 403 and res.url == url_session:
                        async with self.page.expect_response(url_session,timeout=20000) as b:
                            resb = await b.value
                            if resb.status == 200 and resb.url == url_session:
                                await self.page.wait_for_timeout(1000)
                                #break
                    elif res.status == 200 and res.url == url_session:
                        await self.page.wait_for_timeout(1000)
                        #break
                #res = await self.page.goto(url_session, timeout=20000)
                await self.page.wait_for_timeout(60000)

    async def bypass_cf(self):
        #self.logger.info("begin bypass_cf")
        while 1:
            async with self.page.expect_response(url_session,timeout=20000) as a:
                
                res = await self.page.goto(url_session, timeout=20000)
                res = await a.value
                if res.status == 403 and res.url == url_session:
                    async with self.page.expect_response(url_session,timeout=20000) as b:
                        resb = await b.value
                        if resb.status == 200 and resb.url == url_session:
                            await self.page.wait_for_timeout(1000)
                            break
                elif res.status == 200 and res.url == url_session:
                    await self.page.wait_for_timeout(1000)
                    break
                
    def markdown_to_text(self,markdown_string):
        # Remove backslashes from markdown string
        markdown_string = re.sub(r'\\(.)', r'\1', markdown_string)
        # Remove markdown formatting
        markdown_string = re.sub(r'([*_~`])', '', markdown_string)
        return markdown_string      
      
    async def send_msg(self,msg_data: MsgData):
        while not self.status:
            await asyncio.sleep(0.5)
        #await self.bypass_cf()
        if not msg_data.conversation_id and not msg_data.p_msg_id:
            msg_data.post_data = Payload.new_payload(msg_data.msg_send)
        else:
            msg_data.post_data = Payload.old_payload(msg_data.msg_send,msg_data.conversation_id,msg_data.p_msg_id)
            
        self.header = Payload.headers(self.access_token,msg_data.post_data)
        
        async def route_handle(route: Route, request: Request):
            if "cookie" in request.headers:
                self.header["Cookie"] = request.headers["cookie"]
            await route.continue_(method="POST",headers=self.header,post_data=msg_data.post_data)
            
        await self.page.route("**/backend-api/conversation",route_handle) # type: ignore
        
        async with self.page.expect_response("https://chat.openai.com/backend-api/conversation") as response_info:
            try:
                await self.page.goto(url_chatgpt)
            except:
                pass
        resp = await response_info.value
        stream_text = await resp.text()
        stream_lines = stream_text.splitlines()
        for x in stream_lines:
            for x in stream_lines:
                if "finish_details" in x:
                    msg = json.loads(x[6:])
                    msg_data.msg_recv = self.markdown_to_text(msg["message"]["content"]["parts"][0]) 
                    msg_data.conversation_id = msg["conversation_id"]
                    msg_data.next_msg_id = msg["message"]["id"]
                    msg_data.status = True
                    msg_data.msg_type = "old_session"
        await self.save_chat(msg_data)
        return msg_data
        
    
        
    # @asynccontextmanager
    # async def __msg_queue__(self,msg_data: MsgData):
    #     if msg_data.msg_type == "new_session":
    #         msg_data = await self.send_msg(msg_data)
    #     elif msg_data.msg_type == "old_session":
    #         pass
    #     elif msg_data.msg_type == "back_loop":
    #         pass
    #     #self.__status = False
    #     yield msg_data


    # async def msg_handle(self,prompt: str = "",msg_type: str = "",conversation_id: str = "",p_msg_id: str = ""):
    #     msg_data = MsgData(msg_send=prompt,conversation_id=conversation_id,p_msg_id=p_msg_id)
        
    #     msg_data = await self.send_msg(msg_data)
    #     if msg_data.status:
    #         self.logger.info("保存消息中")
    #         await self.save_chat(msg_data)
    #         print(f"消息为：{msg_data.msg_recv}\n会话id为：{msg_data.conversation_id}\nn_msg_id为{msg_data.next_msg_id}")
    #     else:
    #         print("消息失败")
    #     return msg_data
        # async with self.__msg_queue__(msg_data) as msg_data:
        #     if msg_data.status:
                # self.logger.info("保存消息中")
                # await self.save_chat(msg_data)
                # print(f"消息为：{msg_data.msg_recv}\n会话id为：{msg_data.conversation_id}\nn_msg_id为{msg_data.next_msg_id}")
                
    async def save_chat(self,msg_data: MsgData):
        path = self.chat_file/msg_data.conversation_id
        path.touch()
        if not path.stat().st_size:
            with open(path,"w") as f:
                tmp = {
                    "conversation_id":msg_data.conversation_id,
                    "message":[{
                        "input":msg_data.msg_send,
                        "output":msg_data.msg_recv,
                        "type":msg_data.msg_type,
                        "next_msg_id":msg_data.next_msg_id
                    }]
                }
                f.write(json.dumps(tmp)) 
        else:
            with open(path,"r") as f:
                tmp = json.loads(f.read())
            with open(path,"w") as f:
                tmp["message"].append({
                    "input":msg_data.msg_send,
                    "output":msg_data.msg_recv,
                    "type":msg_data.msg_type,
                    "next_msg_id":msg_data.next_msg_id
                })
                f.write(json.dumps(tmp))
                
            
    async def load_chat(self,msg_data: MsgData):
        path = self.chat_file/msg_data.conversation_id
        path.touch()
        if not path.stat().st_size:
            #self.logger.warning(f"不存在{msg_data.conversation_id}历史记录文件")
            return {
                "conversation_id":msg_data.conversation_id,
                "message":[]
                }
        else:
            with open(path,"r") as f:
                tmp = json.loads(f.read())
                return tmp
    
    async def continue_chat(self,msg_data: MsgData) -> MsgData:
        if not msg_data.conversation_id:
            # 未输入会话id，尝试开启新会话
            pass
        
        if msg_data.p_msg_id:
            # 存在输入的p_msg_id
            pass
        else:
            # 未输入，尝试从文件里恢复
            try:
                msg_history = await self.load_chat(msg_data)
                msg_data.p_msg_id = msg_history["message"][-1]["next_msg_id"]
            except:
                # 恢复失败
                pass
            
        msg_data = await self.send_msg(msg_data)
        return msg_data
    
    
    async def show_chat_history(self,msg_data: MsgData) -> str:
        msg_history = await self.load_chat(msg_data)
        msg = ""
        for x in msg_history["message"]:
            msg += f"Q:{x['input']}\nA:{x['output']}\np_msg_id:{x['next_msg_id']}\n\n"
        return msg
    
    async def simple_example(self,msg_data: MsgData):
        if msg_data.msg_type == "old_session":
            msg_data.p_msg_id = msg_data.next_msg_id
        msg_data = await self.continue_chat(msg_data)
        print(f"ChatGPT:{msg_data.msg_recv}")
        
