import re
import sys
import time
import uuid
import json
import pickle
import base64
import asyncio

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional,List
from datetime import datetime
from httpx import AsyncClient
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from aiohttp import ClientSession,ClientWebSocketResponse
from playwright_firefox.async_api import Page
from playwright_firefox.async_api import Response,Route, Request

from .OpenAIAuth import AsyncAuth0
from .config import MsgData,Session,SetCookieParam,Status,LoginFailureKind,url_requirements,Payload

class MockResponse:
    def __init__(self, data, status=200):
        self.data = data
        self.status = status
    
    async def text(self):
        return self.data


@dataclass
class ChatStreamEvent:
    type: str
    text: str = ""
    message_id: str = ""
    conversation_id: str = ""
    image_urls: List[str] = field(default_factory=list)
    model: str = ""
    usage: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    raw: Optional[Dict[str, Any]] = None


class ChatStreamParser:
    def __init__(self):
        self.text = ""
        self.message_id = ""
        self.conversation_id = ""
        self.image_gen = False
        self.image_urls: List[str] = []
        self.model = ""
        self.usage: Dict[str, Any] = {}
        self.metadata: Dict[str, Any] = {}

    def _record_metadata(self, item: Dict[str, Any]):
        metadata = item.get("metadata")
        if isinstance(metadata, dict):
            selected = {}
            for key in (
                "model_slug",
                "default_model_slug",
                "requested_model_slug",
                "finish_details",
                "content_references",
                "citations",
                "aggregate_result",
            ):
                if key in metadata:
                    selected[key] = metadata[key]
            if selected:
                self.metadata.update(selected)
            for key in ("model_slug", "default_model_slug", "requested_model_slug"):
                value = metadata.get(key)
                if isinstance(value, str) and value:
                    self.model = value
                    break

        for key in ("model_slug", "model", "default_model_slug", "requested_model_slug"):
            value = item.get(key)
            if isinstance(value, str) and value:
                self.model = value
                break

        for key in ("usage", "usage_metadata", "quota", "rate_limits"):
            value = item.get(key)
            if isinstance(value, dict):
                self.usage.update(value)

    def _record_ids(self, item: Dict[str, Any]):
        self._record_metadata(item)
        conversation_id = item.get("conversation_id")
        if isinstance(conversation_id, str) and conversation_id:
            self.conversation_id = conversation_id
        message_id = item.get("message_id")
        if isinstance(message_id, str) and message_id:
            self.message_id = message_id

    def _is_finished(self, value: Any) -> bool:
        return value in ("finished_successfully", "completed", "complete", "done")

    def _append_delta(self, value: str, raw: Dict[str, Any]) -> List[ChatStreamEvent]:
        if not value:
            return []
        if value == self.text:
            return []
        if self.text and value.startswith(self.text):
            value = value[len(self.text):]
            if not value:
                return []
        elif self.text:
            max_overlap = min(len(self.text), len(value))
            for overlap in range(max_overlap, 0, -1):
                if self.text.endswith(value[:overlap]):
                    value = value[overlap:]
                    break
            if not value:
                return []
        self.text += value
        return [ChatStreamEvent(type="delta", text=value, raw=raw)]

    def _merge_full_text(self, value: str, raw: Dict[str, Any]) -> List[ChatStreamEvent]:
        if not value:
            return []
        if value.startswith(self.text):
            delta = value[len(self.text):]
        else:
            delta = value
        self.text = value
        if not delta:
            return []
        return [ChatStreamEvent(type="delta", text=delta, raw=raw)]

    def _handle_message(self, item: Dict[str, Any], raw: Dict[str, Any]) -> List[ChatStreamEvent]:
        events: List[ChatStreamEvent] = []
        message = item.get("message")
        if not isinstance(message, dict):
            return events

        self._record_ids(item)
        self._record_metadata(message)

        author = message.get("author")
        role = author.get("role") if isinstance(author, dict) else ""
        if message.get("id") and (role == "assistant" or not self.message_id):
            self.message_id = message["id"]

        if role == "tool":
            metadata = message.get("metadata", {})
            if metadata.get("ui_card_title") == "Processing image":
                self.image_gen = True
                events.append(ChatStreamEvent(type="image_pending", raw=raw))

        content = message.get("content", {})
        if role == "assistant" and isinstance(content, dict):
            parts = content.get("parts")
            if parts and isinstance(parts[0], str):
                events.extend(self._merge_full_text(parts[0], raw))
        elif not role and isinstance(content, dict):
            parts = content.get("parts")
            if parts and isinstance(parts[0], str):
                events.extend(self._merge_full_text(parts[0], raw))

        if message.get("is_complete") or self._is_finished(message.get("status")):
            events.append(self.final_event(raw=raw))
        return events

    def _handle_image_results(self, value: List[Any], raw: Dict[str, Any]) -> List[ChatStreamEvent]:
        for image in value:
            if isinstance(image, dict):
                url = image.get("content_url") or image.get("url")
                if url and url not in self.image_urls:
                    self.image_urls.append(url)
        if self.image_urls:
            self.image_gen = True
            return [ChatStreamEvent(type="image", image_urls=self.image_urls.copy(), raw=raw)]
        return []

    def _handle_patch(self, patch: Dict[str, Any], raw: Dict[str, Any]) -> List[ChatStreamEvent]:
        events: List[ChatStreamEvent] = []
        path = patch.get("p") or patch.get("path") or ""
        op = patch.get("o") or patch.get("op") or ""
        value = patch.get("v") if "v" in patch else patch.get("value")

        if path in ("/conversation_id", "conversation_id") and isinstance(value, str):
            self.conversation_id = value
        elif path in ("/message/id", "message_id") and isinstance(value, str):
            self.message_id = value

        if path.endswith("/message/content/parts/0") and isinstance(value, str):
            events.extend(self._append_delta(value, raw))
        elif path.endswith("/message/content/parts") and isinstance(value, list):
            if value and isinstance(value[0], str):
                events.extend(self._merge_full_text(value[0], raw))
        elif path.endswith("/message/status") and self._is_finished(value):
            events.append(self.final_event(raw=raw))
        elif path.endswith("/message/metadata/image_results") and isinstance(value, list):
            events.extend(self._handle_image_results(value, raw))
        elif path == "/message" and isinstance(value, dict):
            events.extend(self._handle_message({"message": value}, raw))
        elif path == "" and op == "patch" and isinstance(value, list):
            events.extend(self._handle_patch_list(value, raw))
        elif isinstance(value, dict):
            events.extend(self._handle_message(value, raw))
            if any(key in value for key in ("p", "path", "v", "value")):
                events.extend(self._handle_patch(value, raw))
        elif isinstance(value, list):
            events.extend(self._handle_patch_list(value, raw))
        return events

    def _handle_patch_list(self, patches: List[Dict[str, Any]], raw: Dict[str, Any]) -> List[ChatStreamEvent]:
        events: List[ChatStreamEvent] = []
        for patch in patches:
            if not isinstance(patch, dict):
                continue
            events.extend(self._handle_patch(patch, raw))
        return events

    def feed(self, item: Dict[str, Any]) -> List[ChatStreamEvent]:
        events: List[ChatStreamEvent] = []
        if not isinstance(item, dict):
            return events
        self._record_ids(item)
        path = item.get("p", item.get("path"))
        op = item.get("o", item.get("op"))
        value = item.get("v") if "v" in item else item.get("value")

        if "message" in item:
            events.extend(self._handle_message(item, item))

        for key in ("delta", "data", "event"):
            wrapped = item.get(key)
            if isinstance(wrapped, dict):
                events.extend(self.feed(wrapped))
            elif isinstance(wrapped, list):
                events.extend(self._handle_patch_list(wrapped, item))

        if "patches" in item and isinstance(item["patches"], list):
            events.extend(self._handle_patch_list(item["patches"], item))

        if path is not None or op is not None or "v" in item:
            events.extend(self._handle_patch(item, item))
        elif isinstance(value, dict):
            events.extend(self._handle_message(value, item))

        return events

    def final_event(self, raw: Optional[Dict[str, Any]] = None) -> ChatStreamEvent:
        return ChatStreamEvent(
            type="final",
            text=self.text,
            message_id=self.message_id,
            conversation_id=self.conversation_id,
            image_urls=self.image_urls.copy(),
            model=self.model,
            usage=self.usage.copy(),
            metadata=self.metadata.copy(),
            raw=raw,
        )


