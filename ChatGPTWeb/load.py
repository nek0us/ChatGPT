from httpx import AsyncClient
import os
from pathlib import Path

async def load_js(httpx_proxy,local_js:bool = False) -> tuple[str,str]:
    if local_js:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        js = os.path.join(current_dir, 'load.js')
        js2 = os.path.join(current_dir, 'load2.js')
        return Path(js).read_text(),Path(js2).read_text()
    else:
        async with AsyncClient(proxy=httpx_proxy,verify=False) as client:
            try:
                res = await client.get(url="https://raw.githubusercontent.com/nek0us/ChatGPT/main/ChatGPTWeb/load.js")
                res2 = await client.get(url="https://raw.githubusercontent.com/nek0us/ChatGPT/main/ChatGPTWeb/load2.js")
            except Exception as e:
                print(e)
        return res.text,res2.text

