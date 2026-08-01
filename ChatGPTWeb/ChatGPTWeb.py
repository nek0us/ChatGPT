
import os
import sys
import json
import typing
import base64
import random
import re
import asyncio
import threading
import secrets
import ipaddress
import time
from collections import deque
from contextlib import suppress
from datetime import datetime, timedelta
from pathlib import Path
from aiohttp import ClientSession, web
from playwright_firefox.stealth import Stealth
from playwright_firefox.async_api import async_playwright, Route, Request, Page
from typing import Any, AsyncIterator, Dict, Optional,Literal,List
from urllib.parse import parse_qs, quote, unquote, urljoin, urlparse, urlsplit
from .config import (
    Payload,
    Personality,
    IOFile,
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
    LoginFailureKind,
    all_models_values,
    model_list,
)
from .load import load_js
from .http_api import create_control_app
from .service import ChatService
from .content import build_chat_content
from .output_files import OutputFileReference, output_file_references, safe_output_filename
from .storage import RuntimeStorage
from .verification import VerificationBroker, VerificationCodeProvider
from .capabilities import (
    discover_account_plan,
    infer_plan_from_model_categories,
    supports_observed_model,
    supports_paid_models,
)
from .capability_quota import (
    FILE_UPLOAD,
    IMAGE_GENERATION,
    IMAGE_UPLOAD,
    infer_request_capabilities,
)
from .api import (
    async_send_msg,
    recive_handle,
    handle_event_stream,
    create_session,
    retry_keep_alive,
    Auth,
    restore_session_state,
    save_session_state,
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
from .api_keys import ApiKeyStore
from .request_scheduler import RequestLease, RequestScheduler
from .runtime_logging import (
    BoundedLogHandler,
    ColorFormatter,
    color_output_enabled,
    default_stream,
)

class chatgpt:
    def __init__(self,
                 sessions: list[dict] = [],
                 proxy: Optional[str] = None,
                 storage_dir: Path = Path("data", "chatgptweb"),
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
                 session_health_check_interval: int = 300,
                 chat_rate_limit_cooldown_seconds: int = 5 * 60 * 60,
                 capability_quota_enabled: bool = True,
                 free_upload_daily_limit: int = 2,
                 free_image_generation_daily_limit: int = 2,
                 capability_rate_limit_cooldown_seconds: int = 24 * 60 * 60,
                 account_selection_strategy: Literal["least_recently_used", "usage_balanced"] = "least_recently_used",
                 account_selection_window_seconds: int = 5 * 60 * 60,
                 request_queue_timeout_seconds: int = 120,
                 control_host: str = "127.0.0.1",
                 control_port: int | None = None,
                 control_api_key: str | None = None,
                 control_log_path: Path | str | None = None,
                 verification_code_providers: typing.Sequence[VerificationCodeProvider] = (),
                 output_file_max_size: int = 20 * 1024 * 1024,
                 output_file_max_total_size: int = 40 * 1024 * 1024,
                 output_file_max_count: int = 8,
               
                 ) -> None:
        """
        ### sessions : list[dict]
        your session_token or account | 你的session_token 或者账号密码  {"session_token":""}
        ### proxy : {"server": "http://ip:port"}
        your proxy for openai | 你用于访问openai的代理
        ### storage_dir : Path
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
        self.storage = RuntimeStorage(storage_dir)
        self.api_key_store = ApiKeyStore(self.storage)
        self.personality = Personality([{"name": "cat", "value": "you are a cat now."}]) if personality is None else personality
        self.personality.replace_data(self.storage.load_personas() + self.personality.init_list)
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
        if session_health_check_interval < 0:
            raise ValueError("session_health_check_interval must not be negative")
        self.session_health_check_interval = session_health_check_interval
        if not 60 <= chat_rate_limit_cooldown_seconds <= 24 * 60 * 60:
            raise ValueError(
                "chat_rate_limit_cooldown_seconds must be between 60 and 86400"
            )
        self.chat_rate_limit_cooldown_seconds = chat_rate_limit_cooldown_seconds
        if not 0 <= free_upload_daily_limit <= 1000:
            raise ValueError("free_upload_daily_limit must be between 0 and 1000")
        if not 0 <= free_image_generation_daily_limit <= 1000:
            raise ValueError(
                "free_image_generation_daily_limit must be between 0 and 1000"
            )
        if not 60 <= capability_rate_limit_cooldown_seconds <= 7 * 24 * 60 * 60:
            raise ValueError(
                "capability_rate_limit_cooldown_seconds must be between 60 and 604800"
            )
        self.capability_quota_enabled = bool(capability_quota_enabled)
        self.free_upload_daily_limit = free_upload_daily_limit
        self.free_image_generation_daily_limit = free_image_generation_daily_limit
        self.capability_rate_limit_cooldown_seconds = (
            capability_rate_limit_cooldown_seconds
        )
        if account_selection_strategy not in {"least_recently_used", "usage_balanced"}:
            raise ValueError(
                "account_selection_strategy must be 'least_recently_used' or 'usage_balanced'"
            )
        if not 60 <= account_selection_window_seconds <= 24 * 60 * 60:
            raise ValueError(
                "account_selection_window_seconds must be between 60 and 86400"
            )
        self.account_selection_strategy = account_selection_strategy
        self.account_selection_window_seconds = account_selection_window_seconds
        if not 1 <= request_queue_timeout_seconds <= 3600:
            raise ValueError("request_queue_timeout_seconds must be between 1 and 3600")
        self.request_queue_timeout_seconds = request_queue_timeout_seconds
        if not 1024 <= output_file_max_size <= 100 * 1024 * 1024:
            raise ValueError("output_file_max_size must be between 1024 and 104857600")
        if not output_file_max_size <= output_file_max_total_size <= 500 * 1024 * 1024:
            raise ValueError(
                "output_file_max_total_size must be at least output_file_max_size "
                "and no greater than 524288000"
            )
        if not 1 <= output_file_max_count <= 32:
            raise ValueError("output_file_max_count must be between 1 and 32")
        self.output_file_max_size = output_file_max_size
        self.output_file_max_total_size = output_file_max_total_size
        self.output_file_max_count = output_file_max_count
        if control_port is not None and not 0 <= control_port <= 65535:
            raise ValueError("control_port must be between 0 and 65535")
        self.control_host = control_host
        self.control_port = control_port
        self.control_log_path = Path(control_log_path) if control_log_path else None
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
        self._intentional_context_closures = set()
        self._conversation_locks: Dict[str, asyncio.Lock] = {}
        self._conversation_locks_guard = asyncio.Lock()
        self._control_login_tasks: Dict[str, asyncio.Task] = {}
        self._session_health_checked_at: Dict[str, float] = {}
        self._session_health_tasks: Dict[str, asyncio.Task] = {}
        self._usage_by_account: Dict[str, Dict[str, Dict[str, float]]] = {}
        self._account_selection_history: Dict[str, deque[datetime]] = {}
        self._request_scheduler = RequestScheduler(self._request_scheduler_capacity)
        self._activity: List[Dict[str, object]] = []
        self.verification_broker = VerificationBroker(code_providers=verification_code_providers)
        self.logger = logging.getLogger("logger")
        self._standard_logger = self.logger
        self._nonebot_runtime_sink_id = None
        self.logger.setLevel(logger_level)
        sh = logging.StreamHandler()
        sh.setFormatter(ColorFormatter(
            formator,
            enabled=color_output_enabled(getattr(sh, "stream", default_stream())),
        ))
        self.logger.addHandler(sh)
        self._stream_log_handler = sh
        self._runtime_log_handler = BoundedLogHandler()
        self._runtime_log_handler.setFormatter(formator)
        self.logger.addHandler(self._runtime_log_handler)
        self._control_log_handler = None
        if self.control_log_path:
            try:
                self.control_log_path.parent.mkdir(parents=True, exist_ok=True)
                log_handler = logging.FileHandler(self.control_log_path, encoding="utf8")
                log_handler.setFormatter(formator)
                self.logger.addHandler(log_handler)
                self._control_log_handler = log_handler
            except OSError as error:
                self.logger.warning("could not open control runtime log %s: %s", self.control_log_path, error)
        if not self.log_status:
            self.logger.removeHandler(sh)
            self._stream_log_handler = None
        
        if not sessions:
            raise ValueError("session_token is empty!")

        for session in sessions:
            s = Session(**session)
            s = create_session(**session)
            if s.is_valid:
                if not s.type:
                    s.type = "session"
                s = restore_session_state(s, self.storage, self.logger)
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
            if self._stream_log_handler is not None:
                self._standard_logger.removeHandler(self._stream_log_handler)
                self._stream_log_handler.close()
                self._stream_log_handler = None
            self._standard_logger.removeHandler(self._runtime_log_handler)
            self.logger = logger
            self._nonebot_runtime_sink_id = self.logger.add(
                self._runtime_log_handler,
                level=logger_level,
                format="{time:YYYY/MM/DD HH:mm:ss} {file.name} {level} {message}",
                colorize=False,
            )

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

    @staticmethod
    def _firefox_user_prefs() -> Dict[str, bool]:
        return {
            "dom.storageManager.prompt.testing": True,
            "dom.storageManager.prompt.testing.allow": True,
        }
    
    # 检测Firefox是否已经安装 
    async def is_firefox_installed(self):
        '''chekc firefox install | 检测Firefox是否已经安装 '''
        playwright_manager = None
        try:
            playwright_manager = async_playwright()
            playwright = await self._startup_wait_for(
                "startup_firefox_check_playwright_start",
                playwright_manager.start(),
            )
            return Path(playwright.firefox.executable_path).is_file()
        except TimeoutError as e:
            self.logger.warning(f"check firefox timeout, skip install check:{e}")
            return True
        except Exception as e:
            self.logger.warning(f"check firefox:{e}")
            return False
        finally:
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
                        firefox_user_prefs=self._firefox_user_prefs(),
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
        return self.storage.auth_state_path(session.email)

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

    async def _cleanup_pending_page_creation(self, context, page_task, known_pages: set[int]) -> None:
        if not page_task.done():
            page_task.cancel()
            await asyncio.gather(page_task, return_exceptions=True)
        for page in getattr(context, "pages", []):
            if id(page) in known_pages or page.is_closed():
                continue
            try:
                await page.close()
            except Exception:
                pass

    async def _new_page_with_timeout(self, context, label: str, *, retry_after_initial_wait: bool = False):
        """Create a page without leaking a late Playwright task on startup stalls."""
        timeout = self.startup_timeout
        known_pages = {id(page) for page in getattr(context, "pages", [])}
        page_task = asyncio.create_task(context.new_page())
        initial_wait = min(15, timeout)
        try:
            return await asyncio.wait_for(asyncio.shield(page_task), timeout=initial_wait)
        except TimeoutError:
            self.logger.warning(
                f"{label}_page_create is still pending; "
                "if Firefox is blank, bring its window to the foreground"
            )
            if retry_after_initial_wait:
                await self._cleanup_pending_page_creation(context, page_task, known_pages)
                raise TimeoutError(f"{label}_page_create did not respond within {initial_wait}s")
        try:
            return await asyncio.wait_for(page_task, timeout=timeout - initial_wait)
        except TimeoutError as error:
            await self._cleanup_pending_page_creation(context, page_task, known_pages)
            self.logger.warning(f"{label}_page_create timeout after {timeout}s")
            raise TimeoutError(f"{label}_page_create timeout after {timeout}s") from error

    async def _discard_session_context(self, session: Session) -> None:
        """Close an unusable context so a later retry starts from a clean page."""
        context = session.browser_contexts
        session.browser_contexts = None
        session.page = None
        if not context:
            return
        suppressed = getattr(self, "_intentional_context_closures", None)
        if suppressed is None:
            suppressed = self._intentional_context_closures = set()
        suppressed.add(session.email)
        try:
            await context.close()
        except Exception as error:
            self.logger.warning(f"{session.email} could not close unusable context: {error}")
        finally:
            self._intentional_context_closures.discard(session.email)

    def _mark_session_runtime_closed(self, session: Session, source: str):
        if self._closing:
            return
        if session.email in getattr(self, "_intentional_context_closures", set()):
            return
        if session.status == Status.Stop.value:
            return
        session.login_state = False
        session.login_state_first = False
        session.status = Status.Recovering.value
        session.last_login_error = f"runtime {source} closed unexpectedly"
        session.runtime_last_closed_source = source
        session.runtime_last_closed_at = datetime.now()
        if source == "context":
            session.browser_contexts = None
            session.page = None
        elif "page" in source:
            session.page = None
        self._record_activity(session.email, "runtime_closed", f"{source} closed unexpectedly")
        self.logger.warning(f"{session.email} runtime {source} closed unexpectedly, set status Recovering")

    async def _recover_session_context_for_bridge(
        self,
        session: Session,
        *,
        quick_page_recovery: bool = False,
    ) -> bool:
        """Replace one unusable browser context without treating it as a login failure."""
        await self._discard_session_context(session)
        try:
            recovered = await self._ensure_session_runtime(
                session,
                quick_page_recovery=quick_page_recovery,
            )
        except Exception as error:
            self.logger.warning(f"{session.email} bridge context recovery failed: {error}")
            return False
        if recovered:
            self._record_activity(session.email, "bridge_context_recovery", "recreated context after bridge timeout")
        return recovered

    async def _create_startup_page(self, session: Session) -> Page:
        """Create the initial page, replacing a context once when Firefox stalls."""
        context = session.browser_contexts
        if not context:
            raise RuntimeError("startup browser context is missing")
        try:
            page = await self._new_page_with_timeout(
                context,
                f"startup_{session.email}",
                retry_after_initial_wait=True,
            )
        except TimeoutError as error:
            # Firefox can occasionally leave a newly-created context unable to
            # create its first page.  Reusing that context only preserves the
            # stall, so give the account one clean context before cooling it down.
            self.logger.warning(
                f"{session.email} startup page creation timed out; recreating browser context once"
            )
            if not await self._recover_session_context_for_bridge(
                session,
                quick_page_recovery=True,
            ):
                raise RuntimeError("startup context recovery failed") from error
            page = session.page
            if not page:
                raise RuntimeError("startup context recovery created no page") from error
        session.page = page
        self._watch_page_events(session, page)
        return page

    @staticmethod
    def _needs_startup_browser_relaunch(session: Session) -> bool:
        if (
            session.status not in (Status.Update.value, Status.Recovering.value)
            or session.login_failure_kind != LoginFailureKind.Transient.value
        ):
            return False
        details = session.last_login_error.lower()
        return "page_create" in details or "startup context recovery" in details

    async def _retry_startup_after_browser_stall(self) -> bool:
        """Relaunch Firefox once when every initial login hit a page-creation stall."""
        if any(session.status == Status.Ready.value for session in self.Sessions):
            return False
        candidates = [
            session for session in self.Sessions
            if self._needs_startup_browser_relaunch(session)
        ]
        if not candidates:
            return False

        self.logger.warning(
            "all available startup accounts stalled while creating their first page; "
            "relaunching Firefox once"
        )
        for session in self.Sessions:
            await self._discard_session_context(session)
        self._watched_contexts.clear()
        self._watched_pages.clear()
        await self._cleanup_browser_startup()
        await self._launch_browser_with_retry(retries=1)
        for session in candidates:
            # This is an immediate recovery of the same transient startup
            # failure, not an ordinary scheduled retry.  Keeping the first
            # attempt's cooldown would make retry_keep_alive skip the fresh
            # Firefox page we just created.
            session.disabled_until = None
        await asyncio.gather(*(self.__login(session) for session in candidates), return_exceptions=True)
        return True

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

    async def _ensure_session_runtime(
        self,
        session: Session,
        *,
        quick_page_recovery: bool = False,
    ) -> bool:
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
            session.page = await self._new_page_with_timeout(
                session.browser_contexts,
                f"runtime_{session.email}",
                retry_after_initial_wait=quick_page_recovery,
            ) # type: ignore
            recovered = True
            self._watch_page_events(session, session.page)

        if recovered:
            session.runtime_recovery_count += 1
            session.runtime_last_recovered_at = datetime.now()

        return True
    
    async def _conversation_lock(self, conversation_id: str) -> asyncio.Lock:
        async with self._conversation_locks_guard:
            lock = self._conversation_locks.get(conversation_id)
            if lock is None:
                lock = asyncio.Lock()
                self._conversation_locks[conversation_id] = lock
            return lock

    async def __keep_alive__(self, session: Session):
        url = url_check
        controlled_tasks = getattr(self, "_control_login_tasks", {})
        controlled_login = controlled_tasks.get(session.email)
        if controlled_login and not controlled_login.done():
            # Stream-expiry recovery owns this account's page until it either
            # restores a session or reaches a concrete login outcome.  A
            # second keep-alive login can navigate away from the native email
            # drawer midway through the first attempt.
            self.logger.debug(f"{session.email} keep-alive skipped while controlled login is in progress")
            return
        if session.is_login_disabled():
            self.logger.debug(
                f"{session.email} keep-alive skipped, status:{session.status}, "
                f"failure:{session.login_failure_kind}"
            )
            return
        if session.force_fresh_login:
            # A request just received an authoritative Sentinel rejection.  Do
            # not leave recovery behind this account's randomized keep-alive
            # delay; it would turn a recoverable expiry into a user-visible
            # chat failure for up to a minute.
            if not await self._ensure_session_runtime(session):
                return
            controlled_login = getattr(self, "_control_login_tasks", {}).get(session.email)
            if controlled_login and not controlled_login.done():
                self.logger.debug(f"{session.email} keep-alive yielded to controlled login after runtime recovery")
                return
            self.logger.debug(f"{session.email} bypass keep-alive delay for forced fresh login")
            # Authentication alone can return an access token before the
            # Sentinel proof provider is installed.  ``load_page`` keeps the
            # account non-ready until that browser bridge has been rebuilt.
            await self.load_page(session, immediate=True)
            return
        await asyncio.sleep(random.randint(1, 60 if len(self.Sessions) < 10 else 6 * len(self.Sessions)))
        controlled_login = getattr(self, "_control_login_tasks", {}).get(session.email)
        if controlled_login and not controlled_login.done():
            self.logger.debug(f"{session.email} keep-alive yielded to controlled login after delay")
            return
        if session.status == Status.Stop.value or session.is_login_disabled():
            self.logger.debug(
                f"{session.email} keep-alive skipped after delay, status:{session.status}, "
                f"failure:{session.login_failure_kind}"
            )
            return
        if not await self._ensure_session_runtime(session):
            return
        controlled_login = getattr(self, "_control_login_tasks", {}).get(session.email)
        if controlled_login and not controlled_login.done():
            self.logger.debug(f"{session.email} keep-alive yielded to controlled login after runtime check")
            return
        if session.force_fresh_login:
            # Sentinel has already rejected this browser auth state.  Do not
            # let a cached /api/auth/session response mark it ready again.
            self.logger.debug(f"{session.email} bypass keep-alive for forced fresh login")
            await self.load_page(session, immediate=True)
            return
        if session.status == Status.Recovering.value and session.session_refresh_recovery_needed:
            self.logger.debug(f"{session.email} recreate browser context before retrying network recovery")
            if not await self._recover_session_context_for_bridge(session):
                session.mark_login_failure(
                    kind=LoginFailureKind.Transient.value,
                    details="could not recreate browser context after session refresh timeout",
                    cooldown_seconds=60,
                )
                return
            session.session_refresh_recovery_needed = False
        session = await retry_keep_alive(session, url, self.storage, self.js, self.js_used, self.save_screen, self.logger)
        if session.status == Status.Ready.value and session.login_state:
            if not await self._probe_stream_authorization(session):
                return
        # check session_token need update
        if session.status == Status.Update.value and not session.is_login_disabled():
            # yes,we should update it
            self.logger.debug(f"{session.email} begin relogin")
            await self.load_page(session, immediate=True)
            self.logger.debug(f"{session.email} relogin over")
        elif session.status == Status.Login.value:
            self.logger.debug(f"{session.email} loging in")
        

    async def __alive__(self):
        """Keep browser session state and ChatGPT session tokens refreshed.
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
                    self.logger.error(f"add {context_index} session refresh task error! {e}")
            try:
                self.logger.debug(f"{session.email} will refresh session keep-alive tasks")
                await asyncio.wait_for(asyncio.gather(*tasks),timeout=300)
            except TimeoutError:
                self.logger.warning(f"{session.email} session keep-alive tasks timed out after 300 seconds")
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
                await self._create_startup_page(session)
                session.status = Status.Login.value
            elif session.session_token and session.browser_contexts:
                token = session.session_token
                await session.browser_contexts.add_cookies([token]) # type: ignore
                await self._create_startup_page(session)
                session.status = Status.Login.value

            elif session.email and session.password and session.browser_contexts:
                await self._create_startup_page(session)
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
                kind=LoginFailureKind.Transient.value,
                details="login task cancelled by startup timeout",
            )
            raise
        except Exception as e:
            session.mark_login_failure(
                kind=LoginFailureKind.Transient.value,
                details=f"login task failed: {e}",
            )
            if session.page is None:
                await self._discard_session_context(session)
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
            await self._retry_startup_after_browser_stall()
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
                if s.status in (Status.Login.value, Status.Update.value, Status.Recovering.value):
                    s.mark_login_failure(
                        kind=LoginFailureKind.Transient.value,
                        details="startup auth/load_page timeout",
                    )
        except Exception as e:
            a, b, exc_traceback = sys.exc_info()
            self.logger.warning(f"{session.email} auth and load_page error:{e},line: {exc_traceback.tb_lineno}") # type: ignore

        self.manage["browser_contexts"] = self.browser.contexts

        self.manage["start"] = True
        self.logger.debug("start!")
        self.thread = threading.Thread(target=lambda: self.tmp(loop), daemon=True)
        self.thread.start()

    async def _start_control_server(self) -> None:
        if self.control_port is None or self._control_runner:
            return
        if not hasattr(self, "api_key_store"):
            self.api_key_store = ApiKeyStore(self.storage)
        runner = web.AppRunner(create_control_app(
            ChatService(self),
            self.verification_broker,
            api_key=self.control_api_key,
            api_key_store=self.api_key_store,
            runtime_log_path=getattr(self, "control_log_path", None),
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
            self.logger.info("ChatGPTWeb control API key is configured")
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

    async def _run_controlled_login(
        self,
        session: Session,
        *,
        prefer_openai_otp: bool = False,
    ) -> None:
        try:
            await self.load_page(
                session,
                immediate=True,
                prefer_openai_otp=prefer_openai_otp,
            )
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
        capabilities = list(msg_data.required_capabilities)
        elapsed_ms = (
            max(0, int((time.monotonic() - msg_data.request_started_at) * 1000))
            if msg_data.request_started_at else 0
        )
        self._record_activity(
            session.email,
            "chat_completed",
            (
                f"model: {model}"
                + (f"; capabilities: {', '.join(capabilities)}" if capabilities else "")
            ),
            details={
                "model": model,
                "duration_ms": elapsed_ms,
                "uploads": msg_data.request_upload_count,
                "generated_images": self._generated_image_count(msg_data),
            },
        )

    @staticmethod
    def _generated_image_count(msg_data: MsgData) -> int:
        """Count generated images whether they are URLs or downloaded artifacts."""
        downloaded = sum(
            1
            for file in msg_data.download_file
            if str(file.mime_type or "").lower().startswith("image/")
        )
        return max(len(msg_data.img_list), downloaded)

    @staticmethod
    def _is_paid_account(session: Session) -> bool:
        plan = str(getattr(session, "account_plan", "unknown")).lower()
        if plan and plan != "unknown":
            return plan in {
                "plus", "pro", "go", "team", "business", "enterprise",
            }
        return bool(session.gptplus)

    @staticmethod
    def _reset_capability_usage_day(session: Session) -> None:
        today = datetime.now().date().isoformat()
        if session.capability_usage_day == today:
            return
        session.capability_usage_day = today
        session.capability_usage.clear()

    def _required_capabilities(self, msg_data: MsgData) -> list[str]:
        capabilities = infer_request_capabilities(
            msg_data.msg_send,
            msg_data.upload_file,
            msg_data.required_capabilities,
        )
        msg_data.required_capabilities = capabilities
        return capabilities

    def _capability_soft_limit(self, capability: str) -> int:
        if capability in {IMAGE_UPLOAD, FILE_UPLOAD}:
            return getattr(self, "free_upload_daily_limit", 0)
        if capability == IMAGE_GENERATION:
            return getattr(self, "free_image_generation_daily_limit", 0)
        return 0

    @staticmethod
    def _capability_usage_key(capability: str) -> str:
        if capability in {IMAGE_UPLOAD, FILE_UPLOAD}:
            return "upload_total"
        return capability

    def _capability_availability(
        self,
        session: Session,
        capability: str,
    ) -> tuple[bool, int, str]:
        if not getattr(self, "capability_quota_enabled", True):
            return True, 0, ""
        self._reset_capability_usage_day(session)
        limited_until = session.capability_limited_until.get(capability)
        if limited_until and datetime.now() < limited_until:
            return (
                False,
                max(0, int((limited_until - datetime.now()).total_seconds())),
                "upstream",
            )
        if limited_until:
            session.clear_capability_rate_limit(capability)
        if self._is_paid_account(session):
            return True, 0, ""
        limit = self._capability_soft_limit(capability)
        if limit <= 0:
            return True, 0, ""
        used = int(session.capability_usage.get(
            self._capability_usage_key(capability),
            0,
        ))
        if used < limit:
            return True, 0, ""
        tomorrow = datetime.combine(
            datetime.now().date() + timedelta(days=1),
            datetime.min.time(),
        )
        return (
            False,
            max(60, int((tomorrow - datetime.now()).total_seconds())),
            "local_soft_budget",
        )

    def _session_supports_capabilities(
        self,
        session: Session,
        capabilities: typing.Iterable[str],
    ) -> bool:
        return all(
            self._capability_availability(session, capability)[0]
            for capability in capabilities
        )

    def _add_capability_unavailable_error(
        self,
        msg_data: MsgData,
        sessions: typing.Iterable[Session],
        capabilities: typing.Iterable[str],
        *,
        conversation: bool = False,
    ) -> None:
        session_list = list(sessions)
        required = list(capabilities)
        blocked = [
            capability
            for capability in required
            if not any(
                self._capability_availability(session, capability)[0]
                for session in session_list
            )
        ]
        reported = blocked or required
        retry_values = [
            self._capability_availability(session, capability)[1]
            for session in session_list
            for capability in reported
            if not self._capability_availability(session, capability)[0]
        ]
        retry_after = min((value for value in retry_values if value > 0), default=0)
        kind = (
            "conversation_capability_rate_limited"
            if conversation else "capability_rate_limited"
        )
        msg_data.add_error(
            kind=kind,
            message=(
                f"required capability is cooling down: {', '.join(reported)}; "
                f"retry after about {retry_after} seconds"
            ),
            retryable=True,
            capability=reported[0] if len(reported) == 1 else "",
        )

    def _capability_snapshot(self, session: Session) -> Dict[str, object]:
        self._reset_capability_usage_day(session)
        result: Dict[str, object] = {
            "enabled": bool(getattr(self, "capability_quota_enabled", True)),
            "usage_day": session.capability_usage_day,
            "paid_account": self._is_paid_account(session),
            "budget_source": "local_estimate",
            "upstream_state_source": "observed_errors",
            "upload_total": int(session.capability_usage.get("upload_total", 0)),
        }
        for capability in (IMAGE_UPLOAD, FILE_UPLOAD, IMAGE_GENERATION):
            available, retry_after, reason = self._capability_availability(
                session,
                capability,
            )
            usage_key = self._capability_usage_key(capability)
            limit = 0 if self._is_paid_account(session) else self._capability_soft_limit(
                capability
            )
            result[capability] = {
                "used": int(session.capability_usage.get(capability, 0)),
                "budget_used": int(session.capability_usage.get(usage_key, 0)),
                "limit": limit,
                "remaining": (
                    max(0, limit - int(session.capability_usage.get(usage_key, 0)))
                    if limit > 0 else None
                ),
                "available": available,
                "limited": not available,
                "limit_reason": reason,
                "retry_after_seconds": retry_after,
                "limited_until": (
                    session.capability_limited_until[capability].isoformat()
                    if capability in session.capability_limited_until else ""
                ),
                "source": session.capability_limit_source.get(capability, ""),
            }
        return result

    def _record_capability_usage(
        self,
        session: Session,
        msg_data: MsgData,
    ) -> None:
        if (
            not getattr(self, "capability_quota_enabled", True)
            or msg_data.capability_usage_recorded
            or not msg_data.status
        ):
            return
        self._reset_capability_usage_day(session)
        increments = {IMAGE_UPLOAD: 0, FILE_UPLOAD: 0, IMAGE_GENERATION: 0}
        if msg_data.upload_file:
            for file in msg_data.upload_file:
                capability = (
                    IMAGE_UPLOAD
                    if file.content_type == "image_asset_pointer"
                    or str(file.mime_type or "").lower().startswith("image/")
                    else FILE_UPLOAD
                )
                increments[capability] += 1
        else:
            increments[IMAGE_UPLOAD] = msg_data.request_image_upload_count
            increments[FILE_UPLOAD] = msg_data.request_file_upload_count
        generated_images = self._generated_image_count(msg_data)
        if msg_data.image_gen or generated_images:
            increments[IMAGE_GENERATION] = max(1, generated_images)
        changed = False
        upload_count = increments[IMAGE_UPLOAD] + increments[FILE_UPLOAD]
        if upload_count:
            session.capability_usage["upload_total"] = (
                int(session.capability_usage.get("upload_total", 0)) + upload_count
            )
            changed = True
        for capability, count in increments.items():
            if not count:
                continue
            session.capability_usage[capability] = (
                int(session.capability_usage.get(capability, 0)) + count
            )
            changed = True
        msg_data.capability_usage_recorded = True
        if changed:
            save_session_state(session, self.storage, self.logger)
            self._record_activity(
                session.email,
                "capability_usage_recorded",
                ", ".join(
                    f"{capability}: +{count}"
                    for capability, count in increments.items()
                    if count
                ),
            )

    def _record_activity(
        self,
        account: str,
        event: str,
        message: str,
        *,
        severity: str = "info",
        details: Optional[Dict[str, object]] = None,
    ) -> None:
        """Record bounded, credential-free diagnostics for the local console."""
        activity = getattr(self, "_activity", None)
        if activity is None:
            activity = self._activity = []
        item: Dict[str, object] = {
            "at": datetime.now().isoformat(timespec="seconds"),
            "account": account,
            "event": event,
            "message": message[:240],
            "severity": severity,
        }
        if details:
            item["details"] = {
                str(key): value
                for key, value in details.items()
                if isinstance(value, (str, int, float, bool)) or value is None
            }
        activity.append(item)
        if len(activity) > 200:
            del activity[:-200]

    async def get_activity(self, limit: int = 50) -> Dict[str, object]:
        """Return recent local control/runtime activity without secrets or prompts."""
        limit = max(1, min(limit, 200))
        activity = getattr(self, "_activity", [])
        return {"events": list(reversed(activity[-limit:]))}

    async def get_runtime_logs(self, limit: int = 160) -> Dict[str, object]:
        """Return a structured current-process tail when no log file is configured."""
        limit = max(20, min(limit, 800))
        handler = getattr(self, "_runtime_log_handler", None)
        entries = handler.snapshot(limit) if handler is not None else []
        return {
            "available": bool(entries),
            "source": "memory",
            "message": "" if entries else "runtime log is empty",
            "entries": entries,
            "lines": [entry["text"] for entry in entries],
        }

    def _usage_snapshot(self, account: str) -> Dict[str, object]:
        models = getattr(self, "_usage_by_account", {}).get(account, {})
        return {
            "source": "observed_upstream" if models else "unavailable",
            "requests": sum(int(item.get("requests", 0)) for item in models.values()),
            "models": {model: values.copy() for model, values in models.items()},
            "quota": None,
        }

    def _recent_account_assignment_count(self, account: str, now: Optional[datetime] = None) -> int:
        """Return new-conversation assignments inside the configured rolling window."""
        now = now or datetime.now()
        history_by_account = getattr(self, "_account_selection_history", None)
        if history_by_account is None:
            history_by_account = self._account_selection_history = {}
        history = history_by_account.setdefault(account, deque())
        window_seconds = getattr(self, "account_selection_window_seconds", 5 * 60 * 60)
        cutoff = now.timestamp() - window_seconds
        while history and history[0].timestamp() < cutoff:
            history.popleft()
        return len(history)

    def _select_new_conversation_session(self, sessions: List[Session]) -> Session:
        """Choose a ready account for a new logical conversation only."""
        strategy = getattr(self, "account_selection_strategy", "least_recently_used")
        if strategy != "usage_balanced":
            return min(sessions, key=lambda item: item.last_active)

        now = datetime.now()
        counts = {
            session.email: self._recent_account_assignment_count(session.email, now)
            for session in sessions
        }
        minimum_count = min(counts.values())
        least_assigned = [
            session for session in sessions
            if counts[session.email] == minimum_count
        ]
        oldest_active = min(session.last_active for session in least_assigned)
        least_recently_reserved = [
            session for session in least_assigned
            if session.last_active == oldest_active
        ]
        return random.choice(least_recently_reserved)

    def _record_new_conversation_assignment(self, session: Session) -> None:
        """Record a reservation after its browser runtime is ready for work."""
        self._recent_account_assignment_count(session.email)
        self._account_selection_history[session.email].append(datetime.now())

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
            prefer_openai_otp = (
                session.mode == "openai"
                and session.login_failure_kind == LoginFailureKind.NeedVerification.value
            )
            session.manual_disabled = False
            session.login_state = False
            session.login_state_first = False
            session.status = Status.Update.value
            session.login_fail_count = 0
            session.login_failure_kind = ""
            session.last_login_error = "manual login retry requested"
            session.disabled_until = None
            tasks[session.email] = asyncio.create_task(
                self._run_controlled_login(
                    session,
                    prefer_openai_otp=prefer_openai_otp,
                )
            )
        else:
            await self._refresh_account_plan(session)
        save_session_state(session, self.storage, self.logger)
        self._record_activity(session.email, "account_control", f"action: {action}")
        self.logger.info(f"account {session.email} control action: {action}")

        status = await self.token_status()
        return next(item for item in status["accounts"] if item["email"] == account)

    async def load_page(
        self,
        session: Session,
        immediate: bool = False,
        *,
        prefer_openai_otp: bool = False,
    ):
        '''start page | 载入初始页面'''
        if self.begin_sleep_time and not immediate and session.type != "script":
            await asyncio.sleep(random.randint(1, len(self.Sessions)*6))
        page = session.page
        if page:
            session.user_agent = await page.evaluate('() => navigator.userAgent')
            if session.force_fresh_login:
                # A manual retry reaches this path too.  Sentinel already
                # rejected the browser session, so defer to Auth below instead
                # of allowing the keep-alive probe to restore stale state.
                self.logger.debug(f"context {session.email} bypass initial keep-alive for forced fresh login")
                session.status = Status.Update.value
            else:
                session = await retry_keep_alive(
                    session,
                    url_check,
                    self.storage,
                    self.js,
                    self.js_used,
                    self.save_screen,
                    self.logger,
                )
            if session.session_refresh_recovery_needed:
                self.logger.warning(
                    f"context {session.email} recreating after exhausted session refresh"
                )
                if not await self._recover_session_context_for_bridge(session):
                    session.mark_login_failure(
                        kind=LoginFailureKind.Transient.value,
                        details="could not recreate browser context after session refresh timeout",
                        cooldown_seconds=60,
                    )
                    return
                session.session_refresh_recovery_needed = False
                page = session.page
                if not page:
                    return
            try:
                await page.goto("https://chatgpt.com/", timeout=20000, wait_until="domcontentloaded")
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
                        kind=LoginFailureKind.Transient.value,
                        details="load_page relogin retry max",
                    )
                    self.logger.warning(f"context {session.email} relogin retry max, scheduled retry")
                    break
                relogin_try += 1
                self.logger.debug(f"context {session.email} begin relogin")
                await Auth(
                    session,
                    self.logger,
                    self.verification_broker,
                    prefer_openai_otp=prefer_openai_otp,
                    force_fresh_login=session.force_fresh_login,
                )
                self.logger.debug(f"context {session.email} relogin over")
            
            if session.status in (Status.Stop.value, Status.Update.value, Status.Recovering.value):
                session.login_state = False
                self.logger.warning(
                    f"context {session.email} not ready, status:{session.status}, failure:{session.login_failure_kind}, "
                    f"error:{session.last_login_error[:200]}"
                )
                return

            if not await self._initialize_page_bridge_with_recovery(session, page):
                return

            page = session.page
            if not page:
                return

            await self._refresh_account_plan(session)
            
            if session.access_token:
                if session.status not in (Status.Update.value, Status.Recovering.value):
                    session.login_state = True
                    session.status = Status.Ready.value
                    self.logger.debug(f"context {session.email} start!")
                    await self._save_auth_state(session)
                    self._schedule_session_health_probe(session)
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

    def _mark_bridge_initialization_failure(self, session: Session, error: Exception | None) -> None:
        session.mark_login_failure(
            kind="transient",
            details=f"browser bridge initialization failed: {error}",
            cooldown_seconds=60,
        )
        self.logger.warning(
            f"context {session.email} bridge initialization failed twice; status:{session.status}"
        )

    async def _initialize_page_bridge(
        self,
        session: Session,
        page: Page,
        *,
        mark_failure: bool = True,
    ) -> bool:
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
                        await page.goto("https://chatgpt.com/", timeout=20000, wait_until="domcontentloaded")
                    except Exception:
                        pass

        if mark_failure:
            self._mark_bridge_initialization_failure(session, last_error)
        return False

    async def _initialize_page_bridge_with_recovery(self, session: Session, page: Page) -> bool:
        """Give a blank startup context one isolated recreation attempt."""
        if await self._initialize_page_bridge(session, page, mark_failure=False):
            return True

        self.logger.warning(f"context {session.email} recreating context after bridge initialization failure")
        if not await self._recover_session_context_for_bridge(session):
            self._mark_bridge_initialization_failure(session, RuntimeError("context recovery failed"))
            return False

        recovered_page = session.page
        if not recovered_page:
            self._mark_bridge_initialization_failure(session, RuntimeError("recovered context has no page"))
            return False
        try:
            await recovered_page.goto("https://chatgpt.com/", timeout=20000, wait_until="domcontentloaded")
        except Exception as error:
            self.logger.warning(f"context {session.email} recovery navigation failed: {error}")
        return await self._initialize_page_bridge(session, recovered_page, mark_failure=True)
        
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

        health_tasks = list(getattr(self, "_session_health_tasks", {}).values())
        for task in health_tasks:
            if not task.done():
                task.cancel()
        if health_tasks:
            await asyncio.gather(*health_tasks, return_exceptions=True)
        getattr(self, "_session_health_tasks", {}).clear()

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

        log_handler = getattr(self, "_control_log_handler", None)
        if log_handler:
            standard_logger = getattr(self, "_standard_logger", self.logger)
            if log_handler in getattr(standard_logger, "handlers", ()):
                standard_logger.removeHandler(log_handler)
            log_handler.close()
            self._control_log_handler = None

        nonebot_sink_id = getattr(self, "_nonebot_runtime_sink_id", None)
        if nonebot_sink_id is not None:
            try:
                self.logger.remove(nonebot_sink_id)
            except (TypeError, ValueError):
                pass
            self._nonebot_runtime_sink_id = None

        for attribute in ("_stream_log_handler", "_runtime_log_handler"):
            handler = getattr(self, attribute, None)
            if handler:
                standard_logger = getattr(self, "_standard_logger", self.logger)
                if handler in getattr(standard_logger, "handlers", ()):
                    standard_logger.removeHandler(handler)
                handler.close()
                setattr(self, attribute, None)

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
        if self._is_upstream_rate_limit_error(text):
            return False
        if session.status in (Status.Update.value, Status.Recovering.value, Status.Stop.value):
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

    @staticmethod
    def _is_upstream_rate_limit_error(error: Exception | str) -> bool:
        text = str(error).lower()
        return any(marker in text for marker in (
            "reached our limit of messages",
            "limit of messages per hour",
            "rate limit",
            "rate_limited",
            "too many requests",
            "too many messages",
            "status: 429",
            "upload limit",
            "uploads left",
            "file limit reached",
            "image generation limit",
            "image creation limit",
            "can't create more images",
            "cannot create more images",
        ))

    @staticmethod
    def _upstream_rate_limit_cooldown_seconds(error: Exception | str) -> int | None:
        """Extract an explicit upstream retry delay without trusting arbitrary text."""
        text = str(error).lower()
        numeric_patterns = (
            r'"retry_after(?:_seconds)?"\s*[:=]\s*"?(\d+(?:\.\d+)?)"?',
            r"retry_after(?:_seconds)?\s*[:=]\s*(\d+(?:\.\d+)?)",
        )
        for pattern in numeric_patterns:
            match = re.search(pattern, text)
            if match:
                return max(60, min(int(float(match.group(1))), 24 * 60 * 60))

        duration = re.search(
            r"(?:try again|retry|reset(?:s)?|available)\s*(?:after|in)\s*"
            r"(\d+(?:\.\d+)?)\s*(seconds?|secs?|minutes?|mins?|hours?|hrs?)",
            text,
        )
        if not duration:
            return None
        value = float(duration.group(1))
        unit = duration.group(2)
        multiplier = 3600 if unit.startswith(("hour", "hr")) else 60 if unit.startswith(("minute", "min")) else 1
        return max(60, min(int(value * multiplier), 24 * 60 * 60))

    def _mark_chat_rate_limited(self, session: Session, error: Exception | str):
        upstream_cooldown = self._upstream_rate_limit_cooldown_seconds(error)
        cooldown_seconds = upstream_cooldown or getattr(
            self,
            "chat_rate_limit_cooldown_seconds",
            5 * 60 * 60,
        )
        source = "upstream_retry_hint" if upstream_cooldown else "configured_cooldown"
        session.mark_chat_rate_limited(
            str(error),
            cooldown_seconds=cooldown_seconds,
            source=source,
        )
        save_session_state(session, self.storage, self.logger)
        self._record_activity(
            session.email,
            "chat_rate_limited",
            f"new chats paused for about {cooldown_seconds}s ({source})",
        )
        self.logger.warning(
            f"{session.email} upstream chat rate limit reached; "
            f"temporarily excluding this account from new conversations for about {cooldown_seconds}s"
        )

    def _rate_limited_capabilities(
        self,
        error: Exception | str,
        msg_data: MsgData,
    ) -> list[str]:
        text = str(error).lower()
        matches: list[str] = []
        if any(marker in text for marker in (
            "upload limit",
            "uploads left",
            "attachment limit",
            "file upload",
            "upload files",
            "上传限制",
            "上传额度",
            "文件上传",
        )):
            return [IMAGE_UPLOAD, FILE_UPLOAD]
        markers = {
            IMAGE_GENERATION: (
                "image generation", "image creation", "create images",
                "generating images", "生成图片", "图像生成",
            ),
            IMAGE_UPLOAD: (
                "image upload", "upload images", "上传图片", "图片上传",
            ),
            FILE_UPLOAD: (
                "上传文件",
            ),
        }
        for capability, capability_markers in markers.items():
            if any(marker in text for marker in capability_markers):
                matches.append(capability)
        if matches:
            return matches
        required = self._required_capabilities(msg_data)
        return required if len(required) == 1 else []

    @staticmethod
    def _is_image_generation_limit_response(value: str) -> bool:
        """Recognize the normal-text image quota response returned by ChatGPT."""
        text = value.lower()
        markers = (
            "image creation will be available again",
            "image generation will be available again",
            "image limit resets",
            "instant limit resets",
            "image creation limit",
            "image generation limit",
            "生图额度",
            "图像生成额度",
        )
        return any(marker in text for marker in markers)

    def _handle_image_generation_limit_response(
        self,
        session: Session,
        msg_data: MsgData,
        response: str,
        *,
        attempt: int,
    ) -> None:
        self._handle_upstream_rate_limit(session, msg_data, response, attempt=attempt)
        if not msg_data.error_list:
            msg_data.add_error(
                kind="capability_rate_limited",
                message="upstream image generation limit reached",
                retryable=True,
                attempt=attempt,
                session_email=session.email,
                capability=IMAGE_GENERATION,
            )

    def _mark_capability_rate_limited(
        self,
        session: Session,
        capabilities: typing.Iterable[str],
        error: Exception | str,
    ) -> None:
        upstream_cooldown = self._upstream_rate_limit_cooldown_seconds(error)
        cooldown_seconds = upstream_cooldown or getattr(
            self,
            "capability_rate_limit_cooldown_seconds",
            24 * 60 * 60,
        )
        source = "upstream_retry_hint" if upstream_cooldown else "configured_cooldown"
        marked: list[str] = []
        for capability in capabilities:
            session.mark_capability_rate_limited(
                capability,
                str(error),
                cooldown_seconds=cooldown_seconds,
                source=source,
            )
            marked.append(capability)
        if not marked:
            return
        save_session_state(session, self.storage, self.logger)
        self._record_activity(
            session.email,
            "capability_rate_limited",
            f"{', '.join(marked)} paused for about {cooldown_seconds}s ({source})",
        )
        self.logger.warning(
            f"{session.email} upstream capability limit reached for "
            f"{', '.join(marked)}; cooling down for about {cooldown_seconds}s"
        )

    def _handle_upstream_rate_limit(
        self,
        session: Session,
        msg_data: MsgData,
        error: Exception | str,
        *,
        attempt: int,
    ) -> None:
        capabilities = self._rate_limited_capabilities(error, msg_data)
        if capabilities and getattr(self, "capability_quota_enabled", True):
            self._mark_capability_rate_limited(session, capabilities, error)
            msg_data.add_error(
                kind="capability_rate_limited",
                message=(
                    "upstream capability rate limit reached for "
                    + ", ".join(capabilities)
                ),
                retryable=True,
                attempt=attempt,
                session_email=session.email,
                capability=capabilities[0] if len(capabilities) == 1 else "",
            )
            return
        self._mark_chat_rate_limited(session, error)
        msg_data.add_error(
            kind="rate_limited",
            message="upstream chat message rate limit reached",
            retryable=True,
            attempt=attempt,
            session_email=session.email,
        )

    def _clear_chat_rate_limit(self, session: Session) -> None:
        if not session.chat_rate_limited_until:
            return
        session.clear_chat_rate_limit()
        save_session_state(session, self.storage, self.logger)

    @staticmethod
    def _is_expired_stream_auth_error(error: Exception | str) -> bool:
        """Return whether a browser stream failed before generation due to stale auth."""
        text = str(error).lower()
        return any(marker in text for marker in (
            "provided authentication token is expired",
            "token_expired",
            "requirements token unavailable",
            "chat-requirements 401",
        ))

    @staticmethod
    def _is_unready_stream_bridge_error(error: Exception | str) -> bool:
        """Return whether a newly restored page has not installed Sentinel providers yet."""
        text = str(error).lower()
        return any(marker in text for marker in (
            "proof provider is not ready",
            "turnstile provider is not ready",
            "arkose provider is not ready",
            "window._chatp is not ready",
            "browser bridge providers did not become ready",
        ))

    async def _recover_unready_stream_bridge(self, session: Session) -> bool:
        """Finish initializing a freshly authenticated page before one stream retry."""
        page = session.page
        if not page or page.is_closed() or session.is_login_disabled():
            return False
        self.logger.warning(
            f"{session.email} stream bridge is still warming up; rebuilding it once before retry"
        )
        try:
            self.js_used = await flush_page(page, self.js, self.js_used)
        except Exception as error:
            self.logger.warning(f"{session.email} stream bridge warm-up failed: {error}")
            return False
        return True

    async def _probe_stream_authorization(self, session: Session, *, force: bool = False) -> bool:
        """Check the same Sentinel gate used by streams without sending a chat request.

        ``/api/auth/session`` can briefly report a usable token after Sentinel has
        already rejected it.  A successful probe is intentionally lightweight;
        only an authoritative 401 changes the account state, while transient
        network and upstream errors are left to the normal retry path.
        """
        if (
            session.status != Status.Ready.value
            or not session.login_state
            or session.is_login_disabled()
        ):
            return False
        page = session.page
        if not page or page.is_closed():
            return False

        interval = getattr(self, "session_health_check_interval", 300)
        now = asyncio.get_running_loop().time()
        checked = getattr(self, "_session_health_checked_at", None)
        if checked is None:
            checked = self._session_health_checked_at = {}
        checked_at = checked.get(session.email, 0.0)
        if not force and interval > 0 and now - checked_at < interval:
            return True

        try:
            result = await asyncio.wait_for(
                page.evaluate(
                    """
                    async (options) => {
                        const headers = {
                            "accept": "application/json, text/plain, */*",
                            "content-type": "application/json",
                        };
                        if (options.accessToken) headers.authorization = `Bearer ${options.accessToken}`;
                        if (options.deviceId) headers["oai-device-id"] = options.deviceId;
                        try {
                            const response = await fetch("/backend-api/sentinel/chat-requirements", {
                                method: "POST",
                                credentials: "include",
                                headers,
                                body: JSON.stringify({ conversation_mode_kind: "primary_assistant" }),
                            });
                            return { status: response.status };
                        } catch (error) {
                            return { status: 0, error: String(error) };
                        }
                    }
                    """,
                    {
                        "accessToken": session.access_token,
                        "deviceId": session.device_id,
                    },
                ),
                timeout=15,
            )
        except Exception as error:
            self.logger.debug(f"{session.email} Sentinel health probe unavailable: {error}")
            return True

        checked[session.email] = now
        try:
            status = int((result or {}).get("status", 0))
        except (TypeError, ValueError, AttributeError):
            status = 0
        if status == 401:
            self.logger.warning(
                f"{session.email} Sentinel health probe rejected the current authorization; scheduling relogin"
            )
            self._mark_stream_authorization_unavailable(session, "Sentinel health probe returned 401")
            self._schedule_stream_reauthentication(session)
            return False
        if status == 0:
            self.logger.debug(f"{session.email} Sentinel health probe had no definitive response")
        elif status >= 400:
            self.logger.debug(f"{session.email} Sentinel health probe returned HTTP {status}")
        return True

    def _schedule_session_health_probe(self, session: Session) -> None:
        """Warm-check a newly ready account before a caller needs it."""
        if (
            getattr(self, "session_health_check_interval", 300) <= 0
            or not session.email
            or getattr(self, "_closing", False)
        ):
            return
        tasks = getattr(self, "_session_health_tasks", None)
        if tasks is None:
            tasks = self._session_health_tasks = {}
        task = tasks.get(session.email)
        if task and not task.done():
            return

        async def check_when_settled() -> None:
            try:
                # Let the login task finish bookkeeping before a rejected probe
                # schedules a fresh controlled login for the same account.
                await asyncio.sleep(3)
                await self._probe_stream_authorization(session, force=True)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                self.logger.debug(f"{session.email} background Sentinel health probe failed: {error}")
            finally:
                getattr(self, "_session_health_tasks", {}).pop(session.email, None)

        tasks[session.email] = asyncio.create_task(check_when_settled())

    async def _recover_expired_stream_session(self, session: Session) -> bool:
        """Refresh an expired browser session once before failing a fresh stream request."""
        if session.is_login_disabled():
            return False

        self.logger.warning(
            f"{session.email} stream authorization expired; refreshing the browser session once"
        )
        session.status = Status.Update.value
        try:
            # A fixed ``/api/auth/session`` navigation can be served from the
            # browser cache even after Sentinel has rejected its access token.
            # Use a one-off URL so this recovery obtains a genuinely current
            # session document, then rebuild the runtime bridge on the page
            # which will send the retry.
            refresh_url = f"{url_check}?_chatgptweb_refresh={uuid.uuid4().hex}"
            refreshed = await retry_keep_alive(
                session,
                refresh_url,
                self.storage,
                self.js,
                self.js_used,
                self.save_screen,
                self.logger,
            )
        except Exception as error:
            self.logger.warning(f"{session.email} stream authorization refresh failed: {error}")
            return False

        if (
            refreshed.status != Status.Ready.value
            or not refreshed.login_state
            or not refreshed.access_token
        ):
            self.logger.warning(
                f"{session.email} stream authorization refresh did not restore a ready session"
            )
            return False

        if refreshed.page:
            try:
                self.js_used = await flush_page(refreshed.page, self.js, self.js_used)
            except Exception as error:
                # The new token remains useful even when a page reload is
                # temporarily flaky; the retry below will still validate it.
                self.logger.warning(
                    f"{session.email} could not rebuild the browser bridge after authorization refresh: {error}"
                )
        return True

    def _mark_stream_authorization_unavailable(self, session: Session, error: Exception | str) -> None:
        """Avoid reporting a session as ready after two confirmed expired-token responses."""
        session.access_token = ""
        session.force_fresh_login = True
        session.mark_login_failure(
            kind=LoginFailureKind.Transient.value,
            details=f"stream authorization remained expired after refresh: {error}",
            cooldown_seconds=0,
            requires_reauthentication=True,
        )
        self.logger.warning(
            f"{session.email} stream authorization remained expired after refresh; scheduling relogin"
        )

    def _schedule_stream_reauthentication(self, session: Session) -> None:
        """Start the confirmed-expiry recovery immediately and expose it to the control UI."""
        if session.is_login_disabled() or not session.email:
            return
        tasks = getattr(self, "_control_login_tasks", None)
        if tasks is None:
            tasks = self._control_login_tasks = {}
        task = tasks.get(session.email)
        if task and not task.done():
            return
        task = asyncio.create_task(self._run_controlled_login(session))
        tasks[session.email] = task
        self._record_activity(
            session.email,
            "login_retry_started",
            "started automatic recovery after stream authorization expiry",
        )

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
                    const modelSlugs = [];
                    for (const key of Object.keys(localStorage)) {
                        if (!key.endsWith("/models") && !key.includes("/models")) continue;
                        try {
                            const cached = JSON.parse(localStorage.getItem(key));
                            const value = cached && cached.value && typeof cached.value === "object" ? cached.value : cached;
                            for (const category of Array.isArray(value && value.categories) ? value.categories : []) {
                                if (category && category.subscriptionLevel) modelSubscriptionLevels.push(category.subscriptionLevel);
                                if (category && category.defaultModel) modelSlugs.push(category.defaultModel);
                            }
                            for (const model of Array.isArray(value && value.models) ? value.models : []) {
                                if (model && model.slug) modelSlugs.push(model.slug);
                            }
                        } catch (_) {}
                    }
                    if (!response.ok || !contentType.includes("json")) {
                        return { status: response.status, payload: null, modelSubscriptionLevels, modelSlugs };
                    }
                    return { status: response.status, payload: await response.json(), modelSubscriptionLevels, modelSlugs };
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
            observed_models = result.get("modelSlugs")
            if isinstance(observed_models, list):
                session.observed_models = sorted({
                    model for model in observed_models
                    if isinstance(model, str) and model
                })
                session.observed_models_source = "localStorage:models"
                session.observed_models_observed_at = datetime.now()
        except Exception as error:
            self.logger.debug(f"{session.email} account plan refresh skipped: {error}")

    @staticmethod
    def _session_supports_model(session: Session, model: str, requires_paid: bool) -> bool:
        observed = supports_observed_model(getattr(session, "observed_models", []), model)
        if observed is not None:
            return observed
        if not requires_paid:
            return True
        return supports_paid_models(getattr(session, "account_plan", "unknown"), session.gptplus)

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
                "observed_models": list(getattr(session, "observed_models", [])),
                "observed_models_source": getattr(session, "observed_models_source", "unavailable"),
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
                                    contextWindow: model.context_window || model.contextWindow || model.context_length || null,
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
                                    contextWindow: model.context_window || model.contextWindow || model.context_length || null,
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
            if (!["https://chatgpt.com", "https://chat.openai.com"].includes(location.origin)) {
                throw new Error(`browser page is not on ChatGPT: ${location.href}`);
            }
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
                let streamTail = "";
                const remember = (text) => {
                    streamTail = (streamTail + text).slice(-65536);
                };
                if (!response.body) {
                    const text = await response.text();
                    remember(text);
                    await emit({ type: "chunk", text });
                    await emit({ type: "done", tail: streamTail });
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
                        remember(text);
                        await emit({ type: "chunk", text });
                    }
                }
                const tail = decoder.decode();
                if (tail) {
                    remember(tail);
                    await emit({ type: "chunk", text: tail });
                }
                await emit({ type: "done", tail: streamTail });
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
                for (let attempt = 0; attempt < 30; attempt += 1) {
                    for (const name of names) {
                        let provider = window;
                        for (const part of name.split(".")) {
                            provider = provider && provider[part];
                        }
                        if (provider && typeof provider[methodName] === "function") {
                            return await provider[methodName](requirements);
                        }
                    }
                    await new Promise((resolve) => setTimeout(resolve, 500));
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
        await self._reconcile_nonstream_final(session, msg_data)
        return msg_data

    async def _reconcile_nonstream_final(self, session: Session, msg_data: MsgData):
        """Prefer the settled conversation node for a completed non-stream request.

        The browser fetch bridge reads the whole SSE response, but some rich turns
        still publish a short intermediate content patch before the conversation
        mapping receives the final assistant text.  Normal ``continue_chat`` used
        to return that patch directly while ``continue_chat_stream`` reconciled it.
        Keep the two transports consistent without accepting a shorter stale node.
        """
        if not msg_data.conversation_id:
            return
        event = ChatStreamEvent(
            type="final",
            text=msg_data.msg_recv,
            message_id=msg_data.next_msg_id,
            conversation_id=msg_data.conversation_id,
            image_urls=msg_data.img_list.copy(),
            model=msg_data.model_used,
            usage=msg_data.usage.copy(),
            metadata=msg_data.response_metadata.copy(),
        )
        reconciled = await self._reconcile_stream_final(session, event, settle=True)
        if reconciled.text != event.text:
            self.logger.debug(
                f"{session.email} reconciled non-stream response "
                f"from {len(event.text)} to {len(reconciled.text)} characters"
            )
        self._apply_stream_event(msg_data, reconciled)

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
        pending_final: ChatStreamEvent | None = None
        stream_tail = ""
        loop = asyncio.get_running_loop()
        last_content_event_at = loop.time()
        last_status_event_at = last_content_event_at
        idle_timeout = max(0, msg_data.stream_idle_timeout_seconds)
        status_interval = max(0, msg_data.stream_status_interval_seconds)

        def should_emit(event: ChatStreamEvent) -> bool:
            if event.type != "final":
                return True
            if not (event.text or event.image_urls or event.files):
                return False
            signature = (event.text, event.message_id, event.conversation_id, tuple(event.image_urls))
            if signature in emitted_final_signatures:
                return False
            emitted_final_signatures.add(signature)
            return True

        def ready_events(events: List[ChatStreamEvent]) -> List[ChatStreamEvent]:
            nonlocal pending_final
            ready = []
            for event in events:
                if event.type == "final":
                    pending_final = event
                elif should_emit(event):
                    ready.append(event)
            return ready

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
                    for event in ready_events(events):
                        self._apply_stream_event(msg_data, event)
                        yield event
                    continue
                if payload.get("type") == "done":
                    done = True
                    stream_tail = str(payload.get("tail") or "")
                    for event in ready_events(decoder.close()):
                        self._apply_stream_event(msg_data, event)
                        yield event
                    break

            result = await stream_task
            if not isinstance(result, dict) or not result.get("ok"):
                raise RuntimeError(f"browser stream bridge returned invalid result: {result}")
            if not done:
                for event in ready_events(decoder.close()):
                    self._apply_stream_event(msg_data, event)
                    yield event
            pending_final = self._stream_final_candidate(
                msg_data,
                decoder.parser,
                pending_final,
            )
            if not pending_final:
                pending_final = await self._recover_new_stream_final(
                    session,
                    msg_data,
                    stream_tail,
                )
            if pending_final:
                settle_images = (
                    decoder.parser.image_gen
                    or IMAGE_GENERATION in msg_data.required_capabilities
                )
                final_event = await self._reconcile_stream_final(
                    session,
                    pending_final,
                    settle=settle_images,
                )
                # A sparse stream may reveal image processing only when the
                # conversation tree is queried. Probe every empty existing turn
                # once, then extend the wait only when upstream confirms it.
                if (
                    not settle_images
                    and final_event.metadata.get("image_generation_pending")
                    and not final_event.image_urls
                ):
                    final_event = await self._reconcile_stream_final(
                        session,
                        final_event,
                        settle=True,
                    )
                if self._is_image_generation_limit_response(final_event.text):
                    self._handle_image_generation_limit_response(
                        session,
                        msg_data,
                        final_event.text,
                        attempt=attempt,
                    )
                    return
                if (
                    final_event.image_urls
                    or final_event.metadata.get("image_generation_pending")
                    or any(
                        str(file.mime_type or "").lower().startswith("image/")
                        for file in final_event.files
                    )
                ):
                    self._observe_image_generation(msg_data)
                if should_emit(final_event):
                    self._apply_stream_event(msg_data, final_event)
                    yield final_event
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

    @staticmethod
    def _safe_output_download_url(url: str) -> bool:
        try:
            parsed = urlsplit(url)
            if (
                parsed.scheme.lower() != "https"
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.port not in {None, 443}
            ):
                return False
            try:
                return ipaddress.ip_address(parsed.hostname).is_global
            except ValueError:
                return True
        except ValueError:
            return False

    @staticmethod
    def _output_request_headers(url: str, access_token: str) -> Dict[str, str]:
        headers = {"accept": "*/*"}
        hostname = (urlsplit(url).hostname or "").lower()
        if hostname in {"chatgpt.com", "chat.openai.com"} and access_token:
            headers["authorization"] = f"Bearer {access_token}"
        return headers

    @staticmethod
    def _output_filename_from_headers(headers: Dict[str, str], fallback: str) -> str:
        disposition = next(
            (
                value
                for key, value in headers.items()
                if key.lower() == "content-disposition"
            ),
            "",
        )
        encoded = re.search(r"filename\*=UTF-8''(?P<name>[^;]+)", disposition, re.I)
        regular = re.search(r'filename="?(?P<name>[^";]+)', disposition, re.I)
        value = (
            unquote(encoded.group("name"))
            if encoded
            else regular.group("name") if regular else fallback
        )
        return safe_output_filename(value, fallback)

    async def _download_output_reference(
        self,
        session: Session,
        reference: OutputFileReference,
        conversation_id: str,
        *,
        allow_image: bool = False,
    ) -> IOFile | None:
        context = session.browser_contexts
        request_context = getattr(context, "request", None) if context else None
        if request_context is None:
            return None
        if reference.size is not None and reference.size > self.output_file_max_size:
            self.logger.warning(
                "%s output file %s exceeds the configured size limit",
                session.email,
                reference.name,
            )
            return None

        candidates: List[str] = []
        if reference.url and self._safe_output_download_url(reference.url):
            candidates.append(reference.url)
        file_id = reference.file_id.strip()
        if file_id and re.fullmatch(r"[A-Za-z0-9_-]{1,255}", file_id):
            encoded_id = quote(file_id, safe="")
            compact_id = "file_" + re.sub(
                r"[^A-Za-z0-9]",
                "",
                re.sub(r"^file[-_]", "", file_id),
            )
            conversation_query = quote(conversation_id, safe="")
            candidates.extend([
                (
                    f"https://chatgpt.com/backend-api/files/download/{encoded_id}"
                    f"?conversation_id={conversation_query}&inline=false"
                ),
                (
                    f"https://chatgpt.com/backend-api/files/download/{compact_id}"
                    f"?conversation_id={conversation_query}&inline=false"
                ),
                (
                    f"https://chatgpt.com/backend-api/files/{encoded_id}/download"
                    f"?conversation_id={conversation_query}"
                ),
            ])

        queue = list(dict.fromkeys(candidates))
        visited: set[str] = set()
        while queue:
            url = queue.pop(0)
            if url in visited:
                continue
            visited.add(url)
            try:
                response = await request_context.get(
                    url,
                    headers=self._output_request_headers(
                        url,
                        session.access_token,
                    ),
                    timeout=45_000,
                    fail_on_status_code=False,
                    max_redirects=0,
                )
            except Exception as error:
                self.logger.debug(
                    "%s output file candidate failed for %s: %s",
                    session.email,
                    reference.name,
                    error,
                )
                continue
            response_headers = dict(response.headers)
            if 300 <= response.status < 400:
                location = next(
                    (
                        value
                        for key, value in response_headers.items()
                        if key.lower() == "location"
                    ),
                    "",
                )
                redirect_url = urljoin(url, location)
                if (
                    location
                    and self._safe_output_download_url(redirect_url)
                    and redirect_url not in visited
                ):
                    queue.insert(0, redirect_url)
                continue
            if response.status < 200 or response.status >= 300:
                continue
            content_type = next(
                (
                    value.split(";", maxsplit=1)[0].strip().lower()
                    for key, value in response_headers.items()
                    if key.lower() == "content-type"
                ),
                "",
            )
            if content_type == "application/json":
                try:
                    payload = await response.json()
                except Exception:
                    continue
                if isinstance(payload, dict):
                    download_url = payload.get("download_url") or payload.get("url")
                    if (
                        isinstance(download_url, str)
                        and self._safe_output_download_url(download_url)
                        and download_url not in visited
                    ):
                        queue.insert(0, download_url)
                continue
            content_length = next(
                (
                    value
                    for key, value in response_headers.items()
                    if key.lower() == "content-length"
                ),
                "",
            )
            if content_length:
                try:
                    if int(content_length) > self.output_file_max_size:
                        return None
                except ValueError:
                    pass
            try:
                content = await response.body()
            except Exception:
                continue
            if not content or len(content) > self.output_file_max_size:
                return None
            mime_type = content_type or reference.mime_type or "application/octet-stream"
            if mime_type.startswith("image/"):
                if not allow_image:
                    # Generated images have a dedicated image result path.
                    return None
                return IOFile(
                    content=content,
                    name=self._output_filename_from_headers(
                        response_headers,
                        reference.name,
                    ),
                    mime_type=mime_type,
                )
            return IOFile(
                content=content,
                name=self._output_filename_from_headers(
                    response_headers,
                    reference.name,
                ),
                mime_type=mime_type,
            )
        return None

    async def _download_output_files(
        self,
        session: Session,
        metadata: Dict[str, Any],
        conversation_id: str,
    ) -> List[IOFile]:
        files: List[IOFile] = []
        total_size = 0
        for reference in output_file_references(metadata):
            if len(files) >= self.output_file_max_count:
                break
            if reference.mime_type.lower().startswith("image/"):
                continue
            file = await self._download_output_reference(
                session,
                reference,
                conversation_id,
            )
            if file is None:
                continue
            if total_size + len(file.content) > self.output_file_max_total_size:
                self.logger.warning(
                    "%s output files exceed the configured total size limit",
                    session.email,
                )
                break
            identity = (file.name, file.content)
            if any((item.name, item.content) == identity for item in files):
                continue
            files.append(file)
            total_size += len(file.content)
        return files

    @staticmethod
    def _generated_image_filename(url: str, index: int) -> str:
        query_name = parse_qs(urlsplit(url).query).get("fn", [""])[0]
        fallback = f"generated-image-{index}.png"
        return safe_output_filename(query_name, fallback)

    async def _download_generated_images(
        self,
        session: Session,
        image_urls: typing.Iterable[str],
        conversation_id: str,
    ) -> tuple[List[IOFile], set[str]]:
        """Fetch private generated-image URLs through the logged-in browser context."""
        files: List[IOFile] = []
        downloaded_urls: set[str] = set()
        total_size = 0
        for index, url in enumerate(dict.fromkeys(image_urls), start=1):
            if not isinstance(url, str) or not self._safe_output_download_url(url):
                continue
            file = await self._download_output_reference(
                session,
                OutputFileReference(
                    name=self._generated_image_filename(url, index),
                    url=url,
                    mime_type="image/png",
                ),
                conversation_id,
                allow_image=True,
            )
            if file is None:
                continue
            if total_size + len(file.content) > self.output_file_max_total_size:
                self.logger.warning(
                    "%s generated images exceed the configured total size limit",
                    session.email,
                )
                break
            files.append(file)
            downloaded_urls.add(url)
            total_size += len(file.content)
        return files, downloaded_urls

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
            if event.files:
                msg_data.download_file = event.files.copy()
            if (
                event.image_urls
                or event.metadata.get("image_generation_pending")
                or any(
                    str(file.mime_type or "").lower().startswith("image/")
                    for file in event.files
                )
            ):
                self._observe_image_generation(msg_data)
            if event.model:
                msg_data.model_used = event.model
            if event.usage:
                msg_data.usage = event.usage.copy()
            if event.metadata:
                msg_data.response_metadata = event.metadata.copy()
                conversation_title = str(
                    event.metadata.get("conversation_title") or ""
                ).strip()
                if conversation_title:
                    msg_data.title = conversation_title
        elif event.type == "image":
            msg_data.img_list = event.image_urls
            self._observe_image_generation(msg_data)
        elif event.type == "image_pending":
            self._observe_image_generation(msg_data)

    @staticmethod
    def _observe_image_generation(msg_data: MsgData) -> None:
        """Record image work from an upstream result, not only prompt hints."""
        msg_data.image_gen = True
        if IMAGE_GENERATION not in msg_data.required_capabilities:
            msg_data.required_capabilities.append(IMAGE_GENERATION)

    @staticmethod
    def _stream_final_candidate(
        msg_data: MsgData,
        parser: Any,
        pending_final: ChatStreamEvent | None,
    ) -> ChatStreamEvent | None:
        """Provide a conversation-tree fallback for image turns with sparse SSE.

        Image editing occasionally finishes in the upstream conversation mapping
        without emitting a textual or ``Processing image`` SSE event. Existing
        conversations still have an id, so reconcile their final node instead of
        reporting a generic empty-stream failure.
        """
        if pending_final:
            return pending_final
        conversation_id = str(
            getattr(parser, "conversation_id", "") or msg_data.conversation_id or ""
        )
        if not conversation_id:
            return None
        return ChatStreamEvent(
            type="final",
            text=str(getattr(parser, "text", "") or msg_data.msg_recv or ""),
            # ``next_msg_id`` points to the previous assistant node before an
            # empty SSE turn. Passing it would make reconciliation read stale
            # content instead of the new conversation current node.
            message_id=str(getattr(parser, "message_id", "") or ""),
            conversation_id=conversation_id,
            image_urls=list(getattr(parser, "image_urls", []) or msg_data.img_list),
            model=str(getattr(parser, "model", "") or msg_data.model_used or ""),
            usage=dict(getattr(parser, "usage", {}) or msg_data.usage),
            metadata=dict(getattr(parser, "metadata", {}) or msg_data.response_metadata),
        )

    async def _recover_new_stream_final(
        self,
        session: Session,
        msg_data: MsgData,
        stream_tail: str = "",
    ) -> ChatStreamEvent | None:
        """Recover a just-created conversation when its SSE body has no usable node.

        Some rich turns, especially image creation, can close their SSE response
        before exposing a normal assistant patch.  New conversations have no
        known id to reconcile, but their client-generated user message id is in
        the request payload and can identify the newest conversation safely.
        """
        if msg_data.conversation_id:
            return None
        try:
            payload = json.loads(msg_data.post_data or self._build_conversation_payload(msg_data))
            messages = payload.get("messages") if isinstance(payload, dict) else []
            user_message_id = str(messages[0].get("id") or "") if messages else ""
        except (TypeError, ValueError, AttributeError):
            user_message_id = ""
        page = session.page
        if not page or not user_message_id:
            return None
        if stream_tail:
            self.logger.debug(
                f"{session.email} received an unparsed stream for a new conversation; "
                f"recovering by client message id {user_message_id}"
            )
        for attempt in range(6):
            try:
                response = await page.evaluate(
                    """async ({ messageId, accessToken }) => {
                        const headers = { accept: 'application/json' };
                        if (accessToken) headers.authorization = `Bearer ${accessToken}`;
                        const listPaths = [
                            '/backend-api/conversations?offset=0&limit=20&order=updated',
                            '/api/backend-api/conversations?offset=0&limit=20&order=updated',
                        ];
                        const detailPaths = (id) => [
                            `/backend-api/conversation/${encodeURIComponent(id)}`,
                            `/api/backend-api/conversation/${encodeURIComponent(id)}`,
                        ];
                        const assistant = (node) => Boolean(node && node.message && node.message.author
                            && node.message.author.role === 'assistant');
                        for (const listPath of listPaths) {
                            try {
                                const listResponse = await fetch(listPath, { credentials: 'include', headers });
                                if (!listResponse.ok) continue;
                                const listed = await listResponse.json();
                                const items = Array.isArray(listed && listed.items)
                                    ? listed.items : (Array.isArray(listed) ? listed : []);
                                for (const item of items) {
                                    const conversationId = item && (item.id || item.conversation_id);
                                    if (typeof conversationId !== 'string' || !conversationId) continue;
                                    let conversation = null;
                                    for (const detailPath of detailPaths(conversationId)) {
                                        try {
                                            const detailResponse = await fetch(detailPath, { credentials: 'include', headers });
                                            if (detailResponse.ok) {
                                                conversation = await detailResponse.json();
                                                break;
                                            }
                                        } catch (_) {}
                                    }
                                    const mapping = conversation && conversation.mapping;
                                    if (!mapping || typeof mapping !== 'object') continue;
                                    const nodes = Object.values(mapping);
                                    const userNode = nodes.find((node) => node && node.message && node.message.id === messageId);
                                    if (!userNode) continue;
                                    const branch = [];
                                    const seen = new Set();
                                    let branchId = conversation.current_node;
                                    while (branchId && mapping[branchId] && !seen.has(branchId)) {
                                        seen.add(branchId);
                                        branch.push(mapping[branchId]);
                                        branchId = mapping[branchId].parent;
                                    }
                                    branch.reverse();
                                    const userIndex = branch.findIndex((node) => node === userNode
                                        || (node && node.message && node.message.id === messageId));
                                    const afterUser = userIndex >= 0 ? branch.slice(userIndex + 1) : [];
                                    const assistantNode = [...afterUser].reverse().find(assistant);
                                    const imageUrls = [];
                                    let imagePending = false;
                                    for (const node of afterUser) {
                                        const metadata = node && node.message && node.message.metadata || {};
                                        const results = metadata.image_results;
                                        if (Array.isArray(results)) {
                                            for (const image of results) {
                                                const url = image && (image.content_url || image.download_url || image.url);
                                                if (typeof url === 'string' && url && !imageUrls.includes(url)) imageUrls.push(url);
                                            }
                                        }
                                        if (metadata.ui_card_title === 'Processing image') imagePending = true;
                                    }
                                    const message = assistantNode && assistantNode.message;
                                    const parts = message && message.content && message.content.parts;
                                    return {
                                        conversationId,
                                        messageId: message && message.id || '',
                                        text: Array.isArray(parts) && typeof parts[0] === 'string' ? parts[0] : '',
                                        imageUrls,
                                        imagePending,
                                        metadata: message && message.metadata || {},
                                    };
                                }
                            } catch (_) {}
                        }
                        return null;
                    }""",
                    {"messageId": user_message_id, "accessToken": session.access_token},
                )
            except Exception as error:
                self.logger.debug(f"{session.email} new conversation recovery was unavailable: {error}")
                return None
            if isinstance(response, dict) and response.get("conversationId"):
                metadata = dict(response.get("metadata") or {})
                if response.get("imagePending") and not response.get("imageUrls"):
                    metadata["image_generation_pending"] = True
                return ChatStreamEvent(
                    type="final",
                    text=str(response.get("text") or ""),
                    conversation_id=str(response["conversationId"]),
                    message_id=str(response.get("messageId") or ""),
                    image_urls=[
                        str(url) for url in response.get("imageUrls", [])
                        if isinstance(url, str) and url
                    ],
                    metadata=metadata,
                )
            if attempt + 1 < 6:
                await asyncio.sleep(0.8)
        return None

    async def _reconcile_stream_final(
        self,
        session: Session,
        event: ChatStreamEvent,
        *,
        settle: bool = False,
    ) -> ChatStreamEvent:
        """Read the final assistant node after an SSE response completes.

        Search and rich-content turns can revise previously emitted text patches.
        The conversation node is the browser's final canonical message, while the
        stream remains the low-latency source for intermediate events.
        """
        if not event.conversation_id:
            return event
        page = session.page
        if not page:
            return event
        attempts = 20 if settle else 1
        best_event = event
        for attempt in range(attempts):
            try:
                response = await page.evaluate(
                """async ({ conversationId, messageId, accessToken }) => {
                    const headers = { accept: 'application/json' };
                    if (accessToken) headers.authorization = `Bearer ${accessToken}`;
                    const paths = [
                        `/backend-api/conversation/${encodeURIComponent(conversationId)}`,
                        `/api/backend-api/conversation/${encodeURIComponent(conversationId)}`,
                    ];
                    for (const path of paths) {
                        try {
                            const result = await fetch(path, {
                                credentials: 'include',
                                headers,
                            });
                            if (!result.ok) continue;
                            const conversation = await result.json();
                            const mapping = conversation && conversation.mapping;
                            if (!mapping || typeof mapping !== 'object') continue;
                            const nodes = Object.values(mapping);
                            let node = messageId ? mapping[messageId] : null;
                            const isAssistantNode = (item) => Boolean(
                                item && item.message && item.message.author
                                && item.message.author.role === 'assistant'
                            );
                            if (!isAssistantNode(node) && conversation.current_node) {
                                node = mapping[conversation.current_node] || null;
                            }
                            if (!isAssistantNode(node)) {
                                node = [...nodes].reverse().find((item) =>
                                    isAssistantNode(item)
                                );
                            }
                            const message = node && node.message;
                            if (!message) continue;
                            const parts = message && message.content && message.content.parts;
                            const imageUrls = [];
                            let imagePending = false;
                            const addImageResults = (value) => {
                                if (!Array.isArray(value)) return;
                                for (const image of value) {
                                    if (!image || typeof image !== 'object') continue;
                                    const url = image.content_url || image.download_url || image.url;
                                    if (typeof url === 'string' && url && !imageUrls.includes(url)) {
                                        imageUrls.push(url);
                                    }
                                }
                            };
                            // Object value order is not conversation order. Restrict
                            // rich results to the active branch so an old image cannot
                            // be reused for the current assistant response.
                            const branch = [];
                            const seen = new Set();
                            let branchId = (conversation.current_node && mapping[conversation.current_node])
                                ? conversation.current_node
                                : (node && node.id) || messageId;
                            while (branchId && mapping[branchId] && !seen.has(branchId)) {
                                seen.add(branchId);
                                branch.push(mapping[branchId]);
                                branchId = mapping[branchId].parent;
                            }
                            branch.reverse();
                            let latestUserIndex = -1;
                            for (let index = branch.length - 1; index >= 0; index -= 1) {
                                const candidate = branch[index] && branch[index].message;
                                if (candidate && candidate.author && candidate.author.role === 'user') {
                                    latestUserIndex = index;
                                    break;
                                }
                            }
                            for (const candidateNode of branch.slice(latestUserIndex + 1)) {
                                const candidate = candidateNode && candidateNode.message;
                                if (!candidate) continue;
                                const candidateMetadata = candidate.metadata || {};
                                addImageResults(candidateMetadata.image_results);
                                if (candidateMetadata.ui_card_title === 'Processing image') {
                                    imagePending = true;
                                }
                            }
                            return {
                                text: Array.isArray(parts) && typeof parts[0] === 'string'
                                    ? parts[0]
                                    : '',
                                messageId: message.id || messageId || '',
                                metadata: message.metadata || {},
                                imageUrls,
                                imagePending,
                                title: typeof conversation.title === 'string'
                                    ? conversation.title
                                    : '',
                                createTime: conversation.create_time || '',
                                updateTime: conversation.update_time || '',
                            };
                        } catch (_) {
                            // Try the next browser-observed route.
                        }
                    }
                    return null;
                }""",
                {
                    "conversationId": event.conversation_id,
                    "messageId": event.message_id,
                    "accessToken": session.access_token,
                },
                )
            except Exception as error:
                self.logger.debug(f"{session.email} stream final reconciliation was unavailable: {error}")
                break

            if isinstance(response, dict) and isinstance(response.get("text"), str):
                text = response["text"]
                metadata = best_event.metadata.copy()
                if isinstance(response.get("metadata"), dict):
                    metadata.update(response["metadata"])
                conversation_title = str(response.get("title") or "").strip()
                if conversation_title:
                    metadata["conversation_title"] = conversation_title
                if response.get("createTime") not in (None, ""):
                    metadata["conversation_created_at"] = response["createTime"]
                if response.get("updateTime") not in (None, ""):
                    metadata["conversation_updated_at"] = response["updateTime"]
                image_urls: list[str] = []
                for image_url in response.get("imageUrls", []):
                    if isinstance(image_url, str) and image_url and image_url not in image_urls:
                        image_urls.append(image_url)
                if response.get("imagePending") and not image_urls:
                    metadata["image_generation_pending"] = True
                elif image_urls:
                    metadata.pop("image_generation_pending", None)
                else:
                    metadata.pop("image_generation_pending", None)
                # A mapping node may briefly lag behind the final SSE patch.
                # Keep the longer text while always accepting the canonical
                # node metadata, which may contain generated-file references.
                best_event = ChatStreamEvent(
                    type="final",
                    text=(
                        text
                        if text and len(text) >= len(best_event.text)
                        else best_event.text
                    ),
                    message_id=str(
                        response.get("messageId")
                        or best_event.message_id
                    ),
                    conversation_id=event.conversation_id,
                    image_urls=image_urls,
                    model=best_event.model,
                    usage=best_event.usage.copy(),
                    metadata=metadata,
                    files=best_event.files.copy(),
                    raw=best_event.raw,
                )
                if image_urls or (not settle and len(text) > len(event.text)):
                    break

            if attempt + 1 < attempts:
                await asyncio.sleep(1.5 if settle else 0.6)
        if (
            settle
            and not best_event.image_urls
            and best_event.metadata.get("image_generation_pending")
        ):
            best_event.image_urls = await self._generated_image_urls_from_bootstrap(
                session,
                best_event.conversation_id,
            )
        if best_event.image_urls:
            best_event.metadata.pop("image_generation_pending", None)
            generated_images, downloaded_urls = await self._download_generated_images(
                session,
                best_event.image_urls,
                best_event.conversation_id,
            )
            if generated_images:
                existing = {(file.name, file.content) for file in best_event.files}
                best_event.files.extend(
                    file
                    for file in generated_images
                    if (file.name, file.content) not in existing
                )
                best_event.image_urls = [
                    url for url in best_event.image_urls if url not in downloaded_urls
                ]
                best_event.metadata["generated_image_count"] = len(generated_images)
        if not best_event.files:
            best_event.files = await self._download_output_files(
                session,
                best_event.metadata,
                best_event.conversation_id,
            )
        return best_event

    async def _generated_image_urls_from_bootstrap(
        self,
        session: Session,
        conversation_id: str,
    ) -> List[str]:
        """Resolve a completed image task when SSE omitted its final asset URL."""
        page = session.page
        if not page or not conversation_id:
            return []
        for attempt in range(5):
            try:
                result = await page.evaluate(
                """async ({ conversationId, accessToken }) => {
                    const headers = { accept: 'application/json' };
                    if (accessToken) headers.authorization = `Bearer ${accessToken}`;
                    const bootstrap = await fetch('/backend-api/images/bootstrap', {
                        credentials: 'include',
                        headers,
                    });
                    if (!bootstrap.ok) return { error: `bootstrap ${bootstrap.status}` };
                    const payload = await bootstrap.json();
                    const direct = payload && (payload.download_url || payload.content_url);
                    if (typeof direct === 'string' && direct) return { urls: [direct] };
                    const thumbnail = payload && payload.thumbnail_url;
                    if (typeof thumbnail !== 'string' || !thumbnail) return { urls: [] };
                    const match = thumbnail.match(/(?:file[_-])([A-Za-z0-9-]+)/);
                    if (!match) return { urls: [] };
                    const compact = `file_${match[1].replace(/-/g, '')}`;
                    const path = `/backend-api/files/download/${compact}`
                        + `?conversation_id=${encodeURIComponent(conversationId)}&inline=false`;
                    const download = await fetch(path, {
                        credentials: 'include',
                        headers,
                    });
                    if (!download.ok) return { error: `download ${download.status}` };
                    const resolved = await download.json();
                    const url = resolved && resolved.download_url;
                    return { urls: typeof url === 'string' && url ? [url] : [] };
                }""",
                {
                    "conversationId": conversation_id,
                    "accessToken": session.access_token,
                    },
                )
            except Exception as error:
                self.logger.debug(
                    "%s generated image bootstrap reconciliation failed: %s",
                    session.email,
                    error,
                )
                return []
            if isinstance(result, dict):
                urls = [
                    value
                    for value in result.get("urls", [])
                    if isinstance(value, str) and value
                ]
                if urls:
                    return urls
                if result.get("error") and attempt == 4:
                    self.logger.warning(
                        "%s generated image bootstrap did not resolve an asset: %s",
                        session.email,
                        result["error"],
                    )
            if attempt < 4:
                await asyncio.sleep(2)
        return []

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
                    self._clear_chat_rate_limit(session)
                    msg_data.from_email = session.email
                    if session.login_state is False:
                        session.login_state = True
                    if msg_data.persist_history:
                        await self.save_chat(msg_data, context_num)
                return msg_data
            except Exception as e:
                error_text = str(e)
                if self._is_upstream_rate_limit_error(error_text):
                    self._handle_upstream_rate_limit(
                        session,
                        msg_data,
                        error_text,
                        attempt=attempt,
                    )
                    return msg_data
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
                        response_text = await res.text()
                        self.logger.warning(f"download msg may json_wss,and error: {e} {response_text},line number {exc_traceback.tb_lineno}") # type: ignore
                        if self._is_upstream_rate_limit_error(response_text):
                            self._handle_upstream_rate_limit(
                                session,
                                msg_data,
                                response_text,
                                attempt=attempt,
                            )
                            raise RuntimeError(f"upstream chat rate limit: {response_text[:500]}") from e
                        if "token_expired" in response_text:
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
                            message=f"{e} {response_text}",
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
                    msg_data.response_metadata["conversation_title"] = msg_data.title
                if res_json.get("create_time") not in (None, ""):
                    msg_data.response_metadata["conversation_created_at"] = (
                        res_json["create_time"]
                    )
                if res_json.get("update_time") not in (None, ""):
                    msg_data.response_metadata["conversation_updated_at"] = (
                        res_json["update_time"]
                    )
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
            if msg_data.img_list:
                generated_images, downloaded_urls = await self._download_generated_images(
                    session,
                    msg_data.img_list,
                    msg_data.conversation_id,
                )
                if generated_images:
                    existing = {(file.name, file.content) for file in msg_data.download_file}
                    msg_data.download_file.extend(
                        file
                        for file in generated_images
                        if (file.name, file.content) not in existing
                    )
                    msg_data.img_list = [
                        url for url in msg_data.img_list if url not in downloaded_urls
                    ]
            if not msg_data.download_file:
                msg_data.download_file = await self._download_output_files(
                    session,
                    msg_data.response_metadata,
                    msg_data.conversation_id,
                )
            self._clear_chat_rate_limit(session)
            if session.login_state is False:
                session.login_state = True
            if msg_data.persist_history:
                await self.save_chat(msg_data, context_num)
        return msg_data

        
    async def save_chat(self, msg_data: MsgData, context_num: str):
        """save chat file
        保存聊天文件"""
        lock = await self._conversation_lock(msg_data.conversation_id)
        async with lock:
            history = self.storage.load_conversation(msg_data.conversation_id)
            now = datetime.now().isoformat()
            if not history["created_at"]:
                history["created_at"] = now
            history["account"] = context_num
            conversation_title = str(
                msg_data.title
                or msg_data.response_metadata.get("conversation_title")
                or ""
            ).strip()
            if conversation_title:
                history["title"] = conversation_title
            upstream_created_at = msg_data.response_metadata.get(
                "conversation_created_at"
            )
            if upstream_created_at not in (None, ""):
                history["upstream_created_at"] = upstream_created_at
            upstream_updated_at = msg_data.response_metadata.get(
                "conversation_updated_at"
            )
            if upstream_updated_at not in (None, ""):
                history["upstream_updated_at"] = upstream_updated_at
            message = {
                "input": msg_data.msg_send,
                "output": msg_data.msg_recv,
                "type": msg_data.msg_type,
                "next_msg_id": msg_data.next_msg_id,
                "created_at": now,
            }
            if msg_data.p_msg_id:
                message["p_msg_id"] = msg_data.p_msg_id
            history["messages"].append(message)
            history["updated_at"] = now
            self.storage.save_conversation(history)
            self.storage.update_conversation_index(
                msg_data.conversation_id,
                context_num,
                history["created_at"],
                now,
                len(history["messages"]),
                client_id=msg_data.client_id,
            )

    async def load_chat(self, msg_data: MsgData):
        """Load a conversation in the shape required by the legacy MsgData bridge."""
        history = self.storage.load_conversation(msg_data.conversation_id)
        return {
            "conversation_id": history["conversation_id"],
            "message": history["messages"],
        }
    def sleep(self, sc: float | int):
        self.browser_event_loop.run_until_complete(asyncio.sleep(sc))

    def ask(self, msg_data: MsgData) -> MsgData:
        '''Concurrency processing is not implemented and it is not recommended to use this|
        未作并发处理，不推荐使用这个
        '''
        while not self.manage["start"]:
            self.sleep(0.5)
        required_capabilities = self._required_capabilities(msg_data)
        sessions = filter(
            lambda s: (
                s.type != "script"
                and s.login_state is True
                and not s.is_login_disabled()
                and not s.is_chat_rate_limited()
                and self._session_supports_capabilities(
                    s,
                    required_capabilities,
                )
            ),
            sorted(self.Sessions, key=lambda s: s.last_active)
        )
        session: Session = next(sessions, None) # type: ignore

        if not session:
            raise Exception("Not Found Page")
        msg_data = self.browser_event_loop.run_until_complete(self.send_msg(msg_data, session)) # type: ignore
        
        return msg_data

    async def _prepare_chat_session(self, msg_data: MsgData) -> Optional[Session]:
        """Select and reserve the session that should handle this request."""
        required_capabilities = self._required_capabilities(msg_data)
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

        if msg_data.conversation_id and msg_data.client_id and msg_data.enforce_client_ownership:
            owner = self.storage.conversation_client_id(msg_data.conversation_id)
            if owner and owner != msg_data.client_id:
                msg_data.add_error(
                    kind="conversation_client_mismatch",
                    message="this conversation belongs to another API client",
                )
                self.logger.warning(msg_data.error_info)
                return None
            if not owner and self.storage.conversation_exists(msg_data.conversation_id):
                msg_data.add_error(
                    kind="conversation_client_unbound",
                    message="this legacy conversation is not assigned to an API client",
                )
                self.logger.warning(msg_data.error_info)
                return None

        session: Session = Session(status=Status.Working.value)
        if not msg_data.conversation_id:
            session_list = [
                s for s in self.Sessions
                if s.type != "script" and self._session_supports_model(
                    s, msg_data.gpt_model, msg_data.gpt_plus,
                )
            ]
            if session_list == [] and msg_data.gpt_plus:
                msg_data.add_error(
                    kind="no_plus_account",
                    message="no account is known to support the requested paid model",
                )
                self.logger.error(msg_data.error_info)
                return None
            elif msg_data.gpt_model in all_models_values():
                pass
            elif msg_data.gpt_plus:
                pass
            else:
                self.logger.warning(f"unknown model: {msg_data.gpt_model} ,try to use it")

            wait_ready_seconds = 0
            while not session or session.status == Status.Working.value:
                filtered_sessions = [
                    s for s in session_list
                    if (
                        s.type != "script"
                        and s.login_state is True
                        and s.status == Status.Ready.value
                        and not s.is_login_disabled()
                        and not s.is_chat_rate_limited()
                        and self._session_supports_capabilities(
                            s,
                            required_capabilities,
                        )
                    )
                ]
                if filtered_sessions:
                    # A new logical conversation may use any ready account.
                    # Continuations remain pinned to their conversation owner
                    # below. New requests may use either the default LRU policy
                    # or a rolling-window balanced policy.
                    session = self._select_new_conversation_session(filtered_sessions)
                else:
                    pending_sessions = [
                        s for s in session_list
                        if (
                            s.type != "script"
                            and s.status in (
                                Status.Login.value,
                                Status.Update.value,
                                Status.Recovering.value,
                                Status.Working.value,
                            )
                            and not s.is_login_disabled()
                            and self._session_supports_capabilities(
                                s,
                                required_capabilities,
                            )
                        )
                    ]
                    rate_limited_sessions = [
                        s for s in session_list
                        if s.type != "script" and s.is_chat_rate_limited()
                    ]
                    if rate_limited_sessions and len(rate_limited_sessions) == len(session_list):
                        retry_after = min(
                            max(0, int((s.chat_rate_limited_until - datetime.now()).total_seconds()))
                            for s in rate_limited_sessions
                            if s.chat_rate_limited_until
                        )
                        msg_data.add_error(
                            kind="rate_limited",
                            message=f"all eligible accounts are rate limited; retry after about {retry_after} seconds",
                            retryable=True,
                        )
                        self.logger.warning(msg_data.error_info)
                        return None
                    capability_candidates = [
                        s for s in session_list
                        if (
                            s.type != "script"
                            and not s.is_login_disabled()
                            and not s.is_chat_rate_limited()
                        )
                    ]
                    capability_eligible_sessions = [
                        s for s in capability_candidates
                        if self._session_supports_capabilities(
                            s,
                            required_capabilities,
                        )
                    ]
                    if (
                        required_capabilities
                        and capability_candidates
                        and not capability_eligible_sessions
                    ):
                        self._add_capability_unavailable_error(
                            msg_data,
                            session_list,
                            required_capabilities,
                        )
                        self.logger.warning(msg_data.error_info)
                        return None
                    if not pending_sessions:
                        msg_data.add_error(
                            kind="no_available_session",
                            message="no login-capable session is available",
                        )
                        self.logger.error(msg_data.error_info)
                        return None

                await asyncio.sleep(0.5)
                wait_ready_seconds += 0.5
                if session.status == Status.Ready.value:
                    break
                if wait_ready_seconds >= self.ready_timeout:
                    recovering = any(
                        item.status in (Status.Login.value, Status.Update.value, Status.Recovering.value)
                        or (
                            (task := getattr(self, "_control_login_tasks", {}).get(item.email))
                            and not task.done()
                        )
                        for item in pending_sessions
                    )
                    msg_data.add_error(
                        kind="session_recovery_timeout" if recovering else "no_ready_session",
                        message=f"no ready session found within {self.ready_timeout} seconds",
                    )
                    self.logger.error(msg_data.error_info)
                    return None
        else:
            account = msg_data.account_hint or self.storage.conversation_owner(msg_data.conversation_id)
            session = next((item for item in self.Sessions if item.email == account), None) # type: ignore
            if not session:
                msg_data.add_error(
                    kind="conversation_session_missing",
                    message="the account associated with this conversation is not configured",
                )
                self.logger.error(msg_data.error_info)
                return None
            if session.is_login_disabled():
                msg_data.add_error(
                    kind="conversation_session_stopped",
                    message="the account associated with this conversation is not available",
                    session_email=session.email,
                )
                return None
            if session.is_chat_rate_limited():
                retry_after = max(
                    0,
                    int((session.chat_rate_limited_until - datetime.now()).total_seconds()),
                ) if session.chat_rate_limited_until else 0
                msg_data.add_error(
                    kind="conversation_rate_limited",
                    message=f"the account associated with this conversation is rate limited; retry after about {retry_after} seconds",
                    retryable=True,
                    session_email=session.email,
                )
                return None
            if not self._session_supports_capabilities(
                session,
                required_capabilities,
            ):
                self._add_capability_unavailable_error(
                    msg_data,
                    [session],
                    required_capabilities,
                    conversation=True,
                )
                return None
            wait_ready_seconds = 0
            while session.status != Status.Ready.value:
                await asyncio.sleep(0.5)
                wait_ready_seconds += 0.5
                if session.status == Status.Ready.value:
                    break
                if wait_ready_seconds >= self.ready_timeout:
                    task = getattr(self, "_control_login_tasks", {}).get(session.email)
                    recovering = (
                        session.status in (Status.Login.value, Status.Update.value, Status.Recovering.value)
                        or (task and not task.done())
                    )
                    msg_data.add_error(
                        kind=(
                            "conversation_session_recovery_timeout"
                            if recovering else "conversation_session_not_ready"
                        ),
                        message=f"conversation account is not ready within {self.ready_timeout} seconds",
                        session_email=session.email,
                    )
                    self.logger.error(msg_data.error_info)
                    return None

            if not session.email:
                msg_data.add_error(
                    kind="session_not_found",
                    message="Not session found,please check your conversation_id input",
                )
                self.logger.error(msg_data.error_info)
                return None

            msg_data.account_hint = session.email

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

        is_new_conversation = not msg_data.conversation_id
        if is_new_conversation:
            # Reserve before an awaited runtime check so concurrent new
            # requests cannot briefly select the same ready account.
            session.status = Status.Working.value

        if not await self._ensure_session_runtime(session):
            if is_new_conversation and session.status == Status.Working.value:
                session.status = Status.Ready.value
            msg_data.add_error(
                kind="session_runtime_unavailable",
                message=f"session runtime is not available: {session.email}",
                session_email=session.email,
            )
            self.logger.error(msg_data.error_info)
            return None

        if is_new_conversation:
            self._record_new_conversation_assignment(session)
        session.last_active = datetime.now()
        session.status = Status.Working.value
        self.logger.debug(f"session {session.email} begin work")
        return session

    async def assert_conversation_client_access(self, conversation_id: str, client_id: str) -> None:
        """Reject remote reads of conversations owned by another client key."""
        if not conversation_id or not client_id:
            return
        owner = self.storage.conversation_client_id(conversation_id)
        if owner and owner != client_id:
            raise PermissionError("this conversation belongs to another API client")
        if not owner and self.storage.conversation_exists(conversation_id):
            raise PermissionError("this legacy conversation is not assigned to an API client")

    def _request_scheduler_capacity(self) -> int:
        """Use the configured account pool as the shared admission capacity."""
        sessions = getattr(self, "Sessions", [])
        return max(1, sum(1 for session in sessions if session.type != "script"))

    def _scheduler(self) -> RequestScheduler:
        scheduler = getattr(self, "_request_scheduler", None)
        if scheduler is None:
            scheduler = RequestScheduler(self._request_scheduler_capacity)
            self._request_scheduler = scheduler
        return scheduler

    async def request_scheduler_status(self) -> Dict[str, int]:
        """Expose coarse queue state without any prompt or client identifiers."""
        return await self._scheduler().snapshot()

    async def _acquire_request_lease(self, msg_data: MsgData) -> RequestLease | None:
        try:
            return await self._scheduler().acquire(
                priority=msg_data.request_priority,
                client_id=msg_data.client_id or "local",
                timeout_seconds=getattr(self, "request_queue_timeout_seconds", 120),
            )
        except TimeoutError:
            msg_data.add_error(
                kind="request_queue_timeout",
                message="the shared request queue did not admit this request before its timeout",
                retryable=True,
            )
            self.logger.warning(msg_data.error_info)
            return None

    async def continue_chat(self, msg_data: MsgData) -> MsgData:
        """Queue a buffered request before entering the browser/account runtime."""
        lease = await self._acquire_request_lease(msg_data)
        if not lease:
            return msg_data
        try:
            return await self._continue_chat_direct(msg_data)
        finally:
            await lease.release()

    async def _continue_chat_direct(self, msg_data: MsgData) -> MsgData:
        """
        Message processing entry, please use this
        """
        session = await self._prepare_chat_session(msg_data)
        if not session:
            error = msg_data.error_list[-1] if msg_data.error_list else {}
            self._record_activity(
                str(error.get("session_email") or msg_data.account_hint or ""),
                "chat_failed",
                f"request rejected: {error.get('kind') or 'session_unavailable'}",
                severity="error",
                details={"error_kind": str(error.get("kind") or "session_unavailable")},
            )
            return msg_data

        msg_data.request_started_at = time.monotonic()
        msg_data.request_upload_count = len(msg_data.upload_file)
        msg_data.request_image_upload_count = sum(
            1
            for file in msg_data.upload_file
            if (
                file.content_type == "image_asset_pointer"
                or str(file.mime_type or "").lower().startswith("image/")
            )
        )
        msg_data.request_file_upload_count = (
            msg_data.request_upload_count - msg_data.request_image_upload_count
        )
        self._record_activity(
            session.email,
            "chat_started",
            (
                "request accepted"
                + (
                    f"; capabilities: {', '.join(msg_data.required_capabilities)}"
                    if msg_data.required_capabilities else ""
                )
            ),
            details={
                "uploads": msg_data.request_upload_count,
                "new_conversation": not bool(msg_data.conversation_id),
            },
        )
        if msg_data.request_upload_count:
            self._record_activity(
                session.email,
                "attachment_upload_started",
                f"{msg_data.request_upload_count} attachment(s)",
                details={"count": msg_data.request_upload_count},
            )
        if IMAGE_GENERATION in msg_data.required_capabilities:
            self._record_activity(
                session.email,
                "image_generation_started",
                "image generation requested",
            )
        try:
            msg_data = await asyncio.wait_for(self.send_msg(msg_data, session), timeout=180)
            if (
                IMAGE_GENERATION in msg_data.required_capabilities
                and self._is_image_generation_limit_response(msg_data.msg_recv)
            ):
                self._handle_image_generation_limit_response(
                    session,
                    msg_data,
                    msg_data.msg_recv,
                    attempt=1,
                )
            if any(
                error.get("kind") == "capability_rate_limited"
                for error in msg_data.error_list
            ):
                raise RuntimeError(msg_data.error_list[-1]["message"])
            if (
                IMAGE_GENERATION in msg_data.required_capabilities
                and not self._generated_image_count(msg_data)
            ):
                msg_data.add_error(
                    kind="image_generation_no_result",
                    message="upstream image generation completed without a retrievable image",
                    retryable=True,
                    session_email=session.email,
                )
                raise RuntimeError(msg_data.error_list[-1]["message"])
            if not msg_data.status:
                error_kind = (
                    "image_generation_no_result"
                    if IMAGE_GENERATION in msg_data.required_capabilities
                    else "stream_no_final_result"
                )
                msg_data.add_error(
                    kind=error_kind,
                    message=(
                        "upstream image generation completed without a retrievable image"
                        if error_kind == "image_generation_no_result"
                        else "upstream stream completed without a final result"
                    ),
                    retryable=True,
                    session_email=session.email,
                )
                raise RuntimeError(msg_data.error_list[-1]["message"])

            if msg_data.status:
                self._bind_conversation_client(msg_data, session)
            session.status = Status.Ready.value
            self._record_usage(session, msg_data)
            self._record_capability_usage(session, msg_data)
            duration_ms = max(
                0,
                int((time.monotonic() - msg_data.request_started_at) * 1000),
            )
            if msg_data.request_upload_count:
                self._record_activity(
                    session.email,
                    "attachment_upload_completed",
                    f"{msg_data.request_upload_count} attachment(s)",
                    details={
                        "count": msg_data.request_upload_count,
                        "duration_ms": duration_ms,
                    },
                )
            if IMAGE_GENERATION in msg_data.required_capabilities:
                self._record_activity(
                    session.email,
                    "image_generation_completed",
                    f"{self._generated_image_count(msg_data)} image(s)",
                    details={
                        "count": self._generated_image_count(msg_data),
                        "duration_ms": duration_ms,
                    },
                )
        except TimeoutError:
            msg_data.add_error(
                kind="continue_chat_timeout",
                message=f"send msg {msg_data.msg_send} time out",
                retryable=True,
                session_email=session.email,
            )
            self.logger.warning(msg_data.error_info)
            self._record_activity(
                session.email,
                "chat_failed",
                "request failed: continue_chat_timeout",
                severity="error",
                details={
                    "error_kind": "continue_chat_timeout",
                    "duration_ms": max(
                        0,
                        int((time.monotonic() - msg_data.request_started_at) * 1000),
                    ),
                },
            )
            if msg_data.request_upload_count:
                self._record_activity(
                    session.email,
                    "attachment_upload_failed",
                    "attachment request failed with its chat turn",
                    severity="error",
                    details={"count": msg_data.request_upload_count},
                )
            if IMAGE_GENERATION in msg_data.required_capabilities:
                self._record_activity(
                    session.email,
                    "image_generation_failed",
                    "image generation timed out",
                    severity="error",
                )
        except Exception as e:
            if not msg_data.error_info:
                a, b, exc_traceback = sys.exc_info()
                msg_data.add_error(
                    kind="continue_chat_error",
                    message=f"send msg {msg_data.msg_send} error:{e}",
                    session_email=session.email,
                    line=exc_traceback.tb_lineno, # type: ignore
                )
            self.logger.error(msg_data.error_info)
            error_kind = str(
                (msg_data.error_list[-1] if msg_data.error_list else {}).get("kind")
                or "continue_chat_error"
            )
            self._record_activity(
                session.email,
                "chat_failed",
                f"request failed: {error_kind}",
                severity="error",
                details={
                    "error_kind": error_kind,
                    "duration_ms": max(
                        0,
                        int((time.monotonic() - msg_data.request_started_at) * 1000),
                    ),
                },
            )
            if msg_data.request_upload_count:
                self._record_activity(
                    session.email,
                    "attachment_upload_failed",
                    "attachment request failed with its chat turn",
                    severity="error",
                    details={"count": msg_data.request_upload_count},
                )
            if IMAGE_GENERATION in msg_data.required_capabilities:
                self._record_activity(
                    session.email,
                    "image_generation_failed",
                    "upstream image generation failed",
                    severity="error",
                )
        else:
            if not msg_data.error_info or msg_data.status:
                response_text = msg_data.msg_raw or msg_data.msg_recv
                self.logger.info(
                    f"receive message: {build_chat_content(response_text).markdown}"
                )
        finally:
            if session.status not in (Status.Update.value, Status.Recovering.value, Status.Stop.value):
                session.status = Status.Ready.value
        self.logger.debug(f"session {session.email} finish work")
        return msg_data

    async def continue_chat_stream(self, msg_data: MsgData) -> AsyncIterator[ChatStreamEvent]:
        """Queue a streaming request and retain its lease until the stream closes."""
        lease = await self._acquire_request_lease(msg_data)
        if not lease:
            yield ChatStreamEvent(
                type="error",
                text=msg_data.error_info or "request queue timeout",
                metadata={"error_kind": "request_queue_timeout", "retryable": True},
            )
            return
        try:
            async for event in self._continue_chat_stream_direct(msg_data):
                yield event
        finally:
            await lease.release()

    async def _continue_chat_stream_direct(self, msg_data: MsgData) -> AsyncIterator[ChatStreamEvent]:
        """Stream chat events from the browser fetch transport."""
        session = await self._prepare_chat_session(msg_data)
        if not session:
            error = msg_data.error_list[-1] if msg_data.error_list else {}
            self._record_activity(
                str(error.get("session_email") or msg_data.account_hint or ""),
                "chat_failed",
                f"request rejected: {error.get('kind') or 'session_unavailable'}",
                severity="error",
                details={"error_kind": str(error.get("kind") or "session_unavailable")},
            )
            yield ChatStreamEvent(
                type="error",
                text=msg_data.error_info or "failed to prepare chat session",
                metadata={
                    "error_kind": str(error.get("kind") or "stream_error"),
                    "retryable": bool(error.get("retryable", False)),
                    **(
                        {"capability": error["capability"]}
                        if error.get("capability") else {}
                    ),
                },
            )
            return

        context_num = session.email
        msg_data.from_email = session.email
        msg_data.request_started_at = time.monotonic()
        msg_data.request_upload_count = len(msg_data.upload_file)
        msg_data.request_image_upload_count = sum(
            1
            for file in msg_data.upload_file
            if (
                file.content_type == "image_asset_pointer"
                or str(file.mime_type or "").lower().startswith("image/")
            )
        )
        msg_data.request_file_upload_count = (
            msg_data.request_upload_count - msg_data.request_image_upload_count
        )
        self._record_activity(
            session.email,
            "chat_started",
            (
                "request accepted"
                + (
                    f"; capabilities: {', '.join(msg_data.required_capabilities)}"
                    if msg_data.required_capabilities else ""
                )
            ),
            details={
                "uploads": msg_data.request_upload_count,
                "new_conversation": not bool(msg_data.conversation_id),
            },
        )
        if msg_data.request_upload_count:
            self._record_activity(
                session.email,
                "attachment_upload_started",
                f"{msg_data.request_upload_count} attachment(s)",
                details={"count": msg_data.request_upload_count},
            )
        if IMAGE_GENERATION in msg_data.required_capabilities:
            self._record_activity(
                session.email,
                "image_generation_started",
                "image generation requested",
            )
        self.logger.debug(f"session {session.email} begin stream work")
        stream_attempt = 1
        try:
            while True:
                emitted_content = False
                suppressed_auth_error = False
                suppressed_bridge_error = False
                try:
                    async for event in self._stream_msg_by_browser_fetch(msg_data, session, attempt=stream_attempt):
                        if (
                            event.type == "error"
                            and not emitted_content
                            and self._is_expired_stream_auth_error(event.text)
                        ):
                            suppressed_auth_error = True
                            continue
                        if (
                            event.type == "error"
                            and not emitted_content
                            and self._is_unready_stream_bridge_error(event.text)
                        ):
                            suppressed_bridge_error = True
                            continue
                        if event.type in {"delta", "image", "image_pending", "final"}:
                            emitted_content = True
                        yield event
                    break
                except Exception as error:
                    if (
                        stream_attempt == 1
                        and not emitted_content
                        and (suppressed_auth_error or self._is_expired_stream_auth_error(error))
                        and await self._recover_expired_stream_session(session)
                    ):
                        msg_data.error_info = ""
                        msg_data.error_list.clear()
                        stream_attempt += 1
                        self.logger.info(
                            f"{session.email} retrying stream after refreshing expired authorization"
                        )
                        continue
                    if (
                        stream_attempt == 1
                        and not emitted_content
                        and (suppressed_bridge_error or self._is_unready_stream_bridge_error(error))
                        and await self._recover_unready_stream_bridge(session)
                    ):
                        msg_data.error_info = ""
                        msg_data.error_list.clear()
                        stream_attempt += 1
                        self.logger.info(
                            f"{session.email} retrying stream after browser bridge warm-up"
                        )
                        continue
                    if (
                        not emitted_content
                        and (suppressed_auth_error or self._is_expired_stream_auth_error(error))
                    ):
                        self._mark_stream_authorization_unavailable(session, error)
                        self._schedule_stream_reauthentication(session)
                        msg_data.add_error(
                            kind="session_reauthentication_pending",
                            message="the account session expired and automatic reauthentication has started",
                            retryable=True,
                            session_email=session.email,
                        )
                    raise

            if any(
                error.get("kind") == "capability_rate_limited"
                for error in msg_data.error_list
            ):
                raise RuntimeError(msg_data.error_list[-1]["message"])
            if (
                IMAGE_GENERATION in msg_data.required_capabilities
                and not self._generated_image_count(msg_data)
            ):
                msg_data.add_error(
                    kind="image_generation_no_result",
                    message="upstream image generation completed without a retrievable image",
                    retryable=True,
                    session_email=session.email,
                )
                raise RuntimeError(msg_data.error_list[-1]["message"])
            if not msg_data.status:
                msg_data.add_error(
                    kind="stream_no_final_result",
                    message="upstream stream completed without a final result",
                    retryable=True,
                    session_email=session.email,
                )
                raise RuntimeError(msg_data.error_list[-1]["message"])

            if msg_data.status:
                self._clear_chat_rate_limit(session)
                if session.login_state is False:
                    session.login_state = True
                self._bind_conversation_client(msg_data, session)
                if msg_data.persist_history:
                    await self.save_chat(msg_data, context_num)
                self._record_usage(session, msg_data)
                self._record_capability_usage(session, msg_data)
                self.logger.info(
                    f"receive stream message: {build_chat_content(msg_data.msg_recv).markdown}"
                )
                if msg_data.request_upload_count:
                    self._record_activity(
                        session.email,
                        "attachment_upload_completed",
                        f"{msg_data.request_upload_count} attachment(s) delivered",
                        details={"count": msg_data.request_upload_count},
                    )
                if IMAGE_GENERATION in msg_data.required_capabilities:
                    generated_images = self._generated_image_count(msg_data)
                    if generated_images:
                        self._record_activity(
                            session.email,
                            "image_generation_completed",
                            f"{generated_images} image(s) returned",
                            details={"count": generated_images},
                        )
                    else:
                        self._record_activity(
                            session.email,
                            "image_generation_failed",
                            "upstream completed without a generated image",
                            severity="error",
                        )
        except Exception as e:
            if not msg_data.error_info:
                msg_data.add_error(kind="continue_chat_stream_error", message=str(e), session_email=session.email)
            self.logger.error(msg_data.error_info)
            error_kind = str(
                (msg_data.error_list[-1] if msg_data.error_list else {}).get("kind")
                or "continue_chat_stream_error"
            )
            self._record_activity(
                session.email,
                "chat_failed",
                f"request failed: {error_kind}",
                severity="error",
                details={
                    "error_kind": error_kind,
                    "duration_ms": (
                        max(0, int((time.monotonic() - msg_data.request_started_at) * 1000))
                        if msg_data.request_started_at else 0
                    ),
                },
            )
            if msg_data.request_upload_count:
                self._record_activity(
                    session.email,
                    "attachment_upload_failed",
                    "attachment request failed with its chat turn",
                    severity="error",
                    details={"count": msg_data.request_upload_count},
                )
            if IMAGE_GENERATION in msg_data.required_capabilities:
                self._record_activity(
                    session.email,
                    "image_generation_failed",
                    "upstream image generation failed",
                    severity="error",
                )
            structured_error = (
                msg_data.error_list[-1]
                if msg_data.error_list
                else {"kind": error_kind, "retryable": False}
            )
            error_metadata = {
                **msg_data.response_metadata,
                "error_kind": str(structured_error.get("kind") or error_kind),
                "retryable": bool(structured_error.get("retryable", False)),
            }
            if structured_error.get("capability"):
                error_metadata["capability"] = str(structured_error["capability"])
            yield ChatStreamEvent(
                type="error",
                text=msg_data.error_info or str(e),
                message_id=msg_data.next_msg_id,
                conversation_id=msg_data.conversation_id,
                model=msg_data.model_used,
                usage=msg_data.usage.copy(),
                metadata=error_metadata,
            )
        finally:
            if session.status not in (Status.Update.value, Status.Recovering.value, Status.Stop.value):
                session.status = Status.Ready.value
            self.logger.debug(f"session {session.email} finish stream work")

    def _bind_conversation_client(self, msg_data: MsgData, session: Session) -> None:
        if msg_data.client_id and msg_data.conversation_id:
            self.storage.bind_conversation_client(
                msg_data.conversation_id,
                msg_data.client_id,
                session.email,
            )

    async def show_chat_history(self, msg_data: MsgData) -> List[Dict[str, Any]]:
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
                # These fields have always been persisted. Expose them so callers
                # can build a readable history without reopening storage files.
                "message_id": x['next_msg_id'],
                "created_at": x.get('created_at'),
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

    async def get_persona_prompt(self, name: str) -> str:
        """Return one stored persona prompt without exposing personality storage."""
        if not self.personality:
            return ""
        return self.personality.get_value_by_name(name) or ""

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
        self.storage.save_personas(self.personality.init_list) # type: ignore

    async def list_personas(self) -> List[Dict[str, str]]:
        """Return stored personas without exposing runtime/session state."""
        if not self.personality:
            return []
        return [
            {"name": item["name"], "value": item["value"]}
            for item in self.personality.init_list
            if isinstance(item, dict)
            and isinstance(item.get("name"), str)
            and isinstance(item.get("value"), str)
        ]

    async def show_personality_list(self):
        """show_personality_list
        展示人格列表"""
        return self.personality.show_name() # type: ignore

    async def del_personality(self, name: str):
        """del_personality by name
        删除人格根据名字"""
        self.personality.del_data_by_name(name) # type: ignore
        self.storage.save_personas(self.personality.init_list) # type: ignore
        return self.personality.show_name() # type: ignore

    async def token_status(self):
        """get work status|查看session token状态和工作状态"""
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
            chat_rate_limited = session.is_chat_rate_limited()
            retry_task = getattr(self, "_control_login_tasks", {}).get(session.email)
            retry_pending = bool(retry_task and not retry_task.done())
            retry_after_seconds = 0
            if session.disabled_until:
                retry_after_seconds = max(0, int((session.disabled_until - datetime.now()).total_seconds()))
            if session.chat_rate_limited_until:
                retry_after_seconds = max(
                    retry_after_seconds,
                    int((session.chat_rate_limited_until - datetime.now()).total_seconds()),
                )
            login_guidance, retry_mode = self._login_guidance(session, retry_pending, retry_after_seconds)
            operational = self._account_operational_diagnostics(
                session,
                retry_pending=retry_pending,
                has_verification=session.email in verification_by_account,
            )
            accounts.append({
                "email": session.email,
                "mode": session.mode,
                "status": session.status,
                "login_state": session.login_state,
                "available": bool(session.login_state and session.status == Status.Ready.value and not disabled and not chat_rate_limited),
                "disabled": disabled,
                "chat_rate_limited": chat_rate_limited,
                "chat_rate_limited_until": (
                    session.chat_rate_limited_until.isoformat()
                    if session.chat_rate_limited_until else ""
                ),
                "chat_rate_limit_source": session.chat_rate_limit_source,
                "manual_disabled": session.manual_disabled,
                "login_retry_pending": retry_pending,
                "can_retry_login": bool(session.email and session.password),
                "disabled_until": session.disabled_until.isoformat() if session.disabled_until else "",
                "retry_after_seconds": retry_after_seconds,
                "retry_mode": retry_mode,
                "login_guidance": login_guidance,
                "operational_state": operational["state"],
                "operational_guidance": operational["guidance"],
                "recommended_action": operational["action"],
                "gptplus": session.gptplus,
                "account_plan": getattr(session, "account_plan", "unknown"),
                "account_plan_source": getattr(session, "account_plan_source", "unavailable"),
                "account_plan_observed_at": (
                    getattr(session, "account_plan_observed_at", None).isoformat()
                    if getattr(session, "account_plan_observed_at", None) else ""
                ),
                "observed_model_count": len(getattr(session, "observed_models", [])),
                "observed_models_source": getattr(session, "observed_models_source", "unavailable"),
                "observed_models_observed_at": (
                    getattr(session, "observed_models_observed_at", None).isoformat()
                    if getattr(session, "observed_models_observed_at", None) else ""
                ),
                "persist_auth_state": session.persist_auth_state,
                "auth_state_loaded": session.auth_state_loaded,
                "conversation_count": self.storage.conversation_count(session.email),
                "usage": self._usage_snapshot(session.email),
                "capability_quota": self._capability_snapshot(session),
                "recent_assignment_count": self._recent_account_assignment_count(session.email),
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
            "cid_num": [self.storage.conversation_count(session.email) for session in self.Sessions if session.type != "script"],
            "plus": [session.gptplus  for session in self.Sessions if session.type != "script"],
            "model_catalog": self._local_model_catalog(),
            "account_selection": {
                "strategy": getattr(self, "account_selection_strategy", "least_recently_used"),
                "window_seconds": getattr(self, "account_selection_window_seconds", 5 * 60 * 60),
            },
            "capability_quota": {
                "enabled": bool(getattr(self, "capability_quota_enabled", True)),
                "free_upload_daily_limit": int(
                    getattr(self, "free_upload_daily_limit", 0)
                ),
                "free_image_generation_daily_limit": int(
                    getattr(self, "free_image_generation_daily_limit", 0)
                ),
                "upstream_fallback_cooldown_seconds": int(
                    getattr(
                        self,
                        "capability_rate_limit_cooldown_seconds",
                        24 * 60 * 60,
                    )
                ),
            },
            "accounts": accounts,
            "verification": pending_verifications,
        }

    @staticmethod
    def _login_guidance(session: Session, retry_pending: bool, retry_after_seconds: int) -> tuple[str, str]:
        """Return safe, operator-facing login state without exposing page/error text."""
        if session.manual_disabled:
            return "Disabled by operator.", "enable"
        if retry_pending:
            return "Manual login retry is running.", "wait"
        if session.is_chat_rate_limited():
            return "Chat message limit reached. New conversations wait until the estimated reset.", "quota_wait"
        if session.login_state and session.status == Status.Ready.value:
            return "Ready.", "none"

        guidance_by_kind = {
            LoginFailureKind.AccountLocked.value: "Account is permanently unavailable. Retry only after it is restored upstream.",
            LoginFailureKind.NeedVerification.value: "Verification is required. Submit the pending code below, then retry manually if needed.",
            LoginFailureKind.RiskBlocked.value: "Provider risk checks blocked this login. Wait for cooldown before a manual retry.",
            LoginFailureKind.RateLimited.value: "Provider rate limit reached. Wait for cooldown before a manual retry.",
            LoginFailureKind.Transient.value: "Temporary browser or network failure. Retry after cooldown.",
            LoginFailureKind.BadCredentials.value: "Credentials were rejected. Update them before a manual retry.",
            LoginFailureKind.Unknown.value: "Login did not complete. Review the local screenshot or activity, then retry manually.",
        }
        guidance = guidance_by_kind.get(session.login_failure_kind, "Login has not completed yet.")
        if retry_after_seconds:
            return guidance, "cooldown"
        if session.login_failure_kind in (
            LoginFailureKind.AccountLocked.value,
            LoginFailureKind.BadCredentials.value,
            LoginFailureKind.NeedVerification.value,
        ):
            return guidance, "manual"
        return guidance, "retry"

    @staticmethod
    def _account_operational_diagnostics(
            session: Session,
            *,
            retry_pending: bool,
            has_verification: bool,
    ) -> Dict[str, str]:
        """Project runtime state into stable, credential-free operator diagnostics."""
        if session.manual_disabled:
            return {
                "state": "manually_disabled",
                "guidance": "The operator disabled this account. Enable it before scheduling new work.",
                "action": "enable_account",
            }
        if retry_pending:
            return {
                "state": "login_recovery_running",
                "guidance": "A controlled browser login recovery is currently running.",
                "action": "wait",
            }
        if has_verification:
            return {
                "state": "verification_pending",
                "guidance": "A provider verification code is waiting for local submission.",
                "action": "submit_verification",
            }
        if session.is_chat_rate_limited():
            return {
                "state": "chat_quota_cooldown",
                "guidance": "New chats are paused until the estimated upstream quota reset.",
                "action": "wait_for_quota",
            }
        if session.force_fresh_login:
            return {
                "state": "session_reauthentication_required",
                "guidance": "The browser authorization was rejected and needs a fresh sign-in.",
                "action": "retry_login",
            }

        failure_states = {
            LoginFailureKind.AccountLocked.value: (
                "account_unavailable",
                "The upstream account is unavailable. Restore it upstream before retrying.",
                "restore_account",
            ),
            LoginFailureKind.BadCredentials.value: (
                "credentials_rejected",
                "Configured credentials were rejected. Update them before a manual retry.",
                "update_credentials",
            ),
            LoginFailureKind.NeedVerification.value: (
                "verification_required",
                "The provider requires verification before this account can continue.",
                "submit_verification",
            ),
            LoginFailureKind.RiskBlocked.value: (
                "provider_security_check",
                "The provider requested an additional security check. Wait for its cooldown, then retry manually.",
                "wait_then_retry",
            ),
            LoginFailureKind.RateLimited.value: (
                "provider_login_cooldown",
                "Provider login attempts are cooling down. Retry only after the displayed wait.",
                "wait_then_retry",
            ),
        }
        failure = failure_states.get(session.login_failure_kind)
        if failure:
            return {"state": failure[0], "guidance": failure[1], "action": failure[2]}
        if session.login_failure_kind == LoginFailureKind.Transient.value:
            detail = session.last_login_error.lower()
            if "bridge" in detail:
                return {
                    "state": "browser_bridge_unavailable",
                    "guidance": "The browser request bridge did not initialize. The runtime will retry after cooldown.",
                    "action": "wait_then_retry",
                }
            if "page create" in detail or "new page" in detail:
                return {
                    "state": "browser_page_startup_failed",
                    "guidance": "A browser page could not be created. Check the local browser runtime, then retry after cooldown.",
                    "action": "wait_then_retry",
                }
            return {
                "state": "login_transport_failure",
                "guidance": "A temporary browser or network failure interrupted login. Retry after cooldown.",
                "action": "wait_then_retry",
            }
        if session.login_failure_kind == LoginFailureKind.Unknown.value:
            return {
                "state": "login_state_unrecognized",
                "guidance": "The provider login page did not match a known state. Review local diagnostics before retrying.",
                "action": "review_then_retry",
            }
        if session.status == Status.Working.value:
            return {
                "state": "chat_in_progress",
                "guidance": "This account is currently serving a chat request.",
                "action": "wait",
            }
        if session.login_state and session.status == Status.Ready.value:
            return {
                "state": "ready",
                "guidance": "The account is ready for new work.",
                "action": "none",
            }
        if session.status == Status.Login.value:
            return {
                "state": "login_starting",
                "guidance": "The browser sign-in flow is starting.",
                "action": "wait",
            }
        if session.status == Status.Update.value:
            if session.runtime_last_closed_at:
                return {
                    "state": "browser_runtime_recovery_needed",
                    "guidance": "A browser page or context closed unexpectedly. Runtime recovery is required before chat resumes.",
                    "action": "wait_then_retry",
                }
            return {
                "state": "login_recovery_pending",
                "guidance": "The account is waiting for login recovery.",
                "action": "wait_then_retry",
            }
        if session.status == Status.Recovering.value:
            return {
                "state": "login_transport_failure",
                "guidance": "The account is waiting for a network or browser recovery retry.",
                "action": "wait_then_retry",
            }
        return {
            "state": "not_initialized",
            "guidance": "The account has not completed browser initialization yet.",
            "action": "wait",
        }


    async def md2img(self,md: str):
        return await markdown2image(md,self.Sessions[0])
