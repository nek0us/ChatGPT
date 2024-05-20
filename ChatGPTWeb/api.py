import sys
import time
import uuid
import json
import pickle
import base64
import asyncio

from pathlib import Path
from typing import Optional
from httpx import AsyncClient
from aiohttp import ClientSession,ClientWebSocketResponse
from playwright.async_api import Page
from playwright.async_api import Response,Route, Request
from playwright_stealth import stealth_async

from .OpenAIAuth import AsyncAuth0
from .config import MsgData,Session,SetCookieParam,Status,url_requirements,Payload

class MockResponse:
    def __init__(self, data, status=200):
        self.data = data
        self.status = status
    
    async def text(self):
        return self.data
    

async def get_wss(page: Page, header: dict,msg_data: MsgData,httpx_status: bool,logger,httpx_proxy: Optional[str] = None):
    
    if not httpx_status:
        header['Referer'] = f"https://chat.openai.com/c/{msg_data.conversation_id}" if msg_data.conversation_id else "https://chat.openai.com/"
        async def route_handle_wss(route: Route, request: Request):
            header["User-Agent"] = request.headers["user-agent"]
            await route.continue_(method="POST", headers=header)
        await page.route("**/backend-api/register-websocket", route_handle_wss)
        try:
            async with page.expect_response("https://chat.openai.com/backend-api/register-websocket",timeout=10000) as response_info: 
                await page.goto("https://chat.openai.com/backend-api/register-websocket",timeout=10000)
                tmp = await response_info.value
                wss = await tmp.json()
                msg_data.last_wss = wss["wss_url"]
        except Exception as e:
            logger.warning(f"get register-websocket error:{e}") 
            msg_data.error_info += f"get register-websocket error:{e}\n"
        return msg_data,header
    else:
        header['Referer'] = f"https://chat.openai.com/c/{msg_data.conversation_id}" if msg_data.conversation_id else "https://chat.openai.com/"
        try:
            async with AsyncClient(proxies=httpx_proxy) as client: 
                header_copy = header.copy()
                header_copy['Content-Length'] = '0'
                header_copy['Content-Type'] = 'application/json'
                res = await client.post("https://chat.openai.com/backend-api/register-websocket",headers=header_copy,json=None,data=None)
                wss = res.json()
                msg_data.last_wss = wss["wss_url"]
        except Exception as e:
            logger.warning(f"get register-websocket error:{e}")
            msg_data.error_info += f"get register-websocket error:{e} \n"
        return msg_data,header

    
def get_wss_payload(last_wss:str):
    split_jwt = last_wss.split('access_token=')[1].split('.')
    payload = split_jwt[1]
    padding = '=' * (4 - len(payload) % 4)
    decoded_payload = base64.urlsafe_b64decode(payload + padding)
    payload_data = json.loads(decoded_payload)
    return payload_data

async def async_send_msg(session: Session,msg_data: MsgData,url: str,logger,httpx_status: bool = False,httpx_proxy: Optional[str]=None,stdout_flush:bool = False):
    '''msg send handle func'''
    if msg_data.last_wss != "":
        payload_data = get_wss_payload(msg_data.last_wss)
        now_time = int(time.time())
        if now_time < payload_data["exp"]:
            try:
                session.wss_session = ClientSession()
                session.wss = await session.wss_session.ws_connect(msg_data.last_wss,headers=None,proxy=httpx_proxy)
            except Exception as e:
                logger.warning(f"open last wss error:{e}")
    if httpx_status:
        async with AsyncClient(proxies=httpx_proxy) as client:
            # header["Content-Length"] = str(len(str()))
            res = await client.post(url=url,json=json.loads(msg_data.post_data),headers=msg_data.header)
            wss = res.json()
    else:            
        
        
        async with session.page.expect_response(url,timeout=60000) as response_info: # type: ignore
            try:
                logger.debug(f"send:{msg_data.msg_send}")
                await session.page.goto(url, timeout=60000) # type: ignore
            except Exception as e:
                if "Download is starting" not in e.args[0]:
                    logger.warning(f"send msg error:{e}")
                    msg_data.error_info += f"{str(e)}\n"
                    raise e
                await session.page.wait_for_load_state("load") # type: ignore
                if response_info.is_done():
                    return await response_info.value
            else:
                tmp = await response_info.value
                wss = await tmp.json()
    return await try_wss(wss=wss,msg_data=msg_data,session=session,proxy=httpx_proxy,logger=logger,ws=session.wss,stdout_flush=stdout_flush)