class ChatStreamDecoder:
    def __init__(self):
        self.buffer = ""
        self.parser = ChatStreamParser()
        self.done = False
        self._final_sent = False

    def _feed_block(self, block: str) -> List[ChatStreamEvent]:
        events: List[ChatStreamEvent] = []
        data_lines = []
        for line in block.splitlines():
            if line.startswith("data:"):
                data_lines.append(line[5:].strip())
        if not data_lines:
            return events
        payload = "\n".join(data_lines).strip()
        if not payload:
            return events
        if payload == "[DONE]":
            self.done = True
            if not self._final_sent and (self.parser.text or self.parser.image_gen):
                self._final_sent = True
                events.append(self.parser.final_event())
            return events
        try:
            item = json.loads(payload)
        except json.JSONDecodeError:
            payload = payload.replace("\\\\", "\\")
            item = json.loads(payload)
        events.extend(self.parser.feed(item))
        if events and events[-1].type == "final" and (events[-1].text or events[-1].image_urls):
            self._final_sent = True
        return events

    def feed(self, chunk: str) -> List[ChatStreamEvent]:
        if not chunk:
            return []
        self.buffer += chunk
        events: List[ChatStreamEvent] = []
        while "\n\n" in self.buffer:
            block, self.buffer = self.buffer.split("\n\n", 1)
            events.extend(self._feed_block(block))
        return events

    def close(self) -> List[ChatStreamEvent]:
        events: List[ChatStreamEvent] = []
        if self.buffer.strip():
            events.extend(self._feed_block(self.buffer))
        self.buffer = ""
        if not self._final_sent and (self.parser.text or self.parser.image_gen):
            self._final_sent = True
            events.append(self.parser.final_event())
        return events


