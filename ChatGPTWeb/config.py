import typing
import uuid
import json
import logging
from typing import TypedDict,Optional,Literal,List,Dict
import random
import urllib.parse
import time
import base64

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
                 arkose: str|None = ""
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
    def new_payload(prompt: str,arkose: str|None) -> str:
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
    def old_payload(prompt: str,conversation_id: str,p_msg_id: str,arkose: str|None) -> str:
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
    def rdm_arkose(ua: str,bda: str) -> str:
        return urllib.parse.urlencode(
            {
                "bda":bda,
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
        
    @staticmethod
    def get_data():
        old_bda1:str = r'[{"key":"api_type","value":"js"},{"key":"p","value":1},{"key":"f","value":"e044ef78d628d5ddb3fffb713817e113"},{"key":"n","value":"'
        old_bda2:str = r'"},{"key":"wh","value":"1eeb1284b181b4d4b6814e7ed617dcf7|5ab5738955e0611421b686bc95655ad0"},{"key":"enhanced_fp","value":[{"key":"webgl_extensions","value":"ANGLE_instanced_arrays;EXT_blend_minmax;EXT_color_buffer_half_float;EXT_float_blend;EXT_frag_depth;EXT_shader_texture_lod;EXT_sRGB;EXT_texture_compression_bptc;EXT_texture_compression_rgtc;EXT_texture_filter_anisotropic;OES_element_index_uint;OES_fbo_render_mipmap;OES_standard_derivatives;OES_texture_float;OES_texture_float_linear;OES_texture_half_float;OES_texture_half_float_linear;OES_vertex_array_object;WEBGL_color_buffer_float;WEBGL_compressed_texture_s3tc;WEBGL_compressed_texture_s3tc_srgb;WEBGL_debug_renderer_info;WEBGL_debug_shaders;WEBGL_depth_texture;WEBGL_draw_buffers;WEBGL_lose_context;WEBGL_provoking_vertex"},{"key":"webgl_extensions_hash","value":"c602e4d0f2e623f401e51e32cb465ed7"},{"key":"webgl_renderer","value":"ANGLE (NVIDIA, NVIDIA GeForce GTX 980 Direct3D11 vs_5_0 ps_5_0)"},{"key":"webgl_vendor","value":"Mozilla"},{"key":"webgl_version","value":"WebGL 1.0"},{"key":"webgl_shading_language_version","value":"WebGL GLSL ES 1.0"},{"key":"webgl_aliased_line_width_range","value":"[1, 1]"},{"key":"webgl_aliased_point_size_range","value":"[1, 1024]"},{"key":"webgl_antialiasing","value":"yes"},{"key":"webgl_bits","value":"8,8,24,8,8,0"},{"key":"webgl_max_params","value":"16,32,16384,1024,16384,16,16384,30,16,16,4095"},{"key":"webgl_max_viewport_dims","value":"[32767, 32767]"},{"key":"webgl_unmasked_vendor","value":"Google Inc. (NVIDIA)"},{"key":"webgl_unmasked_renderer","value":"ANGLE (NVIDIA, NVIDIA GeForce GTX 980 Direct3D11 vs_5_0 ps_5_0)"},{"key":"webgl_vsf_params","value":"23,127,127,23,127,127,23,127,127"},{"key":"webgl_vsi_params","value":"0,31,30,0,31,30,0,31,30"},{"key":"webgl_fsf_params","value":"23,127,127,23,127,127,23,127,127"},{"key":"webgl_fsi_params","value":"0,31,30,0,31,30,0,31,30"},{"key":"webgl_hash_webgl","value":"269baaa8291a5a86d34ab298bb929207"},{"key":"user_agent_data_brands","value":null},{"key":"user_agent_data_mobile","value":null},{"key":"navigator_connection_downlink","value":null},{"key":"navigator_connection_downlink_max","value":null},{"key":"network_info_rtt","value":null},{"key":"network_info_save_data","value":null},{"key":"network_info_rtt_type","value":null},{"key":"screen_pixel_depth","value":24},{"key":"navigator_device_memory","value":null},{"key":"navigator_languages","value":"en-US,en"},{"key":"window_inner_width","value":0},{"key":"window_inner_height","value":0},{"key":"window_outer_width","value":1280},{"key":"window_outer_height","value":720},{"key":"browser_detection_firefox","value":true},{"key":"browser_detection_brave","value":false},{"key":"audio_codecs","value":"{\\"ogg\\":\\"probably\\",\\"mp3\\":\\"maybe\\",\\"wav\\":\\"probably\\",\\"m4a\\":\\"maybe\\",\\"aac\\":\\"maybe\\"}"},{"key":"video_codecs","value":"{\\"ogg\\":\\"probably\\",\\"h264\\":\\"probably\\",\\"webm\\":\\"probably\\",\\"mpeg4v\\":\\"\\",\\"mpeg4a\\":\\"\\",\\"theora\\":\\"\\"}"},{"key":"media_query_dark_mode","value":false},{"key":"headless_browser_phantom","value":false},{"key":"headless_browser_selenium","value":false},{"key":"headless_browser_nightmare_js","value":false},{"key":"document__referrer","value":""},{"key":"window__ancestor_origins","value":null},{"key":"window__tree_index","value":[1]},{"key":"window__tree_structure","value":"[[],[]]"},{"key":"window__location_href","value":"https://tcr9i.chat.openai.com/v2/1.5.5/enforcement.fbfc14b0d793c6ef8359e0e4b4a91f67.html#3D86FBBA-9D22-402A-B512-3420086BA6CC"},{"key":"client_config__sitedata_location_href","value":"https://chat.openai.com/"},{"key":"client_config__surl","value":"https://tcr9i.chat.openai.com"},{"key":"mobile_sdk__is_sdk"},{"key":"client_config__language","value":null},{"key":"audio_fingerprint","value":"35.749968223273754"}]},{"key":"fe","value":["DNT:unspecified","L:en-US","D:24","PR:2","S:1280,720","AS:1280,720","TO:-480","SS:true","LS:true","IDB:true","B:false","ODB:false","CPUC:unknown","PK:Win32","CFP:27143903","FR:false","FOS:false","FB:false","JSF:","P:","T:0,false,false","H:16","SWF:false"]},{"key":"ife_hash","value":"9c34512d1ba12162c163aff6d835f71a"},{"key":"cs","value":1},{"key":"jsbd","value":"{\\"HL\\":2,\\"NCE\\":true,\\"DT\\":\\"\\",\\"NWD\\":\\"false\\",\\"DOTO\\":1,\\"DMTO\\":1}"}]'
        tim = base64.b64encode(str(int(time.time())).encode('utf8')).decode('utf8')
        return old_bda1 + tim + old_bda2
    
    @staticmethod
    def get_key(ua:str):
        t = time.time() # 获取当前时间的秒数
        bw = round(t - t % 21600)
        return ua + str(bw)
        
    @staticmethod
    def get_ajs():
        return """const script = document.createElement("script");
script.type = "text/javascript";
script.src = "https://tcr9i.chat.openai.com/cdn/fc/js/6af2c0d87b9879cbf3365be1a208293f84d37b1e/standard/funcaptcha_api.js?onload=loadChallenge";
document.head.appendChild(script);"""