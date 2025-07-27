import io
import uuid
import time
import json
import random
import base64
import typing
import logging
import datetime
import filetype
import urllib.parse


from enum import Enum
from PIL import Image
from pathlib import Path
from dataclasses import dataclass
from aiohttp import ClientSession,ClientWebSocketResponse
from typing import TypedDict, Optional, Literal, List, Dict, Any, Tuple
from playwright_firefox._impl._api_structures import Cookie
from playwright_firefox.async_api import Page, BrowserContext

from pydantic import BaseModel,Field,model_validator,validator,computed_field

url_session = "https://chatgpt.com/api/auth/session"
url_chatgpt = "https://chatgpt.com/backend-api/conversation"
url_check = "https://chatgpt.com/api/auth/session"
url_arkose = "https://tcr9i.chat.openai.com/fc/gt2/public_key/3D86FBBA-9D22-402A-B512-3420086BA6CC"
url_arkose_gpt4 = "https://tcr9i.chat.openai.com/fc/gt2/public_key/35536E1E-65B4-4D96-9D97-6ADB7EFF8147"
url_requirements = "https://chatgpt.com/backend-api/sentinel/chat-requirements"

formator = logging.Formatter(fmt="%(asctime)s %(filename)s %(levelname)s %(message)s", datefmt="%Y/%m/%d %X")


MODEL_DICT = {
        "free":{
            "41m":"gpt-4-1-mini",
            "4om":"gpt-4o-mini",
            "3.5":"text-davinci-002-render-sha",
        },
        "plus":{
            "41m":"gpt-4-1-mini",

            "4om":"gpt-4o-mini",
            "4":"gpt-4",
            "3.5":"text-davinci-002-render-sha",

            "4o":"gpt-4o",
            "o3":"o3",
            "o4m":"o4-mini",
            "o4mh":"o4-mini-high",
            "45":"gpt-4-5",
            "41":"gpt-4-1",

        }
    }

def model_list(plus: bool = False) -> Dict[str, str]:
    '''get model dict'''
    return MODEL_DICT['plus'] if plus else MODEL_DICT["free"]

def all_models_keys():
    '''get all model keys'''
    return list(MODEL_DICT['plus'].keys())

def all_models_values():
    '''get all model names(values)'''
    return list(MODEL_DICT['plus'].values())

def all_free_models_values():
    '''get all model names(values)'''
    return list(MODEL_DICT['free'].values())

def get_model_by_key(key: str, plus: bool = False) -> Optional[str]:
    """get model name by key"""
    models = model_list(plus)
    return models.get(key)

class Status(Enum):
    Login = "Login"
    Working = "Working"
    Stop = "Stop"
    Update = "Update"
    Ready = "Ready"


@dataclass
class Session:
    email: str = ""
    password: str = ""
    access_token: str = ""
    gptplus: bool = False
    session_token: Cookie|None = None
    status: str = ""
    login_state: bool = False
    login_state_first: Optional[bool] = None
    browser_contexts: Optional[BrowserContext] = None
    page: Optional[Page] = None
    user_agent: str = ""
    cookies: str = ""
    login_cookies: Optional[list] = None
    type: str = ""
    help_email: str = ""
    last_wss: str = ""
    wss: Optional[ClientWebSocketResponse] = None
    wss_session: Optional[ClientSession] = None
    device_id: str = ""
    mode: Literal["openai", "google", "microsoft"] = "openai"
    last_active: 'datetime.datetime' = datetime.datetime.now()
    input_session_token = session_token
    
    def __post_init__(self):
        if self.input_session_token is None:
            self.input_session_token = self.session_token

    @property
    def is_valid(self):
        # TODO::
        return True


class Personality:
    def __init__(self, 
                 init_list: List[Dict[str, str]] = [],
                 path: Path = None): # type: ignore
        self.init_list = init_list
        self.path =  path / "personality" if path else Path() / "data" / "chat_history" / "personality"
        init_list += self.read_data(self.path)
        for item in init_list:
            if str(item) not in [str(x) for x in self.init_list]:
                self.init_list.append(item)

    def show_name(self):
        name = [f"{index + 1}. {x.get('name')}" for index, x in enumerate(self.init_list)]
        return '\n'.join(name)

    def get_value_by_name(self, name: str) -> str|None:
        return next((x.get("value") for x in self.init_list if x.get("name") == name), "")

    def add_dict_to_list(self, new_dict: dict):
        self.init_list.append(new_dict)

    def save_data(self):
        tmp = '\n'.join([json.dumps(x) for x in self.init_list])
        try:
            with open(self.path, "w") as f:
                f.write(tmp)
        except:
            pass

    @classmethod
    def read_data(cls,path:str|Path):
        try:
            with open(path, "r") as f:
                init_list = [json.loads(x) for x in f.read().split("\n")]
        except:
            init_list = []
        return init_list

    def flush_data(self,path: Path):
        self.save_data()
        self.read_data(path)

    def del_data_by_name(self, name: str):
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