async def try_wss(wss: dict, msg_data: MsgData,session: Session,proxy: Optional[str],logger,ws: Optional[ClientWebSocketResponse] = None,stdout_flush:bool = False):            
    wss_url = wss["wss_url"]
    msg_data.last_wss = wss_url
    try:
        if ws:
            data = await recv_ws(session,ws,stdout_flush)
        else:
            async with ClientSession() as wss_session:
                async with wss_session.ws_connect(wss_url,headers=None,proxy=proxy) as websocket:
                    data = await recv_ws(session,websocket,stdout_flush) 
    except Exception as e:
        logger.error(f"get recv wss msg error:{e}")
        msg_data.error_info += f"{str(e)}\n"
    return data

async def recv_ws(session: Session,ws:ClientWebSocketResponse,stdout_flush: bool = False):
    body = ""
    while 1:
        recv = await asyncio.wait_for(ws.receive(),timeout=20)
        if json.loads(recv.data)["body"] == "ZGF0YTogW0RPTkVdCgo=":
            sys.stdout.write("\r" + " " * 40 + "\r")
            sys.stdout.flush()
            return MockResponse(body)
        ws_tmp = json.loads(recv.data)
        ws_tmp_body = base64.b64decode(ws_tmp['body']).decode('utf-8')
        msg_body = json.loads(ws_tmp_body[5:])
        if 'message' in msg_body:
            if msg_body['message']:
                if msg_body['message']['author']['role'] == 'assistant':
                    if stdout_flush and "parts" in msg_body['message']["content"]:
                        text = msg_body['message']["content"]["parts"][0]
                        # yield text
                        #TODO
                        sys.stdout.write(f"\rChatGPT:{text}")
                        sys.stdout.flush()
                        body = ws_tmp_body
                    elif not stdout_flush and "parts" in msg_body['message']['content']:
                        body = ws_tmp_body
                    if "is_complete" in msg_body['message']:
                        return MockResponse(ws_tmp_body)

async def get_msg_from_history(page: Page,msg_data: MsgData,url: str,logger):
    url_cid = url + '/' + msg_data.conversation_id
    async with page.expect_response(url_cid,timeout=60000) as response_info:
        try:
            # logger.info(f"send:{msg_data.msg_send}")
            await page.goto(url_cid, timeout=60000)
            tmp = await response_info.value
            text = await tmp.json()
            if msg_data.last_id in text["mapping"]:
                # msg = text["mapping"][msg_data.last_id]
                # return "data: " + json.dumps(msg)
                msg = list(text["mapping"].items())[-1][-1]
                if msg_data.last_id == msg["parent"]:
                    return "data: " + json.dumps(msg)

            return "error"
        except Exception as e:
            raise e
            
def markdown_to_text(markdown_string):
    '''it's not work now'''
    # Remove backslashes from markdown string
    # markdown_string = re.sub(r'\\(.)', r'\1', markdown_string)
    # Remove markdown formatting
    # markdown_string = re.sub(r'([*_~`])', '', markdown_string)
    # markdown_string = re.sub(r'\\(.)', r'\1', markdown_string)
    return markdown_string

def stream2msgdata(stream_lines:list,msg_data:MsgData):
    for x in stream_lines[::-1]:
        # for x in stream_lines:
        if ('"end_turn": true' not in x) and ("finished_successfully" not in x):
            continue
        msg = json.loads(x[6:])
        if "parts" in msg["message"]["content"]:
            tmp = msg["message"]["content"]["parts"][0]
        msg_data.msg_recv = markdown_to_text(tmp)
        try:
            msg_data.conversation_id = msg["conversation_id"]
        except KeyError as e:
            pass
        except Exception as e:
            raise e
        msg_data.next_msg_id = msg["message"]["id"]
        msg_data.status = True
        msg_data.msg_type = "old_session"
        break
    return msg_data