def parse_event_stream_items(stream_text: str) -> List[Dict[str, Any]]:
    text_tmp1 = stream_text[33:] if stream_text.startswith("event: delta_encoding") else stream_text
    text_tmp1 = text_tmp1[7:] if text_tmp1.startswith("\ndata: ") else text_tmp1
    text_tmp2 = text_tmp1[:-16] if text_tmp1.endswith("\n\ndata: [DONE]\n\n") else text_tmp1
    text_list: List[Dict[str, Any]] = []
    for x in text_tmp2.replace("""event: delta""","").split("""\n\ndata: """):
        if x == "":
            continue
        tmp1 = x.strip()
        if tmp1 == "[DONE]":
            continue
        if not tmp1.startswith("{"):
            start_index = tmp1.find("{")
            tmp1 = tmp1[start_index:]
        if not tmp1.endswith("}"):
            end_index = tmp1.rfind("}")
            tmp1 = tmp1[:end_index + 1]
        try:
            tmp = json.loads(tmp1)
        except:
            tmp2 = tmp1.replace("\\\\","\\")
            tmp = json.loads(tmp2)
        text_list.append(tmp)
    return text_list


def parse_event_stream_events(stream_text: str) -> List[ChatStreamEvent]:
    parser = ChatStreamParser()
    events: List[ChatStreamEvent] = []
    for item in parse_event_stream_items(stream_text):
        events.extend(parser.feed(item))
    if parser.text or parser.image_gen:
        if not events or events[-1].type != "final":
            events.append(parser.final_event())
    return events

@asynccontextmanager
async def new_script_page(session: Session) -> AsyncIterator[Page]:
    context = session.browser_contexts
    md_page = await context.new_page()
    await md_page.set_viewport_size({"width": 980, "height": 720})
    async with md_page:
        yield md_page
    
async def markdown2image(md: str,session: Session) -> bytes:

    async with new_script_page(session) as page:
        await page.goto("https://markdown.lovejade.cn/", wait_until="networkidle")
        # editor = page.locator("pre[class='vditor-sv vditor-reset']")
        await asyncio.sleep(1)

        # await page.screenshot(path="1.png")
        # if await editor.count() > 0:
        # await editor.fill(md)
        # await page.evaluate(f"""localStorage.setItem('vditorvditor', {repr(md)});""")
        info = await page.evaluate(
            """
            (md) => {
                const activeDoc = localStorage.getItem('arya_active_doc');
                if (!activeDoc) {
                    throw new Error('localStorage not have arya_active_doc');
                }

                const newKey = `arya_doc_${activeDoc}`;
                localStorage.setItem(newKey, md);

                return { activeDoc, newKey };
            }
            """,
            md
        )
        await page.goto("https://markdown.lovejade.cn/export/png",wait_until="networkidle")
        await asyncio.sleep(2)
        scr = page.locator("div[class='vditor-reset']")
        # await page.screenshot(path="2.png")
#         export_button = page.locator("button[class='el-button el-button--primary is-round']")
#         hook_download = """
# (function() {
#     var oldClick = HTMLAnchorElement.prototype.click;
#     HTMLAnchorElement.prototype.click = function() {
#         if (this.href && this.href.startsWith('data:image/png;base64,')) {
#             window.dd = this.href;
#             return;
#         }
#         return oldClick.apply(this, arguments);
#     };
# })();
# """     
#         # run_download = "() =>  document.querySelector('.export-page').__vue__.exportAndDownloadImg(document.querySelectorAll('.vditor-preview')[1])"
#         get_base64 = "window.dd"
        header_locator = page.locator("header[class='header-wrapper']")
        await header_locator.wait_for(state="attached", timeout=5000)
        await page.evaluate("""
                    () => {
                        const el = document.querySelector('.header-wrapper');
                        if (el) el.remove();
                    }
                """)
        # if await export_button.count() > 0:
        #     await page.evaluate(hook_download)
        #     await page.evaluate(run_download)
        #     await export_button.click()
        #     res = await page.evaluate(get_base64)
            # return base64.b64decode(res.replace("data:image/png;base64,",""))
            # print(res)
        return await scr.screenshot(
        # full_page=True,
        type="png",
        )


    


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
            async with AsyncClient(proxy=httpx_proxy) as client: 
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
        async with AsyncClient(proxy=httpx_proxy) as client:
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

