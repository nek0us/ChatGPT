
import os
import sys
import json
import typing
import base64
import hashlib
import random
import asyncio
import threading
import secrets
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from aiohttp import ClientSession, web
from playwright_firefox.stealth import Stealth
from playwright_firefox.async_api import async_playwright, Route, Request, Page
from typing import AsyncIterator, Dict, Optional,Literal,List
from urllib.parse import urlparse
from .config import (
    Payload,
    Personality,
    MsgData,
    ProxySettings,
    logging,
    formator,
    Session,
    uuid,
    url_check,
    url_session,
    url_chatgpt,
    url_requirements,
    Status,
    all_models_values,
    model_list,
)
from .load import load_js
from .http_api import create_control_app
from .service import ChatService
from .verification import VerificationBroker
from .capabilities import discover_account_plan, infer_plan_from_model_categories, supports_paid_models
from .api import (
    async_send_msg,
    recive_handle,
    handle_event_stream,
    create_session,
    retry_keep_alive,
    Auth,
    get_session_token,
    update_session_token,
    try_wss,
    flush_page,
    upload_file,
    save_screen,
    get_json_url,
    get_all_msg,
    markdown2image,
    MockResponse,
    ChatStreamDecoder,
    ChatStreamEvent,
)

class chatgpt:
    def __init__(self,
                 sessions: list[dict] = [],
                 proxy: Optional[str] = None,
                 chat_file: Path = Path("data", "chat_history", "conversation"),
                 personality: Personality = None, # type: ignore
                 log_status: bool = True,
                 plugin: bool = False,
                 headless: bool = True,
                 begin_sleep_time: bool = True,
                 arkose_status: bool = False,
                 httpx_status: bool = False,
                 logger_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO",
                 stdout_flush: bool = False,
                 local_js: bool = False,
                 save_screen: bool = False,
                 ready_timeout: int = 180,
                 startup_timeout: int = 60,
                 control_host: str = "127.0.0.1",
                 control_port: int | None = None,
                 control_api_key: str | None = None,
               
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
        ### httpx_status
        use httpx | 使用httpx
        ### logger_level
        logger level.choose in ["DEBUG", "INFO", "WARNING", "ERROR"] | 日志等级，默认INFO
        ### stdout_flush
        command shell flush stdout|命令行即时输出
        """
        self.Sessions: List[Session] = []
        self.data = MsgData()
        self.proxy: typing.Optional[ProxySettings] = self.parse_proxy(proxy)
        self.httpx_proxy = proxy
        self.chat_file = chat_file
        self.personality =  Personality([{"name": "cat", "value": "you are a cat now."}], chat_file) if personality is None else personality
        self.log_status = log_status
        self.plugin = plugin
        self.headless = headless
        self.begin_sleep_time = begin_sleep_time
        self.arkose_status = arkose_status
        self.httpx_status = httpx_status
        self.stdout_flush = stdout_flush
        self.local_js = local_js
        self.js_used = 0
        self.save_screen = save_screen
        self.ready_timeout = ready_timeout
        self.startup_timeout = startup_timeout
        if control_port is not None and not 0 <= control_port <= 65535:
            raise ValueError("control_port must be between 0 and 65535")
        self.control_host = control_host
        self.control_port = control_port
        self.control_api_key = (
            control_api_key or secrets.token_urlsafe(24)
            if control_port is not None else None
        )
        self._control_runner: Optional[web.AppRunner] = None
        self._control_site: Optional[web.BaseSite] = None
        self.control_url = ""
        self._closing = False
        self._start_task: Optional[asyncio.Future] = None
        self._alive_task: Optional[asyncio.Future] = None
        self._watched_contexts = set()
        self._watched_pages = set()
        self._conversation_locks: Dict[str, asyncio.Lock] = {}
        self._conversation_locks_guard = asyncio.Lock()
        self._conversation_map_lock = asyncio.Lock()
        self._control_login_tasks: Dict[str, asyncio.Task] = {}
        self._usage_by_account: Dict[str, Dict[str, Dict[str, float]]] = {}
        self._activity: List[Dict[str, str]] = []
        self.verification_broker = VerificationBroker()
        self.set_chat_file()
        self.logger = logging.getLogger("logger")
        self.logger.setLevel(logger_level)
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
                if not s.type:
                    s.type = "session"
                s = get_session_token(s,self.chat_file,self.logger)
                if not s.device_id:
                    s.device_id = str(uuid.uuid4())
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
            self._start_task = asyncio.run_coroutine_threadsafe(self.__start__(self.browser_event_loop),self.browser_event_loop)
        elif self.log_status:
            from nonebot.log import logger # type: ignore
            self.logger = logger

        '''
        data : base data type | 内部数据类型
        '''
    def parse_proxy(self, proxy: str|None) -> ProxySettings|None:
        if not proxy:
            return None

        parsed_proxy = urlparse(proxy)
        proxy_settings = ProxySettings(server=f"{parsed_proxy.scheme}://{parsed_proxy.hostname}:{parsed_proxy.port}")
        

        if parsed_proxy.username and parsed_proxy.password:
            proxy_settings["username"] = parsed_proxy.username
            proxy_settings["password"] = parsed_proxy.password

        return proxy_settings
    
    # 检测Firefox是否已经安装 
    async def is_firefox_installed(self):
        '''chekc firefox install | 检测Firefox是否已经安装 '''
        playwright_manager = None
        browser = None
        try:
            playwright_manager = async_playwright()
            playwright = await self._startup_wait_for(
                "startup_firefox_check_playwright_start",
                playwright_manager.start(),
            )
            browser = await self._startup_wait_for(
                "startup_firefox_check_browser_launch",
                playwright.firefox.launch(
                    headless=self.headless,
                    slow_mo=50,
                    proxy=self.proxy,
                ),
            )
            await browser.close()
            browser = None
            return True
        except TimeoutError as e:
            self.logger.warning(f"check firefox timeout, skip install check:{e}")
            return True
        except Exception as e:
            self.logger.warning(f"check firefox:{e}")
            return False
        finally:
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass
            if playwright_manager:
                try:
                    await playwright_manager.__aexit__()
                except Exception:
                    pass

    # 安装Firefox
    def install_firefox(self):
        os.system('playwright_firefox install firefox')

    async def _startup_wait_for(self, name: str, awaitable, timeout: Optional[int] = None):
        timeout = timeout or self.startup_timeout
        try:
            return await asyncio.wait_for(awaitable, timeout=timeout)
        except TimeoutError as e:
            self.logger.warning(f"{name} timeout after {timeout}s")
            raise TimeoutError(f"{name} timeout after {timeout}s") from e

    async def _cleanup_browser_startup(self):
        browser = getattr(self, "browser", None)
        if browser:
            try:
                await browser.close()
            except Exception:
                pass
            self.browser = None
        playwright_manager = getattr(self, "playwright_manager", None)
        if playwright_manager:
            try:
                await playwright_manager.__aexit__()
            except Exception:
                pass
            self.playwright_manager = None
        self.playwright = None

    async def _launch_browser_with_retry(self, retries: int = 1):
        last_error = None
        for attempt in range(1, retries + 2):
            try:
                self.logger.debug(f"startup browser launch attempt {attempt}/{retries + 1}")
                self.playwright_manager = async_playwright()
                self.playwright = await self._startup_wait_for(
                    "startup_playwright_start",
                    self.playwright_manager.start(),
                )
                self.browser = await self._startup_wait_for(
                    "startup_browser_launch",
                    self.playwright.firefox.launch(
                        headless=self.headless,
                        slow_mo=50,
                        proxy=self.proxy,
                    ),
                )
                self.browser.on("disconnected", lambda *args: self.logger.warning("browser disconnected unexpectedly") if not self._closing else None)
                return
            except Exception as e:
                last_error = e
                self.logger.warning(f"startup browser launch attempt {attempt} failed: {e}")
                await self._cleanup_browser_startup()
                if attempt <= retries:
                    await asyncio.sleep(2)
        raise last_error if last_error else RuntimeError("startup browser launch failed")

    async def _new_context_with_timeout(self, label: str, storage_state: str | None = None):
        """Create a context with a longer recovery window for headful Firefox."""
        timeout = self.startup_timeout
        if not getattr(self, "headless", True):
            timeout = max(timeout, 120)
        context_task = asyncio.create_task(self.browser.new_context(storage_state=storage_state))
        try:
            return await asyncio.wait_for(asyncio.shield(context_task), timeout=min(15, timeout))
        except TimeoutError:
            if not context_task.done():
                self.logger.warning(
                    f"{label}_context_create is still pending; "
                    "if Firefox is blank, bring its window to the foreground"
                )
            try:
                return await asyncio.wait_for(context_task, timeout=timeout - min(15, timeout))
            except TimeoutError as error:
                self.logger.warning(f"{label}_context_create timeout after {timeout}s")
                raise TimeoutError(f"{label}_context_create timeout after {timeout}s") from error

    def _auth_state_path(self, session: Session) -> Path | None:
        if not session.persist_auth_state or not session.email:
            return None
        digest = hashlib.sha256(session.email.lower().encode("utf8")).hexdigest()
        return self.chat_file / "auth_states" / f"{digest}.json"

    async def _new_session_context(self, session: Session, label: str):
        state_path = self._auth_state_path(session)
        session.auth_state_loaded = False
        if state_path and state_path.is_file():
            try:
                context = await self._new_context_with_timeout(label, storage_state=str(state_path))
                session.auth_state_loaded = True
                self.logger.debug(f"{session.email} restored local auth state")
                return context
            except Exception as error:
                self.logger.warning(f"{session.email} could not restore local auth state: {error}")
        return await self._new_context_with_timeout(label)

    async def _save_auth_state(self, session: Session):
        state_path = self._auth_state_path(session)
        context = session.browser_contexts
        if not state_path or not context:
            return
        try:
            state_path.parent.mkdir(parents=True, exist_ok=True)
            await context.storage_state(path=str(state_path))
        except Exception as error:
            self.logger.warning(f"{session.email} could not save local auth state: {error}")

    async def _new_page_with_timeout(self, context, label: str):
        return await self._startup_wait_for(
            f"{label}_page_create",
            context.new_page(),
        )

    def _mark_session_runtime_closed(self, session: Session, source: str):
        if self._closing:
            return
        if session.status == Status.Stop.value:
            return
        session.login_state = False
        session.login_state_first = False
        session.status = Status.Update.value
        session.last_login_error = f"runtime {source} closed unexpectedly"
        session.runtime_last_closed_source = source
        session.runtime_last_closed_at = datetime.now()
        if source == "context":
            session.browser_contexts = None
            session.page = None
        elif "page" in source:
            session.page = None
        self._record_activity(session.email, "runtime_closed", f"{source} closed unexpectedly")
        self.logger.warning(f"{session.email} runtime {source} closed unexpectedly, set status Update")

    def _watch_page_events(self, session: Session, page: Page, label: str = "page"):
        page_id = id(page)
        if page_id in self._watched_pages:
            return
        self._watched_pages.add(page_id)
        page.on("close", lambda *args: self._mark_session_runtime_closed(session, label))
        page.on("crash", lambda *args: self._mark_session_runtime_closed(session, f"{label} crash"))
        page.on("pageerror", lambda error: self.logger.warning(f"{session.email} {label} pageerror: {error}"))

    def _watch_context_events(self, session: Session):
        context = session.browser_contexts
        if not context:
            return
        context_id = id(context)
        if context_id in self._watched_contexts:
            return
        self._watched_contexts.add(context_id)
        context.on("close", lambda *args: self._mark_session_runtime_closed(session, "context"))
        for page in context.pages:
            if page == session.page:
                self._watch_page_events(session, page)

    async def _ensure_session_runtime(self, session: Session) -> bool:
        if self._closing or session.status == Status.Stop.value:
            return False
        browser = getattr(self, "browser", None)
        if not browser or not browser.is_connected():
            self._mark_session_runtime_closed(session, "browser")
            return False

        recovered = False
        context = session.browser_contexts
        if not context:
            self.logger.warning(f"{session.email} runtime context missing, recreate it")
            session.browser_contexts = await self._new_session_context(session, f"runtime_{session.email}")
            recovered = True
            await Stealth().apply_stealth_async(session.browser_contexts)
            self._watch_context_events(session)
            if session.login_cookies and not session.auth_state_loaded:
                await session.browser_contexts.add_cookies(session.login_cookies)
            elif session.session_token and not session.auth_state_loaded:
                await session.browser_contexts.add_cookies([session.session_token]) # type: ignore
        else:
            self._watch_context_events(session)

        page = session.page
        if not page or page.is_closed():
            self.logger.warning(f"{session.email} runtime page missing or closed, recreate it")
            session.page = await self._new_page_with_timeout(session.browser_contexts, f"runtime_{session.email}") # type: ignore
            recovered = True
            self._watch_page_events(session, session.page)

        if recovered:
            session.runtime_recovery_count += 1
            session.runtime_last_recovered_at = datetime.now()

        return True
    
    def set_chat_file(self):
        """
        mkdir chat file path
        创建聊天文件目录
        """
        self.chat_file.mkdir(parents=True, exist_ok=True)
        session_file_dir = self.chat_file / "sessions"
        session_file_dir.mkdir(parents=True, exist_ok=True)
        if self.chat_file == Path("data", "chat_history", "conversation"):
            # 兼容性更新
            self.conversation_dir = self.chat_file
        else:
            # 规范性更新
            self.conversation_dir = self.chat_file / "conversation"
            self.conversation_dir.mkdir(parents=True, exist_ok=True)
        self.cc_map = self.chat_file.joinpath("map.json")
        self.cc_map.touch()
        if not self.cc_map.stat().st_size:
            self.cc_map.write_text("{}")

    def _conversation_path(self, conversation_id: str) -> Path:
        if not conversation_id or "/" in conversation_id or "\\" in conversation_id or conversation_id in (".", ".."):
            raise ValueError("conversation_id must be a non-empty file name")
        return self.conversation_dir / conversation_id

    async def _conversation_lock(self, conversation_id: str) -> asyncio.Lock:
        async with self._conversation_locks_guard:
            lock = self._conversation_locks.get(conversation_id)
            if lock is None:
                lock = asyncio.Lock()
                self._conversation_locks[conversation_id] = lock
            return lock

    @staticmethod
    def _write_json_atomic(path: Path, data: Dict[str, typing.Any]):
        temporary_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporary_path.write_text(json.dumps(data), encoding="utf8")
            os.replace(temporary_path, path)
        finally:
            if temporary_path.exists():
                temporary_path.unlink()

    async def __keep_alive__(self, session: Session):
        url = url_check
        if session.is_login_disabled():
            self.logger.debug(
                f"{session.email} keep-alive skipped, status:{session.status}, "
                f"failure:{session.login_failure_kind}"
            )
            return
        await asyncio.sleep(random.randint(1, 60 if len(self.Sessions) < 10 else 6 * len(self.Sessions)))
        if not await self._ensure_session_runtime(session):
            return
        session = await retry_keep_alive(session,url,self.chat_file,self.js,self.js_used,self.save_screen,self.logger)
        # check session_token need update
        if session.status == Status.Update.value and not session.is_login_disabled():
            # yes,we should update it
            self.logger.debug(f"{session.email} begin relogin")
            await Auth(session, self.logger, self.verification_broker)
            self.logger.debug(f"{session.email} relogin over")
        elif session.status == Status.Login.value:
            self.logger.debug(f"{session.email} loging in")
        

    async def __alive__(self):
        """keep cf cookie alive
        保持cf cookie存活
        """
        while not self._closing and self.browser.contexts:
            # browser_context:BrowserContext
            tasks = []
            for session in filter(lambda s: s.type != "script", self.Sessions):
                context_index = session.email
                try:
                    if session.status == Status.Stop.value or session.is_login_disabled():
                        continue
                    tasks.append(self.__keep_alive__(session))
                except Exception as e:
                    self.logger.error(f"add {context_index} flush cf task error! {e}")
            try:
                self.logger.debug(f"{session.email} will flush alive tasks")
                await asyncio.wait_for(asyncio.gather(*tasks),timeout=300)
            except TimeoutError:
                self.logger.warning(f"{session.email} flush alive tasks timeout 300")
            except Exception as e:
                a, b, exc_traceback = sys.exc_info()
                self.logger.warning(f"{session.email} flush alive tasks error:{e},line: {exc_traceback.tb_lineno}") # type: ignore
            self.logger.debug("flush over,wait next...")

            await asyncio.sleep(60 if len(self.Sessions) < 10 else 6 * len(self.Sessions))

        # for task in tasks: 
        #     task.cancel()
        # await asyncio.gather(*tasks,return_exceptions=True)    


    

    async def __login(self, session: Session):
        try:
            if self.begin_sleep_time:
                await asyncio.sleep(random.randint(1, len(self.Sessions)*6))
            if not session.browser_contexts:
                session.browser_contexts = await self._new_session_context(session, f"startup_{session.email}")
                await Stealth().apply_stealth_async(session.browser_contexts)
                self._watch_context_events(session)
            self.logger.debug(f"{session.email} begin login when it start")
            if session.auth_state_loaded and session.browser_contexts:
                session.page = await self._new_page_with_timeout(session.browser_contexts, f"startup_{session.email}")
                self._watch_page_events(session, session.page)
                session.status = Status.Login.value
            elif session.session_token and session.browser_contexts:
                token = session.session_token
                await session.browser_contexts.add_cookies([token]) # type: ignore
                session.page = await self._new_page_with_timeout(session.browser_contexts, f"startup_{session.email}")
                self._watch_page_events(session, session.page)
                session.status = Status.Login.value

            elif session.email and session.password and session.browser_contexts:
                session.page = await self._new_page_with_timeout(session.browser_contexts, f"startup_{session.email}")
                self._watch_page_events(session, session.page)
                await Auth(session, self.logger, self.verification_broker)
            else:
                session.mark_login_failure(
                    details="No session_token or email/password was provided",
                    stop=True,
                )
            if session.login_cookies and session.browser_contexts and not session.auth_state_loaded:
                await session.browser_contexts.add_cookies(session.login_cookies)
        except asyncio.CancelledError:
            session.mark_login_failure(
                details="login task cancelled by startup timeout",
                stop=True,
            )
            raise
        except Exception as e:
            session.mark_login_failure(
                details=f"login task failed: {e}",
                stop=True,
            )
            self.logger.warning(f"{session.email} login task failed:{e}")
        

    async def __start__(self, loop):
        """
        init | 初始化
        """
        if not await self.is_firefox_installed():
            self.logger.info("Firefox browser is not installed, installing...")
            self.install_firefox()
            self.logger.info("Firefox browser has been successfully installed.")
        else:
            self.logger.debug("Firefox browser is already installed.")
        self.js = await load_js(self.httpx_proxy,self.local_js)    
        await self._launch_browser_with_retry(retries=1)
        await self._start_control_server()
        
        # arkose context
        auth_tasks = []
        # s = Session(type="script")
        # s.browser_contexts = await self.browser.new_context(service_workers="block")
        # s.page = await s.browser_contexts.new_page()
        # await stealth_async(s.page)
        # self.Sessions.append(s)
        # load_tasks.append(self.load_page(s))
        # gpt cookie contexts
        for session in self.Sessions:
            auth_tasks.append(self.__login(session))
        # auth login
        try:
            self.logger.debug(f"{session.email} will auth_task")
            auth_timeout = max(300, self.verification_broker.default_timeout_seconds + 60)
            await asyncio.wait_for(asyncio.gather(*auth_tasks, return_exceptions=True), timeout=auth_timeout)
            # load page
            load_tasks = [
                self.load_page(session)
                for session in self.Sessions
                if session.status != Status.Stop.value
            ]
            self.logger.debug(f"{session.email} will load_task")
            if load_tasks:
                await asyncio.wait_for(asyncio.gather(*load_tasks, return_exceptions=True),timeout=240)
        except TimeoutError:
            self.logger.warning(f"{session.email} auth and load_page timeout")
            for s in self.Sessions:
                if s.status in (Status.Login.value, Status.Update.value):
                    s.mark_login_failure(
                        details="startup auth/load_page timeout",
                        stop=True,
                    )
        except Exception as e:
            a, b, exc_traceback = sys.exc_info()
            self.logger.warning(f"{session.email} auth and load_page error:{e},line: {exc_traceback.tb_lineno}") # type: ignore

        self.manage["browser_contexts"] = self.browser.contexts

        self.personality.read_data(self.chat_file) # type: ignore
        self.manage["start"] = True
        self.logger.debug("start!")
        self.thread = threading.Thread(target=lambda: self.tmp(loop), daemon=True)
        self.thread.start()

    async def _start_control_server(self) -> None:
        if self.control_port is None or self._control_runner:
            return
        runner = web.AppRunner(create_control_app(
            ChatService(self),
            self.verification_broker,
            api_key=self.control_api_key,
        ))
        try:
            await runner.setup()
            site = web.TCPSite(runner, self.control_host, self.control_port)
            await site.start()
            self._control_runner = runner
            self._control_site = site
            sockets = getattr(getattr(site, "_server", None), "sockets", [])
            port = sockets[0].getsockname()[1] if sockets else self.control_port
            self.control_url = f"http://{self.control_host}:{port}"
            self.manage["control_url"] = self.control_url
            self.logger.info(f"ChatGPTWeb control dashboard: {self.control_url}")
            self.logger.info(f"ChatGPTWeb control API key: {self.control_api_key}")
        except Exception as error:
            await runner.cleanup()
            self.logger.warning(f"control dashboard did not start: {error}")

    async def _close_control_server(self) -> None:
        runner = self._control_runner
        self._control_runner = None
        self._control_site = None
        self.control_url = ""
        self.manage["control_url"] = ""
        if runner:
            await runner.cleanup()

    async def _run_controlled_login(self, session: Session) -> None:
        try:
            await self.load_page(session, immediate=True)
        except asyncio.CancelledError:
            self._record_activity(session.email, "login_retry_cancelled", "controlled login was cancelled")
            self.logger.info(f"account {session.email} controlled login cancelled")
            raise
        except Exception as error:
            self._record_activity(session.email, "login_retry_failed", "controlled login failed; see account diagnostics")
            self.logger.warning(f"account {session.email} controlled login failed: {error}")
        else:
            self._record_activity(session.email, "login_retry_finished", f"status: {session.status}")
        finally:
            tasks = getattr(self, "_control_login_tasks", {})
            if tasks.get(session.email) is asyncio.current_task():
                tasks.pop(session.email, None)

    def _record_usage(self, session: Session, msg_data: MsgData) -> None:
        """Keep in-process, upstream-reported usage separate from quota state."""
        if not msg_data.status or not session.email:
            return
        model = msg_data.model_used or msg_data.model_requested or msg_data.gpt_model or "unknown"
        by_account = getattr(self, "_usage_by_account", None)
        if by_account is None:
            by_account = self._usage_by_account = {}
        by_model = by_account.setdefault(session.email, {})
        usage = by_model.setdefault(model, {"requests": 0})
        usage["requests"] += 1
        for key, value in msg_data.usage.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                usage[key] = usage.get(key, 0) + value
        self._record_activity(session.email, "chat_completed", f"model: {model}")

    def _record_activity(self, account: str, event: str, message: str) -> None:
        """Record bounded, credential-free diagnostics for the local console."""
        activity = getattr(self, "_activity", None)
        if activity is None:
            activity = self._activity = []
        activity.append({
            "at": datetime.now().isoformat(timespec="seconds"),
            "account": account,
            "event": event,
            "message": message[:240],
        })
        if len(activity) > 200:
            del activity[:-200]

    async def get_activity(self, limit: int = 50) -> Dict[str, object]:
        """Return recent local control/runtime activity without secrets or prompts."""
        limit = max(1, min(limit, 200))
        activity = getattr(self, "_activity", [])
        return {"events": list(reversed(activity[-limit:]))}

    def _usage_snapshot(self, account: str) -> Dict[str, object]:
        models = getattr(self, "_usage_by_account", {}).get(account, {})
        return {
            "source": "observed_upstream" if models else "unavailable",
            "requests": sum(int(item.get("requests", 0)) for item in models.values()),
            "models": {model: values.copy() for model, values in models.items()},
            "quota": None,
        }

    async def control_account(self, account: str, action: str) -> Dict[str, object]:
        """Apply an explicit local operator action to one account."""
        if action not in {"disable", "enable", "retry_login", "refresh_capabilities"}:
            raise ValueError("action must be 'disable', 'enable', 'retry_login', or 'refresh_capabilities'")
        session = next(
            (item for item in self.Sessions if item.type != "script" and item.email == account),
            None,
        )
        if not session:
            raise KeyError("account was not found")

        tasks = getattr(self, "_control_login_tasks", None)
        if tasks is None:
            tasks = self._control_login_tasks = {}

        if action == "disable":
            session.manual_disabled = True
            task = tasks.pop(session.email, None)
            if task and not task.done():
                task.cancel()
            await self.verification_broker.cancel_account(session.email)
        elif action == "enable":
            session.manual_disabled = False
        elif action == "retry_login":
            if not session.email or not session.password:
                raise ValueError("account has no configured login credentials")
            if session.email in tasks and not tasks[session.email].done():
                raise ValueError("account login is already in progress")
            session.manual_disabled = False
            session.login_state = False
            session.login_state_first = False
            session.status = Status.Update.value
            session.login_fail_count = 0
            session.login_failure_kind = ""
            session.last_login_error = "manual login retry requested"
            session.disabled_until = None
            tasks[session.email] = asyncio.create_task(self._run_controlled_login(session))
        else:
            await self._refresh_account_plan(session)
        update_session_token(session, self.chat_file, self.logger)
        self._record_activity(session.email, "account_control", f"action: {action}")
        self.logger.info(f"account {session.email} control action: {action}")

        status = await self.token_status()
        return next(item for item in status["accounts"] if item["email"] == account)

    async def load_page(self, session: Session, immediate: bool = False):
        '''start page | 载入初始页面'''
        if self.begin_sleep_time and not immediate and session.type != "script":
            await asyncio.sleep(random.randint(1, len(self.Sessions)*6))
        page = session.page
        if page:
            session.user_agent = await page.evaluate('() => navigator.userAgent')
            session = await retry_keep_alive(session,url_check,self.chat_file,self.js,self.js_used,self.save_screen,self.logger)
            try:
                await page.goto("https://chatgpt.com/",timeout=20000,wait_until='load')
            except Exception as e:
                self.logger.warning(e)
                await save_screen(save_screen_status=self.save_screen,path=f"context_{session.email}_goto_chatgpt.com_faild!",page=page)
            # await page.wait_for_load_state()
            # current_url = page.url
            # await page.wait_for_url(current_url)
            # current_url = page.url 
            
            relogin_try = 0
            while session.status == Status.Update.value:
                if session.is_login_disabled():
                    self.logger.warning(
                        f"context {session.email} stop relogin, failure:{session.login_failure_kind}, "
                        f"fail_count:{session.login_fail_count}"
                    )
                    break
                if relogin_try >= session.max_login_failures:
                    session.mark_login_failure(
                        details="load_page relogin retry max",
                        stop=True,
                    )
                    self.logger.warning(f"context {session.email} relogin retry max, set Stop")
                    break
                relogin_try += 1
                self.logger.debug(f"context {session.email} begin relogin")
                await Auth(session, self.logger, self.verification_broker)
                self.logger.debug(f"context {session.email} relogin over")
            
            if session.status in (Status.Stop.value, Status.Update.value):
                session.login_state = False
                self.logger.warning(
                    f"context {session.email} not ready, status:{session.status}, failure:{session.login_failure_kind}, "
                    f"error:{session.last_login_error[:200]}"
                )
                return

            if not await self._initialize_page_bridge(session, page):
                return

            await self._refresh_account_plan(session)
            
            if session.access_token:
                if session.status != Status.Update.value:
                    session.login_state = True
                    session.status = Status.Ready.value
                    self.logger.debug(f"context {session.email} start!")
                    await self._save_auth_state(session)
                else:
                    self.logger.debug(f"context {session.email} need relogin!")
            else:
                session.login_state = False
                session.login_state_first = False
                # await page.screenshot(path=f"context {session.email} faild!.png")
                await save_screen(save_screen_status=self.save_screen,path=f"context_{session.email}_faild!",page=page)
                self.logger.warning(f"context {session.email} faild!")
            if self.httpx_status:
                self.logger.debug("load page over,http_status true,close page")
                await page.close()
                
            return

    async def _initialize_page_bridge(self, session: Session, page: Page) -> bool:
        """Load browser bridge code with a bounded retry during runtime startup."""
        last_error: Optional[Exception] = None
        for attempt in range(1, 3):
            try:
                self.js_used = await asyncio.wait_for(
                    flush_page(page, self.js, self.js_used),
                    timeout=self.startup_timeout,
                )
                return True
            except Exception as error:
                last_error = error
                self.logger.warning(
                    f"context {session.email} bridge initialization attempt {attempt}/2 failed: {error}"
                )
                if attempt == 1:
                    try:
                        await page.goto("https://chatgpt.com/", timeout=20000, wait_until="load")
                    except Exception:
                        pass

        session.mark_login_failure(
            kind="transient",
            details=f"browser bridge initialization failed: {last_error}",
            cooldown_seconds=60,
        )
        self.logger.warning(
            f"context {session.email} bridge initialization failed twice; status:{session.status}"
        )
        return False
        
    def tmp(self, loop):
        # task = asyncio.create_task(self.__alive__())
        # await task
        self._alive_task = asyncio.run_coroutine_threadsafe(self.__alive__(), loop)

    async def close(self):
        """Close background tasks and browser resources."""
        self._closing = True
        await self._close_control_server()

        control_login_tasks = list(getattr(self, "_control_login_tasks", {}).values())
        for task in control_login_tasks:
            if not task.done():
                task.cancel()
        if control_login_tasks:
            await asyncio.gather(*control_login_tasks, return_exceptions=True)
        getattr(self, "_control_login_tasks", {}).clear()

        for task in (self._alive_task,):
            if task and not task.done():
                task.cancel()
                try:
                    await asyncio.wrap_future(task)
                except (asyncio.CancelledError, Exception):
                    pass

        for session in self.Sessions:
            for resource_name in ("wss", "wss_session"):
                resource = getattr(session, resource_name, None)
                if resource:
                    try:
                        await resource.close()
                    except Exception:
                        pass
                    setattr(session, resource_name, None)
            context = getattr(session, "browser_contexts", None)
            if context:
                try:
                    await context.close()
                except Exception:
                    pass
                session.browser_contexts = None
                session.page = None

        browser = getattr(self, "browser", None)
        if browser:
            try:
                await browser.close()
            except Exception:
                pass
            self.browser = None

        playwright_manager = getattr(self, "playwright_manager", None)
        if playwright_manager:
            try:
                await playwright_manager.__aexit__()
            except Exception:
                pass
            self.playwright_manager = None

        self.manage["browser_contexts"] = []

    async def get_bda(self, data: str, key: str):
        session: Session = next(filter(lambda s: s.type == "script", self.Sessions))
        # page: Page = self.manage["browser_contexts"][-1].pages[0]
        page: Page = session.page # type: ignore
        js = f"ALFCCJS.encrypt('{data}','{key}')"
        res = await page.evaluate_handle(js)
        result: str = await res.json_value()
        return base64.b64encode(result.encode('utf8')).decode('utf8')



    def _is_retryable_send_error(self, error: Exception, session: Session) -> bool:
        text = str(error).lower()
        if session.status in (Status.Update.value, Status.Stop.value):
            return False
        retryable_marks = (
            "timeout",
            "network",
            "net::",
            "closed",
            "websocket",
            "wss",
            "download is starting",
        )
        return any(mark in text for mark in retryable_marks)

    def _build_conversation_payload(self, msg_data: MsgData) -> str:
        msg_data.model_requested = msg_data.gpt_model
        if not msg_data.conversation_id:
            return Payload.new_payload(
                msg_data.msg_send,
                gpt_model=msg_data.gpt_model,
                files=msg_data.upload_file,
                search=msg_data.web_search,
            )
        return Payload.old_payload(
            msg_data.msg_send,
            msg_data.conversation_id,
            msg_data.p_msg_id,
            gpt_model=msg_data.gpt_model,
            files=msg_data.upload_file,
            search=msg_data.web_search,
        )

    def _local_model_catalog(self) -> Dict[str, typing.Any]:
        return {
            "free": model_list(False),
            "plus": model_list(True),
            "source": "local_static",
        }

    async def _refresh_account_plan(self, session: Session) -> None:
        """Read the previously verified billing capability endpoint in-page."""
        page = session.page
        if not page or page.is_closed() or not session.access_token:
            return
        try:
            result = await asyncio.wait_for(
                page.evaluate(
                """
                async (options) => {
                    const headers = { "accept": "application/json, text/plain, */*" };
                    if (options.accessToken) headers.authorization = `Bearer ${options.accessToken}`;
                    if (options.deviceId) headers["oai-device-id"] = options.deviceId;
                    const response = await fetch("/backend-api/pageConfigs/billing", {
                        method: "GET", credentials: "include", headers,
                    });
                    const contentType = response.headers.get("content-type") || "";
                    const modelSubscriptionLevels = [];
                    for (const key of Object.keys(localStorage)) {
                        if (!key.endsWith("/models") && !key.includes("/models")) continue;
                        try {
                            const cached = JSON.parse(localStorage.getItem(key));
                            const value = cached && cached.value && typeof cached.value === "object" ? cached.value : cached;
                            for (const category of Array.isArray(value && value.categories) ? value.categories : []) {
                                if (category && category.subscriptionLevel) modelSubscriptionLevels.push(category.subscriptionLevel);
                            }
                        } catch (_) {}
                    }
                    if (!response.ok || !contentType.includes("json")) {
                        return { status: response.status, payload: null, modelSubscriptionLevels };
                    }
                    return { status: response.status, payload: await response.json(), modelSubscriptionLevels };
                }
                """,
                    {"accessToken": session.access_token, "deviceId": session.device_id},
                ),
                timeout=15,
            )
            if not isinstance(result, dict):
                return
            payload = result.get("payload")
            plan = (
                discover_account_plan(payload, "fetch:/backend-api/pageConfigs/billing")
                if isinstance(payload, (dict, list)) else discover_account_plan(None, "unavailable")
            )
            if plan.value == "unknown":
                plan = infer_plan_from_model_categories(
                    result.get("modelSubscriptionLevels"),
                    "inferred:localStorage:model-categories",
                )
            session.account_plan = plan.value
            session.account_plan_source = plan.source
            session.account_plan_observed_at = datetime.now()
        except Exception as error:
            self.logger.debug(f"{session.email} account plan refresh skipped: {error}")

    async def get_model_catalog(self, fetch_remote: bool = True) -> Dict[str, typing.Any]:
        """Return model catalogs discovered from authenticated browser sessions."""
        startup_wait_seconds = 0
        while not self.manage["start"]:
            await asyncio.sleep(0.5)
            startup_wait_seconds += 0.5
            if startup_wait_seconds >= self.ready_timeout:
                return {
                    "source": "startup_timeout",
                    "local": self._local_model_catalog(),
                    "accounts": [],
                }

        accounts = []
        for session in self.Sessions:
            if session.type == "script":
                continue
            info: Dict[str, typing.Any] = {
                "email": session.email,
                "mode": session.mode,
                "status": session.status,
                "login_state": session.login_state,
                "gptplus": session.gptplus,
                "account_plan": getattr(session, "account_plan", "unknown"),
                "account_plan_source": getattr(session, "account_plan_source", "unavailable"),
                "remote": None,
                "cached": [],
                "errors": [],
            }
            if not await self._ensure_session_runtime(session):
                info["errors"].append("session runtime is not available")
                accounts.append(info)
                continue
            page = session.page
            if not page or page.is_closed():
                info["errors"].append("page is not ready")
                accounts.append(info)
                continue
            try:
                discovered = await page.evaluate(
                    """
                    async (options) => {
                        const summarizeModelCatalog = (data, source) => {
                            const value = data && data.value && typeof data.value === "object" ? data.value : data;
                            const categories = Array.isArray(value && value.categories) ? value.categories : [];
                            const models = Array.isArray(value && value.models) ? value.models : [];
                            if (!categories.length && !models.length) {
                                return null;
                            }
                            return {
                                source,
                                title: value && value.title ? value.title : "",
                                categories: categories.map((category) => ({
                                    categoryId: category.categoryId || category.id || "",
                                    label: category.label || "",
                                    shortLabel: category.shortLabel || "",
                                    defaultModel: category.defaultModel || "",
                                    subscriptionLevel: category.subscriptionLevel || "",
                                })),
                                models: models.map((model) => ({
                                    slug: model.slug || "",
                                    title: model.title || "",
                                    description: model.description || "",
                                    maxTokens: model.max_tokens || model.maxTokens || null,
                                    tags: Array.isArray(model.tags) ? model.tags : [],
                                })),
                            };
                        };
                        const parseJsonOrNull = (text) => {
                            try {
                                return JSON.parse(text);
                            } catch (_) {
                                return null;
                            }
                        };
                        const cached = Object.keys(localStorage)
                            .filter((key) => key.endsWith("/models") || key.includes("/models"))
                            .map((key) => {
                                const parsed = parseJsonOrNull(localStorage.getItem(key));
                                return parsed ? summarizeModelCatalog(parsed, `localStorage:${key}`) : null;
                            })
                            .filter(Boolean);

                        let remote = null;
                        const errors = [];
                        if (options.fetchRemote) {
                            try {
                                const headers = { "accept": "application/json, text/plain, */*" };
                                if (options.accessToken) {
                                    headers["authorization"] = `Bearer ${options.accessToken}`;
                                }
                                if (options.deviceId) {
                                    headers["oai-device-id"] = options.deviceId;
                                }
                                const response = await fetch(options.modelsUrl, {
                                    method: "GET",
                                    credentials: "include",
                                    headers,
                                });
                                const text = await response.text();
                                if (!response.ok) {
                                    errors.push(`models ${response.status}: ${text.slice(0, 300)}`);
                                } else {
                                    remote = summarizeModelCatalog(parseJsonOrNull(text), `fetch:${options.modelsUrl}`);
                                    if (!remote) {
                                        errors.push("models response did not contain catalog fields");
                                    }
                                }
                            } catch (error) {
                                errors.push(error && error.message ? error.message : String(error));
                            }
                        }
                        return { remote, cached, errors };
                    }
                    """,
                    {
                        "fetchRemote": fetch_remote,
                        "modelsUrl": "/backend-api/models?iim=false&is_gizmo=false&supports_model_picker_upgrade_presets=true",
                        "accessToken": session.access_token,
                        "deviceId": session.device_id,
                    },
                )
                if isinstance(discovered, dict):
                    info["remote"] = discovered.get("remote")
                    info["cached"] = discovered.get("cached") or []
                    info["errors"].extend(discovered.get("errors") or [])
            except Exception as e:
                info["errors"].append(str(e))
            accounts.append(info)

        return {
            "source": "browser_authenticated",
            "local": self._local_model_catalog(),
            "accounts": accounts,
        }

    async def probe_browser_runtime(self, fetch_capabilities: bool = False) -> List[Dict[str, typing.Any]]:
        """Inspect browser-side capabilities required by the fetch bridge."""
        probes = []
        for session in self.Sessions:
            if session.type == "script":
                continue
            info: Dict[str, typing.Any] = {
                "email": session.email,
                "status": session.status,
                "login_state": session.login_state,
                "page_ready": bool(session.page and not session.page.is_closed()),
                "context_ready": bool(session.browser_contexts),
            }
            if not session.page or session.page.is_closed():
                info["error"] = "page is not ready"
                probes.append(info)
                continue
            try:
                info.update(
                    await session.page.evaluate(
                        """
                        async (options) => {
                            const typeOf = (name) => {
                                let value = window;
                                for (const part of name.split(".")) {
                                    value = value && value[part];
                                }
                                return {
                                    name,
                                    type: typeof value,
                                    keys: value && typeof value === "object" ? Object.keys(value).slice(0, 20) : [],
                                    hasGetEnforcementToken: !!(value && typeof value.getEnforcementToken === "function"),
                                    hasStartEnforcement: !!(value && typeof value.startEnforcement === "function"),
                                };
                            };
                            const resourceEntries = performance.getEntriesByType("resource");
                            const resources = resourceEntries.map((entry) => entry.name);
                            const toPath = (url) => {
                                try {
                                    const parsed = new URL(url, location.origin);
                                    return parsed.pathname + parsed.search;
                                } catch (_) {
                                    return url;
                                }
                            };
                            const keywordPattern = /model|quota|usage|limit|rate|entitlement|subscription|plan|account|billing/i;
                            const richMediaPattern = /image|media|file|download|upload|task|generation/i;
                            const safePreview = (value) => {
                                try {
                                    const text = String(value);
                                    return text.length > 300 ? text.slice(0, 300) : text;
                                } catch (_) {
                                    return "";
                                }
                            };
                            const storageMatches = (storage) => Object.keys(storage)
                                .filter((key) => keywordPattern.test(key))
                                .slice(0, 30)
                                .map((key) => ({ key, valuePreview: safePreview(storage.getItem(key)) }));
                            const richMediaStorageKeys = (storage) => Object.keys(storage)
                                .filter((key) => richMediaPattern.test(key))
                                .slice(0, 30);
                            const safeResourcePath = (url) => {
                                try {
                                    return new URL(url, location.origin).pathname;
                                } catch (_) {
                                    return url.split("?")[0];
                                }
                            };
                            const richMediaResources = resourceEntries
                                .filter((entry) => richMediaPattern.test(entry.name))
                                .slice(-50)
                                .map((entry) => ({
                                    path: safeResourcePath(entry.name),
                                    initiatorType: entry.initiatorType || "",
                                    durationMs: Math.round(entry.duration || 0),
                                }));
                            const richMediaFetchCandidates = [...new Set(richMediaResources
                                .map((resource) => resource.path)
                                .filter((path) => path === "/backend-api/tasks"))];
                            const summarizeModelCatalog = (data, source) => {
                                const value = data && data.value && typeof data.value === "object" ? data.value : data;
                                const categories = Array.isArray(value && value.categories) ? value.categories : [];
                                const models = Array.isArray(value && value.models) ? value.models : [];
                                if (!categories.length && !models.length) {
                                    return null;
                                }
                                return {
                                    source,
                                    title: value && value.title ? value.title : "",
                                    categories: categories.slice(0, 40).map((category) => ({
                                        categoryId: category.categoryId || category.id || "",
                                        label: category.label || "",
                                        shortLabel: category.shortLabel || "",
                                        defaultModel: category.defaultModel || "",
                                        subscriptionLevel: category.subscriptionLevel || "",
                                    })),
                                    models: models.slice(0, 80).map((model) => ({
                                        slug: model.slug || "",
                                        title: model.title || "",
                                        description: model.description || "",
                                        maxTokens: model.max_tokens || model.maxTokens || null,
                                        tags: Array.isArray(model.tags) ? model.tags.slice(0, 10) : [],
                                    })),
                                };
                            };
                            const parseJsonOrNull = (text) => {
                                try {
                                    return JSON.parse(text);
                                } catch (_) {
                                    return null;
                                }
                            };
                            const storageModelCatalogs = Object.keys(localStorage)
                                .filter((key) => key.endsWith("/models") || key.includes("/models"))
                                .slice(0, 5)
                                .map((key) => {
                                    const parsed = parseJsonOrNull(localStorage.getItem(key));
                                    const catalog = parsed ? summarizeModelCatalog(parsed, `localStorage:${key}`) : null;
                                    return catalog;
                                })
                                .filter(Boolean);
                            const knownCapabilityCandidates = [
                                "/backend-api/models?iim=false&is_gizmo=false&supports_model_picker_upgrade_presets=true",
                                "/backend-api/pageConfigs/billing",
                            ];
                            const capabilityResources = [...new Set(resources
                                .filter((name) => keywordPattern.test(name))
                                .map(toPath)
                                .concat(knownCapabilityCandidates))]
                                .slice(-40);
                            const conversationEndpointCandidates = [...new Set([
                                "/backend-api/f/conversation",
                                "/backend-api/conversation",
                                "/api/backend-api/f/conversation",
                                "/api/backend-api/conversation",
                                ...resources
                                    .filter((name) => name.includes("conversation"))
                                    .map(toPath)
                                    .filter((path) => path.endsWith("/conversation") || path.endsWith("/f/conversation")),
                            ])];
                            const capabilityFetchResults = [];
                            if (options.fetchCapabilities) {
                                const getCandidates = capabilityResources
                                    .filter((path) => path.startsWith("/"))
                                    .filter((path) => !path.includes("/conversation/"))
                                    .slice(-10)
                                    .concat(richMediaFetchCandidates);
                                for (const path of getCandidates) {
                                    try {
                                        const headers = { "accept": "application/json, text/plain, */*" };
                                        if (options.accessToken) {
                                            headers["authorization"] = `Bearer ${options.accessToken}`;
                                        }
                                        if (options.deviceId) {
                                            headers["oai-device-id"] = options.deviceId;
                                        }
                                        const response = await fetch(path, {
                                            method: "GET",
                                            credentials: "include",
                                            headers,
                                        });
                                        const contentType = response.headers.get("content-type") || "";
                                        let preview = "";
                                        let modelCatalog = null;
                                        if (contentType.includes("json") || contentType.includes("text")) {
                                            const text = await response.text();
                                            preview = text.slice(0, 500);
                                            if (path.includes("/models")) {
                                                const parsed = parseJsonOrNull(text);
                                                modelCatalog = parsed ? summarizeModelCatalog(parsed, `fetch:${path}`) : null;
                                            }
                                        }
                                        capabilityFetchResults.push({
                                            url: path,
                                            status: response.status,
                                            contentType,
                                            preview,
                                            modelCatalog,
                                        });
                                    } catch (error) {
                                        capabilityFetchResults.push({
                                            url: path,
                                            error: error && error.message ? error.message : String(error),
                                        });
                                    }
                                }
                            }
                            return {
                                url: location.href,
                                userAgent: navigator.userAgent,
                                providers: [
                                    typeOf("_chatp"),
                                    typeOf("_chatp_old"),
                                    typeOf("_proof"),
                                    typeOf("_proof.Z"),
                                    typeOf("_turnstile"),
                                    typeOf("_turnstile.Z"),
                                    typeOf("_ark"),
                                    typeOf("_ark.ZP"),
                                ],
                                requirementsResources: resources
                                    .filter((name) => name.includes("/backend-api/sentinel/chat-requirements"))
                                    .slice(-10),
                                conversationResources: resources
                                    .filter((name) => name.includes("/backend-api/") && name.includes("conversation"))
                                    .slice(-10),
                                conversationEndpointCandidates,
                                capabilityResources,
                                capabilityFetchResults,
                                richMediaResources,
                                richMediaFetchCandidates,
                                richMediaStorage: {
                                    localStorageKeys: richMediaStorageKeys(localStorage),
                                    sessionStorageKeys: richMediaStorageKeys(sessionStorage),
                                },
                                modelCatalogObserved: storageModelCatalogs,
                                modelCatalogLocal: options.localModelCatalog,
                                localStorageCapabilityKeys: storageMatches(localStorage),
                                sessionStorageCapabilityKeys: storageMatches(sessionStorage),
                                localStorageKeys: Object.keys(localStorage).slice(0, 30),
                                sessionStorageKeys: Object.keys(sessionStorage).slice(0, 30),
                            };
                        }
                        """,
                        {
                            "fetchCapabilities": fetch_capabilities,
                            "localModelCatalog": self._local_model_catalog(),
                            "accessToken": session.access_token,
                            "deviceId": session.device_id,
                        },
                    )
                )
            except Exception as e:
                info["error"] = str(e)
            probes.append(info)
        return probes

    def _browser_fetch_bridge_script(self) -> str:
        return """
        async (options) => {
            const errors = [];
            const streamControllers = window.__chatgptwebStreamControllers ||
                (window.__chatgptwebStreamControllers = Object.create(null));
            const streamController = options.stream && options.streamId ? new AbortController() : null;
            if (streamController) {
                streamControllers[options.streamId] = streamController;
            }
            const emit = async (payload) => {
                if (options.stream && options.emitBinding) {
                    await window[options.emitBinding](payload);
                }
            };

            const unique = (items) => [...new Set(items.filter(Boolean))];
            const toPath = (url) => {
                try {
                    const parsed = new URL(url, location.origin);
                    return parsed.pathname + parsed.search;
                } catch (_) {
                    return url;
                }
            };
            const readText = async (response) => {
                if (!response.body) {
                    return await response.text();
                }
                const reader = response.body.getReader();
                const decoder = new TextDecoder();
                let text = "";
                while (true) {
                    const chunk = await reader.read();
                    if (chunk.done) {
                        break;
                    }
                    text += decoder.decode(chunk.value, { stream: true });
                }
                text += decoder.decode();
                return text;
            };
            const streamResponse = async (response) => {
                if (!response.body) {
                    await emit({ type: "chunk", text: await response.text() });
                    await emit({ type: "done" });
                    return;
                }
                const reader = response.body.getReader();
                const decoder = new TextDecoder();
                while (true) {
                    const item = await reader.read();
                    if (item.done) {
                        break;
                    }
                    const text = decoder.decode(item.value, { stream: true });
                    if (text) {
                        await emit({ type: "chunk", text });
                    }
                }
                const tail = decoder.decode();
                if (tail) {
                    await emit({ type: "chunk", text: tail });
                }
                await emit({ type: "done" });
            };
            const fetchWithTimeout = async (url, init, timeoutMs, controller = null) => {
                const activeController = controller || new AbortController();
                const timer = setTimeout(() => activeController.abort(), timeoutMs);
                try {
                    return await fetch(url, { ...init, signal: activeController.signal });
                } finally {
                    clearTimeout(timer);
                }
            };
            const resourceUrls = performance.getEntriesByType("resource").map((entry) => entry.name);
            const sentinelEntries = resourceUrls
                .filter((name) => name.includes("/backend-api/sentinel/chat-requirements"))
                .map(toPath);
            const conversationEntries = resourceUrls
                .filter((name) => name.includes("conversation"))
                .map(toPath)
                .filter((path) => path.endsWith("/conversation") || path.endsWith("/f/conversation"));
            const requirementsUrls = unique([
                toPath(options.requirementsUrl),
                "/backend-api/sentinel/chat-requirements",
                ...sentinelEntries,
            ]);
            const baseHeaders = {
                "accept": "*/*",
                "content-type": "application/json",
                "oai-language": "en-US",
            };
            if (options.accessToken) {
                baseHeaders["authorization"] = `Bearer ${options.accessToken}`;
            }
            if (options.deviceId) {
                baseHeaders["oai-device-id"] = options.deviceId;
            }

            let requirements = null;
            for (const reqUrl of requirementsUrls) {
                try {
                    const response = await fetchWithTimeout(reqUrl, {
                        method: "POST",
                        credentials: "include",
                        headers: baseHeaders,
                        body: JSON.stringify({ conversation_mode_kind: "primary_assistant" }),
                    }, options.timeoutMs, streamController);
                    const text = await response.text();
                    if (!response.ok) {
                        errors.push(`requirements ${reqUrl} ${response.status}: ${text.slice(0, 300)}`);
                        continue;
                    }
                    const parsed = JSON.parse(text);
                    if (parsed && parsed.token) {
                        requirements = parsed;
                        break;
                    }
                    errors.push(`requirements ${reqUrl} returned no token`);
                } catch (error) {
                    errors.push(`requirements ${reqUrl}: ${error && error.message ? error.message : String(error)}`);
                }
            }
            if (!requirements || !requirements.token) {
                throw new Error(`requirements token unavailable: ${errors.join(" | ")}`);
            }

            const getToken = async (names, methodName, errorName) => {
                for (const name of names) {
                    let provider = window;
                    for (const part of name.split(".")) {
                        provider = provider && provider[part];
                    }
                    if (provider && typeof provider[methodName] === "function") {
                        return await provider[methodName](requirements);
                    }
                }
                throw new Error(`${errorName} provider is not ready`);
            };

            const proof = await getToken(["_chatp_old", "_proof", "_proof.Z"], "getEnforcementToken", "proof");
            const conversationHeaders = {
                ...baseHeaders,
                "accept": "text/event-stream",
                "openai-sentinel-chat-requirements-token": requirements.token,
                "openai-sentinel-proof-token": proof,
            };
            if (requirements.turnstile) {
                conversationHeaders["openai-sentinel-turnstile-token"] = await getToken(
                    ["_turnstile", "_turnstile.Z"],
                    "getEnforcementToken",
                    "turnstile"
                );
            }
            if (requirements.arkose) {
                const arkose = await getToken(["_ark", "_ark.ZP"], "startEnforcement", "arkose");
                conversationHeaders["openai-sentinel-arkose-token"] = arkose && arkose.token ? arkose.token : arkose;
            }

            const conversationUrls = unique([
                "/backend-api/f/conversation",
                toPath(options.conversationUrl),
                "/backend-api/conversation",
                "/api/backend-api/f/conversation",
                "/api/backend-api/conversation",
                ...conversationEntries,
            ]);
            for (const conversationUrl of conversationUrls) {
                try {
                    const response = await fetchWithTimeout(conversationUrl, {
                        method: "POST",
                        credentials: "include",
                        headers: conversationHeaders,
                        body: options.payload,
                    }, options.timeoutMs, streamController);
                    const contentType = response.headers.get("content-type") || "";
                    if (!response.ok) {
                        const text = await response.text();
                        errors.push(`conversation ${conversationUrl} ${response.status}: ${text.slice(0, 500)}`);
                        continue;
                    }
                    if (options.stream) {
                        await emit({ type: "meta", url: conversationUrl, status: response.status, contentType });
                        await streamResponse(response);
                        return { ok: true, url: conversationUrl, status: response.status, contentType };
                    }
                    const text = await readText(response);
                    return {
                        ok: true,
                        url: conversationUrl,
                        status: response.status,
                        contentType,
                        text,
                        requirementsKeys: Object.keys(requirements),
                    };
                } catch (error) {
                    errors.push(`conversation ${conversationUrl}: ${error && error.message ? error.message : String(error)}`);
                }
            }
            throw new Error(`conversation fetch failed: ${errors.join(" | ")}`);
        }
        """

    async def _send_msg_by_browser_fetch(self, msg_data: MsgData, session: Session, attempt: int) -> MsgData:
        page = session.page
        if not page:
            raise RuntimeError("session page is not ready")

        if msg_data.upload_file:
            self.logger.debug(f"{session.email} browser fetch path will upload file first")
            await upload_file(msg_data=msg_data, session=session, logger=self.logger)

        data = self._build_conversation_payload(msg_data)

        bridge_result = await asyncio.wait_for(
            page.evaluate(
                self._browser_fetch_bridge_script(),
                {
                    "payload": data,
                    "accessToken": session.access_token,
                    "deviceId": session.device_id,
                    "conversationUrl": url_chatgpt,
                    "requirementsUrl": url_requirements,
                    "timeoutMs": 120000,
                    "stream": False,
                },
            ),
            timeout=150,
        )

        if not isinstance(bridge_result, dict) or not bridge_result.get("ok"):
            raise RuntimeError(f"browser fetch bridge returned invalid result: {bridge_result}")

        self.logger.debug(
            f"{session.email} browser fetch conversation ok, url:{bridge_result.get('url')}, "
            f"status:{bridge_result.get('status')}, content-type:{bridge_result.get('contentType')}"
        )
        msg_data.post_data = data
        msg_data.header = {}
        msg_data = await handle_event_stream(
            MockResponse(bridge_result.get("text", ""), bridge_result.get("status", 200)),
            msg_data,
        )
        if not msg_data.status:
            raise RuntimeError("browser fetch stream parsed no final message")
        return msg_data

    async def _stream_msg_by_browser_fetch(
            self,
            msg_data: MsgData,
            session: Session,
            attempt: int = 1
    ) -> AsyncIterator[ChatStreamEvent]:
        page = session.page
        if not page:
            raise RuntimeError("session page is not ready")

        if msg_data.upload_file:
            self.logger.debug(f"{session.email} browser stream path will upload file first")
            await upload_file(msg_data=msg_data, session=session, logger=self.logger)

        data = self._build_conversation_payload(msg_data)
        msg_data.post_data = data
        binding_name = f"__chatgptweb_stream_{uuid.uuid4().hex}"
        stream_id = uuid.uuid4().hex
        queue: asyncio.Queue = asyncio.Queue()

        def emit_chunk(source, payload):
            queue.put_nowait(payload)

        await page.expose_binding(binding_name, emit_chunk)
        stream_task = asyncio.create_task(
            page.evaluate(
                self._browser_fetch_bridge_script(),
                {
                    "payload": data,
                    "accessToken": session.access_token,
                    "deviceId": session.device_id,
                    "conversationUrl": url_chatgpt,
                    "requirementsUrl": url_requirements,
                    "timeoutMs": 120000,
                    "stream": True,
                    "streamId": stream_id,
                    "emitBinding": binding_name,
                },
            )
        )

        decoder = ChatStreamDecoder()
        done = False
        emitted_final_signatures = set()
        loop = asyncio.get_running_loop()
        last_content_event_at = loop.time()
        last_status_event_at = last_content_event_at
        idle_timeout = max(0, msg_data.stream_idle_timeout_seconds)
        status_interval = max(0, msg_data.stream_status_interval_seconds)

        def should_emit(event: ChatStreamEvent) -> bool:
            if event.type != "final":
                return True
            if not (event.text or event.image_urls):
                return False
            signature = (event.text, event.message_id, event.conversation_id, tuple(event.image_urls))
            if signature in emitted_final_signatures:
                return False
            emitted_final_signatures.add(signature)
            return True

        try:
            while True:
                if stream_task.done() and queue.empty():
                    break
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=0.5)
                except TimeoutError:
                    now = loop.time()
                    idle_seconds = now - last_content_event_at
                    if idle_timeout and idle_seconds >= idle_timeout:
                        raise TimeoutError(f"stream received no upstream chunks for {int(idle_seconds)} seconds")
                    if status_interval and now - last_status_event_at >= status_interval:
                        last_status_event_at = now
                        yield ChatStreamEvent(
                            type="status",
                            metadata={
                                "phase": "waiting_for_upstream",
                                "idle_seconds": int(idle_seconds),
                            },
                        )
                    continue
                if not isinstance(payload, dict):
                    continue
                if payload.get("type") == "meta":
                    self.logger.debug(
                        f"{session.email} browser stream conversation ok, url:{payload.get('url')}, "
                        f"status:{payload.get('status')}, content-type:{payload.get('contentType')}"
                    )
                    continue
                if payload.get("type") == "chunk":
                    events = decoder.feed(payload.get("text", ""))
                    if any(event.type != "final" or event.text or event.image_urls for event in events):
                        last_content_event_at = loop.time()
                    for event in events:
                        if not should_emit(event):
                            continue
                        self._apply_stream_event(msg_data, event)
                        yield event
                    continue
                if payload.get("type") == "done":
                    done = True
                    for event in decoder.close():
                        if not should_emit(event):
                            continue
                        self._apply_stream_event(msg_data, event)
                        yield event
                    break

            result = await stream_task
            if not isinstance(result, dict) or not result.get("ok"):
                raise RuntimeError(f"browser stream bridge returned invalid result: {result}")
            if not done:
                for event in decoder.close():
                    if not should_emit(event):
                        continue
                    self._apply_stream_event(msg_data, event)
                    yield event
        except Exception as e:
            if not stream_task.done():
                stream_task.cancel()
            msg_data.add_error(
                kind="browser_stream_bridge",
                message=str(e),
                retryable=True,
                attempt=attempt,
                session_email=session.email,
            )
            yield ChatStreamEvent(type="error", text=str(e))
            raise
        finally:
            if not stream_task.done():
                await self._cleanup_browser_stream(page, stream_id, abort=True)
                stream_task.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await stream_task
            else:
                await self._cleanup_browser_stream(page, stream_id, abort=False)
            if msg_data.upload_file:
                msg_data.upload_file.clear()

    async def _cleanup_browser_stream(self, page: Page, stream_id: str, abort: bool):
        """Abort and remove one browser-side streaming fetch controller."""
        try:
            await page.evaluate(
                """
                ({ streamId, abort }) => {
                    const controllers = window.__chatgptwebStreamControllers;
                    const controller = controllers && controllers[streamId];
                    if (controller && abort) {
                        controller.abort();
                    }
                    if (controllers) {
                        delete controllers[streamId];
                    }
                    return Boolean(controller);
                }
                """,
                {"streamId": stream_id, "abort": abort},
            )
        except Exception as error:
            self.logger.debug(f"browser stream cleanup skipped: {error}")

    def _apply_stream_event(self, msg_data: MsgData, event: ChatStreamEvent):
        if event.type == "delta" and event.text:
            msg_data.msg_recv += event.text
        elif event.type == "final":
            msg_data.status = True
            if event.text:
                msg_data.msg_recv = event.text
            if event.message_id:
                msg_data.next_msg_id = event.message_id
            if event.conversation_id:
                msg_data.conversation_id = event.conversation_id
            if event.image_urls:
                msg_data.img_list = event.image_urls
                msg_data.image_gen = True
            if event.model:
                msg_data.model_used = event.model
            if event.usage:
                msg_data.usage = event.usage.copy()
            if event.metadata:
                msg_data.response_metadata = event.metadata.copy()
        elif event.type == "image":
            msg_data.img_list = event.image_urls
            msg_data.image_gen = True

    async def send_msg(self, msg_data: MsgData, session: Session, send_status: bool = True,retry: int = 3) -> MsgData:
        """send message body function
        发送消息处理函数"""
        max_attempts = max(1, retry)
        for attempt in range(1, max_attempts + 1):
            if attempt > 1:
                self.logger.debug(f"resend attempt {attempt}/{max_attempts}")
            try:
                return await self._send_msg_once(msg_data, session, send_status=send_status, attempt=attempt)
            except Exception as e:
                retryable = self._is_retryable_send_error(e, session)
                if not retryable:
                    return msg_data
                if attempt >= max_attempts:
                    msg_data.add_error(
                        kind="send_retry_max",
                        message="send msg retry max",
                        retryable=False,
                        attempt=attempt,
                        session_email=session.email,
                    )
                    return msg_data
                await asyncio.sleep(min(attempt, 3))
        return msg_data

    async def _send_msg_once(self, msg_data: MsgData, session: Session, send_status: bool = True, attempt: int = 1) -> MsgData:
        """send message body function
        发送消息处理函数"""
        page = session.page
        token = session.access_token
        context_num = session.email
        self.logger.debug(f"{session.email} begin create send msg cookie and header")
        header = {}
        header['authorization'] = 'Bearer ' + token
        header['Content-Type'] = 'application/json'
        header["User-Agent"] = session.user_agent
        header['Origin'] = "https://chatgpt.com" if "chatgpt" in page.url else 'https://chat.openai.com' # page.url
        header['Referer'] = f"https://chatgpt.com/c/{msg_data.conversation_id}" if msg_data.conversation_id else "https://chatgpt.com"
        header['Accept'] = 'text/event-stream'
        header['Accept-Encoding'] = 'gzip, deflate, zstd'
        header['Accept-Language'] = 'zh-CN,zh;q=0.8,zh-TW;q=0.7,zh-HK;q=0.5,en-US;q=0.3,en;q=0.2'
        header['Host'] = 'chatgpt.com'
        header['Sec-Fetch-Dest'] = 'empty'
        header['Sec-Fetch-Mode'] = 'cors'
        header['Sec-Fetch-Site'] = 'same-origin'
        header['Sec-GPC'] = '1'
        header['Connection'] = 'keep-alive'
        header['DNT'] = '1'
        # header['OAI-Device-Id'] = session.device_id = await page.evaluate("() => window._device()")
        header['OAI-Language'] = 'en-US'
        headers = header.copy()
        if page and not self.httpx_status:
            try:
                self.logger.debug(f"{session.email} will send msg by browser fetch bridge")
                msg_data = await self._send_msg_by_browser_fetch(msg_data, session, attempt=attempt)
                if msg_data.status:
                    msg_data.from_email = session.email
                    if session.login_state is False:
                        session.login_state = True
                    await self.save_chat(msg_data, context_num)
                return msg_data
            except Exception as e:
                error_text = str(e)
                if "Unusual activity" in error_text or "unusual activity" in error_text:
                    session.mark_login_failure(
                        kind="risk_blocked",
                        details=error_text,
                        cooldown_seconds=900,
                    )
                    msg_data.add_error(
                        kind="risk_blocked",
                        message=error_text,
                        retryable=False,
                        attempt=attempt,
                        session_email=session.email,
                    )
                    return msg_data
                self.logger.warning(f"{session.email} browser fetch bridge failed, fall back to legacy route: {e}")
        send_page = None
        try:
            if page and not self.httpx_status:
                send_page: Page = await session.browser_contexts.new_page() # type: ignore
                self.logger.debug(f"{session.email} create new page to send msg")
                async def route_handle(route: Route, request: Request):
                    json_result = None
                    self.logger.debug(f"{session.email} will use page's _chatp")
                    js_test = await page.evaluate("window._chatp")
                    if not js_test:
                        self.logger.debug(f"{session.email} page's _chatp not ready,test other js")
                        js_res = await page.evaluate_handle(self.js[self.js_used])
                        await js_res.json_value()
                        await asyncio.sleep(2)
                        await page.wait_for_load_state("load")
                        await page.wait_for_load_state(state="networkidle")
                        js_test2 = await page.evaluate("() => window._chatp")
                        if not js_test2:
                            js_res = await page.evaluate_handle(self.js[(self.js_used ^ 1)])
                            await js_res.json_value()
                            await asyncio.sleep(2)
                            await page.wait_for_load_state("load")
                            await page.wait_for_load_state(state="networkidle")
                    try:
                        self.logger.debug(f"{session.email} will run page's _chatp.getRequirementsToken()")        
                        json_result = await page.evaluate("() => window._chatp(true)")
                        self.logger.debug(f"{session.email} get _chatp.getRequirementsToken() json_result,wait networkidle")
                        await page.wait_for_load_state("networkidle",timeout=300)
                    except Exception as e:
                        a, b, exc_traceback = sys.exc_info()
                        if "token is expired" in str(e.args[0]):
                            self.logger.debug(f"{session.email} send msg,but page's access_token expired,it will run js")
                            await flush_page(page,self.js,self.js_used)
                            await asyncio.sleep(2)
                            try:
                                await page.wait_for_load_state(state="networkidle",timeout=300)
                            except Exception as e:
                                self.logger.debug(f"{session.email} flush page's access_token networkidle exception:{e}")
                            self.logger.debug(f"{session.email} will run page's _chatp.getRequirementsToken() in try catch")        
                            json_result = await page.evaluate("() => window._chatp(true)")
                        if "Timeout" not in e.args[0]:
                            self.logger.debug(f"{session.email} wait networkidle meet error:{e},line number {exc_traceback.tb_lineno}") # type: ignore
                            pass
                        # self.logger.debug(f"{session.email} wait networkidle ：{e}")
                        else:
                            self.logger.warning(f"route_handle try else error:{e},line number {exc_traceback.tb_lineno}") # type: ignore
                            await save_screen(save_screen_status=self.save_screen,path=f"context_{session.email}_page_send_faild!",page=session.page) # type: ignore
                        
                    if not isinstance(json_result, dict) or "token" not in json_result:
                        try:
                            chatp_type = await page.evaluate("() => typeof window._chatp")
                            chatp_keys = await page.evaluate(
                                "() => window._chatp && typeof window._chatp === 'object' ? Object.keys(window._chatp).slice(0, 20) : []"
                            )
                        except Exception as e:
                            chatp_type = "unknown"
                            chatp_keys = [str(e)]
                        msg_data.add_error(
                            kind="requirements_token_unavailable",
                            message=f"window._chatp is not ready, type:{chatp_type}, keys:{chatp_keys}",
                            retryable=False,
                            attempt=attempt,
                            session_email=session.email,
                        )
                        await route.abort()
                        return
                        
                        
                    self.logger.debug(f"{session.email} will run _proof")
                    try:
                        proof = await page.evaluate(
                            """(jsonResult) => {
                                const providers = [window._chatp_old, window._proof, window._proof && window._proof.Z];
                                for (const provider of providers) {
                                    if (provider && typeof provider.getEnforcementToken === "function") {
                                        return provider.getEnforcementToken(jsonResult);
                                    }
                                }
                                throw new Error("proof provider is not ready");
                            }""",
                            json_result,
                        )
                    except Exception as e:
                        msg_data.add_error(
                            kind="proof_token_unavailable",
                            message=str(e),
                            retryable=False,
                            attempt=attempt,
                            session_email=session.email,
                        )
                        await route.abort()
                        return
                    self.logger.debug(f"{session.email} get proof token")
                    if len(proof) < 30:
                        self.logger.warning(f"{session.email} 's proof may error: {proof}")
                    header['OpenAI-Sentinel-Chat-Requirements-Token'] = json_result['token']
                    header['OpenAI-Sentinel-Proof-Token'] = proof
                    self.logger.debug(f"{session.email} check chatp's turnstile")
                    if json_result.get('turnstile'):
                        try:
                            turnstile = await page.evaluate(
                                """(jsonResult) => {
                                    const providers = [window._turnstile, window._turnstile && window._turnstile.Z];
                                    for (const provider of providers) {
                                        if (provider && typeof provider.getEnforcementToken === "function") {
                                            return provider.getEnforcementToken(jsonResult);
                                        }
                                    }
                                    throw new Error("turnstile provider is not ready");
                                }""",
                                json_result,
                            )
                        except Exception as e:
                            msg_data.add_error(
                                kind="turnstile_token_unavailable",
                                message=str(e),
                                retryable=True,
                                attempt=attempt,
                                session_email=session.email,
                            )
                            await route.abort()
                            return
                        self.logger.debug(f"{session.email} get turnstile token")
                        header['OpenAI-Sentinel-turnstile-Token'] = turnstile
                    self.logger.debug(f"{session.email} check chatp's arkose")
                    if 'arkose' in json_result:
                        if json_result.get('arkose'):
                            # self.logger.debug(f"{session.email} get a arkose token")
                            # async with page.expect_response("https://tcr9i.chat.openai.com/**/public_key/**", timeout=40000) as arkose_info:
                            #     self.logger.debug(f"{session.email} will handle arkose")
                            #     await page.evaluate(f"() => window._ark.ZP.startEnforcement({json.dumps(json_result)})")
                            #     res_ark = await arkose_info.value
                            #     arkose = await res_ark.json()
                            #     header['OpenAI-Sentinel-Arkose-Token'] = arkose['token']
                            #     self.logger.debug(f"{session.email} handle arkose success")
                            
                            self.logger.debug(f"{session.email} will handle arkose")
                            try:
                                arkose = await page.evaluate(
                                    """(jsonResult) => {
                                        const providers = [window._ark, window._ark && window._ark.ZP];
                                        for (const provider of providers) {
                                            if (provider && typeof provider.startEnforcement === "function") {
                                                return provider.startEnforcement(jsonResult);
                                            }
                                        }
                                        throw new Error("arkose provider is not ready");
                                    }""",
                                    json_result,
                                )
                            except Exception as e:
                                msg_data.add_error(
                                    kind="arkose_token_unavailable",
                                    message=str(e),
                                    retryable=True,
                                    attempt=attempt,
                                    session_email=session.email,
                                )
                                await route.abort()
                                return
                            header['OpenAI-Sentinel-Arkose-Token'] = arkose['token']
                            self.logger.debug(f"{session.email} handle arkose success")
                        
                    
                    # self.logger.debug(f"{session.email} will run _device()")
                    
                    msg_data.header = header
                    self.logger.debug(f"{session.email} will test wss alive")
                    # wss_test = await page.evaluate('() => window._wss.ut.activeSocketMap.entries().next().value')
                    try:
                        wss_test = await page.evaluate('() => window._wss.postRegisterWebsocket()')
                    except Exception:
                        pass
                    else:
                        if wss_test:
                            self.logger.debug(f"{session.email} wss alive,will stop it")
                            # await page.evaluate(f'() => window._wss.ut.activeSocketMap.get("{wss_test[0]}").stop()')
                            await page.evaluate('() => window._wss.stopWebsocketConversation()')
                            self.logger.debug(f"{session.email} stop wss success,will register it")
                            # await page.evaluate('() => window._wss.ut.register()')
                            wss = await page.evaluate('() => window._wss.postRegisterWebsocket()')
                            self.logger.debug(f"{session.email} register success,will get it and stop")
                            # await page.evaluate(f'() => window._wss.ut.activeSocketMap.get("{wss_test[0]}").stop()')
                            await page.evaluate('() => window._wss.stopWebsocketConversation()')
                            # wss = await page.evaluate('() => window._wss.ut.activeSocketMap.entries().next().value')
                            self.logger.debug(f"{session.email} get new wss success,it's :{wss}")
                            session.last_wss = wss['wss_url'] # wss[1]['connectionUrl']
                            session.wss_session = ClientSession()
                            session.wss = await session.wss_session.ws_connect(session.last_wss,proxy=self.httpx_proxy,headers=None)
                            self.logger.debug(f"{session.email} aleady connect wss")

                    header["Cookie"] = request.headers["cookie"] 
                    self.logger.debug(f"{session.email} will test upload")
                    if msg_data.upload_file:
                        self.logger.debug(f"{session.email} upload file")
                        await upload_file(msg_data=msg_data,session=session,logger=self.logger)
                    if not msg_data.conversation_id:
                        self.logger.debug(f"{session.email} msg is new conversation")
                        data = Payload.new_payload(msg_data.msg_send,gpt_model=msg_data.gpt_model,files=msg_data.upload_file)
                    else:
                        self.logger.debug(f"{session.email} is old conversation,id: {msg_data.conversation_id}")
                        data = Payload.old_payload(msg_data.msg_send,msg_data.conversation_id,msg_data.p_msg_id,gpt_model=msg_data.gpt_model,files=msg_data.upload_file)
                    header['Content-Length'] = str(len(json.dumps(data).encode('utf-8')))
                    self.logger.debug(f"{session.email} used model: {msg_data.gpt_model}")
                    self.logger.debug(f"{session.email} will continue_ send msg")
                    await route.continue_(method="POST", headers=header, post_data=data)
                self.logger.debug(f"{session.email} will register conversation api route")
                await send_page.route("**/backend-api/f/conversation", route_handle)  

                async with send_page.expect_response("https://chatgpt.com/backend-api/f/conversation",timeout=70000) as response_info: 
                    try:
                        self.logger.debug(f"send:{msg_data.msg_send}")
                        await send_page.goto(url_check, timeout=60000)
                        await send_page.goto("https://chatgpt.com/backend-api/f/conversation", timeout=60000,wait_until='networkidle') 
                    except Exception as e:
                        a, b, exc_traceback = sys.exc_info()
                        if "Download is starting" not in e.args[0]:
                            # 处理重定向
                            self.logger.warning(f"Download message error:{e},line number {exc_traceback.tb_lineno}") # type: ignore
                            msg_data.add_error(
                                kind="download_message",
                                message=str(e),
                                retryable=True,
                                attempt=attempt,
                                session_email=session.email,
                                line=exc_traceback.tb_lineno, # type: ignore
                            )
                            raise e
                    self.logger.debug(f"{session.email} download msg will wait networkidle")
                    await send_page.wait_for_load_state('networkidle')
                    if response_info.is_done():
                        self.logger.debug(f"{session.email} get response is done,will check it")
                    res = await response_info.value
                    
                self.logger.debug(f"{session.email} download msg,will test content-type")
                if res.headers['content-type'] != 'application/json':
                    self.logger.debug(f"{session.email} download msg context-type != json")
                    msg_data = await recive_handle(session,res,msg_data,self.logger) 
                else: #if res.headers['content-type'] == 'application/json':
                    self.logger.debug(f"{session.email} download msg context-type == json,maybe wss")
                    try:
                        json_data = await res.json()
                        self.logger.debug(f"{session.email} get json ok,will run try_wss()")
                        data = await try_wss(wss=json_data,msg_data=msg_data,session=session,ws=session.wss,proxy=self.httpx_proxy,logger=self.logger)
                        self.logger.debug(f"{session.email} run try_wss ok,will handle data")
                        msg_data = await recive_handle(session,data,msg_data,self.logger) 
                    except Exception as e:
                        a, b, exc_traceback = sys.exc_info()
                        self.logger.warning(f"download msg may json_wss,and error: {e} {await res.text()},line number {exc_traceback.tb_lineno}") # type: ignore
                        if "token_expired" in await res.text():
                            session.status = Status.Update.value
                            self.logger.warning(f"{session.email} maybe token expired,set session.status Update,please try again later")
                            msg_data.add_error(
                                kind="token_expired",
                                message=f"{session.email} maybe token expired,set session.status Update,please try again later",
                                retryable=False,
                                attempt=attempt,
                                session_email=session.email,
                            )
                            raise e
                        msg_data.add_error(
                            kind="json_wss",
                            message=f"{e} {await res.text()}",
                            retryable=True,
                            attempt=attempt,
                            session_email=session.email,
                            line=exc_traceback.tb_lineno, # type: ignore
                        )
                        raise e
                    finally:
                        if session.wss:
                            self.logger.debug(f"{session.email} will close wss")
                            await session.wss.close()
                        if session.wss_session:
                            self.logger.debug(f"{session.email} will close wss_session")
                            await session.wss_session.close()
                        session.wss = None
                        session.wss_session = None

                # handle image_gen
                if msg_data.image_gen:
                    await asyncio.sleep(10)
                    file_gpt_url = ""
                    file_gpt_router = ""
                    async def route_handle_image_gen(route: Route, request: Request):
                        await route.continue_(headers=headers)
                    await send_page.route("**/backend-api/images/bootstrap", route_handle_image_gen)  
                    
                    retry_get_img = 3
                    while retry_get_img:
                        res_json = await get_json_url(send_page,session,"https://chatgpt.com/backend-api/images/bootstrap",self.logger)
                        if res_json and "thumbnail_url" in res_json:
                            thumbnail_url: str = res_json["thumbnail_url"]
                            if thumbnail_url == None:
                                self.logger.debug(f"{session.email} get img thumbnail_url seems not ready,retry{retry_get_img}")
                                await asyncio.sleep(5)
                                retry_get_img -= 1
                                continue
                            else:
                                file_id_tmp = thumbnail_url.split("_")[1] 
                                file_id = file_id_tmp.split("/")[0]
                                file_gpt_router = f"/backend-api/files/download/file_{file_id.replace('-','')}?conversation_id={msg_data.conversation_id}&inline=false"
                                file_gpt_url = f"https://chatgpt.com{file_gpt_router}"
                                self.logger.debug(f"{session.email} get img url seems not ready,retry{retry_get_img}")
                                break
                        else:
                            self.logger.warning(f"{session.email} get gen thumbnail image:{res_json},retry{retry_get_img}")
                            retry_get_img -= 1

                    if file_gpt_url:
                        async def route_handle_image_get(route: Route, request: Request):
                            await route.continue_(headers=headers)
                        await send_page.route(f"**{file_gpt_router}", route_handle_image_get)  
                        res_json = await get_json_url(send_page,session,file_gpt_url,self.logger)
                        if res_json and "status" in res_json and res_json["status"] == "success" and "download_url" in res_json:
                            self.logger.debug(f"{session.email} get gen image url {file_gpt_url} :{res_json['download_url']}")
                            msg_data.img_list.append(res_json["download_url"])
                        else:
                            self.logger.warning(f"{session.email} get gen image url {file_gpt_url} :{res_json}")

                # if msg_data.title == "":
                    # get title and email and all_msg
                msg_data.from_email = session.email
                self.logger.info(f"{session.email} {msg_data.conversation_id} will get title")
                title_url_api = f"https://chatgpt.com/backend-api/conversation/{msg_data.conversation_id}"
                async def route_handle_title_url(route: Route, request: Request):
                    await route.continue_(headers=headers)
                await send_page.route(f"**/backend-api/conversation/{msg_data.conversation_id}", route_handle_title_url)
                res_json = await get_json_url(send_page,session,title_url_api,self.logger)
                if "title" in res_json:
                    msg_data.title = res_json["title"]
                self.logger.info(f"{session.email} {msg_data.conversation_id} will get end_msg")
                end_msg: dict = res_json["mapping"][msg_data.next_msg_id]["message"]
                msg = get_all_msg(end_msg)
                msg_data.msg_raw = msg
                if msg_data.msg_md2img:
                    if len(msg_data.msg_raw) > 1:
                        msg_data.msg_md_img = await markdown2image(''.join(msg_data.msg_raw),session)
                    else:
                        msg_data.msg_md_img = await markdown2image(msg_data.msg_raw[0],session)


                    

            
        except Exception as e:
            a, b, exc_traceback = sys.exc_info()
            self.logger.warning(f"send message error:{e}")
            retryable = self._is_retryable_send_error(e, session)
            msg_data.add_error(
                kind="send_message",
                message=str(e),
                retryable=retryable,
                attempt=attempt,
                session_email=session.email,
                line=exc_traceback.tb_lineno, # type: ignore
            )
            raise e
        finally:
            if send_page:
                await send_page.close()
            if msg_data.upload_file:
                msg_data.upload_file.clear()
        if msg_data.status:
            if session.login_state is False:
                session.login_state = True
            await self.save_chat(msg_data, context_num)
        return msg_data

        
    async def save_chat(self, msg_data: MsgData, context_num: str):
        """save chat file
        保存聊天文件"""
        path = self._conversation_path(msg_data.conversation_id)
        lock = await self._conversation_lock(msg_data.conversation_id)
        async with lock:
            if not path.exists() or not path.stat().st_size:
                history = {
                    "conversation_id": msg_data.conversation_id,
                    "message": [],
                }
            else:
                history = json.loads(path.read_text("utf8"))
            message = {
                "input": msg_data.msg_send,
                "output": msg_data.msg_recv,
                "type": msg_data.msg_type,
                "next_msg_id": msg_data.next_msg_id,
            }
            if msg_data.p_msg_id:
                message["p_msg_id"] = msg_data.p_msg_id
            history["message"].append(message)
            self._write_json_atomic(path, history)

        async with self._conversation_map_lock:
            map_tmp = json.loads(self.cc_map.read_text("utf8"))
            conversations = map_tmp.setdefault(str(context_num), [])
            if msg_data.conversation_id not in conversations:
                conversations.append(msg_data.conversation_id)
                self._write_json_atomic(self.cc_map, map_tmp)

    async def load_chat(self, msg_data: MsgData):
        """load chat file
        读取聊天文件"""
        path = self._conversation_path(msg_data.conversation_id)
        if not path.exists() or not path.stat().st_size:
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
            lambda s: s.type != "script" and s.login_state is True and not s.is_login_disabled(),
            sorted(self.Sessions, key=lambda s: s.last_active)
        )
        session: Session = next(sessions, None) # type: ignore

        if not session:
            raise Exception("Not Found Page")
        msg_data = self.browser_event_loop.run_until_complete(self.send_msg(msg_data, session)) # type: ignore
        
        return msg_data

    async def _prepare_chat_session(self, msg_data: MsgData) -> Optional[Session]:
        """Select and reserve the session that should handle this request."""
        startup_wait_seconds = 0
        while not self.manage["start"]:
            await asyncio.sleep(0.5)
            startup_wait_seconds += 0.5
            if startup_wait_seconds >= self.ready_timeout:
                msg_data.add_error(
                    kind="startup_timeout",
                    message=f"chatgpt startup did not finish within {self.ready_timeout} seconds",
                )
                self.logger.error(msg_data.error_info)
                return None

        session: Session = Session(status=Status.Working.value)
        if not msg_data.conversation_id:
            gpt4_list = [
                s for s in self.Sessions
                if s.type != "script" and supports_paid_models(
                    getattr(s, "account_plan", "unknown"), s.gptplus,
                )
            ]
            if gpt4_list == [] and msg_data.gpt_plus:
                msg_data.add_error(
                    kind="no_plus_account",
                    message="you use gptplus model,but gptplus account not found",
                )
                self.logger.error(msg_data.error_info)
                return None
            elif msg_data.gpt_model in all_models_values():
                pass
            elif msg_data.gpt_plus:
                pass
            else:
                self.logger.warning(f"unknown model: {msg_data.gpt_model} ,try to use it")

            session_list = gpt4_list if msg_data.gpt_plus else self.Sessions
            wait_ready_seconds = 0
            while not session or session.status == Status.Working.value:
                filtered_sessions = [
                    s for s in session_list
                    if (
                        s.type != "script"
                        and s.login_state is True
                        and s.status == Status.Ready.value
                        and not s.is_login_disabled()
                    )
                ]
                if filtered_sessions:
                    session = random.choice(filtered_sessions)
                else:
                    pending_sessions = [
                        s for s in session_list
                        if (
                            s.type != "script"
                            and s.status in (Status.Login.value, Status.Update.value, Status.Working.value)
                            and not s.is_login_disabled()
                        )
                    ]
                    if not pending_sessions:
                        msg_data.add_error(
                            kind="no_available_session",
                            message="no login-capable session is available",
                        )
                        self.logger.error(msg_data.error_info)
                        return None

                await asyncio.sleep(0.5)
                wait_ready_seconds += 0.5
                if wait_ready_seconds >= self.ready_timeout:
                    msg_data.add_error(
                        kind="no_ready_session",
                        message=f"no ready session found within {self.ready_timeout} seconds",
                    )
                    self.logger.error(msg_data.error_info)
                    return None
        else:
            map_tmp = json.loads(self.cc_map.read_text("utf8"))
            for context_name in map_tmp:
                if msg_data.conversation_id in map_tmp[context_name]:
                    sessions = [s for s in self.Sessions if s.email == context_name]
                    if sessions:
                        session = sessions[0]
                    else:
                        msg_data.add_error(
                            kind="conversation_session_missing",
                            message=f"the session corresponding to the conversation_id:{msg_data.conversation_id} was not found. Please check whether the session account has been removed.",
                        )
                        self.logger.error(msg_data.error_info)
                        return None
                    if session.is_login_disabled():
                        self.logger.warning(f"ur conversation_id:{msg_data.conversation_id} 'session doesn't work.")
                        msg_data.add_error(
                            kind="conversation_session_stopped",
                            message=f"ur conversation_id:{msg_data.conversation_id} 'session doesn't work.",
                            session_email=session.email,
                        )
                        return None
                    wait_ready_seconds = 0
                    while session.status != Status.Ready.value:
                        await asyncio.sleep(0.5)
                        wait_ready_seconds += 0.5
                        if wait_ready_seconds >= self.ready_timeout:
                            msg_data.add_error(
                                kind="conversation_session_not_ready",
                                message=f"conversation session is not ready within {self.ready_timeout} seconds, status:{session.status}",
                                session_email=session.email,
                            )
                            self.logger.error(msg_data.error_info)
                            return None
                    break

            if not session.email:
                msg_data.add_error(
                    kind="session_not_found",
                    message="Not session found,please check your conversation_id input",
                )
                self.logger.error(msg_data.error_info)
                return None

            if not msg_data.p_msg_id:
                try:
                    msg_history = await self.load_chat(msg_data)
                    msg_data.p_msg_id = msg_history["message"][-1]["next_msg_id"]
                    msg_data.msg_type = "old_session"
                except Exception:
                    a, b, exc_traceback = sys.exc_info()
                    self.logger.error(f"ur p_msg_id:{msg_data.p_msg_id} 'chatfile not found,line number {exc_traceback.tb_lineno}.") # type: ignore
                    msg_data.add_error(
                        kind="parent_message_restore_failed",
                        message=f"ur p_msg_id:{msg_data.p_msg_id} 'chatfile not found",
                        line=exc_traceback.tb_lineno, # type: ignore
                    )
                    return None

        if msg_data.conversation_id != "" and msg_data.msg_type == "new_session":
            msg_data.msg_type = "old_session"

        if not await self._ensure_session_runtime(session):
            msg_data.add_error(
                kind="session_runtime_unavailable",
                message=f"session runtime is not available: {session.email}",
                session_email=session.email,
            )
            self.logger.error(msg_data.error_info)
            return None

        session.status = Status.Working.value
        self.logger.debug(f"session {session.email} begin work")
        return session

    async def continue_chat(self, msg_data: MsgData) -> MsgData:
        """
        Message processing entry, please use this
        """
        session = await self._prepare_chat_session(msg_data)
        if not session:
            return msg_data

        try:
            msg_data = await asyncio.wait_for(self.send_msg(msg_data, session), timeout=180)
            session.status = Status.Ready.value
            self._record_usage(session, msg_data)
        except TimeoutError:
            msg_data.add_error(
                kind="continue_chat_timeout",
                message=f"send msg {msg_data.msg_send} time out",
                retryable=True,
                session_email=session.email,
            )
            self.logger.warning(msg_data.error_info)
        except Exception as e:
            a, b, exc_traceback = sys.exc_info()
            msg_data.add_error(
                kind="continue_chat_error",
                message=f"send msg {msg_data.msg_send} error:{e}",
                session_email=session.email,
                line=exc_traceback.tb_lineno, # type: ignore
            )
            self.logger.error(msg_data.error_info)
        else:
            if not msg_data.error_info or msg_data.status:
                if msg_data.msg_raw:
                    self.logger.info(f"receive message: {msg_data.msg_raw}")
                else:
                    self.logger.info(f"receive message: {msg_data.msg_recv}")
        finally:
            if session.status not in (Status.Update.value, Status.Stop.value):
                session.status = Status.Ready.value
        self.logger.debug(f"session {session.email} finish work")
        return msg_data

    async def continue_chat_stream(self, msg_data: MsgData) -> AsyncIterator[ChatStreamEvent]:
        """Stream chat events from the browser fetch transport."""
        session = await self._prepare_chat_session(msg_data)
        if not session:
            yield ChatStreamEvent(type="error", text=msg_data.error_info or "failed to prepare chat session")
            return

        context_num = session.email
        msg_data.from_email = session.email
        self.logger.debug(f"session {session.email} begin stream work")
        try:
            async for event in self._stream_msg_by_browser_fetch(msg_data, session):
                yield event
            if msg_data.status:
                if session.login_state is False:
                    session.login_state = True
                await self.save_chat(msg_data, context_num)
                self._record_usage(session, msg_data)
                self.logger.info(f"receive stream message: {msg_data.msg_recv}")
        except Exception as e:
            if not msg_data.error_info:
                msg_data.add_error(kind="continue_chat_stream_error", message=str(e), session_email=session.email)
            self.logger.error(msg_data.error_info)
            yield ChatStreamEvent(
                type="error",
                text=msg_data.error_info or str(e),
                message_id=msg_data.next_msg_id,
                conversation_id=msg_data.conversation_id,
                model=msg_data.model_used,
                usage=msg_data.usage.copy(),
                metadata=msg_data.response_metadata.copy(),
            )
        finally:
            if session.status not in (Status.Update.value, Status.Stop.value):
                session.status = Status.Ready.value
            self.logger.debug(f"session {session.email} finish stream work")

    async def show_chat_history(self, msg_data: MsgData) -> List[Dict[str, str]]:
        """show chat history
        展示聊天记录"""
        msg_history = await self.load_chat(msg_data)
        msg = []
        for i,x in enumerate(msg_history["message"]):
            msg.append({
                "index": str(i+1),
                "Q": x['input'],
                "A": x['output'],
                "next_msg_id": x['next_msg_id'],
            })
        return msg
    
    async def show_history_tree_md(self, msg_data: MsgData, md: bool = True, end_num: int = 25) -> str:
        """将聊天历史转换为树状Markdown格式，默认问答只显示25个字符"""
        if end_num == 0:
            end_num = None
        msg_history = await self.load_chat(msg_data)
        messages = msg_history["message"]
        
        # 1. 构建消息映射和索引映射
        msg_map = {}
        index_map = {}  # 存储消息ID到原始索引的映射
        root_nodes = []
        
        # 创建ID到消息的映射，并识别根节点
        for idx, msg in enumerate(messages):
            msg_id = msg['next_msg_id']
            msg_map[msg_id] = msg
            index_map[msg_id] = idx  # 存储原始索引
            
            # 检查是否是根节点
            if 'p_msg_id' not in msg or not msg['p_msg_id']:
                root_nodes.append(msg_id)
        
        # 2. 构建树结构
        tree = {}
        for msg in messages:
            msg_id = msg['next_msg_id']
            
            # 初始化当前节点的子树
            if msg_id not in tree:
                tree[msg_id] = []
            
            # 将当前节点添加到父节点的子树
            parent_id = msg.get('p_msg_id', None)
            if parent_id and parent_id in tree:
                tree[parent_id].append(msg_id)
        
        # 3. 根据md参数选择输出格式
        if md:
            # Markdown列表格式（第一种方法）
            def build_md_branch(node_id, level=0, parent_index=""):
                """递归构建Markdown列表分支"""
                msg = msg_map[node_id]
                idx = index_map[node_id]
                
                # 当前节点的索引
                if parent_index:
                    current_index = f"{parent_index}.{level+1}"
                else:
                    current_index = f"{level+1}"
                
                # 构建问题行
                indent = "    " * level
                output = [f"{indent}- [{idx}] Q: {msg['input'][:end_num]}"]
                
                # 构建回答行
                output.append(f"{indent}    A: {msg['output'][:end_num]}")
                
                # 处理子节点
                children = tree.get(node_id, [])
                for i, child_id in enumerate(children):
                    output.extend(build_md_branch(child_id, level+1, current_index))
                
                return output
            
            # 构建完整Markdown树
            lines = []
            for i, root_id in enumerate(root_nodes):
                root_msg = msg_map[root_id]
                root_idx = index_map[root_id]
                
                # 根节点
                lines.append(f"- [{root_idx}] Q: {root_msg['input'][:end_num]}")
                lines.append(f"    A: {root_msg['output'][:end_num]}")
                
                # 添加根的子节点
                children = tree.get(root_id, [])
                for child_id in children:
                    lines.extend(build_md_branch(child_id, 1, "1"))
            
            # 添加标题
            header = "### 聊天历史树状图\n"
            return header + "\n".join(lines)
        
        else:
            # 原始树状ASCII格式
            def build_branch(node_id, prefix="", is_last=False):
                """递归构建分支"""
                msg = msg_map[node_id]
                idx = index_map[node_id]  # 获取原始索引
                output = []
                
                # 当前节点前缀符号
                connector = "└── " if is_last else "├── "
                
                # 添加问题行（带索引）
                output.append(f"{prefix}{connector}[{idx}] Q: {msg['input'][:end_num]}")
                
                # 添加回答行（与问题行对齐）
                answer_prefix = prefix + ("    " if is_last else "│   ")
                output.append(f"{answer_prefix}    A: {msg['output'][:end_num]}")
                
                # 处理子节点
                children = tree.get(node_id, [])
                for i, child_id in enumerate(children):
                    # 确定子节点前缀
                    child_prefix = prefix + ("    " if is_last else "│   ")
                    is_child_last = (i == len(children) - 1)
                    
                    # 递归添加子节点
                    output.extend(build_branch(
                        child_id, 
                        child_prefix, 
                        is_child_last
                    ))
                
                return output
            
            # 构建完整树
            lines = []
            for i, root_id in enumerate(root_nodes):
                root_msg = msg_map[root_id]
                root_idx = index_map[root_id]  # 根节点索引
                
                is_last_root = (i == len(root_nodes) - 1)
                
                # 根节点特殊格式
                root_connector = "└── " if is_last_root else "├── "
                lines.append(f"{root_connector}[{root_idx}] Q: {root_msg['input'][:end_num]}")
                lines.append(f"    A: {root_msg['output'][:end_num]}")
                
                # 添加根的子节点
                children = tree.get(root_id, [])
                for j, child_id in enumerate(children):
                    is_last_child = (j == len(children) - 1)
                    lines.extend(build_branch(
                        child_id, 
                        "    " if is_last_root else "│   ",
                        is_last_child
                    ))
            
            # 添加标题并返回
            header = "### 聊天历史树状图\n```"
            footer = "```"
            return header + "\n" + "\n".join(lines) + "\n" + footer


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
        self.personality.flush_data(self.chat_file) # type: ignore

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
        verification_broker = getattr(self, "verification_broker", None)
        pending_verifications = await verification_broker.snapshot() if verification_broker else []
        verification_by_account = {
            challenge["account"]: challenge
            for challenge in pending_verifications
        }
        # cid_num may not match the number of sessions, because it only records sessions with successful sessions, which will be automatically resolved after a period of time.
        # cid_num 可能和session数量对不上，因为它只记录会话成功的session，这在允许一段时间后会自动解决
        accounts = []
        for session in self.Sessions:
            if session.type == "script":
                continue
            page = session.page
            page_ready = bool(page and not page.is_closed())
            disabled = session.is_login_disabled()
            retry_task = getattr(self, "_control_login_tasks", {}).get(session.email)
            accounts.append({
                "email": session.email,
                "status": session.status,
                "login_state": session.login_state,
                "available": bool(session.login_state and session.status == Status.Ready.value and not disabled),
                "disabled": disabled,
                "manual_disabled": session.manual_disabled,
                "login_retry_pending": bool(retry_task and not retry_task.done()),
                "can_retry_login": bool(session.email and session.password),
                "disabled_until": session.disabled_until.isoformat() if session.disabled_until else "",
                "gptplus": session.gptplus,
                "account_plan": getattr(session, "account_plan", "unknown"),
                "account_plan_source": getattr(session, "account_plan_source", "unavailable"),
                "account_plan_observed_at": (
                    getattr(session, "account_plan_observed_at", None).isoformat()
                    if getattr(session, "account_plan_observed_at", None) else ""
                ),
                "persist_auth_state": session.persist_auth_state,
                "auth_state_loaded": session.auth_state_loaded,
                "conversation_count": len(cid_all.get(session.email, [])),
                "usage": self._usage_snapshot(session.email),
                "login_fail_count": session.login_fail_count,
                "max_login_failures": session.max_login_failures,
                "login_failure_kind": session.login_failure_kind,
                "last_login_error": session.last_login_error,
                "verification": verification_by_account.get(session.email),
                "runtime": {
                    "context_ready": bool(session.browser_contexts),
                    "page_ready": page_ready,
                    "last_closed_source": session.runtime_last_closed_source,
                    "last_closed_at": session.runtime_last_closed_at.isoformat() if session.runtime_last_closed_at else "",
                    "last_recovered_at": session.runtime_last_recovered_at.isoformat() if session.runtime_last_recovered_at else "",
                    "recovery_count": session.runtime_recovery_count,
                },
            })
        return {
            "account": [session.email  for session in self.Sessions if session.type != "script"],
            "token": [True if session.login_state else False for session in self.Sessions if session.type != "script"],
            "work": [session.status for session in self.Sessions if session.type != "script"],
            "login_fail_count": [session.login_fail_count for session in self.Sessions if session.type != "script"],
            "login_failure_kind": [session.login_failure_kind for session in self.Sessions if session.type != "script"],
            "last_login_error": [session.last_login_error for session in self.Sessions if session.type != "script"],
            "disabled_until": [session.disabled_until.isoformat() if session.disabled_until else "" for session in self.Sessions if session.type != "script"],
            "cid_num": [len(cid_all[session.email]) for session in self.Sessions if session.email in cid_all],
            "plus": [session.gptplus  for session in self.Sessions if session.type != "script"],
            "model_catalog": self._local_model_catalog(),
            "accounts": accounts,
            "verification": pending_verifications,
        }


    async def md2img(self,md: str):
        return await markdown2image(md,self.Sessions[0])