async def recive_handle(session: Session,resp: Response,msg_data: MsgData,logger):
    '''recive handle stream to msgdata'''
    stream_text = await resp.text()
    stream_lines = stream_text.splitlines()
    msg_data = stream2msgdata(stream_lines,msg_data)
    if msg_data.msg_recv == "":
        logger.warning(f"recive_handle error:msg_data.recv == None,This content may violate openai's content policy,error:{msg_data.error_info}")
        msg_data.error_info += f"recive_handle error:msg_data.recv == None, This content may violate openai's content policy,error:{msg_data.error_info}\n"
        raise Exception("recive_handle error:msg_data.recv == None")
        
    if not msg_data.status:
        logger.warning(f"recive_handle error:,msg_data.status==false{msg_data.error_info}")
        msg_data.error_info += f"recive_handle error:,msg_data.status==false{msg_data.error_info}\n"
        raise Exception("recive_handle error,msg_data.status==false")
    return msg_data

def create_session(**kwargs) -> Session:
    session_token = kwargs.get("session_token")
    if session_token and isinstance(session_token, str):
        kwargs["session_token"] = SetCookieParam(
            url="https://chat.openai.com",
            name="__Secure-next-auth.session-token",
            value=session_token
        )
    return Session(**kwargs)

async def retry_keep_alive(session: Session,url: str,chat_file: Path,logger,retry:int = 2) -> Session:
    if retry != 2:
        logger.debug(f"{session.email} flush retry {retry}")
    if retry == 0:
        logger.debug(f"{session.email} stop flush")
        return session
    retry -= 1
    
    if session.page:
        page = await session.browser_contexts.new_page() # type: ignore
        await stealth_async(page)
        try:
            async with page.expect_response(url, timeout=40000) as a:
                res = await page.goto(url, timeout=40000)
            res = await a.value

            if res.status == 403 and res.url == url:
                session = await retry_keep_alive(session,url,chat_file,logger,retry)
            elif (res.status == 200 or res.status == 307) and res.url == url:
                logger.debug(f"flush {session.email} cf cookie OK!")
                await page.wait_for_timeout(1000)
                cookies = await session.page.context.cookies()
                cookie = next(filter(lambda x: x.get("name") == "__Secure-next-auth.session-token", cookies), None)

                if cookie:
                    session.session_token = SetCookieParam(
                        url="https://chat.openai.com",
                        name="__Secure-next-auth.session-token",
                        value=cookie["value"] # type: ignore
                    ) # type: ignore
                    cookie_str = ''
                    for cookie in cookies:
                        if "chat.openai.com" in cookie["domain"]:
                            cookie_str += f"{cookie['name']}={cookie['value']}; "
                    session.cookies = cookie_str.strip()
                    session.login_cookies = cookies
                    
                    update_session_token(session,chat_file,logger)
                    
                    if session.status == Status.Login.value:
                        session.status = Status.Ready.value
                    
                else:
                    # no session-token,re login
                    session.status = Status.Update.value
                token = await page.evaluate(
                    '() => JSON.parse(document.querySelector("body").innerText)')
                if "error" in token and session.status != Status.Login.value:
                    session.status = Status.Update.value
                session.access_token = token['accessToken']

            else:
                logger.error(f"flush {session.email} cf cookie error!")
                # await page.screenshot(path=f"flush error {session.email}.jpg")
                session = await retry_keep_alive(session,url,chat_file,logger,retry)
        except Exception as e:
            logger.warning(f"retry_keep_alive {retry},error:{e}")
            # await page.screenshot(path=f"flush error {session.email}.jpg")
            session = await retry_keep_alive(session,url,chat_file,logger,retry)
        finally:
            await page.close()
    else:
        logger.error(f"error! session {session.email} no page!")
    return session


async def Auth(session: Session,logger):
    '''Auth account login func'''
    if session.email and session.password:
        auth = AsyncAuth0(email=session.email, password=session.password, page=session.page, # type: ignore
                            mode=session.mode,
                            browser_contexts=session.browser_contexts,
                            logger=logger,
                            help_email=session.help_email
                            # loop=self.browser_event_loop
                            )
        session.status = Status.Login.value
        cookie, access_token = await auth.get_session_token(logger)
        if cookie and access_token:
            session.session_token = cookie
            session.access_token = access_token
            session.status = Status.Ready.value
            logger.debug(f"{session.email} login success")
        else:
            logger.warning(f"{session.email} login error,waiting for next try")
            session.status = Status.Update.value

    else:
        logger.warning("No email or password")
        
                