async def try_wss(wss: dict, msg_data: MsgData,session: Session,proxy: Optional[str],logger,ws: Optional[ClientWebSocketResponse] = None,stdout_flush:bool = False) -> MockResponse:            
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

async def recv_ws(session: Session,ws:ClientWebSocketResponse,stdout_flush: bool = False) -> MockResponse:
    body = ""
    parser = ChatStreamParser()
    printed_prefix = False
    while 1:
        recv = await asyncio.wait_for(ws.receive(),timeout=20)
        if json.loads(recv.data)["body"] == "ZGF0YTogW0RPTkVdCgo=":
            sys.stdout.write("\r" + " " * 40 + "\r")
            sys.stdout.flush()
            return MockResponse(body)
        ws_tmp = json.loads(recv.data)
        ws_tmp_body = base64.b64decode(ws_tmp['body']).decode('utf-8')
        msg_body = json.loads(ws_tmp_body[5:])
        for event in parser.feed(msg_body):
            if stdout_flush and event.type == "delta" and event.text:
                if not printed_prefix:
                    sys.stdout.write("ChatGPT:")
                    printed_prefix = True
                sys.stdout.write(event.text)
                sys.stdout.flush()
            if event.type in ("delta", "final"):
                body = ws_tmp_body
            if event.type == "final":
                return MockResponse(ws_tmp_body)
    return MockResponse(body)

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
        except KeyError:
            pass
        except Exception as e:
            raise e
        msg_data.next_msg_id = msg["message"]["id"]
        msg_data.status = True
        msg_data.msg_type = "old_session"
        break
    return msg_data

async def handle_event_stream(response: Response|MockResponse,msg_data: MsgData) -> MsgData:
    stream_text = await response.text()
    decoder = ChatStreamDecoder()
    decoder.feed(stream_text)
    decoder.close()
    parser = decoder.parser

    msg_data.image_gen = parser.image_gen
    if parser.text or msg_data.image_gen:
        msg_list = parser.text
        if "turn0" in msg_list or "city" in msg_list:
            pattern = r'[\ue200-\ue203]?([a-z]+)?[\ue200-\ue203](?:turn\d+(?:image|search|fetch|forecast)\d+|city)'
            msg_list_str_re = re.sub(pattern, '', msg_list)
            msg_list = msg_list_str_re
        
        msg_data.status = True
        msg_data.next_msg_id = parser.message_id
        if parser.conversation_id:
            msg_data.conversation_id = parser.conversation_id
        msg_data.msg_recv = markdown_to_text(msg_list)
        msg_data.img_list = parser.image_urls
        if parser.model:
            msg_data.model_used = parser.model
        if parser.usage:
            msg_data.usage = parser.usage.copy()
        if parser.metadata:
            msg_data.response_metadata = parser.metadata.copy()
        
    return msg_data

def get_all_msg(msg: dict) -> list:
    text = msg["content"]["parts"][0] if msg["content"]["parts"] else ""
    pattern = r'[\ue200-\ue206]?[a-z]+[\ue200-\ue203]+(?:turn\d+[a-z]+\d+|city)[\ue200-\ue206]'
    sub = re.search(pattern,text)
    if sub:
        meta = sub.group()
        texts = text.split(meta)
        content_references = msg["metadata"]["content_references"]
        metadata = ""
        for content in content_references:
            if meta in content["matched_text"]:
                metadata = content["alt"]
                break
        all_msg = [texts[0],metadata,texts[1]]
        return all_msg
    return [text]

async def recive_handle(session: Session,resp: Response|MockResponse,msg_data: MsgData,logger) -> MsgData:
    '''recive handle stream to msgdata'''
    # stream_text = await resp.text()
    logger.debug(f"{session.email} get stream_text ok")
    # stream_lines = stream_text.splitlines()
    # logger.debug(f"{session.email} get stream_lines ok")
    # msg_data = stream2msgdata(stream_lines,msg_data)
    # logger.debug(f"{session.email} original msg:\n{await resp.text()}")
    msg_data = await handle_event_stream(resp,msg_data)
    if msg_data.msg_recv == "" and msg_data.image_gen:
        logger.warning(f"recive_handle error:msg_data.recv == None,This content may violate openai's content policy,error:{msg_data.error_info}")
        msg_data.error_info += f"recive_handle error:msg_data.recv == None, This content may violate openai's content policy,error:{msg_data.error_info}\n"
        raise Exception("recive_handle error:msg_data.recv == None")
    elif msg_data.msg_recv == msg_data.msg_send:
        pass
    elif msg_data.msg_recv == "" and not msg_data.image_gen:
        logger.info(f"{session.email} generation image,over recive_handle")
        
    if not msg_data.status:
        logger.warning(f"recive_handle error:,msg_data.status==false{msg_data.error_info}")
        msg_data.error_info += f"recive_handle error:,msg_data.status==false{msg_data.error_info}\n"
        raise Exception("recive_handle error,msg_data.status==false")
    return msg_data