class IOFile(BaseModel):
    '''### content: bytes
    ### name: str'''
    content: bytes
    name: str
    file_id: Optional[str] = Field(None, description="File identifier")
    upload_url: Optional[str] = Field(None, description="Upload URL")
    size: Optional[int] = Field(None, description="File size in bytes")
    mime_type: Optional[str] = Field(None, description="Detected MIME type")
    content_type: Optional[str] = Field(None, description="Content type")
    width: Optional[int] = Field(None, description="Image width (if application)")
    height: Optional[int] = Field(None, description="Image height (if application)")

    @model_validator(mode="after")
    def calculate_properties(self) -> "IOFile":
        self.size = len(self.content)

        kind = filetype.guess(self.content)
        self.mime_type = kind.mime if kind else 'application/octet-stream'

        if self.mime_type and "image" in self.mime_type:
            self.content_type = "image_asset_pointer"

            self.width, self.height = self._get_image_dimensions()
        else:
            self.content_type = None

        return self
    
    def _get_image_dimensions(self) -> Tuple[int, int]:
        try:
            image = Image.open(io.BytesIO(self.content))
            return image.size
        except Exception:
            return (0, 0)
        
    
    # def get_size(self):
    #     return len(self.content)
        
    # def get_mime_type(self):
    #     kind = filetype.guess(self.content)
    #     return kind.mime if kind else 'application/octet-stream'
        
    # def get_hw(self) -> tuple:
    #     image = Image.open(io.BytesIO(self.content))
    #     return image.size
    
    @property
    def to_dict(self) -> Dict[str, Any]:
        if self.content_type == "image_asset_pointer":
            return {
                "asset_pointer": f"file-service://{self.file_id}",
                "content_type": self.content_type,
                "height": self.height,
                "size_bytes": self.size,
                "width": self.width
            }
        return {}
        
    @property
    def to_attachment(self) -> Dict[str, Any]:
        attachment = {
            "id": self.file_id,
            "mime_type": self.mime_type,
            "name": self.name,
            "size": self.size
        }
        if self.content_type == "image_asset_pointer":
            attachment.update({
                "height": self.height,
                "width": self.width
            })
        return attachment
    

