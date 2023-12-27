import asyncio
from ChatGPTWeb.OpenAIAuth import Auth0
from playwright.sync_api import sync_playwright
from ChatGPTWeb.OpenAIAuth import AsyncAuth0
from playwright.async_api import async_playwright

playwright_manager = sync_playwright()
playwright = playwright_manager.start()
browser = playwright.firefox.launch(headless=True, slow_mo=50, )
context = browser.new_context(service_workers="block")
page = context.new_page()
email = " "
password = " "
self = Auth0(email, password, page)
print(self.get_access_token())


# async def main():
#     playwright_manager = async_playwright()
#     playwright = await playwright_manager.start()
#     browser = await playwright.firefox.launch(headless=True, slow_mo=50, )
#     context = await browser.new_context(service_workers="block")
#     page = await context.new_page()
#     email = " "
#     password = " "
#     self = AsyncAuth0(email, password, page)
#     print(await self.get_access_token())
#
#
# asyncio.run(main())