def create_session(**kwargs) -> Session:
    session_token = kwargs.get("session_token")
    if session_token and isinstance(session_token, str):
        kwargs["session_token"] = SetCookieParam(
            url="https://chatgpt.com",
            name="__Secure-next-auth.session-token",
            value=session_token
        )
    return Session(**kwargs)

async def retry_keep_alive(session: Session,url: str,chat_file: Path,js: tuple,js_num: int,save_screen_status: bool,logger,retry:int = 2) -> Session:
    if session.is_login_disabled():
        logger.debug(f"{session.email} skip keep-alive, status:{session.status}, failure:{session.login_failure_kind}")
        return session
    if retry != 2:
        logger.debug(f"{session.email} flush retry {retry}")
    if retry == 0:
        logger.debug(f"{session.email} stop flush")
        return session
    retry -= 1
    
    if session.page:
        page = await session.browser_contexts.new_page() # type: ignore
        try:
            async with page.expect_response(url, timeout=40000) as a:
                res = await page.goto(url, timeout=40000)
            res = await a.value

            if res.status == 403 and res.url == url:
                session = await retry_keep_alive(session,url,chat_file,js,js_num,save_screen_status,logger,retry)
            elif (res.status == 200 or res.status == 307 or res.status == 304) and res.url == url:
                if await res.json():
                    # await page.wait_for_timeout(1000)
                    cookies = await session.page.context.cookies()
                    # cookies = [cookie for cookie in cookies if (cookie["name"] != '__Secure-next-auth.session-token') or (cookie["name"] == '__Secure-next-auth.session-token' and cookie["domain"] == 'chatgpt.com')]
                    cookie = next(filter(lambda x: x.get("name") == "__Secure-next-auth.session-token", cookies), None)
                    cookie0 = next(filter(lambda x: x.get("name") == "__Secure-next-auth.session-token.0", cookies), None)

                    if cookie or cookie0:
                        if cookie:
                            session.session_token = SetCookieParam(
                                url="https://chatgpt.com",
                                name="__Secure-next-auth.session-token",
                                value=cookie["value"] # type: ignore
                            ) # type: ignore
                            if cookie0:
                                cookies.remove(cookie0)
                                await session.page.context.clear_cookies()
                                await session.page.context.add_cookies(cookies) # type: ignore
                        else:
                            session.session_token = SetCookieParam(
                                url="https://chatgpt.com",
                                name="__Secure-next-auth.session-token.0",
                                value=cookie0["value"] # type: ignore
                            ) # type: ignore
                            if cookie:
                                cookies.remove(cookie)
                                await session.page.context.clear_cookies()
                                await session.page.context.add_cookies(cookies) # type: ignore
                        cookie_str = ''
                        for cookie in cookies:
                            if "chatgpt.com" in cookie["domain"]: # type: ignore
                                cookie_str += f"{cookie['name']}={cookie['value']}; " # type: ignore
                        session.cookies = cookie_str.strip()
                        session.login_cookies = cookies
                        
                        update_session_token(session,chat_file,logger)
                        
                        if session.status == Status.Login.value:
                            session.status = Status.Ready.value
                            if session.login_state_first is False:
                                await flush_page(session.page,js,js_num)
                                if session.login_state is False:
                                    token = await page.evaluate(
                                        '() => JSON.parse(document.querySelector("body").innerText)')
                                    logger.debug(f"flush {session.email}'s cf cookie,Login to Ready")
                                    if "error" in token and session.status != Status.Login.value:
                                        session.status = Status.Update.value
                                        logger.debug(f"the error in {session.email}'s access_token,it begin Status.Update")
                                    else:
                                        await flush_page(session.page,js,js_num)
                                        js_test = await session.page.evaluate("window._chatp")
                                        if js_test:
                                            session.login_state = True
                                            session.login_state_first = True
                        elif session.status == Status.Ready.value:
                            if session.login_state_first is False or session.login_state is False:
                                token = await page.evaluate(
                                        '() => JSON.parse(document.querySelector("body").innerText)')
                                logger.debug(f"flush {session.email}'s cf cookie,Login to Ready")
                                if "error" in token and session.status != Status.Login.value:
                                    session.status = Status.Update.value
                                    logger.debug(f"the error in {session.email}'s access_token,it begin Status.Update")
                                else:
                                    await flush_page(session.page,js,js_num)
                                    js_test = await session.page.evaluate("window._chatp")
                                    if js_test:
                                        session.login_state = True
                                        session.login_state_first = True

                        
                    else:
                        # no session-token,re login
                        session.status = Status.Update.value
                    token = await page.evaluate(
                        '() => JSON.parse(document.querySelector("body").innerText)')
                    if "error" in token and session.status != Status.Login.value:
                        session.status = Status.Update.value
                        logger.debug(f"the error in {session.email}'s access_token,it begin Status.Update")
                    if 'accessToken' not in token:
                        logger.debug(f"flush {session.email}'s cookie but no accessToken in response,it begin Status.Update,html text: \n{await res.body()}\n")
                        session.status = Status.Update.value
                    else:
                        session.access_token = token['accessToken']
                        logger.debug(f"flush {session.email} cf cookie OK!")
                else:
                    logger.debug(f"flush {session.email}'s cookie get a {res.status} code,html text: \n{await res.body()}\n,it begin Status.Update")
                    session.status = Status.Update.value

            else:
                logger.error(f"flush {session.email} cf cookie error!")
                # await page.screenshot(path=f"flush error {session.email}.jpg")
                session = await retry_keep_alive(session,url,chat_file,js,js_num,save_screen_status,logger,retry)
        except Exception as e:
            logger.warning(f"retry_keep_alive {retry},error:{e}")
            # await page.screenshot(path=f"flush error {session.email}.jpg")
            await save_screen(save_screen_status=save_screen_status,path=f"context_{session.email}_page_flush_faild!",page=page)
            session = await retry_keep_alive(session,url,chat_file,js,js_num,save_screen_status,logger,retry)
        finally:
            await page.close()
    else:
        logger.error(f"error! session {session.email} no page!")
    return session


