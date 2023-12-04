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

class chatgpt():
    def __init__(self,
                 proxy: typing.Optional[ProxySettings] = None,
                 session_token: list = [],
                 chat_file: Path = Path()/"data"/"chat_history"/"conversation",
                 personality: Optional[Personality] = Personality([{"name":"cat","value":"you are a cat now."}]),
                 log_status: bool = True,
                 plugin: bool = False,
                 headless: bool = True,
                 begin_sleep_time: bool = True,
                 arkose_status: bool = False) -> None:
        '''
        ### proxy : {"server": "http://ip:port"}
        your proxy for openai | 你用于访问openai的代理
        ### session_token : list
        your session_token | 你的 session_token
        ### chat_file : Path
        save the chat history file path | 保存聊天文件的路径，默认 data/chat_history/..  
        ### personality : list[dict]
        init personality | 初始化人格 [{"name":"人格名","value":"预设内容"},{"name":"personality name","value":"personality value"},....]
        ### log_status : bool = True
        start log? | 开启日志输出吗
        ### plugin : bool = False
        is a Nonebot bot plugin? | 作为 Nonebot 插件实现吗？
        ### headless : bool = True
        headless mode | 无头浏览器模式
        ### begin_sleep_time : bool = False
        cancel random time sleep when it start (When the number of accounts exceeds 5, they may be banned)
        
        取消启动时账号随机等待时间（账号数量大于5时可能会被临时封禁）
        ### arkose_status : bool = False
        arkose status | arokse验证状态
        '''
        self.data = MsgData()
        self.join = False
        self.proxy = proxy
        self.chat_file = chat_file
        self.personality = personality
        self.log_status = log_status
        self.plugin = plugin
        self.headless = headless
        self.begin_sleep_time = begin_sleep_time
        self.arkose_status = arkose_status
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
            "access_token":["" for x in range(0,len(self.cookie))],
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
        else:
            from nonebot.log import logger
            self.logger = logger
            
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
            async with page.expect_response(url_check,timeout=20000) as a:
                res = await page.goto(url_check, timeout=20000)
            res = await a.value
            
            
            if res.status == 403 and res.url == url_check:
                async with page.expect_response(url_check,timeout=20000) as b:
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
            for context_index,browser_context in enumerate(self.manage["browser_contexts"][:-1]):
                try:
                    if not self.manage["access_token"][context_index]:
                        continue
                    page:Page = browser_context.pages[0]
                    tasks.append(self.__keep_alive__(page,context_index))
                    
                except Exception as e:
                    self.logger.error(f"add {context_index} flush cf task error! {e}")
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
            headless=self.headless,
            slow_mo=50,proxy=self.proxy)
        tasks = []
        # chatgpt cookie context
        for context_index,x in enumerate(self.cookie):
            context = await self.browser.new_context(service_workers="block")
            await context.add_cookies([x])
            page = await context.new_page()
            tasks.append(self.load_page(context_index,page))
            
        # chatgpt arkose context (index 9999)
        context = await self.browser.new_context(service_workers="block")
        page = await context.new_page()
        tasks.append(self.load_page(99999,page))
        
        await asyncio.gather(*tasks)
        #for context_index,browser_context in enumerate(self.browser.contexts):
            
            
            
        self.manage["browser_contexts"] = self.browser.contexts    
        

        self.personality.read_data()
        self.manage["start"] = True
        self.logger.info("start!")
        self.thread = threading.Thread(target=lambda: self.tmp(loop),daemon=True)
        self.thread.start()
        
    async def load_page(self,context_index:int,page: Page):
        if self.begin_sleep_time and context_index != 99999:
            await asyncio.sleep(random.randint(1,60))
        retry = 3
        access_token = None
        if context_index != 99999:
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
            self.manage["access_token"][context_index] = access_token
            
            if access_token:
                self.manage["status"][str(context_index)] = True
                self.logger.info(f"context {context_index} start!")
            else:
                self.manage["status"][str(context_index)] = False
                await page.screenshot(path=f"context {context_index} faild!.png")
                self.logger.info(f"context {context_index} faild!")
            
        
        else:
            if self.arkose_status:
                await page.evaluate(Payload.get_ajs())
            self.manage["status"][str(context_index)] = False
            self.logger.info(f"context {context_index} js start!")
            return 
        
            
    def tmp(self,loop):
        #task = asyncio.create_task(self.__alive__())
        #await task
        asyncio.run_coroutine_threadsafe(self.__alive__(),loop)

            
    async def get_bda(self,data: str,key: str):
        page:Page = self.manage["browser_contexts"][-1].pages[0]
        js = f"ALFCCJS.encrypt('{data}','{key}')"
        res = await page.evaluate_handle(js)
        result:str = await res.json_value()
        return base64.b64encode(result.encode('utf8')).decode('utf8')     
           
    def markdown_to_text(self,markdown_string):
        # Remove backslashes from markdown string
        # markdown_string = re.sub(r'\\(.)', r'\1', markdown_string)
        # Remove markdown formatting
        # markdown_string = re.sub(r'([*_~`])', '', markdown_string)
        # markdown_string = re.sub(r'\\(.)', r'\1', markdown_string)
        return markdown_string      
      
    async def send_msg(self,msg_data: MsgData,page:Page,token:str,context_num:int):
        '''send message body function
        发送消息处理函数'''
        
        # 获取arkose
        if self.arkose_status:
            async def route_arkose(route: Route, request: Request):
                userAgent = request.headers["user-agent"]
                data = Payload.get_data()
                key = Payload.get_key(userAgent)
                bda = await self.get_bda(data,key)
                
                msg_data.arkose_data = Payload.rdm_arkose(userAgent,bda)
                msg_data.arkose_header = Payload.header_arkose(msg_data.arkose_data)
                msg_data.arkose_header["Cookie"] = request.headers["cookie"]
                msg_data.arkose_header["User-Agent"] = request.headers["user-agent"]
                await route.continue_(method="POST",headers=msg_data.arkose_header,post_data=msg_data.arkose_data)
                
            await page.route("**/fc/gt2/public_key/3D86FBBA-9D22-402A-B512-3420086BA6CC",route_arkose) # type: ignore
            
            async with page.expect_response("https://tcr9i.chat.openai.com/fc/gt2/public_key/3D86FBBA-9D22-402A-B512-3420086BA6CC",timeout=400000) as arkose_info:
                try:
                    
                    await page.wait_for_load_state('load')
                    self.logger.debug("get arkose")
                    await page.goto(url_arkose,timeout=500000)
                    await page.wait_for_load_state('load')
                except Exception as e:
                    logging.warning(e)
                    await page.goto(url_arkose,timeout=300000)
                    await page.wait_for_load_state('load')
                resp_arkose = await arkose_info.value
                if resp_arkose.status == 200:
                    arkose_json = await resp_arkose.json()
                    msg_data.arkose = arkose_json["token"]
                else:
                    pass
        else:
            msg_data.arkose = None
            
        if not msg_data.conversation_id and not msg_data.p_msg_id:
            msg_data.post_data = Payload.new_payload(msg_data.msg_send,msg_data.arkose)
            #msg_data.post_data = Payload.system_new_payload(msg_data.msg_send)
        else:
            msg_data.post_data = Payload.old_payload(msg_data.msg_send,msg_data.conversation_id,msg_data.p_msg_id,msg_data.arkose)
            
        header = Payload.headers(token,msg_data.post_data)
        
        async def route_handle(route: Route, request: Request):
            header["Cookie"] = request.headers["cookie"]
            header["User-Agent"] = request.headers["user-agent"]
            await route.continue_(method="POST",headers=header,post_data=msg_data.post_data)
            
        await page.route("**/backend-api/conversation",route_handle) # type: ignore
        try:
            async with page.expect_response("https://chat.openai.com/backend-api/conversation",timeout=40000) as response_info:
                try:
                    self.logger.debug(f"send:{msg_data.msg_send}")
                    await page.goto(url_chatgpt,timeout=50000)
                except Exception as e:
                    # logging.warning(e)
                    pass
            resp = await response_info.value
            if resp.status == 200:
                stream_text = await resp.text()
                stream_lines = stream_text.splitlines()
                for x in stream_lines:
                    for x in stream_lines:
                        if "finish_details" in x:
                            msg = json.loads(x[6:])
                            tmp = msg["message"]["content"]["parts"][0]
                            msg_data.msg_recv = self.markdown_to_text(tmp) 
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
                msg_data.msg_recv = "error http code 429"
            else:
                msg_data.msg_recv = str(resp.status) +" "+ resp.status_text +" "+ await resp.text()
            return msg_data
        except:
            try:
                async with page.expect_response("https://chat.openai.com/backend-api/conversation",timeout=30000) as response_info:
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
                    msg_data.msg_recv = "429 error http code ..."
                else:
                    msg_data.msg_recv = str(resp.status) +" "+ resp.status_text +" "+ await resp.text()
                return msg_data
            except Exception as e:
        
                msg_data.msg_recv = f"error:{e}"
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
        iscid = False
        # 判断cid是否可用
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
                    iscid = True
                    break

        if not iscid:
            # keys = list(self.manage["status"].keys())
            # random.shuffle(keys)
            # self.manage["status"] = {key: self.manage["status"][key] for key in keys}
            # 每次打乱顺序，以避免持续访问第一个
            status = False
            # 是否找到可用环境
            while True:
                true_status = [value for value in self.manage["status"] if self.manage["status"][value]]
                # 状态元组 (index,value)
                    # context_name 环境名
                if not true_status:
                    # 都没准备好，继续等待
                    await asyncio.sleep(1)
                    continue
                select_context = random.choice(true_status)    
                # if self.manage["status"][context_name]:
                    # 如果该环境好了
                    
                self.manage["status"][select_context[0]] = False
                
                page = self.manage["browser_contexts"][int(select_context[0])].pages[0]
                token = self.manage["access_token"][int(select_context[0])]
                context_num = int(select_context[0])
                status = True
                
                if status:
                    break
                await asyncio.sleep(0.5)
                
        
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
            "work":[self.manage["status"][x] for x in self.manage["status"] if x != "99999"],
            "cid_num":[len(cid_all[x]) for x in cid_all]
        }

    