class MsgData(BaseModel):
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
    error_info : error info
    gpt4o: this msg used gpt40
    upload_file: upload file in this msg
    upload_file_name: the name of upload file in this msg
    '''
    # 状态字段
    status: bool = Field(False, description="操作执行状态")
    msg_md2img: bool = Field(False,description="markdown to image status")
    
    # 消息类型
    msg_type: Optional[Literal["old_session", "back_loop", "new_session"]] = Field(
        "new_session", description="操作类型: old_session, back_loop, new_session"
    )
    
    # 消息内容
    msg_send: str = Field("hi", description="待发送消息")
    msg_recv: str = Field("", description="待接收消息")
    msg_raw: List[str] = Field([],description="原始消息")
    msg_md_img: bytes = Field(b"",description="markdown to image")
    error_info: str = Field("", description="错误信息")
    
    # 会话标识
    conversation_id: str = Field("", description="会话id")
    p_msg_id: str = Field("", description="待发送上下文id")
    next_msg_id: str = Field("", description="待接收上下文id")
    last_id: str = Field("", description="最后消息ID")
    last_wss: str = Field("", description="最后WebSocket地址")
    title: str = Field("", description="conversation title")
    image_gen: bool = Field(False, description="image generation")
    from_email: str = Field("", description="from email")
    # 请求数据
    post_data: str = Field("", description="POST请求数据")
    # Arkose 验证相关
    arkose_data: str = Field("", description="Arkose验证数据")
    arkose_header: Dict[str, str] = Field({}, description="Arkose验证头")
    arkose: Optional[str] = Field(None, description="Arkose令牌")
    sentinel: str = Field("", description="sentinel")
    # 请求头
    header: Dict[str, str] = Field({}, description="HTTP请求头")
    # 模型选择
    gpt_model: str = Field(
        MODEL_DICT['free']['41m'], 
        description="使用的GPT模型"
    )
    gpt_plus: bool = Field(False, description="use plus account")
    # 文件处理
    upload_file: List[IOFile] = Field(
        [], 
        description="上传文件列表"
    )
    
    download_file: List[IOFile] = Field(
        [], 
        description="下载文件列表"
    )
    
    # 图像处理
    img_list: List[Dict] = Field(
        [], 
        description="图像列表"
    )
    
    # 功能开关
    web_search: bool = Field(
        False, 
        description="是否启用网页搜索"
    )
    
    deep_research: bool = Field(
        False, 
        description="是否启用深度研究"
    )

    def is_plus_model(self) -> bool:
        """检查当前模型是否属于Plus模型"""
        return self.gpt_model in all_models_values() and self.gpt_model not in all_free_models_values()

    @model_validator(mode="after")
    def validate_plus(self) -> 'MsgData':
        if self.is_plus_model():
            self.gpt_plus = True
        return self
    
    def __setattr__(self, name, value):
        super().__setattr__(name, value)
        if name == "gpt_model":
            self.gpt_plus = self.is_plus_model()

    # @model_validator(mode="after")
    # def validate_model(self):
    #     """验证模型名称是否有效"""
    #     # 获取所有可能的模型值
    #     all_models = set()
    #     for models in MODEL_DICT.values():
    #         all_models.update(models.values())
        
    #     if value not in all_models:
    #         raise ValueError(
    #             f"无效的模型名称: '{value}'. "
    #             f"有效模型包括: {', '.join(all_models)}"
    #         )
    #     return value

class Payload():
        
    @staticmethod
    def new_payload(prompt: str, gpt_model: str = Field(MODEL_DICT['free']['41m'],description="used gpt model"), files: Optional[List[IOFile]] = None, search: bool = False) -> str:
        create_time = time.time()
        files = files or []
        is_image = any(files.content_type == "image_asset_pointer" for files in files)
        parts = [files.to_dict for files in files if files.content_type == "image_asset_pointer"] if is_image else [prompt]
        content_type = "multimodal_text" if is_image else "text"
        attachments = [file.to_attachment for file in files]
        
        return json.dumps({
            "action": "next",
            "client_contextual_info": {
                "is_dark_mode": False,
                "time_since_loaded": 19,
                "page_height": 992,
                "page_width": 1100,
                "pixel_ratio": 1.25,
                "screen_height": 1152,
                "screen_width": 2048
            },
            "client_reported_search_source": "conversation_composer_web_icon",
            "conversation_mode": {
                "kind": "primary_assistant"
            },
            "enable_message_followups": True,
            "force_use_search": search,
            "infer_debug_info": {},
            "messages": [{
                "author": {
                    "role": "user"
                },
                "content": {
                    "content_type": content_type,
                    "parts": parts + ([prompt] if is_image else [])
                },
                "create_time": create_time,
                "id": str(uuid.uuid4()),
                "metadata": {
                    "selected_all_github_repos": False,
                    "selected_github_repos": [],
                    "attachments": attachments,
                    "system_hints": ["search"] if search else [],
                } if attachments else {"selected_all_github_repos": False,"selected_github_repos": [],"serialization_metadata": {"custom_symbol_offsets": []},"system_hints": ["search"] if search else [],},
            }],
            "model": gpt_model,
            "paragen_cot_summary_display_override": "allow",
            "parent_message_id": "client-created-root",# "aaa" + str(uuid.uuid4())[3:],
            
            "supported_encodings": [
                "v1"
            ],
            "supports_buffering": True,
            "system_hints": [],
            "timezone": "Asia/Shanghai",
            "timezone_offset_min": -480,
            # "suggestions": [],
            # "history_and_training_disabled": False,
            # "conversation_origin": None,
            # "force_paragen": False,
            # "force_nulligen":False,
            # "force_rate_limit": False,
            # "force_paragen_model_slug": "",
            # "force_use_sse": True,
            # "reset_rate_limits": False,
            # "websocket_request_id": str(uuid.uuid4()),
            # "paragen_stream_type_override": None,
            
        })

    @staticmethod
    def old_payload(prompt: str, conversation_id: str, p_msg_id: str,gpt_model: str = Field(MODEL_DICT['free']['41m'],description="used gpt model"),files: Optional[List[IOFile]] = None, search: bool = False ) -> str:
        create_time = time.time()
        files = files or []
        is_image = any(files.content_type == "image_asset_pointer" for files in files)
        parts = [files.to_dict for files in files if files.content_type == "image_asset_pointer"] if is_image else [prompt]
        content_type = "multimodal_text" if is_image else "text"
        attachments = [file.to_attachment for file in files]
        return json.dumps({
            "action":
                "next",
            "client_contextual_info": {
                "is_dark_mode": False,
                "time_since_loaded": 19,
                "page_height": 992,
                "page_width": 1100,
                "pixel_ratio": 1.25,
                "screen_height": 1152,
                "screen_width": 2048
            },
            "client_reported_search_source": "conversation_composer_web_icon",
            "conversation_mode": {
                "kind": "primary_assistant",
            },
            "enable_message_followups": True,
            "force_use_search": search,
            "infer_debug_info": {},
            "messages": [{
                "id": str(uuid.uuid4()),
                "author": {
                    "role": "user"
                },
                "content": {
                    "content_type": content_type,
                    "parts": parts + ([prompt] if is_image else [])
                },
                "create_time": create_time,
                "metadata": {
                    "selected_all_github_repos": False,
                    "selected_github_repos": [],
                    "attachments": attachments,
                    "system_hints": ["search"] if search else [],
                } if attachments else {"selected_all_github_repos": False,"selected_github_repos": [],"serialization_metadata": {"custom_symbol_offsets": []},"system_hints": ["search"] if search else [],},
            }],
            "conversation_id":
                conversation_id,
            "parent_message_id":
                p_msg_id,
            "model":
                gpt_model,
            "timezone_offset_min":
                -480,
            "timezone": "Asia/Shanghai",
            # "suggestions": [],
            # "force_paragen": False,
            # "force_paragen_model_slug": "",
            # "force_rate_limit": False,
            # "reset_rate_limits": False,
            # "websocket_request_id": str(uuid.uuid4()),
            "system_hints": [],
            "supported_encodings": [
                "v1"
            ],
            # "conversation_origin": None,
            # "paragen_stream_type_override": None,
            "paragen_cot_summary_display_override": "allow",
            "supports_buffering": True
        })

    @staticmethod
    def headers(token: str, data: str,device_id: str):
        return {
            "Host": "chat.openai.com",
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh;q=0.8,zh-TW;q=0.7,zh-HK;q=0.5,en-US;q=0.3,en;q=0.2",
            "Accept-Encoding": "gzip, deflate",
            "Content-Type": "application/json",
            "Content-Length": str(len(str(data))),
            "Referer": "https://chat.openai.com/",
            "Authorization": f"Bearer {token}",
            "OAI-Device-Id": device_id,
            "OAI-Language": "en-US",
            "Origin": "https://chat.openai.com",
            "Connection": "keep-alive",
            "sec-ch-ua-mobile": "?0",
            # "sec-ch-ua-platform": "\"Windows\"",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin"
            # "TE": "trailers"
        }

    @staticmethod
    def rdm_arkose(ua: str, bda: str) -> str:
        return urllib.parse.urlencode(
            {
                "bda": bda,
                "public_key": "3D86FBBA-9D22-402A-B512-3420086BA6CC",
                "site": "https://chat.openai.com",
                "capi_version": "1.5.5",
                "capi_mode": "inline",
                "style_theme": "default",
                "userbrowser": ua,
                "rnd": f"0.{random.randint(10 ** 15, 10 ** 18 - 1)}",
            }
        )
    @staticmethod
    def rdm_arkose_new(ua: str, bda: str, paid) -> str:
        return urllib.parse.urlencode(
            {
                "bda": bda,
                "public_key": "35536E1E-65B4-4D96-9D97-6ADB7EFF8147",
                "site": "https://chat.openai.com",
                "userbrowser": ua,
                "capi_version": "2.4.3",
                "capi_mode": "inline",
                "style_theme": "default",
                "rnd": f"0.{random.randint(10 ** 15, 10 ** 18 - 1)}",
                "data[blob]":paid
            }
        )
        
    @staticmethod
    def header_arkose(data: str):
        return {
            "Host": "tcr9i.chat.openai.com",
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh;q=0.8,zh-TW;q=0.7,zh-HK;q=0.5,en-US;q=0.3,en;q=0.2",
            "Accept-Encoding": "gzip, deflate",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Content-Length": str(len(data)),
            "Origin": "https://tcr9i.chat.openai.com",
            "Connection": "keep-alive",
            "Referer": "https://tcr9i.chat.openai.com/v2/2.4.3/enforcement.f6478716f67eb008b598024953b7143d.html",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        }

    @staticmethod
    def get_data():
        old_bda1: str = r'[{"key":"api_type","value":"js"},{"key":"p","value":1},{"key":"f","value":"e044ef78d628d5ddb3fffb713817e113"},{"key":"n","value":"'
        old_bda2: str = r'"},{"key":"wh","value":"1eeb1284b181b4d4b6814e7ed617dcf7|5ab5738955e0611421b686bc95655ad0"},{"key":"enhanced_fp","value":[{"key":"webgl_extensions","value":"ANGLE_instanced_arrays;EXT_blend_minmax;EXT_color_buffer_half_float;EXT_float_blend;EXT_frag_depth;EXT_shader_texture_lod;EXT_sRGB;EXT_texture_compression_bptc;EXT_texture_compression_rgtc;EXT_texture_filter_anisotropic;OES_element_index_uint;OES_fbo_render_mipmap;OES_standard_derivatives;OES_texture_float;OES_texture_float_linear;OES_texture_half_float;OES_texture_half_float_linear;OES_vertex_array_object;WEBGL_color_buffer_float;WEBGL_compressed_texture_s3tc;WEBGL_compressed_texture_s3tc_srgb;WEBGL_debug_renderer_info;WEBGL_debug_shaders;WEBGL_depth_texture;WEBGL_draw_buffers;WEBGL_lose_context;WEBGL_provoking_vertex"},{"key":"webgl_extensions_hash","value":"c602e4d0f2e623f401e51e32cb465ed7"},{"key":"webgl_renderer","value":"ANGLE (NVIDIA, NVIDIA GeForce GTX 980 Direct3D11 vs_5_0 ps_5_0)"},{"key":"webgl_vendor","value":"Mozilla"},{"key":"webgl_version","value":"WebGL 1.0"},{"key":"webgl_shading_language_version","value":"WebGL GLSL ES 1.0"},{"key":"webgl_aliased_line_width_range","value":"[1, 1]"},{"key":"webgl_aliased_point_size_range","value":"[1, 1024]"},{"key":"webgl_antialiasing","value":"yes"},{"key":"webgl_bits","value":"8,8,24,8,8,0"},{"key":"webgl_max_params","value":"16,32,16384,1024,16384,16,16384,30,16,16,4095"},{"key":"webgl_max_viewport_dims","value":"[32767, 32767]"},{"key":"webgl_unmasked_vendor","value":"Google Inc. (NVIDIA)"},{"key":"webgl_unmasked_renderer","value":"ANGLE (NVIDIA, NVIDIA GeForce GTX 980 Direct3D11 vs_5_0 ps_5_0)"},{"key":"webgl_vsf_params","value":"23,127,127,23,127,127,23,127,127"},{"key":"webgl_vsi_params","value":"0,31,30,0,31,30,0,31,30"},{"key":"webgl_fsf_params","value":"23,127,127,23,127,127,23,127,127"},{"key":"webgl_fsi_params","value":"0,31,30,0,31,30,0,31,30"},{"key":"webgl_hash_webgl","value":"269baaa8291a5a86d34ab298bb929207"},{"key":"user_agent_data_brands","value":null},{"key":"user_agent_data_mobile","value":null},{"key":"navigator_connection_downlink","value":null},{"key":"navigator_connection_downlink_max","value":null},{"key":"network_info_rtt","value":null},{"key":"network_info_save_data","value":null},{"key":"network_info_rtt_type","value":null},{"key":"screen_pixel_depth","value":24},{"key":"navigator_device_memory","value":null},{"key":"navigator_languages","value":"en-US,en"},{"key":"window_inner_width","value":0},{"key":"window_inner_height","value":0},{"key":"window_outer_width","value":1280},{"key":"window_outer_height","value":720},{"key":"browser_detection_firefox","value":true},{"key":"browser_detection_brave","value":false},{"key":"audio_codecs","value":"{\\"ogg\\":\\"probably\\",\\"mp3\\":\\"maybe\\",\\"wav\\":\\"probably\\",\\"m4a\\":\\"maybe\\",\\"aac\\":\\"maybe\\"}"},{"key":"video_codecs","value":"{\\"ogg\\":\\"probably\\",\\"h264\\":\\"probably\\",\\"webm\\":\\"probably\\",\\"mpeg4v\\":\\"\\",\\"mpeg4a\\":\\"\\",\\"theora\\":\\"\\"}"},{"key":"media_query_dark_mode","value":false},{"key":"headless_browser_phantom","value":false},{"key":"headless_browser_selenium","value":false},{"key":"headless_browser_nightmare_js","value":false},{"key":"document__referrer","value":""},{"key":"window__ancestor_origins","value":null},{"key":"window__tree_index","value":[1]},{"key":"window__tree_structure","value":"[[],[]]"},{"key":"window__location_href","value":"https://tcr9i.chat.openai.com/v2/1.5.5/enforcement.fbfc14b0d793c6ef8359e0e4b4a91f67.html#3D86FBBA-9D22-402A-B512-3420086BA6CC"},{"key":"client_config__sitedata_location_href","value":"https://chat.openai.com/"},{"key":"client_config__surl","value":"https://tcr9i.chat.openai.com"},{"key":"mobile_sdk__is_sdk"},{"key":"client_config__language","value":null},{"key":"audio_fingerprint","value":"35.749968223273754"}]},{"key":"fe","value":["DNT:unspecified","L:en-US","D:24","PR:2","S:1280,720","AS:1280,720","TO:-480","SS:true","LS:true","IDB:true","B:false","ODB:false","CPUC:unknown","PK:Win32","CFP:27143903","FR:false","FOS:false","FB:false","JSF:","P:","T:0,false,false","H:16","SWF:false"]},{"key":"ife_hash","value":"9c34512d1ba12162c163aff6d835f71a"},{"key":"cs","value":1},{"key":"jsbd","value":"{\\"HL\\":2,\\"NCE\\":true,\\"DT\\":\\"\\",\\"NWD\\":\\"false\\",\\"DOTO\\":1,\\"DMTO\\":1}"}]'
        tim = base64.b64encode(str(int(time.time())).encode('utf8')).decode('utf8')
        return old_bda1 + tim + old_bda2
    
    @staticmethod
    def get_data_new():
        old_bda1: str = r'[{"key":"api_type","value":"js"},{"key":"f","value":"b953e380a38fe996957473ccf642a63a"},{"key":"n","value":"'
        old_bda2: str = r'"},{"key":"wh","value":"02aaa7309775645028aecc8590cd13da|72627afbfd19a741c7da1732218301ac"},{"key":"enhanced_fp","value":[{"key":"webgl_extensions","value":"ANGLE_instanced_arrays;EXT_blend_minmax;EXT_clip_control;EXT_color_buffer_half_float;EXT_depth_clamp;EXT_disjoint_timer_query;EXT_float_blend;EXT_frag_depth;EXT_polygon_offset_clamp;EXT_shader_texture_lod;EXT_texture_compression_bptc;EXT_texture_compression_rgtc;EXT_texture_filter_anisotropic;EXT_sRGB;KHR_parallel_shader_compile;OES_element_index_uint;OES_fbo_render_mipmap;OES_standard_derivatives;OES_texture_float;OES_texture_float_linear;OES_texture_half_float;OES_texture_half_float_linear;OES_vertex_array_object;WEBGL_blend_func_extended;WEBGL_color_buffer_float;WEBGL_compressed_texture_s3tc;WEBGL_compressed_texture_s3tc_srgb;WEBGL_debug_renderer_info;WEBGL_debug_shaders;WEBGL_depth_texture;WEBGL_draw_buffers;WEBGL_lose_context;WEBGL_multi_draw;WEBGL_polygon_mode"},{"key":"webgl_extensions_hash","value":"a7a3e349689be1d59e501cd4e7043578"},{"key":"webgl_renderer","value":"WebKitWebGL"},{"key":"webgl_vendor","value":"WebKit"},{"key":"webgl_version","value":"WebGL1.0(OpenGLES2.0Chromium)"},{"key":"webgl_shading_language_version","value":"WebGLGLSLES1.0(OpenGLESGLSLES1.0Chromium)"},{"key":"webgl_aliased_line_width_range","value":"[1,1]"},{"key":"webgl_aliased_point_size_range","value":"[1,1024]"},{"key":"webgl_antialiasing","value":"yes"},{"key":"webgl_bits","value":"8,8,24,8,8,0"},{"key":"webgl_max_params","value":"16,32,16384,1024,16384,16,16384,30,16,16,4095"},{"key":"webgl_max_viewport_dims","value":"[32767,32767]"},{"key":"webgl_unmasked_vendor","value":"GoogleInc.(NVIDIA)"},{"key":"webgl_unmasked_renderer","value":"ANGLE(NVIDIA,NVIDIAGeForceRTX4090(0x00002684)Direct3D11vs_5_0ps_5_0,D3D11)"},{"key":"webgl_vsf_params","value":"23,127,127,23,127,127,23,127,127"},{"key":"webgl_vsi_params","value":"0,31,30,0,31,30,0,31,30"},{"key":"webgl_fsf_params","value":"23,127,127,23,127,127,23,127,127"},{"key":"webgl_fsi_params","value":"0,31,30,0,31,30,0,31,30"},{"key":"webgl_hash_webgl","value":"02031c2d1b986c59452de7c127d567cf"},{"key":"user_agent_data_brands","value":"Chromium,Not(A:Brand,GoogleChrome"},{"key":"user_agent_data_mobile","value":false},{"key":"navigator_connection_downlink","value":1.45},{"key":"navigator_connection_downlink_max","value":null},{"key":"network_info_rtt","value":400},{"key":"network_info_save_data","value":false},{"key":"network_info_rtt_type","value":null},{"key":"screen_pixel_depth","value":24},{"key":"navigator_device_memory","value":8},{"key":"navigator_pdf_viewer_enabled","value":true},{"key":"navigator_languages","value":"zh-CN,zh"},{"key":"window_inner_width","value":0},{"key":"window_inner_height","value":0},{"key":"window_outer_width","value":1920},{"key":"window_outer_height","value":1032},{"key":"browser_detection_firefox","value":false},{"key":"browser_detection_brave","value":false},{"key":"browser_api_checks","value":["permission_status:true","eye_dropper:true","audio_data:true","writable_stream:true","css_style_rule:true","navigator_ua:true","barcode_detector:false","display_names:true","contacts_manager:false","svg_discard_element:false","usb:defined","media_device:defined","playback_quality:true"]},{"key":"browser_object_checks","value":"554838a8451ac36cb977e719e9d6623c"},{"key":"audio_codecs","value":"{\"ogg\":\"probably\",\"mp3\":\"probably\",\"wav\":\"probably\",\"m4a\":\"maybe\",\"aac\":\"probably\"}"},{"key":"audio_codecs_extended","value":"{\"audio/mp4;codecs=\\\"mp4a.40\\\"\":{\"canPlay\":\"maybe\",\"mediaSource\":false},\"audio/mp4;codecs=\\\"mp4a.40.1\\\"\":{\"canPlay\":\"\",\"mediaSource\":false},\"audio/mp4;codecs=\\\"mp4a.40.2\\\"\":{\"canPlay\":\"probably\",\"mediaSource\":true},\"audio/mp4;codecs=\\\"mp4a.40.3\\\"\":{\"canPlay\":\"\",\"mediaSource\":false},\"audio/mp4;codecs=\\\"mp4a.40.4\\\"\":{\"canPlay\":\"\",\"mediaSource\":false},\"audio/mp4;codecs=\\\"mp4a.40.5\\\"\":{\"canPlay\":\"probably\",\"mediaSource\":true},\"audio/mp4;codecs=\\\"mp4a.40.6\\\"\":{\"canPlay\":\"\",\"mediaSource\":false},\"audio/mp4;codecs=\\\"mp4a.40.7\\\"\":{\"canPlay\":\"\",\"mediaSource\":false},\"audio/mp4;codecs=\\\"mp4a.40.8\\\"\":{\"canPlay\":\"\",\"mediaSource\":false},\"audio/mp4;codecs=\\\"mp4a.40.9\\\"\":{\"canPlay\":\"\",\"mediaSource\":false},\"audio/mp4;codecs=\\\"mp4a.40.12\\\"\":{\"canPlay\":\"\",\"mediaSource\":false},\"audio/mp4;codecs=\\\"mp4a.40.13\\\"\":{\"canPlay\":\"\",\"mediaSource\":false},\"audio/mp4;codecs=\\\"mp4a.40.14\\\"\":{\"canPlay\":\"\",\"mediaSource\":false},\"audio/mp4;codecs=\\\"mp4a.40.15\\\"\":{\"canPlay\":\"\",\"mediaSource\":false},\"audio/mp4;codecs=\\\"mp4a.40.16\\\"\":{\"canPlay\":\"\",\"mediaSource\":false},\"audio/mp4;codecs=\\\"mp4a.40.17\\\"\":{\"canPlay\":\"\",\"mediaSource\":false},\"audio/mp4;codecs=\\\"mp4a.40.19\\\"\":{\"canPlay\":\"\",\"mediaSource\":false},\"audio/mp4;codecs=\\\"mp4a.40.20\\\"\":{\"canPlay\":\"\",\"mediaSource\":false},\"audio/mp4;codecs=\\\"mp4a.40.21\\\"\":{\"canPlay\":\"\",\"mediaSource\":false},\"audio/mp4;codecs=\\\"mp4a.40.22\\\"\":{\"canPlay\":\"\",\"mediaSource\":false},\"audio/mp4;codecs=\\\"mp4a.40.23\\\"\":{\"canPlay\":\"\",\"mediaSource\":false},\"audio/mp4;codecs=\\\"mp4a.40.24\\\"\":{\"canPlay\":\"\",\"mediaSource\":false},\"audio/mp4;codecs=\\\"mp4a.40.25\\\"\":{\"canPlay\":\"\",\"mediaSource\":false},\"audio/mp4;codecs=\\\"mp4a.40.26\\\"\":{\"canPlay\":\"\",\"mediaSource\":false},\"audio/mp4;codecs=\\\"mp4a.40.27\\\"\":{\"canPlay\":\"\",\"mediaSource\":false},\"audio/mp4;codecs=\\\"mp4a.40.28\\\"\":{\"canPlay\":\"\",\"mediaSource\":false},\"audio/mp4;codecs=\\\"mp4a.40.29\\\"\":{\"canPlay\":\"probably\",\"mediaSource\":true},\"audio/mp4;codecs=\\\"mp4a.40.32\\\"\":{\"canPlay\":\"\",\"mediaSource\":false},\"audio/mp4;codecs=\\\"mp4a.40.33\\\"\":{\"canPlay\":\"\",\"mediaSource\":false},\"audio/mp4;codecs=\\\"mp4a.40.34\\\"\":{\"canPlay\":\"\",\"mediaSource\":false},\"audio/mp4;codecs=\\\"mp4a.40.35\\\"\":{\"canPlay\":\"\",\"mediaSource\":false},\"audio/mp4;codecs=\\\"mp4a.40.36\\\"\":{\"canPlay\":\"\",\"mediaSource\":false},\"audio/mp4;codecs=\\\"mp4a.66\\\"\":{\"canPlay\":\"probably\",\"mediaSource\":false},\"audio/mp4;codecs=\\\"mp4a.67\\\"\":{\"canPlay\":\"probably\",\"mediaSource\":true},\"audio/mp4;codecs=\\\"mp4a.68\\\"\":{\"canPlay\":\"probably\",\"mediaSource\":false},\"audio/mp4;codecs=\\\"mp4a.69\\\"\":{\"canPlay\":\"probably\",\"mediaSource\":false},\"audio/mp4;codecs=\\\"mp4a.6B\\\"\":{\"canPlay\":\"probably\",\"mediaSource\":false},\"audio/mp4;codecs=\\\"mp3\\\"\":{\"canPlay\":\"probably\",\"mediaSource\":false},\"audio/mp4;codecs=\\\"flac\\\"\":{\"canPlay\":\"probably\",\"mediaSource\":true},\"audio/mp4;codecs=\\\"bogus\\\"\":{\"canPlay\":\"\",\"mediaSource\":false},\"audio/mp4;codecs=\\\"aac\\\"\":{\"canPlay\":\"\",\"mediaSource\":false},\"audio/mp4;codecs=\\\"ac3\\\"\":{\"canPlay\":\"\",\"mediaSource\":false},\"audio/mp4;codecs=\\\"A52\\\"\":{\"canPlay\":\"\",\"mediaSource\":false},\"audio/mpeg;codecs=\\\"mp3\\\"\":{\"canPlay\":\"probably\",\"mediaSource\":false},\"audio/wav;codecs=\\\"0\\\"\":{\"canPlay\":\"\",\"mediaSource\":false},\"audio/wav;codecs=\\\"2\\\"\":{\"canPlay\":\"\",\"mediaSource\":false},\"audio/wave;codecs=\\\"0\\\"\":{\"canPlay\":\"\",\"mediaSource\":false},\"audio/wave;codecs=\\\"1\\\"\":{\"canPlay\":\"\",\"mediaSource\":false},\"audio/wave;codecs=\\\"2\\\"\":{\"canPlay\":\"\",\"mediaSource\":false},\"audio/x-wav;codecs=\\\"0\\\"\":{\"canPlay\":\"\",\"mediaSource\":false},\"audio/x-wav;codecs=\\\"1\\\"\":{\"canPlay\":\"probably\",\"mediaSource\":false},\"audio/x-wav;codecs=\\\"2\\\"\":{\"canPlay\":\"\",\"mediaSource\":false},\"audio/x-pn-wav;codecs=\\\"0\\\"\":{\"canPlay\":\"\",\"mediaSource\":false},\"audio/x-pn-wav;codecs=\\\"1\\\"\":{\"canPlay\":\"\",\"mediaSource\":false},\"audio/x-pn-wav;codecs=\\\"2\\\"\":{\"canPlay\":\"\",\"mediaSource\":false}}"},{"key":"audio_codecs_extended_hash","value":"805036349642e2569ec299baed02315b"},{"key":"video_codecs","value":"{\"ogg\":\"\",\"h264\":\"probably\",\"webm\":\"probably\",\"mpeg4v\":\"\",\"mpeg4a\":\"\",\"theora\":\"\"}"},{"key":"video_codecs_extended","value":"{\"video/mp4;codecs=\\\"hev1.1.6.L93.90\\\"\":{\"canPlay\":\"probably\",\"mediaSource\":true},\"video/mp4;codecs=\\\"hvc1.1.6.L93.90\\\"\":{\"canPlay\":\"probably\",\"mediaSource\":true},\"video/mp4;codecs=\\\"hev1.1.6.L93.B0\\\"\":{\"canPlay\":\"probably\",\"mediaSource\":true},\"video/mp4;codecs=\\\"hvc1.1.6.L93.B0\\\"\":{\"canPlay\":\"probably\",\"mediaSource\":true},\"video/mp4;codecs=\\\"vp09.00.10.08\\\"\":{\"canPlay\":\"probably\",\"mediaSource\":true},\"video/mp4;codecs=\\\"vp09.00.50.08\\\"\":{\"canPlay\":\"probably\",\"mediaSource\":true},\"video/mp4;codecs=\\\"vp09.01.20.08.01\\\"\":{\"canPlay\":\"probably\",\"mediaSource\":true},\"video/mp4;codecs=\\\"vp09.01.20.08.01.01.01.01.00\\\"\":{\"canPlay\":\"probably\",\"mediaSource\":true},\"video/mp4;codecs=\\\"vp09.02.10.10.01.09.16.09.01\\\"\":{\"canPlay\":\"probably\",\"mediaSource\":true},\"video/mp4;codecs=\\\"av01.0.08M.08\\\"\":{\"canPlay\":\"probably\",\"mediaSource\":true},\"video/webm;codecs=\\\"vorbis\\\"\":{\"canPlay\":\"probably\",\"mediaSource\":true},\"video/webm;codecs=\\\"vp8\\\"\":{\"canPlay\":\"probably\",\"mediaSource\":true},\"video/webm;codecs=\\\"vp8.0\\\"\":{\"canPlay\":\"probably\",\"mediaSource\":false},\"video/webm;codecs=\\\"vp8.0,vorbis\\\"\":{\"canPlay\":\"probably\",\"mediaSource\":false},\"video/webm;codecs=\\\"vp8,opus\\\"\":{\"canPlay\":\"probably\",\"mediaSource\":true},\"video/webm;codecs=\\\"vp9\\\"\":{\"canPlay\":\"probably\",\"mediaSource\":true},\"video/webm;codecs=\\\"vp9,vorbis\\\"\":{\"canPlay\":\"probably\",\"mediaSource\":true},\"video/webm;codecs=\\\"vp9,opus\\\"\":{\"canPlay\":\"probably\",\"mediaSource\":true},\"video/x-matroska;codecs=\\\"theora\\\"\":{\"canPlay\":\"\",\"mediaSource\":false},\"application/x-mpegURL;codecs=\\\"avc1.42E01E\\\"\":{\"canPlay\":\"\",\"mediaSource\":false},\"video/ogg;codecs=\\\"dirac,vorbis\\\"\":{\"canPlay\":\"\",\"mediaSource\":false},\"video/ogg;codecs=\\\"theora,speex\\\"\":{\"canPlay\":\"\",\"mediaSource\":false},\"video/ogg;codecs=\\\"theora,vorbis\\\"\":{\"canPlay\":\"\",\"mediaSource\":false},\"video/ogg;codecs=\\\"theora,flac\\\"\":{\"canPlay\":\"\",\"mediaSource\":false},\"video/ogg;codecs=\\\"dirac,flac\\\"\":{\"canPlay\":\"\",\"mediaSource\":false},\"video/ogg;codecs=\\\"flac\\\"\":{\"canPlay\":\"probably\",\"mediaSource\":false},\"video/3gpp;codecs=\\\"mp4v.20.8,samr\\\"\":{\"canPlay\":\"\",\"mediaSource\":false}}"},{"key":"video_codecs_extended_hash","value":"67b509547efe3423d32a3a70a2553c16"},{"key":"media_query_dark_mode","value":false},{"key":"css_media_queries","value":0},{"key":"css_color_gamut","value":"srgb"},{"key":"css_contrast","value":"no-preference"},{"key":"css_monochrome","value":false},{"key":"css_pointer","value":"fine"},{"key":"css_grid_support","value":false},{"key":"headless_browser_phantom","value":false},{"key":"headless_browser_selenium","value":false},{"key":"headless_browser_nightmare_js","value":false},{"key":"headless_browser_generic","value":4},{"key":"document__referrer","value":"https://chat.openai.com/"},{"key":"window__ancestor_origins","value":["https://chat.openai.com"]},{"key":"window__tree_index","value":[2]},{"key":"window__tree_structure","value":"[[],[],[]]"},{"key":"window__location_href","value":"https://tcr9i.chat.openai.com/v2/2.4.3/enforcement.f6478716f67eb008b598024953b7143d.html"},{"key":"client_config__sitedata_location_href","value":"https://chat.openai.com/"},{"key":"client_config__language","value":null},{"key":"client_config__surl","value":"https://tcr9i.chat.openai.com"},{"key":"client_config__triggered_inline","value":false},{"key":"mobile_sdk__is_sdk","value":false},{"key":"audio_fingerprint","value":"124.04347527516074"},{"key":"navigator_battery_charging","value":true},{"key":"media_device_kinds","value":["audioinput","videoinput","audiooutput"]},{"key":"media_devices_hash","value":"199eba60310b53c200cc783906883c67"},{"key":"navigator_permissions_hash","value":"67419471976a14a1430378465782c62d"},{"key":"math_fingerprint","value":"3b2ff195f341257a6a2abbc122f4ae67"},{"key":"supported_math_functions","value":"e9dd4fafb44ee489f48f7c93d0f48163"},{"key":"screen_orientation","value":"landscape-primary"},{"key":"rtc_peer_connection","value":5},{"key":"4b4b269e68","value":"9766499a-673a-40c3-94c6-8d757fb4e85b"},{"key":"6a62b2a558","value":"f6478716f67eb008b598024953b7143d"},{"key":"speech_default_voice","value":"MicrosoftHuihui-Chinese(Simplified,PRC)||zh-CN"},{"key":"speech_voices_hash","value":"73ad71db4552328df27e3d2c113ddeb2"}]},{"key":"fe","value":["DNT:unknown","L:zh-CN","D:24","PR:2","S:1920,1080","AS:1920,1032","TO:-480","SS:true","LS:true","IDB:true","B:false","ODB:false","CPUC:unknown","PK:Win32","CFP:-73690784","FR:false","FOS:false","FB:false","JSF:","P:ChromePDFViewer,ChromiumPDFViewer,MicrosoftEdgePDFViewer,PDFViewer,WebKitbuilt-inPDF","T:0,false,false","H:16","SWF:false"]},{"key":"ife_hash","value":"20bf4621e1913538ae627cd43398a2bf"},{"key":"jsbd","value":"{\"HL\":5,\"NCE\":true,\"DT\":\"\",\"NWD\":\"false\",\"DMTO\":1,\"DOTO\":1}"}]'
        tim = base64.b64encode(str(int(time.time())).encode('utf8')).decode('utf8')
        return old_bda1 + tim + old_bda2
        
        
    @staticmethod
    def get_key(ua: str):
        t = time.time()  # 获取当前时间的秒数
        bw = round(t - t % 21600)
        return ua + str(bw)

    @staticmethod
    def get_ajs():
        return """const script = document.createElement("script");
script.type = "text/javascript";
script.src = "https://tcr9i.chat.openai.com/cdn/fc/js/6af2c0d87b9879cbf3365be1a208293f84d37b1e/standard/funcaptcha_api.js?onload=loadChallenge";
document.head.appendChild(script);"""