def classify_login_failure(details: str, mode: str) -> str:
    text = (details or "").lower()
    if any(x in text for x in (
        "your account has been locked",
        "account has been locked",
        "temporarily suspended",
        "microsoft services agreement",
        "account.live.com/abuse",
        "account is locked",
        "account locked",
        "account banned",
        "account disabled",
    )):
        return LoginFailureKind.AccountLocked.value
    if any(x in text for x in (
        "incorrect password",
        "password is incorrect",
        "wrong password",
        "enter a valid password",
        "couldn't find an account",
        "could not find an account",
        "doesn't exist",
        "does not exist",
        "invalid username or password",
    )):
        return LoginFailureKind.BadCredentials.value
    if any(x in text for x in (
        "verify your email",
        "security code",
        "help us protect your account",
        "approve sign in request",
        "need microsoft login help email",
        "change your password",
        "two-step verification",
    )):
        return LoginFailureKind.NeedVerification.value
    if any(x in text for x in (
        "too many requests",
        "too many attempts",
        "try again later",
        "temporarily unavailable",
        "rate limit",
    )):
        return LoginFailureKind.RateLimited.value
    if mode == "google" or any(x in text for x in (
        "couldn't sign you in",
        "this browser or app may not be secure",
        "suspicious",
        "risk",
        "captcha",
        "cloudflare",
        "turnstile",
    )):
        return LoginFailureKind.RiskBlocked.value
    if any(x in text for x in ("timeout", "network", "net::", "closed", "context")):
        return LoginFailureKind.Transient.value
    return LoginFailureKind.Unknown.value


def login_failure_cooldown(kind: str) -> int:
    if kind == LoginFailureKind.RateLimited.value:
        return 1800
    if kind == LoginFailureKind.RiskBlocked.value:
        return 3600
    if kind == LoginFailureKind.Transient.value:
        return 300
    return 600


async def Auth(session: Session,logger):
    '''Auth account login func'''
    if session.is_login_disabled():
        logger.warning(
            f"{session.email} login skipped, status:{session.status}, "
            f"failure:{session.login_failure_kind}, disabled_until:{session.disabled_until}"
        )
        return
    if session.email and session.password:
        auth = AsyncAuth0(email=session.email, password=session.password, page=session.page, # type: ignore
                            mode=session.mode,
                            browser_contexts=session.browser_contexts,
                            logger=logger,
                            help_email=session.help_email
                            # loop=self.browser_event_loop
                            )
        if session.status != Status.Update.value:
            session.status = Status.Login.value
        cookie, access_token, login_error = await auth.get_session_token(logger)
        if cookie and access_token:
            session.session_token = cookie
            session.access_token = access_token
            session.mark_login_success()
            logger.debug(f"{session.email} login success")
        else:
            kind = classify_login_failure(login_error, session.mode)
            session.mark_login_failure(
                kind=kind,
                details=login_error,
                cooldown_seconds=login_failure_cooldown(kind),
            )
            logger.warning(
                f"{session.email} login error, kind:{kind}, "
                f"fail_count:{session.login_fail_count}/{session.max_login_failures}, "
                f"status:{session.status}"
            )

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
        tmp.login_fail_count = session.login_fail_count
        tmp.max_login_failures = session.max_login_failures
        tmp.login_failure_kind = session.login_failure_kind
        tmp.last_login_error = session.last_login_error
        tmp.disabled_until = session.disabled_until
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
            if load_session:
                if load_session.session_token:
                    if 'url' in load_session.session_token:
                        if load_session.session_token['url'] == 'https://chat.openai.com':
                            load_session.session_token['url'] = 'https://chatgpt.com'
            session.session_token = load_session.session_token
            session.login_cookies = load_session.login_cookies
            session.last_wss = load_session.last_wss
            session.device_id = load_session.device_id
            session.login_fail_count = getattr(load_session, "login_fail_count", 0)
            session.max_login_failures = getattr(load_session, "max_login_failures", session.max_login_failures)
            session.login_failure_kind = getattr(load_session, "login_failure_kind", "")
            session.last_login_error = getattr(load_session, "last_login_error", "")
            session.disabled_until = getattr(load_session, "disabled_until", None)
            return session
    except FileNotFoundError:
        session.device_id = str(uuid.uuid4())
        return session
    except Exception as e:
        logger.warning(f"get session_token from file error : {e}")
        return session
            
