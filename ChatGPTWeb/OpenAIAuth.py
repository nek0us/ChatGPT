# Credits to github.com/rawandahmad698/PyChatGPT
import asyncio
from logging import Logger
import re
from typing import Literal
import urllib.parse
from playwright.async_api import Route as ARoute, Request as ARequest
from playwright.async_api import Page as APage
from playwright.async_api import BrowserContext
from playwright.async_api import Response
from playwright_stealth import stealth_async

from .config import url_check

class Error(Exception):
    """
    Base error class
    """

    location: str
    status_code: int
    details: str

    def __init__(self, location: str, status_code: int, details: str):
        self.location = location
        self.status_code = status_code
        self.details = details


class AsyncAuth0:
    """
    OpenAI Authentication Reverse Engineered
    """

    def __init__(
            self,
            email: str,
            password: str,
            page: "APage",
            logger: Logger,
            browser_contexts,
            mode: Literal["openai", "google", "microsoft"] = "openai",
            loop=None
    ):
        self.email_address = email
        self.password = password
        self.page = page
        self.logger = logger
        self.browser_contexts = browser_contexts
        self.mode = mode

        self.access_token = None

    async def auth_error(self, response: Response | None):
        return Error(
            location=self.__str__(),
            status_code=response.status if response else 000,
            details=await response.text() if response else f"{self.__str__()} error",
        )

    @staticmethod
    def url_encode(string: str) -> str:
        """
        URL encode a string
        :param string:
        :return:
        """
        return urllib.parse.quote(string)

    @staticmethod
    def json_text(var: dict, sp="&"):
        li = []
        for key, value in var.items():
            li.append(
                f"{key}={value}"
            )
        return f"{sp}".join(li)
    

    async def normal_begin(self):
        EnterKey = "Enter"
        await self.browser_contexts.clear_cookies()
        await self.login_page.goto(
            url="https://chat.openai.com/auth/login",
            wait_until="networkidle"
        )
        await asyncio.sleep(3)
        await self.login_page.click('[data-testid="login-button"]')
        await self.login_page.wait_for_load_state(state="networkidle")

        # Select Mode
        if self.mode == "google":
            try:
                await self.login_page.click('[data-provider="google"] button')
            except Exception as e:
                self.logger.warning(f"google point error:{e}")
                raise e

        elif self.mode == "microsoft":
            try:
                await self.login_page.click('[data-provider="windowslive"] button')
            except Exception as e:
                self.logger.warning(f"microsoft point error:{e}")
                raise e

        await self.login_page.wait_for_load_state(state="networkidle")

        # Start Fill
        # TODO: SPlit Parts from select mode
        if self.mode == "microsoft":
            # enter email_address
            await self.login_page.fill('//*[@id="i0116"]', self.email_address)
            await asyncio.sleep(1)
            await self.login_page.click('//*[@id="idSIButton9"]')
            await self.login_page.wait_for_load_state()
            await asyncio.sleep(1)
            # enter passwd
            await self.login_page.fill('//*[@id="i0118"]', self.password)
            await asyncio.sleep(1)
            await self.login_page.click('//*[@id="idSIButton9"]')
            await self.login_page.wait_for_load_state()
            # don't stay
            await self.login_page.wait_for_timeout(1000)
            # await self.page.click('//*[@id="idBtn_Back"]')
            await self.login_page.keyboard.press(EnterKey)
            await self.login_page.wait_for_load_state()


        elif self.mode == "google":
            # enter google email
            await self.login_page.fill('//*[@id="identifierId"]', self.email_address)
            await self.login_page.keyboard.press(EnterKey)
            await self.login_page.wait_for_load_state()
            # enter passwd
            await self.login_page.locator(
                "#password > div:nth-child(1) > div:nth-child(1) > div:nth-child(1) > input:nth-child(1)").fill(
                self.password)

            # await self.page.locator("#password > div:nth-child(1) > div:nth-child(1) > div:nth-child(1) > input:nth-child(1)").first.fill(self.password)
            await asyncio.sleep(1)
            await self.login_page.keyboard.press(EnterKey)
            await self.login_page.wait_for_load_state()

        else:
            await self.login_page.fill('[name="username"]', self.email_address)
            await asyncio.sleep(1)
            await self.login_page.click('button[type="submit"]._button-login-id')
            await self.login_page.wait_for_load_state(state="networkidle")
            await self.login_page.locator('[name="password"]').first.fill(self.password)
            await asyncio.sleep(1)
            await self.login_page.click('button[type="submit"]._button-login-password')
            await self.login_page.wait_for_load_state(state="networkidle")

        # go chatgpt
        try:
            await self.login_page.wait_for_url("https://chat.openai.com/")
        except Exception as e:
            self.logger.warning(e)
            # Try Again
            await self.login_page.wait_for_url("https://chat.openai.com/")

        async with self.login_page.expect_response(url_check, timeout=20000) as a:
            res = await self.login_page.goto(url_check, timeout=20000)
        res = await a.value
        if res.status == 200 and res.url == url_check:
            await asyncio.sleep(3)
            await self.login_page.wait_for_load_state('load')
            json_data = await self.login_page.evaluate(
                '() => JSON.parse(document.querySelector("body").innerText)')
            access_token = json_data['accessToken']
            return access_token
        return None
    


    async def get_session_token(self):
        self.login_page = await self.browser_contexts.new_page()
        await stealth_async(self.login_page)
        access_token = None
        try:
            access_token = await self.normal_begin()
        except Exception as e:
            self.logger.warning(f"save screenshot {self.email_address}_login_error.png,login error:{e}")
            await self.login_page.screenshot(path=f"{self.email_address}_login_error.png")
        finally:
            cookies = await self.browser_contexts.cookies()
            await self.login_page.close()
            
        try:
            return next(filter(lambda x: x.get("name") == "__Secure-next-auth.session-token", cookies), None),access_token
        except Exception as e:
            self.logger.warning(f"get cookie error:{e}")
        
        return None,None