def update_session_token(session: Session,chat_file: Path,logger):
    session_file = chat_file / "sessions" / session.email
    try:
        # tmp = copy.copy(session)
        tmp = Session()
        tmp.access_token = session.access_token
        tmp.email = session.email
        tmp.input_session_token = session.input_session_token
        tmp.cookies = session.cookies
        tmp.login_cookies = session.login_cookies
        tmp.last_active = session.last_active
        tmp.last_wss = session.last_wss
        tmp.mode = session.mode
        tmp.password = session.password
        tmp.session_token = session.session_token
        tmp.browser_contexts = None
        tmp.page = None
        with open(session_file,"wb") as file:
            pickle.dump(tmp, file)
        del tmp
    except Exception as e:
        logger.warning(f"save session_token error：{e}")

def get_session_token(session: Session,chat_file: Path,logger):
    session_file = chat_file / "sessions" / session.email
    try:
        with open(session_file, 'rb') as file:
            load_session: Session = pickle.load(file)
            session.session_token = load_session.session_token
            session.login_cookies = load_session.login_cookies
            session.last_wss = load_session.last_wss
            session.device_id = load_session.device_id
            return session
    except FileNotFoundError:
        session.device_id = str(uuid.uuid4())
        return session
    except Exception as e:
        logger.warning(f"get session_token from file error : {e}")
        return session
            
async def get_paid(page: Page,token: str,device_id: str,logger):
    
    async def route_handle_paid(route: Route, request: Request):
        data = {"conversation_mode_kind":"primary_assistant"}
        header = Payload.headers(token,json.dumps(data),device_id)
        header['Cookie'] = request.headers['cookie']
        header["User-Agent"] = request.headers["user-agent"]
        header['Accept'] = "*/*"
        header['Accept-Encoding'] = "gzip, deflate, br"
        header['Content-Type'] = "application/json"
        header['OAI-Device-Id'] = device_id
        header['OAI-Language'] = 'zh-Hans'
        header['Accept-Language'] = 'zh-CN,zh;q=0.8,zh-TW;q=0.7,zh-HK;q=0.5,en-US;q=0.3,en;q=0.2'
        header['Cache-Control'] = 'no-cache'
        header['Connection'] = 'keep-alive'
        header['Pragma'] = 'no-cache'
        await route.continue_(method="POST",headers=header,post_data=data)
            
    await page.route("**/backend-api/sentinel/chat-requirements", route_handle_paid)  # type: ignore
    async with page.expect_response(url_requirements) as ares:
        
        try:
            res = await page.goto(url=url_requirements)
            res = await ares.value
            return await res.json()
        except Exception as e:
            logger.error(f"get chat-requirements exception:{e}")
            raise e
    
async def get_paid_by_httpx(cookies: str,token: str,device_id: str,ua: str,proxy: Optional[str],logger):
    data = {"conversation_mode_kind":"primary_assistant"}
    header = Payload.headers(token,json.dumps(data),device_id)
    header['Cookie'] = cookies
    header["User-Agent"] = ua
    header['Accept'] = "*/*"
    header['Accept-Encoding'] = "gzip, deflate"
    header['Content-Type'] = "application/json"
    header['OAI-Device-Id'] = device_id
    header['OAI-Language'] = 'zh-Hans'
    header['Accept-Language'] = 'zh-CN,zh;q=0.8,zh-TW;q=0.7,zh-HK;q=0.5,en-US;q=0.3,en;q=0.2'
    header['Cache-Control'] = 'no-cache'
    header['Connection'] = 'keep-alive'
    header['Pragma'] = 'no-cache'
    try:
        async with AsyncClient(proxy=proxy) as client:
            res = await client.post(url_requirements,headers=header,json=data)
            return res.json()
    except Exception as e:
        logger.error(f"get chat-requirements exception:{e}")
        raise e
        