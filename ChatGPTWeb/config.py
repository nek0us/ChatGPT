import typing
import uuid
import json
import logging
from typing import TypedDict,Optional,Literal,List,Dict

url_session = "https://chat.openai.com/api/auth/session"
url_chatgpt = "https://chat.openai.com:443/backend-api/conversation"

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
    
    
    def get_value_by_name(self, name: str):
        return next((x.get("value") for x in self.init_list if x.get("name") == name), None)
    
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
                 post_data: str = ""
                 ) -> None:
        '''
        status ： 操作执行状态
        msg_type ：操作类型
        msg_send ：待发送消息
        msg_recv ：待接收消息
        conversation_id ：会话id
        p_msg_id ：待发送上下文id
        next_msg_id ：待接收上下文id
        '''
        self.status = status
        self.msg_type = msg_type
        self.msg_send = msg_send
        self.msg_recv = msg_recv
        self.conversation_id = conversation_id
        self.p_msg_id = p_msg_id
        self.next_msg_id = next_msg_id
        self.post_data = post_data
        
class Payload():
    @staticmethod
    def new_payload(prompt: str) -> str:
        return json.dumps({
            "action":
            "next",
            "messages": [{
                "id": str(uuid.uuid4()),
                "author": {
                    "role": "user"
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
    def old_payload(prompt: str,conversation_id: str,p_msg_id: str) -> str:
        return json.dumps({
            "action":
            "next",
            "messages": [{
                "id": str(uuid.uuid4()),
                "author": {
                    "role": "user"
                },
                "content": {
                    "content_type": "text",
                    "parts": [prompt]
                }
            }],
            "conversation_id":
            conversation_id,
            "parent_message_id":
            p_msg_id,
            "model":
            "text-davinci-002-render-sha",
            "timezone_offset_min":
            -480
        })
    @staticmethod
    def headers(token: str,data: str):
        return {
            "Host": "chat.openai.com",
            "User-Agent":
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/109.0",
            "Accept": "text/event-stream",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate, br",
            "Content-Type": "application/json",
            "Content-Length": str(len(str(data))),
            "Referer": "https://chat.openai.com/chat",
            "Authorization": f"Bearer {token}",
            "Origin": "https://chat.openai.com",
            "Connection": "keep-alive",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "TE": "trailers"
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