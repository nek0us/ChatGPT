import typing
import uuid
import json
import logging
from typing import TypedDict,Optional,Literal,List,Dict
import random
import urllib.parse

url_session = "https://chat.openai.com/api/auth/session"
url_chatgpt = "https://chat.openai.com:443/backend-api/conversation"
url_check = "https://chat.openai.com/api/auth/session"
url_arkose = "https://tcr9i.chat.openai.com/fc/gt2/public_key/3D86FBBA-9D22-402A-B512-3420086BA6CC"

formator = logging.Formatter(fmt = "%(asctime)s %(filename)s %(levelname)s %(message)s",datefmt="%Y/%m/%d %X")


class Personality:
    def __init__(self, init_list: List[Dict[str, str]]):
        self.init_list = []
        init_list += self.read_data()
        for item in init_list:
            if str(item) not in [str(x) for x in self.init_list]:
                self.init_list.append(item)
       
    
    def show_name(self):
        name = [f"{index+1}. {x.get('name')}" for index,x in enumerate(self.init_list)]
        return '\n'.join(name)
    
    
    def get_value_by_name(self, name: str) -> str:
        return next((x.get("value") for x in self.init_list if x.get("name") == name), "")
    
    def add_dict_to_list(self, new_dict: dict):
        self.init_list.append(new_dict)
        
    def save_data(self):
        tmp = '\n'.join([json.dumps(x) for x in self.init_list])
        try:
            with open("data/chat_history/personality","w") as f:
                f.write(tmp)
        except:
            pass
            
    def read_data(self):
        try:
            with open("data/chat_history/personality","r") as f:
                init_list = [json.loads(x) for x in f.read().split("\n")]
        except:
            init_list = []
        return init_list
                
    def flush_data(self):
        self.save_data()
        self.read_data()
        
    def del_data_by_name(self,name:str):
        for item in self.init_list:
            if item.get('name') == name:
                self.init_list.remove(item)
        self.save_data()


class SetCookieParam(TypedDict, total=False):
    name: str
    value: str
    url: Optional[str]
    domain: Optional[str]
    path: Optional[str]
    expires: Optional[float]
    httpOnly: Optional[bool]
    secure: Optional[bool]
    sameSite: Optional[Literal["Lax", "None", "Strict"]]

class ProxySettings(TypedDict, total=False):
    server: str
    bypass: Optional[str]
    username: Optional[str]
    password: Optional[str]

class MsgData():
    def __init__(self,
                 status: bool = False,
                 msg_type: typing.Optional[typing.Literal["old_session","back_loop","new_session"]] = "new_session",
                 msg_send: str = "hi",
                 msg_recv: str = "",
                 conversation_id: str = "",
                 p_msg_id: str = "",
                 next_msg_id: str = "",
                 post_data: str = "",
                 arkose_data: str = "",
                 arkose_header: dict[str,str] = {},
                 arkose: str = ""
                 ) -> None:
        '''
        status ： 操作执行状态
        msg_type ：操作类型
        msg_send ：待发送消息
        msg_recv ：待接收消息
        conversation_id ：会话id
        p_msg_id ：待发送上下文id
        next_msg_id ：待接收上下文id
        arkose_data : arkose http data
        arkose_header : arkose http header
        arkose : arkose
        '''
        self.status = status
        self.msg_type = msg_type
        self.msg_send = msg_send
        self.msg_recv = msg_recv
        self.conversation_id = conversation_id
        self.p_msg_id = p_msg_id
        self.next_msg_id = next_msg_id
        self.post_data = post_data
        self.arkose_data = arkose_data,
        self.arkose_header = arkose_header,
        self.arkose = arkose
        
