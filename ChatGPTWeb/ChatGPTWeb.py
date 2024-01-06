import json
import os
from playwright.async_api import async_playwright, Route, Request, BrowserContext, Page
import asyncio
import typing
import threading
import re
import random
from pathlib import Path
import sys

from .config import *
from .api import (
    async_send_msg,
    recive_handle,
    create_session,
    retry_keep_alive,
    Auth,
    get_session_token,
)

class chatgpt:
    def __init__(self,
                 sessions: list[dict] = [],
                 proxy: typing.Optional[ProxySettings] = None,
                 chat_file: Path = Path("data", "chat_history", "conversation"),
                 personality: Optional[Personality] = Personality([{"name": "cat", "value": "you are a cat now."}]),
                 log_status: bool = True,
                 plugin: bool = False,
                 headless: bool = True,
                 begin_sleep_time: bool = True,
                 arkose_status: bool = False

                 ) -> None:
        """
        ### sessions : list[dict]
        your session_token or account | 你的session_token 或者账号密码  {"session_token":""}
        ### proxy : {"server": "http://ip:port"}
        your proxy for openai | 你用于访问openai的代理
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
        """
        self.Sessions = []
        self.data = MsgData()
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
        
        if not sessions:
            raise ValueError("session_token is empty!")

        for session in sessions:
            s = Session(**session)
            s = create_session(**session)
            if s.is_valid:
                s.type = "session"
                s = get_session_token(s,self.chat_file,self.logger)
                self.Sessions.append(s)

        self.manage = {
            "start": False,
            "sessions": self.Sessions,
            "browser_contexts": [],
            # "access_token": ["" for x in range(0, len(self.cookies))],
            # "status": {}
        }

        '''
        start:bool All started | 全部启动完毕 
        
        sessions：list sessions |  sessions 列表
        
        browser_contexts：list Browser environment list | 浏览器环境列表
        '''
        if not self.plugin:
            self.browser_event_loop = asyncio.get_event_loop()
            asyncio.run_coroutine_threadsafe(self.__start__(self.browser_event_loop),self.browser_event_loop)
        elif self.log_status:
            from nonebot.log import logger # type: ignore
            self.logger = logger

        '''
        data : base data type | 内部数据类型
        '''

    # 检测Firefox是否已经安装 
    async def is_firefox_installed(self):
        '''chekc firefox install | 检测Firefox是否已经安装 '''
        try:
            playwright_manager = async_playwright()
            playwright = await playwright_manager.start()
            browser = await playwright.firefox.launch(
            headless=self.headless,
            slow_mo=50, proxy=self.proxy)
            await browser.close()
            return True
        except Exception as e:
            return False

    # 安装Firefox
    def install_firefox(self):
        os.system('playwright install firefox')
    
    def set_chat_file(self):
        """
        mkdir chat file path
        创建聊天文件目录
        """
        self.chat_file.mkdir(parents=True, exist_ok=True)
        session_file_dir = self.chat_file / "sessions"
        session_file_dir.mkdir(parents=True, exist_ok=True)
        self.cc_map = self.chat_file.joinpath("map.json")
        self.cc_map.touch()
        if not self.cc_map.stat().st_size:
            self.cc_map.write_text("{}")

    async def __keep_alive__(self, session: Session):
        url = url_check
        await asyncio.sleep(random.randint(1, 60 if len(self.Sessions) < 10 else 6 * len(self.Sessions)))
        session = await retry_keep_alive(session,url,self.chat_file,self.logger)

    async def __alive__(self):
        """keep cf cookie alive
        保持cf cookie存活
        """
        while self.browser.contexts:
            # browser_context:BrowserContext
            tasks = []
            for session in filter(lambda s: s.type != "script", self.Sessions):
                context_index = session.email
                try:
                    if session.status == Status.Stop:
                        continue
                    tasks.append(self.__keep_alive__(session))
                except Exception as e:
                    self.logger.error(f"add {context_index} flush cf task error! {e}")

            await asyncio.gather(*tasks)
            self.logger.info("flush over,wait next...")
            await asyncio.sleep(60 if len(self.Sessions) < 10 else 6 * len(self.Sessions))

        # for task in tasks:
        #     task.cancel()
        # await asyncio.gather(*tasks,return_exceptions=True)    

        await self.browser.close()
        await self.playwright_manager.__aexit__()
        loop = asyncio.get_event_loop()
        loop.stop()
        # loop.close()
        current_thread = threading.current_thread()
        current_thread._stop() # type: ignore

    

    async def __login(self, session: Session):
        if not session.browser_contexts:
            session.browser_contexts = await self.browser.new_context(service_workers="block")

        if session.session_token:
            token = session.session_token
            await session.browser_contexts.add_cookies([token]) # type: ignore
            session.page = await session.browser_contexts.new_page()
            session.status = Status.Login.value 

        elif session.email and session.password:
            session.page = await session.browser_contexts.new_page()
            await Auth(session,self.logger)
        else:
            # TODO:
            pass

    async def __start__(self, loop):
        """
        init | 初始化
        """
        if not await self.is_firefox_installed():
            self.logger.info("Firefox browser is not installed, installing...")
            self.install_firefox()
            self.logger.info("Firefox browser has been successfully installed.")
        else:
            self.logger.info("Firefox browser is already installed.")
            
        self.playwright_manager = async_playwright()
        self.playwright = await self.playwright_manager.start()
        self.browser = await self.playwright.firefox.launch(
            headless=self.headless,
            slow_mo=50, proxy=self.proxy)
        
        # arkose context
        tasks = []
        s = Session(type="script")
        s.browser_contexts = await self.browser.new_context(service_workers="block")
        s.page = await s.browser_contexts.new_page()
        self.Sessions.append(s)
        tasks.append(self.load_page(s))
        # gpt cookie contexts
        for index, session in enumerate(self.Sessions):
            await self.__login(session)
            if index != len(self.Sessions) - 1:
                await asyncio.sleep(random.randint(1,15))
            if session.status == Status.Login.value:
                tasks.append(self.load_page(session))

        await asyncio.gather(*tasks)

        self.manage["browser_contexts"] = self.browser.contexts

        self.personality.read_data() # type: ignore
        self.manage["start"] = True
        self.logger.info("start!")
        self.thread = threading.Thread(target=lambda: self.tmp(loop), daemon=True)
        self.thread.start()

    async def load_page(self, session: Session):
        '''start page | 载入初始页面'''
        if self.begin_sleep_time and session.type != "script":
            await asyncio.sleep(random.randint(1, len(self.Sessions)*6))
        access_token = None
        page = session.page
        if session.type != "script" and page:
            session = await retry_keep_alive(session,url_check,self.chat_file,self.logger)
            try:
                await asyncio.sleep(3)
                await page.wait_for_load_state('load')
                json_data = await page.evaluate(
                    '() => JSON.parse(document.querySelector("body").innerText)')
                access_token = json_data['accessToken']
                if not session.email:
                    session.email = json_data["user"]["name"]
            except Exception as e:
                access_token = ""
                self.logger.debug(f"{session.email}'s have cf checkbox?")
            session.access_token = access_token

            if access_token:
                session.login_state = True
                self.logger.info(f"context {session.email} start!")
            else:
                session.login_state = False
                await page.screenshot(path=f"context {session.email} faild!.png")
                self.logger.info(f"context {session.email} faild!")

        elif page:

            if self.arkose_status:
                await page.evaluate(Payload.get_ajs())
            session.login_state = False
            self.logger.info(f"context {session.email} js start!")
            return

    def tmp(self, loop):
        # task = asyncio.create_task(self.__alive__())
        # await task
        asyncio.run_coroutine_threadsafe(self.__alive__(), loop)

    async def get_bda(self, data: str, key: str):
        session: Session = next(filter(lambda s: s.type == "script", self.Sessions))
        # page: Page = self.manage["browser_contexts"][-1].pages[0]
        page: Page = session.page # type: ignore
        js = f"ALFCCJS.encrypt('{data}','{key}')"
        res = await page.evaluate_handle(js)
        result: str = await res.json_value()
        return base64.b64encode(result.encode('utf8')).decode('utf8')



    async def send_msg(self, msg_data: MsgData, session: Session):
        """send message body function
        发送消息处理函数"""
        page = session.page
        token = session.access_token
        # context_num = self.Sessions.index(session)
        context_num = session.email

        # Get arkose | 获取arkose
        if self.arkose_status and page:
            async def route_arkose(route: Route, request: Request):
                userAgent = request.headers["user-agent"]
                data = Payload.get_data()
                key = Payload.get_key(userAgent)
                bda = await self.get_bda(data, key)

                msg_data.arkose_data = Payload.rdm_arkose(userAgent, bda) # type: ignore
                msg_data.arkose_header = Payload.header_arkose(msg_data.arkose_data) # type: ignore
                msg_data.arkose_header["Cookie"] = request.headers["cookie"]
                msg_data.arkose_header["User-Agent"] = request.headers["user-agent"]
                await route.continue_(method="POST", headers=msg_data.arkose_header, post_data=msg_data.arkose_data)

            await page.route("**/fc/gt2/public_key/3D86FBBA-9D22-402A-B512-3420086BA6CC", route_arkose)  # type: ignore

            async with page.expect_response(
                    "https://tcr9i.chat.openai.com/fc/gt2/public_key/3D86FBBA-9D22-402A-B512-3420086BA6CC",
                    timeout=400000) as arkose_info:
                try:

                    await page.wait_for_load_state('load')
                    self.logger.info("get arkose")
                    await page.goto(url_arkose, timeout=500000)
                    await page.wait_for_load_state('load')
                except Exception as e:
                    logging.warning(e)
                    await page.goto(url_arkose, timeout=300000)
                    await page.wait_for_load_state('load')
                resp_arkose = await arkose_info.value
                if resp_arkose.status == 200:
                    arkose_json = await resp_arkose.json()
                    msg_data.arkose = arkose_json["token"]
                else:
                    pass
        elif page:
            msg_data.arkose = None

        if not msg_data.conversation_id and not msg_data.p_msg_id:
            msg_data.post_data = Payload.new_payload(msg_data.msg_send, msg_data.arkose)
            # msg_data.post_data = Payload.system_new_payload(msg_data.msg_send)
        else:
            msg_data.post_data = Payload.old_payload(msg_data.msg_send, msg_data.conversation_id, msg_data.p_msg_id,
                                                     msg_data.arkose)

        header = Payload.headers(token, msg_data.post_data)

        async def route_handle(route: Route, request: Request):
            header["Cookie"] = request.headers["cookie"]
            header["User-Agent"] = request.headers["user-agent"]
            await route.continue_(method="POST", headers=header, post_data=msg_data.post_data)

        await page.route("**/backend-api/conversation", route_handle)  # type: ignore
        if page:
            msg_data = await self.resend(session,page,msg_data,context_num)
        else:
            msg_data.msg_recv = f"error! session {session.email} no page!"
        
        self.logger.info(f"recv:{msg_data.msg_recv}")    
        return msg_data
        
    async def resend(self,session: Session,page: Page,msg_data: MsgData,context_num: str,retry: int = 3):
        '''Multiple attempts to send message | 多次尝试发送消息'''
        if retry != 3:
            self.logger.info(f"resend {retry}")
        retry -= 1 
        if retry < 0:
            msg_data.msg_recv = "error: send msg retry max"
            return msg_data
        
        try:
            resp = await async_send_msg(page,msg_data,url_chatgpt,self.logger)
            msg_data = await recive_handle(session,resp,msg_data,self.logger)
        except Exception as e:
            self.logger.warning(e)
            msg_data = await self.resend(session,page,msg_data,context_num,retry)
            
        if msg_data.status:
            await self.save_chat(msg_data, context_num)
        return msg_data
        
    async def save_chat(self, msg_data: MsgData, context_num: str):
        """save chat file
        保存聊天文件"""
        path = self.chat_file / msg_data.conversation_id
        path.touch()
        if not path.stat().st_size:
            tmp = {
                "conversation_id": msg_data.conversation_id,
                "message": [{
                    "input": msg_data.msg_send,
                    "output": msg_data.msg_recv,
                    "type": msg_data.msg_type,
                    "next_msg_id": msg_data.next_msg_id
                }]
            }
            path.write_text(json.dumps(tmp))
        else:
            tmp = json.loads(path.read_text("utf8"))
            tmp["message"].append({
                "input": msg_data.msg_send,
                "output": msg_data.msg_recv,
                "type": msg_data.msg_type,
                "next_msg_id": msg_data.next_msg_id
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

    async def load_chat(self, msg_data: MsgData):
        """load chat file
        读取聊天文件"""
        path = self.chat_file.joinpath(msg_data.conversation_id)
        path.touch()
        if not path.stat().st_size:
            # self.logger.warning(f"不存在{msg_data.conversation_id}历史记录文件")
            return {
                "conversation_id": msg_data.conversation_id,
                "message": []
            }
        else:
            return json.loads(path.read_text("utf8"))

    def sleep(self, sc: float | int):
        self.browser_event_loop.run_until_complete(asyncio.sleep(sc))

    def ask(self, msg_data: MsgData) -> MsgData:
        '''Concurrency processing is not implemented and it is not recommended to use this|
        未作并发处理，不推荐使用这个
        '''
        while not self.manage["start"]:
            self.sleep(0.5)
        sessions = filter(
            lambda s: s.type != "script" and s.login_state is True,
            sorted(self.Sessions, key=lambda s: s.last_active)
        )
        session: Session = next(sessions, None) # type: ignore

        if not session:
            raise Exception("Not Found Page")
        msg_data = self.browser_event_loop.run_until_complete(self.send_msg(msg_data, session)) # type: ignore
        
        return msg_data

    async def continue_chat(self, msg_data: MsgData) -> MsgData:
        """
        Message processing entry, please use this
        聊天处理入口，一般用这个
        """
        while not self.manage["start"]:
            await asyncio.sleep(0.5)
        session:Session = Session(status=Status.Working.value)
        # We need to get c_id back to the session that created it
        if not msg_data.conversation_id:
            # new chat
            while not session or session.status == Status.Working.value:
                # Sorted by Last activity and filter only Login
                sessions = filter(
                    lambda s: s.type != "script" and s.login_state is True and s.status != Status.Working.value,
                    sorted(self.Sessions, key=lambda s: s.last_active)
                )
                session: Session = next(sessions, None) # type: ignore
                await asyncio.sleep(0.5)
            session.status = Status.Working.value
            self.logger.info(f"session {session.email} begin work")
        else:
            # if input c_id,find old session from c_id to continue | 根据输入内容定位c_id所在session
            map_tmp = json.loads(self.cc_map.read_text("utf8"))
            for context_name in map_tmp:
                # 遍历环境的cid
                if msg_data.conversation_id in map_tmp[context_name]:
                    # find c_id from all session如果cid在这个环境里
                    session = [session for session in self.Sessions if session.email == context_name][0]
                    if not session:
                        self.logger.info(f"not found conversation_id:{msg_data.conversation_id} in all sessions,pleases check it.")
                        msg_data.msg_recv = f"not found conversation_id:{msg_data.conversation_id} in all sessions,pleases check it."
                        return msg_data
                    if session.status == Status.Stop.value:
                        self.logger.info(f"ur conversation_id:{msg_data.conversation_id} 'session doesn't work.")
                        msg_data.msg_recv = f"ur conversation_id:{msg_data.conversation_id} 'session doesn't work."
                        return msg_data
                    while session.status == Status.Working.value:
                        # if this session is working,waitting | 如果它还在工作，那就等
                        await asyncio.sleep(0.5)
                    session.status = Status.Working.value
                    self.logger.info(f"session {session.email} begin work")
                    break

            if not msg_data.p_msg_id:
                # Not entered, try to restore from file | 未输入，尝试从文件里恢复
                try:
                    msg_history = await self.load_chat(msg_data)
                    msg_data.p_msg_id = msg_history["message"][-1]["next_msg_id"]
                except Exception as e:
                    # Recovery failed | 恢复失败
                    self.logger.info(f"ur p_msg_id:{msg_data.p_msg_id} 'chatfile not found.")
                    msg_data.msg_recv = f"ur p_msg_id:{msg_data.p_msg_id} 'chatfile not found."
                    return msg_data
        if not session:
            raise Exception("Not Found Page")
        msg_data = await self.send_msg(msg_data, session)
        session.status = Status.Login.value
        self.logger.info(f"session {session.email} finish work")
        # self.join = True
        # self.manage["status"][str(context_num)] = True
        
        return msg_data

    async def show_chat_history(self, msg_data: MsgData) -> list:
        """show chat history
        展示聊天记录"""
        msg_history = await self.load_chat(msg_data)
        msg = []
        for x in msg_history["message"]:
            msg.append(f"Q:{x['input']}\n\nA:{x['output']}\n\np_msg_id:{x['next_msg_id']}")
        return msg

    async def back_chat_from_input(self, msg_data: MsgData):
        """back chat from input
        You can enter the text that appeared last time, or the number of dialogue rounds starts from 1

        通过输入来回溯
        你可以输入最后一次出现过的文字，或者对话回合序号(从1开始)

        Note: backtracking will not reset the recorded chat files,
        please pay attention to whether the content displayed in the chat records exists when backtracking again

        注意：回溯不会重置记录的聊天文件，请注意再次回溯时聊天记录展示的内容是否存在

        """
        if not msg_data.conversation_id:
            msg_data.msg_recv = "no conversation_id"
            return msg_data
        msg_history = await self.load_chat(msg_data)
        tmp_p = ""
        tmp_i = ""
        try:
            index = int(msg_data.msg_send)
            tmp_p = msg_history["message"][index - 1]["next_msg_id"]
            tmp_i = msg_history["message"][index]["input"]
        except ValueError:
            for index, x in enumerate(msg_history["message"][::-1]):
                if msg_data.msg_send in x["input"] or msg_data.msg_send in x["output"]:
                    tmp_p = x["next_msg_id"]
                    tmp_i = msg_history["message"][::-1][index - 1]["input"]
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

    async def init_personality(self, msg_data: MsgData):
        """init_personality
        初始化人格"""
        msg_data.msg_send = self.personality.get_value_by_name(msg_data.msg_send) # type: ignore
        if msg_data.msg_send:
            msg_data.msg_type = "new_session"
            return await self.continue_chat(msg_data)
        else:
            msg_data.msg_recv = "not found"
            return msg_data

    async def back_init_personality(self, msg_data: MsgData):
        """
        back the init_personality time
        回到初始化人格之后"""
        msg_data.msg_send = "1"
        msg_data.msg_type = "back_loop"
        return await self.back_chat_from_input(msg_data)

    async def add_personality(self, personality: dict):
        """
        personality = {"name":"cat1","value":"you are a cat now1."}

        add personality,please input json just like this.
        添加人格 ,请传像这样的json数据
        """
        self.personality.add_dict_to_list(personality) # type: ignore
        self.personality.flush_data() # type: ignore

    async def show_personality_list(self):
        """show_personality_list
        展示人格列表"""
        return self.personality.show_name() # type: ignore

    async def del_personality(self, name: str):
        """del_personality by name
        删除人格根据名字"""
        self.personality.del_data_by_name(name) # type: ignore
        return self.personality.show_name() # type: ignore

    async def token_status(self):
        """get work status|查看session token状态和工作状态"""
        cid_all = json.loads(self.cc_map.read_text("utf8"))
        # cid_num may not match the number of sessions, because it only records sessions with successful sessions, which will be automatically resolved after a period of time.
        # cid_num 可能和session数量对不上，因为它只记录会话成功的session，这在允许一段时间后会自动解决
        return {
            "account": [session.email  for session in self.Sessions if session.type != "script"],
            "token": [True if session.access_token else False for session in self.Sessions if session.type != "script"],
            "work": [session.status for session in self.Sessions if session.type != "script"],
            "cid_num": [len(cid_all[x]) for x in cid_all]
        }
