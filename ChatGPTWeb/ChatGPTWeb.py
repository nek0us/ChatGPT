import json
from playwright.async_api import async_playwright, Route, Request,BrowserContext,Page
import asyncio
import typing
import threading
from .config import *
import logging
import re
import random
from pathlib import Path
import sys

# import json
# import random
# from playwright.async_api import async_playwright, Route, Request,BrowserContext,Page
# import asyncio
# import typing
# import threading
# from config import *
# import logging
# import re
# from pathlib import Path

class chatgpt():
    def __init__(self,
                 proxy: typing.Optional[ProxySettings] = None,
                 session_token: list = [],
                 chat_file: Path = Path()/"data"/"chat_history"/"conversation",
                 personality: Optional[Personality] = Personality([{"name":"cat","value":"you are a cat now."}]),
                 log_status: bool = True,
                 plugin: bool = False) -> None:
        '''
        proxy : your proxy for openai | 你用于访问openai的代理
        session_token : your session_token | 你的session_token
        chat_file : save the chat history file path | 保存聊天文件的路径，默认 data/chat_history/..  
        personality : init personality | 初始化人格 [{"name":"人格名","value":"预设内容"},{"name":"personality name","value":"personality value"},....]
        log_status : start log? | 开启日志输出吗
        plugin : is a Nonebot bot? | 作为Nonebot 插件实现
        '''
        self.data = MsgData()
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
                "value": x
            } for x in session_token]
        else:
            raise ValueError("session_token is empty!")
        self.manage = {
            "start":False,
            "browser_contexts":[],
            "access_token":[],
            "status":{}
        }
        
        '''start:bool 全部启动完毕
        
        browser_contexts：list 浏览器环境列表
        
        access_token：list token列表
        
        status：dict name:bool 对应环境是否加载成功
        '''
        
        
        
        if not self.plugin:
            self.browser_event_loop = asyncio.get_event_loop()
            asyncio.run_coroutine_threadsafe(self.__start__(self.browser_event_loop),self.browser_event_loop)
            
        '''
        data : base data type | 内部数据类型
        join : queue lock | 队列锁
        cookie : chatgpt cookie
        '''

    
    def set_chat_file(self):
        '''mkdir chat file path 
        创建聊天文件目录'''
        self.chat_file.mkdir(parents=True,exist_ok=True)  
        self.cc_map = self.chat_file/"map.json"
        self.cc_map.touch()
        if not self.cc_map.stat().st_size:
            self.cc_map.write_text("{}")
            
    async def __keep_alive__(self,page: Page,context_index: int):
        await asyncio.sleep(random.randint(1,60))
        try:
            async with page.expect_response(url_check,timeout=10000) as a:
                res = await page.goto(url_check, timeout=10000)
            res = await a.value
            if res.status == 403 and res.url == url_check:
                async with page.expect_response(url_check,timeout=10000) as b:
                    resb = await b.value
                    if resb.status == 200 and resb.url == url_check:
                        self.logger.info(f"flush {context_index} cf cookie OK!")
                        await page.wait_for_timeout(1000)
                        #break
                    elif resb.status == 401 and resb.url == url_check:   
                        # token过期 需要重新登录
                        self.logger.error(f"flush {context_index} cf cookie has expired!")
                        self.manage["access_token"][context_index] = ""
                        self.manage["status"][str(context_index)] = False
                        
                    else:
                        self.logger.error(f"flush {context_index} cf cookie error!")
            elif res.status == 200 and res.url == url_check:
                self.logger.info(f"flush {context_index} cf cookie OK!")
                await page.wait_for_timeout(1000)
            
            elif res.status == 401 and res.url == url_check:   
                # token过期 需要重新登录
                self.logger.error(f"flush {context_index} cf cookie has expired!")
                self.manage["access_token"][context_index] = ""
                self.manage["status"][str(context_index)] = False
                
            else:
                self.logger.error(f"flush {context_index} cf cookie error!")
            
            #await page.wait_for_timeout(self.timesleep)
        except:
            self.logger.error(f"flush {context_index} cf cookie error!")

    async def __alive__(self):
        '''keep cf cookie alive
        保持cf cookie存活
        '''
        while self.browser.contexts:
            #browser_context:BrowserContext
            tasks = []
            for context_index,browser_context in enumerate(self.manage["browser_contexts"]):
                try:
                    if not self.manage["access_token"][context_index]:
                        continue
                    page:Page = browser_context.pages[0]
                    tasks.append(self.__keep_alive__(page,context_index))
                    
                except:
                    self.logger.error(f"add {context_index} flush cf task error!")
            await asyncio.gather(*tasks)
            self.logger.info("flush over,wait next...")
            await asyncio.sleep(60)
            
        # for task in tasks:
        #     task.cancel()
        # await asyncio.gather(*tasks,return_exceptions=True)    
        
        await self.browser.close()
        await self.ap.__aexit__()
        loop = asyncio.get_event_loop()
        loop.stop()
        #loop.close()
        current_thread = threading.current_thread()
        current_thread._stop()
        


    async def __start__(self,loop):
        '''init 
        初始化'''
        self.ap = async_playwright()
        self.ass = await self.ap.start()
        self.browser = await self.ass.firefox.launch(
            #headless=False,
            slow_mo=50,proxy=self.proxy)
        tasks = []
        for context_index,x in enumerate(self.cookie):
            context = await self.browser.new_context(service_workers="block")
            await context.add_cookies([x])
            page = await context.new_page()
            tasks.append(self.load_page(context_index,page))
        
        await asyncio.gather(*tasks)
        #for context_index,browser_context in enumerate(self.browser.contexts):
            
            
            
        self.manage["browser_contexts"] = self.browser.contexts    
        
        if self.plugin:
            from nonebot.log import logger
            self.logger = logger
        self.personality.read_data()
        self.manage["start"] = True
        self.logger.info("start!")
        self.thread = threading.Thread(target=lambda: self.tmp(loop),daemon=True)
        self.thread.start()
        
    async def load_page(self,context_index:int,page: Page):
        await asyncio.sleep(random.randint(1,60))
        retry = 3
        access_token = None
        while retry:
            try:
                
                async with page.expect_response(url_session,timeout=30000) as a:
                    
                    res = await page.goto(url_session, timeout=30000)
                    #await page.wait_for_load_state('networkidle')
                    res = await a.value
                    if res.status == 403 and res.url == url_session:
                        async with page.expect_response(url_session,timeout=30000) as b:
                            await page.wait_for_load_state('load')
                            resb = await b.value
                            if resb.status == 200 and resb.url == url_session:
                                await page.wait_for_timeout(1000)
                                break
                            else:
                                retry -= 1
                                self.logger.debug(f"{str(context_index)}'s no 200!retry {str(retry)} ")
                                #await page.screenshot(path=f"{str(context_index)}'s no 200!retry {str(retry)} .png")
                                continue
                    elif res.status == 200 and res.url == url_session:
                        await page.wait_for_timeout(1000)
                        break
                    else:
                        retry -= 1
                        self.logger.debug(f"{str(context_index)}'s no 200!retry {str(retry)} ")
                        #await page.screenshot(path=f"{str(context_index)}'s no 200!retry {str(retry)} .png")
                        continue
                    
            except:
                retry -= 1
                self.logger.debug(f"{str(context_index)}'s session_token login error!retry {str(retry)} ")
                exc_type, exc_value, exc_traceback = sys.exc_info()
                #await page.screenshot(path=f"{str(context_index)}'s session_token login error!retry {str(retry)} .png")
                continue

        try:
            await asyncio.sleep(3)
            await page.wait_for_load_state('load')
            json_data = await page.evaluate(
                '() => JSON.parse(document.querySelector("body").innerText)')
            access_token = json_data['accessToken']
        except:
            #retry -= 1
            try:
                await asyncio.sleep(1)
                await page.wait_for_load_state('load')
                json_data = await page.evaluate(
                    '() => JSON.parse(document.querySelector("body").innerText)')
                access_token = json_data['accessToken']
            except:
                access_token = None
                self.logger.debug(f"{str(context_index)}'s have cf checkbox?retry {str(retry)} ")
            #await page.screenshot(path=f"{str(context_index)}'s have cf checkbox?retry {str(retry)} .png")
            #continue
            
        self.manage["access_token"].append(access_token)
        if access_token:
            self.manage["status"][str(context_index)] = True
            self.logger.info(f"context {context_index} start!")
        else:
            self.manage["status"][str(context_index)] = False
            await page.screenshot(path=f"context {context_index} faild!.png")
            self.logger.info(f"context {context_index} faild!")
            
    def tmp(self,loop):
        #task = asyncio.create_task(self.__alive__())
        #await task
        asyncio.run_coroutine_threadsafe(self.__alive__(),loop)

                
    def markdown_to_text(self,markdown_string):
        # Remove backslashes from markdown string
        markdown_string = re.sub(r'\\(.)', r'\1', markdown_string)
        # Remove markdown formatting
        markdown_string = re.sub(r'([*_~`])', '', markdown_string)
        return markdown_string      
      
    async def send_msg(self,msg_data: MsgData,page:Page,token:str,context_num:int):
        '''send message body function
        发送消息处理函数'''
        
        if not msg_data.conversation_id and not msg_data.p_msg_id:
            msg_data.post_data = Payload.new_payload(msg_data.msg_send)
            #msg_data.post_data = Payload.system_new_payload(msg_data.msg_send)
        else:
            msg_data.post_data = Payload.old_payload(msg_data.msg_send,msg_data.conversation_id,msg_data.p_msg_id)
            
        header = Payload.headers(token,msg_data.post_data)
        
        async def route_handle(route: Route, request: Request):
            header["Cookie"] = request.headers["cookie"]
            header["User-Agent"] = request.headers["user-agent"]
            await route.continue_(method="POST",headers=header,post_data=msg_data.post_data)
            
        await page.route("**/backend-api/conversation",route_handle) # type: ignore
        try:
            async with page.expect_response("https://chat.openai.com/backend-api/conversation",timeout=50000) as response_info:
                try:
                    self.logger.debug(f"send:{msg_data.msg_send}")
                    await page.goto(url_chatgpt,timeout=50000)
                except:
                    pass
            resp = await response_info.value
            if resp.status == 200:
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
                    await self.save_chat(msg_data,context_num)
                else:
                    msg_data.msg_recv = str(resp.status)
            elif resp.status == 429:
                msg_data.msg_recv = "猪咪...被玩坏了..等明天再聊吧..."
            else:
                msg_data.msg_recv = str(resp.status) +" "+ resp.status_text +" "+ await resp.text()
            return msg_data
        except:
            msg_data.msg_recv = "error"
            self.join = True
            return msg_data
        

    async def save_chat(self,msg_data: MsgData,context_num:int):
        '''save chat file
        保存聊天文件'''
        path = self.chat_file/msg_data.conversation_id
        path.touch()
        if not path.stat().st_size:
            tmp = {
                    "conversation_id":msg_data.conversation_id,
                    "message":[{
                        "input":msg_data.msg_send,
                        "output":msg_data.msg_recv,
                        "type":msg_data.msg_type,
                        "next_msg_id":msg_data.next_msg_id
                    }]
                }
            path.write_text(json.dumps(tmp))
        else:
            tmp = json.loads(path.read_text("utf8"))
            tmp["message"].append({
                    "input":msg_data.msg_send,
                    "output":msg_data.msg_recv,
                    "type":msg_data.msg_type,
                    "next_msg_id":msg_data.next_msg_id
                })
            path.write_text(json.dumps(tmp))
        
        map_tmp = json.loads(self.cc_map.read_text("utf8"))
        if str(context_num) in map_tmp:
            if msg_data.conversation_id not in map_tmp[str(context_num)]:
                map_tmp[str(context_num)].append(msg_data.conversation_id)
                self.cc_map.write_text(json.dumps(map_tmp))
        else:
            map_tmp[str(context_num)] = []
            map_tmp[str(context_num)].append(msg_data.conversation_id)
            self.cc_map.write_text(json.dumps(map_tmp))
        
                
            
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
            return json.loads(path.read_text("utf8"))
    
    async def continue_chat(self,msg_data: MsgData) -> MsgData:
        '''Message processing entry, please use this
        聊天处理入口，一般用这个'''
        while not self.manage["start"]:
            await asyncio.sleep(0.5)

        context_num:int = 0
        if msg_data.conversation_id:
            map_tmp = json.loads(self.cc_map.read_text("utf8"))
            for context_name in map_tmp:
                # 遍历环境的cid
                if msg_data.conversation_id in map_tmp[context_name]:
                    #如果cid在这个环境里
                    while not self.manage["status"][context_name]:
                        #检查这个环境有没有准备好
                        await asyncio.sleep(0.5)
                    self.manage["status"][context_name] = False
                    page = self.manage["browser_contexts"][int(context_name)].pages[0]
                    token = self.manage["access_token"][int(context_name)]
                    context_num = int(context_name)
                    break
        else:
            keys = list(self.manage["status"].keys())
            random.shuffle(keys)
            self.manage["status"] = {key: self.manage["status"][key] for key in keys}
            # 每次打乱顺序，以避免持续访问第一个
            status = False
            # 是否找到可用环境
            while True:
                for context_name in self.manage["status"]:
                    # context_name 环境名
                    if self.manage["status"][context_name]:
                        # 如果该环境好了
                        self.manage["status"][context_name] = False
                        page = self.manage["browser_contexts"][int(context_name)].pages[0]
                        token = self.manage["access_token"][int(context_name)]
                        context_num = int(context_name)
                        status = True
                        break
                if status:
                    break
                await asyncio.sleep(0.5)
                    
        # while not self.join:
        #     await asyncio.sleep(0.3)
        # self.join = False
        # if msg_data.msg_type == "old_session":
        #     msg_data.p_msg_id = msg_data.next_msg_id
        # if not msg_data.conversation_id:
        #     # 未输入会话id，尝试开启新会话
        #     pass
        
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
            
        msg_data = await self.send_msg(msg_data,page,token,context_num)
        #self.join = True
        self.manage["status"][str(context_num)] = True
        return msg_data
    

    
    async def show_chat_history(self,msg_data: MsgData) -> list:
        '''show chat history
        展示聊天记录'''
        msg_history = await self.load_chat(msg_data)
        msg = []
        for x in msg_history["message"]:
            msg.append(f"Q:{x['input']}\n\nA:{x['output']}\n\np_msg_id:{x['next_msg_id']}")
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
        msg_data.msg_send = self.personality.get_value_by_name(msg_data.msg_send)
        if msg_data.msg_send:
            msg_data.msg_type = "new_session"
            return await self.continue_chat(msg_data)
        else:
            msg_data.msg_recv = "not found"
            return msg_data
    
    async def back_init_personality(self,msg_data: MsgData):
        '''
        back the init_personality time
        回到初始化人格之后'''
        msg_data.msg_send = "1"
        msg_data.msg_type = "back_loop"
        return await self.back_chat_from_input(msg_data)
    
    async def add_personality(self,personality: dict):
        '''
        personality = {"name":"cat1","value":"you are a cat now1."}
        
        add personality,please input json just like this.
        添加人格 ,请传像这样的json数据
        '''
        self.personality.add_dict_to_list(personality)
        self.personality.flush_data()
        
    async def show_personality_list(self):
        '''show_personality_list 
        展示人格列表'''
        return self.personality.show_name()
    
    async def del_personality(self,name: str):
        '''del_personality by name
        删除人格根据名字'''
        self.personality.del_data_by_name(name)
        return self.personality.show_name()
    
    async def token_status(self):
        '''查看session token状态和工作状态'''
        cid_all = json.loads(self.cc_map.read_text("utf8"))
        return {
            "token":[True if x else False for x in self.manage["access_token"]],
            "work":self.manage["status"],
            "cid_num":[len(cid_all[x]) for x in cid_all]
        }