class Payload():



    @staticmethod
    def new_payload(prompt: str,arkose: str) -> str:
        return json.dumps({
            "action":"next",
            "messages": [{
                "id": str(uuid.uuid4()),
                "author": {
                    "role": "user"
                },
                "content": {
                    "content_type": "text",
                    "parts": [prompt]
                },
                "metadata":{}
            }],
            "parent_message_id":str(uuid.uuid4()),
            "model":"text-davinci-002-render-sha",
            "timezone_offset_min":-480,
            # "suggestions": [
            #     "'Explain what this bash command does: lazy_i18n(\"cat config.yaml | awk NF\"'",
            #     "What are 5 creative things I could do with my kids' art? I don't want to throw them away, but it's also so much clutter.",
            #     "Tell me a random fun fact about the Roman Empire",
            #     "What are five fun and creative activities to do indoors with my dog who has a lot of energy?"
            # ],
            "suggestions": [],
            "history_and_training_disabled":False,
            "arkose_token": arkose,
            "conversation_mode": {
        "kind": "primary_assistant"
    },
            "force_paragen": False,
            "force_rate_limit": False
        })
    @staticmethod
    def old_payload(prompt: str,conversation_id: str,p_msg_id: str,arkose: str) -> str:
        return json.dumps({
            "action":
            "next",
            "history_and_training_disabled":False,
            "messages": [{
                "id": str(uuid.uuid4()),
                "author": {
                    "role": "user"
                },
                "content": {
                    "content_type": "text",
                    "parts": [prompt]
                },
                "metadata":{}
            }],
            "conversation_id":
            conversation_id,
            "parent_message_id":
            p_msg_id,
            "model":
            "text-davinci-002-render-sha",
            "timezone_offset_min":
            -480,
            "suggestions":[],
            "arkose_token":arkose,
            "conversation_mode": {
            "kind": "primary_assistant"
        },
        "force_paragen": False,
        "force_rate_limit": False
        })
    @staticmethod
    def headers(token: str,data: str):
        return {
            "Host": "chat.openai.com",
            "Accept": "text/event-stream",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Accept-Encoding": "gzip, deflate",
            "Content-Type": "application/json",
            "Content-Length": str(len(str(data))),
            "Referer": "https://chat.openai.com/",
            "Authorization": f"Bearer {token}",
            "Origin": "https://chat.openai.com",
            "Connection": "keep-alive",
            "sec-ch-ua-mobile": "?0",
            #"sec-ch-ua-platform": "\"Windows\"", 
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin"
            #"TE": "trailers"
        }
        
    @staticmethod        
    def system_new_payload(prompt: str) -> str:
        return json.dumps({
            "action":
            "next",
            "messages": [{
                "id": str(uuid.uuid4()),
                "author": {
                    "role": "system"
                },
                "content": {
                    "content_type": "text",
                    "parts": [prompt]
                }
            }],
            "parent_message_id":
            str(uuid.uuid4()),
            "model":
            "text-davinci-002-render-sha",
            "timezone_offset_min":
            -480
        })
    
    @staticmethod
    def rdm_arkose(ua: str) -> str:
        return urllib.parse.urlencode(
            {
                "public_key": "3D86FBBA-9D22-402A-B512-3420086BA6CC",
                "site": "https://chat.openai.com",
                "capi_version": "1.5.5",
                "capi_mode": "inline",
                "style_theme": "default",
                "userbrowser": ua,
                "rnd": f"0.{random.randint(10**15, 10**18 - 1)}",
            }
        )
        
    @staticmethod
    def header_arkose(data:str):
        return {
            "Host": "tcr9i.chat.openai.com",
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh;q=0.8,zh-TW;q=0.7,zh-HK;q=0.5,en-US;q=0.3,en;q=0.2",
            "Accept-Encoding": "gzip, deflate, br",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Content-Length": str(len(data)),
            "Origin": "https://tcr9i.chat.openai.com",
            "Connection": "keep-alive",
            "Referer": "https://tcr9i.chat.openai.com/v2/1.5.5/enforcement.fbfc14b0d793c6ef8359e0e4b4a91f67.html",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        }
        