async def get_paid(page: Page,token: str,chatp: str,device_id: str,logger):
    
    async def route_handle_paid(route: Route, request: Request):
        data = {"p":chatp}
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
        header['Origin'] = header['Referer'] = "https://chatgpt.com"
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

async def flush_page(page: Page,js: tuple, js_used: int) -> int:
    try:
        await page.goto("https://chatgpt.com",wait_until="load")
    except Exception as e:
        pass
    await asyncio.sleep(1)
    res = await page.evaluate_handle(js[0])
    await res.json_value()
    await page.wait_for_load_state('networkidle')
    js_test = await page.evaluate("window._chatp")
    if not js_test:
        js_res = await page.evaluate_handle(js[1])
        await js_res.json_value()
        await asyncio.sleep(2)
        await page.wait_for_load_state("load")
        await asyncio.sleep(4)
        js_test2 = await page.evaluate("window._chatp")
        if js_test2:
            js_used = 1
        else:
            js_res = await page.evaluate(js[1])
            js_used = 0
    else:
        js_used = 0
    return js_used

async def upload_file(msg_data: MsgData,session: Session,logger) -> MsgData:
    page: Page = await session.browser_contexts.new_page() # type: ignore
    try:
        header = {}
        header['authorization'] = 'Bearer ' + session.access_token
        header['Content-Type'] = 'application/json'
        header['Origin'] = "https://chatgpt.com" if "chatgpt" in page.url else 'https://chat.openai.com' 
        header['Referer'] = f"https://chatgpt.com/c/{msg_data.conversation_id}" if msg_data.conversation_id else "https://chatgpt.com"
        header['Accept'] = '*/*'
        header['Accept-Encoding'] = 'gzip, deflate, zstd'
        header['Accept-Language'] = 'zh-CN,zh;q=0.8,zh-TW;q=0.7,zh-HK;q=0.5,en-US;q=0.3,en;q=0.2'
        header['Host'] = 'chatgpt.com'
        header['OAI-Device-Id'] = session.device_id  
        header['OAI-Language'] = 'en-US'
        header['Connection'] = 'keep-alive'
        header['Sec-Fetch-Dest'] = 'empty'
        header['Sec-Fetch-Mode'] = 'cors'
        header['Sec-Fetch-Site'] = 'same-origin'
        header['Sec-GPC'] = '1'      
        logger.debug(f"{session.email} have {len(msg_data.upload_file)}'s file")
        for index,file in enumerate(msg_data.upload_file):
            async def route_files(route: Route, request: Request):
                logger.debug(f"{session.email} begin create upload cookie and header")
                payload = {
                    "file_name":file.name,
                    "file_size":file.size,
                    "use_case":"multimodal",
                    "timezone_offset_min":-480,
                    "reset_rate_limits":False
                    } 
                header["User-Agent"] = request.headers["user-agent"]
                header['Content-Length'] = str(len(json.dumps(payload).encode('utf-8')))
                header["Cookie"] = request.headers["cookie"] 
                logger.debug(f"{session.email} will continue_ upload")
                await route.continue_(method="POST", headers=header, post_data=payload)         
            await page.route("**/backend-api/files", route_files)  
            
            async def route_put(route: Route, request: Request):
                logger.debug(f"{session.email} begin create put cookie and header")
                header_put = {}
                header_put['Accept'] = "application/json, text/plain, */*"
                header_put['Host'] = "files.oaiusercontent.com"
                header_put['Accept-Language'] = "zh-CN,zh;q=0.8,zh-TW;q=0.7,zh-HK;q=0.5,en-US;q=0.3,en;q=0.2"
                header_put['Accept-Encoding'] = "gzip, deflate"
                header_put['Referer'] = "https://chatgpt.com/"
                header_put['x-ms-blob-type'] = "BlockBlob"
                header_put['x-ms-version'] = "2020-04-08"
                header_put['Content-Length'] = str(file.size)
                header_put['Content-Type'] = file.mime_type
                header_put['Origin'] = "https://chatgpt.com"
                header_put['Connection'] = "keep-alive"
                header_put['Sec-Fetch-Dest'] = 'empty'
                header_put['Sec-Fetch-Mode'] = 'cors'
                header_put['Sec-Fetch-Site'] = 'same-origin'
                header_put["User-Agent"] = request.headers["user-agent"]
                header_put["Cookie"] = request.headers["cookie"] 
                logger.debug(f"{session.email} will continue_ put")
                await route.continue_(method="PUT", headers=header_put, post_data=file.content)
            await page.route("**/file-**", route_put)  
            
            retry = 3
            while retry != 0:
                
                logger.debug(f"{session.email} begin upload")
                async with page.expect_response("https://chatgpt.com/backend-api/files",timeout=120000) as response_info: # type: ignore
                    await page.goto("https://chatgpt.com/backend-api/files",timeout=60000)
                    res_value = await response_info.value   
                    res: dict = await res_value.json()
                    if res_value.status in (200,201):
                        msg_data.upload_file[index].upload_url = file.upload_url = res['upload_url']
                        msg_data.upload_file[index].file_id = file.file_id = res['file_id']
                        logger.debug(f"{session.email} upload get id: {file.file_id} url: {file.upload_url}")
                    else:
                        logger.debug(f"{session.email} upload error,retry:{retry},status:{res_value.status} {res_value.status_text},{await res_value.text()}")
                        retry -= 1
                        continue
                logger.debug(f"{session.email} begin put")
            
                async with page.expect_response(file.upload_url,timeout=120000) as response_info: # type: ignore
                    await page.goto(file.upload_url,timeout=60000) # type: ignore
                    res_value = await response_info.value   
                    if res_value.status in (200,201):
                        logger.debug(f"{session.email} put ok")
                        break
                    else:
                        logger.debug(f"{session.email} put error,retry:{retry},status:{res_value.status} {res_value.status_text},{await res_value.text()}")
                        retry -= 1
                        await asyncio.sleep(1)

            async def route_uploaded(route: Route, request: Request):
                logger.debug(f"{session.email} begin create uploaded cookie and header")
                payload = {} 
                header["User-Agent"] = request.headers["user-agent"]
                header['Content-Length'] = "2"
                header["Cookie"] = request.headers["cookie"] 
                logger.debug(f"{session.email} will continue_ uploaded")
                await route.continue_(method="POST", headers=header, post_data=payload)         
            await page.route("**/backend-api/files/file-**/uploaded", route_uploaded)  
            logger.debug(f"{session.email} began uploaded")
            retry = 3
            while retry != 0:
                async with page.expect_response(f"https://chatgpt.com/backend-api/files/{file.file_id}/uploaded",timeout=120000) as response_info: # type: ignore
                    await page.goto(f"https://chatgpt.com/backend-api/files/{file.file_id}/uploaded",timeout=60000)
                    res_value = await response_info.value   
                    res: dict = await res_value.json()
                    if res['status'] == "success":
                        logger.debug(f"{session.email} uploaded ok")
                        break
                    else:
                        logger.debug(f"{session.email} uploaded faid,retry:{retry},https://chatgpt.com/backend-api/files/{file.file_id}/uploaded {res_value.status} {res_value.status_text} {res}")
                        retry -= 1
    except Exception as e:
        logger.warning(f"upload file error:{e}")
    finally:
        await page.close()
        return msg_data
    
