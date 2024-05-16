from httpx import AsyncClient

async def load_js(httpx_proxy):
    async with AsyncClient(proxies=httpx_proxy) as client:
        res = await client.get(url="https://raw.githubusercontent.com/nek0us/ChatGPT/main/ChatGPTWeb/load.js")
        res2 = await client.get(url="https://raw.githubusercontent.com/nek0us/ChatGPT/main/ChatGPTWeb/load2.js")
    return res.text,res2.text

