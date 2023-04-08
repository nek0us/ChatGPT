import json
from playwright.async_api import async_playwright, Route, Request
import asyncio
import typing
import threading
from config import *
import logging
import re
from pathlib import Path

class chatgpt():
    def __init__(self,
                 proxy: typing.Optional[ProxySettings] = None,
                 session_token: str = "",
                 chat_file: Path = Path()/"data"/"chat_history",
                 personality: str = "",
                 log_status: bool = True,
                 plugin: bool = False) -> None:
        '''
        proxy : your proxy for openai | 你用于访问openai的代理
        session_token : your session_token | 你的session_token
        chat_file : save the chat history file path | 保存聊天文件的路径，默认 data/chat_history/..  
        personality : init personality | 初始化人格
        log_status : start log? | 开启日志输出吗
        plugin : is a Nonebot bot? | 作为Nonebot 插件实现
        '''
        self.data = MsgData()
        self.status = False
        self.join = False
        self.proxy = proxy
        self.chat_file = chat_file
        self.personality = personality
        self.log_status = log_status
        self.plugin = plugin
        self.set_chat_file()
        self.logger = logging.getLogger("logger")
        self.logger.setLevel(logging.INFO)
        sh = logging.StreamHandler()
        sh.setFormatter(formator)
        self.logger.addHandler(sh)
        if not self.log_status:
            self.logger.removeHandler(sh)
            
        if session_token:
            self.cookie: typing.List[SetCookieParam] = [{
                "url": "https://chat.openai.com",
                "name": "__Secure-next-auth.session-token",
                "value": session_token
            }]
        else:
            raise ValueError("session_token is empty!")
        '''
        data : base data type | 内部数据类型
        status : is init ok? | 等待初始化完成
        join : queue lock | 队列锁
        cookie : chatgpt cookie
        '''
        
        if not self.plugin:
            self.browser_event_loop = asyncio.get_event_loop()
            asyncio.run_coroutine_threadsafe(self.__start__(self.browser_event_loop),self.browser_event_loop)

    
    def set_chat_file(self):
        '''mkdir chat file path 
        创建聊天文件目录'''
        self.chat_file.mkdir(parents=True,exist_ok=True)  

    async def __alive__(self):
        '''keep cf cookie alive
        保持cf cookie存活
        '''
        while 1:
            try:
                async with self.page.expect_response(url_session,timeout=20000) as a:
                    res = await self.page.goto(url_session, timeout=20000)
                res = await a.value
                if res.status == 403 and res.url == url_session:
                    async with self.page.expect_response(url_session,timeout=20000) as b:
                        resb = await b.value
                        if resb.status == 200 and resb.url == url_session:
                            self.logger.info("flush cf cookie OK!")
                            await self.page.wait_for_timeout(1000)
                            #break
                        else:
                            self.logger.error("flush cf cookie error!")
                elif res.status == 200 and res.url == url_session:
                    self.logger.info("flush cf cookie OK!")
                    await self.page.wait_for_timeout(1000)
                else:
                    self.logger.error("flush cf cookie error!")
            except:
                self.logger.error("flush cf cookie error!")
            await self.page.wait_for_timeout(60000)
                
    async def __start__(self,loop):
        '''init 
        初始化'''
        self.ap = await async_playwright().start()
        self.browser = await self.ap.firefox.launch(
            #headless=False,
            slow_mo=50,proxy=self.proxy)
        self.context = await self.browser.new_context(service_workers="block")
        await self.context.add_cookies(self.cookie)
        self.page = await self.context.new_page()
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
            self.join = True
            
        if self.plugin:
            from nonebot.log import logger
            self.logger = logger
        threading.Thread(target=self.tmp(loop)).start()
            
    def tmp(self,loop):
        asyncio.run_coroutine_threadsafe(self.__alive__(),loop)

                
    def markdown_to_text(self,markdown_string):
        # Remove backslashes from markdown string
        markdown_string = re.sub(r'\\(.)', r'\1', markdown_string)
        # Remove markdown formatting
        markdown_string = re.sub(r'([*_~`])', '', markdown_string)
        return markdown_string      
      
    async def send_msg(self,msg_data: MsgData):
        '''send message body function
        发送消息处理函数'''
        while not self.status:
            await asyncio.sleep(0.5)
        
        if not msg_data.conversation_id and not msg_data.p_msg_id:
            msg_data.post_data = Payload.new_payload(msg_data.msg_send)
        else:
            msg_data.post_data = Payload.old_payload(msg_data.msg_send,msg_data.conversation_id,msg_data.p_msg_id)
            
        self.header = Payload.headers(self.access_token,msg_data.post_data)
        
        async def route_handle(route: Route, request: Request):
            if "cookie" in request.headers:
                self.header["Cookie"] = request.headers["cookie"]
            if "user-agent" in request.headers:
                self.header["User-Agent"] = request.headers["user-agent"]
            await route.continue_(method="POST",headers=self.header,post_data=msg_data.post_data)
            
        await self.page.route("**/backend-api/conversation",route_handle) # type: ignore
        
        async with self.page.expect_response("https://chat.openai.com/backend-api/conversation") as response_info:
            try:
                self.logger.debug(f"send:{msg_data.msg_send}")
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
        if stream_lines:
            self.logger.debug(f"recive:{msg_data.msg_recv}")
            await self.save_chat(msg_data)
        else:
            msg_data.msg_recv = str(resp.status)
        return msg_data
        

    async def save_chat(self,msg_data: MsgData):
        '''save chat file
        保存聊天文件'''
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
        '''load chat file
        读取聊天文件'''
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
        '''Message processing entry, please use this
        聊天处理入口，一般用这个'''
        
        while not self.join:
            await asyncio.sleep(0.3)
        self.join = False
        if msg_data.msg_type == "old_session":
            msg_data.p_msg_id = msg_data.next_msg_id
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
        self.join = True
        return msg_data
    
    
    async def show_chat_history(self,msg_data: MsgData) -> str:
        '''show chat history
        展示聊天记录'''
        msg_history = await self.load_chat(msg_data)
        msg = ""
        for x in msg_history["message"]:
            msg += f"Q:{x['input']}\nA:{x['output']}\np_msg_id:{x['next_msg_id']}\n\n"
        return msg
    
    async def back_chat_from_input(self,msg_data: MsgData):
        '''back chat from input
        You can enter the text that appeared last time, or the number of dialogue rounds starts from 1
        
        通过输入来回溯
        你可以输入最后一次出现过的文字，或者对话回合序号(从1开始)
        
        Note: backtracking will not reset the recorded chat files, 
        please pay attention to whether the content displayed in the chat records exists when backtracking again
        
        注意：回溯不会重置记录的聊天文件，请注意再次回溯时聊天记录展示的内容是否存在
        
        '''
        if not msg_data.conversation_id:
            msg_data.msg_recv = "no conversation_id"
            return msg_data
        msg_history = await self.load_chat(msg_data)
        tmp_p = ""
        tmp_i = ""
        try:
            index = int(msg_data.msg_send)
            tmp_p = msg_history["message"][index-1]["next_msg_id"]
            tmp_i = msg_history["message"][index]["input"]
        except ValueError:
            for index,x in enumerate(msg_history["message"][::-1]):
                if msg_data.msg_send in x["input"] or msg_data.msg_send in x["output"]:
                    tmp_p = x["next_msg_id"]
                    tmp_i = msg_history["message"][::-1][index-1]["input"] 
        except:
            pass
        if tmp_p:
            msg_data.p_msg_id = tmp_p
            msg_data.msg_send = tmp_i
            msg_data.msg_type = "back_loop"
            return await self.continue_chat(msg_data)
        else:
            msg_data.msg_recv = "back error"
            return msg_data
            
    async def init_personality(self,msg_data: MsgData):
        '''init_personality
        初始化人格'''
        msg_data.msg_send = self.personality
        msg_data.conversation_id = ""
        msg_data.p_msg_id = ""
        msg_data.msg_type = "new_session"
        return await self.continue_chat(msg_data)
    
    async def back_init_personality(self,msg_data: MsgData):
        '''
        back the init_personality time
        回到初始化人格之后'''
        msg_data.msg_send = "1"
        msg_data.msg_type = "back_loop"
        return await self.back_chat_from_input(msg_data)
    