async def save_screen(save_screen_status: bool, path: str,page: Page):
    if save_screen_status:
        screen_path = Path("screen")
        screen_path.mkdir(parents=True, exist_ok=True)
        now = datetime.now()
        time_str = now.strftime("%Y_%m_%d_%H_%M_%S") 
        screenshot_path = screen_path / f"{path}_{time_str}.png"
        await page.screenshot(path=screenshot_path)
        screenshots = list(screen_path.glob(f"{path}_*.png"))
        max_files = 10
        if len(screenshots) > max_files:
            screenshots.sort(key=lambda f: f.stat().st_ctime)
            files_to_delete = screenshots[:len(screenshots) - max_files]
            for file in files_to_delete:
                # print(f"Deleting old screenshot: {file}")
                file.unlink()

async def get_json_url(send_page: Page,session: Session,url: str,logger) -> dict:
    async with send_page.expect_response(url,timeout=70000) as response_info: 
        try:
            logger.debug(f"{session.email} will get gen thumbnail image url:{url}")
            await send_page.goto(url, timeout=60000,wait_until='networkidle') 
            res_value = await response_info.value
            res_json = await res_value.json()
            return res_json
        except Exception as e:
            a, b, exc_traceback = sys.exc_info()
            logger.warning(f"{session.email} get gen image error:{e},url:{url},line number {exc_traceback.tb_lineno}") # type: ignore
    return {}
