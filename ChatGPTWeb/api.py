import copy
from pathlib import Path
from playwright.async_api import Page
from playwright.async_api import Response
import pickle
import json

from .config import MsgData,Session,SetCookieParam,Status
from .OpenAIAuth import AsyncAuth0

async def async_send_msg(page: Page,msg_data: MsgData,url: str,logger):
    '''msg send handle func'''
    async with page.expect_response(url,timeout=40000) as response_info:
        try:
            logger.info(f"send:{msg_data.msg_send}")
            await page.goto(url, timeout=50000)
        
        except Exception as e:
            if "Download is starting" not in e.args[0]:
                logger.warning(f"send msg error:{e}")
                raise e
            await page.wait_for_load_state("load")
            if response_info.is_done():
                return await response_info.value
    return await response_info.value

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
        if '"end_turn": true' not in x:
            continue
        msg = json.loads(x[6:])
        tmp = msg["message"]["content"]["parts"][0]
        msg_data.msg_recv = markdown_to_text(tmp)
        msg_data.conversation_id = msg["conversation_id"]
        msg_data.next_msg_id = msg["message"]["id"]
        msg_data.status = True
        msg_data.msg_type = "old_session"
        break
    return msg_data

async def recive_handle(session: Session,resp: Response,msg_data: MsgData,logger):
    '''recive handle stream to msgdata'''
    if resp.status == 200:
        stream_text = await resp.text()
        stream_lines = stream_text.splitlines()
        msg_data = stream2msgdata(stream_lines,msg_data)
        if msg_data.msg_recv == "":
            logger.warning("This content may violate openai's content policy")
            msg_data.msg_recv = "This content may violate openai's content policy"
        if not msg_data.status:
            msg_data.msg_recv = str(resp.status) + " or maybe stream not end"
    elif resp.status == 401:
        # Token expired and you need to log in again | token过期 需要重新登录
        logger.error(f"{session.email} 401,relogin now")
        session.login_state = False
        session.access_token = ""
        await Auth(session,logger)
        msg_data.msg_recv = f"{session.email} 401,relogin last,pleases try send again."
    else:
        msg_data.msg_recv = str(resp.status) + "\n" + resp.status_text + "\n" + await resp.text()
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
        logger.info(f"{session.email} flush retry {retry}")
    if retry == 0:
        logger.info(f"{session.email} stop flush")
        return session
    retry -= 1
    if page := session.page:
        async with page.expect_response(url, timeout=20000) as a:
            res = await page.goto(url, timeout=20000)
        res = await a.value

        if res.status == 403 and res.url == url:
            session = await retry_keep_alive(session,url,logger,retry)
        elif res.status == 200 and res.url == url:
            logger.info(f"flush {session.email} cf cookie OK!")
            await page.wait_for_timeout(1000)
            cookies = await session.page.context.cookies()
            cookie = next(filter(lambda x: x.get("name") == "__Secure-next-auth.session-token", cookies), None)

            if cookie:
                session.session_token = SetCookieParam(
                    url="https://chat.openai.com",
                    name="__Secure-next-auth.session-token",
                    value=cookie["value"] # type: ignore
                ) # type: ignore
                update_session_token(session,chat_file,logger)

        elif res.status == 401 and res.url == url:
            # Token expired and you need to log in again | token过期 需要重新登录
            logger.error(f"flush {session.email} cf cookie has expired! waiting relogi.")
            # self.manage["access_token"][context_index] = ""
            # self.manage["status"][str(context_index)] = False
            session.login_state = False
            session.access_token = ""
            await Auth(session,logger)

        else:
            logger.error(f"flush {session.email} cf cookie error!")
    else:
        logger.error(f"error! session {session.email} no page!")
    return session


async def Auth(session: Session,logger):
    '''Auth account login func'''
    if session.email and session.password:
        auth = AsyncAuth0(email=session.email, password=session.password, page=session.page, # type: ignore
                            mode=session.mode,
                            logger=logger,
                            # loop=self.browser_event_loop
                            )
        t = await auth.get_session_token()
        if t:
            session.session_token = t
            session.status = Status.Login.value
            session.login_state = True
    else:
        logger.info("No email or password")
        
                
def update_session_token(session: Session,chat_file: Path,logger):
    session_file = chat_file / "sessions" / session.email
    try:
        tmp = copy.copy(session)
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
            return session
    except FileNotFoundError:
        return session
    except Exception as e:
        logger.warning(f"get session_token from file error : {e}")
        return session
            
        
        



    
