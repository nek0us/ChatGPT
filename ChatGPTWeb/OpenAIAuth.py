# Credits to github.com/rawandahmad698/PyChatGPT
import asyncio
from logging import Logger
import re
from typing import Literal, Optional
import urllib.parse
from playwright.async_api import Route as ARoute, Request as ARequest
from playwright.async_api import Page as APage
from playwright.async_api import Response


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
            mode: Optional[Literal["openai", "google", "microsoft"]] = "openai",
            loop=None
    ):
        self.email_address = email
        self.password = password
        self.page = page
        self.logger = logger
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
        await self.page.goto(
            url="https://chat.openai.com/auth/login",
            wait_until="networkidle"
        )
        await asyncio.sleep(3)
        await self.page.click('[data-testid="login-button"]')
        await self.page.wait_for_load_state(state="networkidle")

        # Select Mode
        if self.mode == "google":
            try:
                await self.page.click('[data-provider="google"] button')
            except Exception as e:
                self.logger.warning(f"google point error:{e}")
                raise e

        elif self.mode == "microsoft":
            try:
                await self.page.click('[data-provider="windowslive"] button')
            except Exception as e:
                self.logger.warning(f"microsoft point error:{e}")
                raise e

        await self.page.wait_for_load_state(state="networkidle")

        # Start Fill
        # TODO: SPlit Parts from select mode
        if self.mode == "microsoft":
            # enter email_address
            await self.page.fill('//*[@id="i0116"]', self.email_address)
            await asyncio.sleep(1)
            await self.page.click('//*[@id="idSIButton9"]')
            await self.page.wait_for_load_state()
            # enter passwd
            await self.page.fill('//*[@id="i0118"]', self.password)
            await asyncio.sleep(1)
            await self.page.click('//*[@id="idSIButton9"]')
            await self.page.wait_for_load_state()
            # don't stay
            await self.page.click('//*[@id="idBtn_Back"]')
            await self.page.wait_for_load_state()


        elif self.mode == "google":
            # enter google email
            EnterKey = "Enter"
            await self.page.fill('//*[@id="identifierId"]', self.email_address)
            await self.page.keyboard.press(EnterKey)
            await self.page.wait_for_load_state()
            # enter passwd
            await self.page.locator(
                "#password > div:nth-child(1) > div:nth-child(1) > div:nth-child(1) > input:nth-child(1)").fill(
                self.password)

            # await self.page.locator("#password > div:nth-child(1) > div:nth-child(1) > div:nth-child(1) > input:nth-child(1)").first.fill(self.password)
            await asyncio.sleep(1)
            await self.page.keyboard.press(EnterKey)
            await self.page.wait_for_load_state()

        else:
            await self.page.fill('[name="username"]', self.email_address)
            await asyncio.sleep(1)
            await self.page.click('button[type="submit"]._button-login-id')
            await self.page.wait_for_load_state(state="networkidle")
            await self.page.locator('[name="password"]').first.fill(self.password)
            await asyncio.sleep(1)
            await self.page.click('button[type="submit"]._button-login-password')
            await self.page.wait_for_load_state(state="networkidle")

        # go chatgpt
        try:
            await self.page.wait_for_url("https://chat.openai.com/")
        except Exception as e:
            self.logger.warning(e)
            # Try Again
            await self.page.wait_for_url("https://chat.openai.com/")

    

    async def get_access_token(self):
        """
        Gets access token
        """
        await self.normal_begin()

        response = await self.page.goto(
            "https://chat.openai.com/api/auth/session",
        )
        if not response or response.status != 200:
            raise await self.auth_error(response)

        self.access_token = (await response.json()).get("accessToken")
        return self.access_token

    async def get_session_token(self):

        try:
            await self.normal_begin()
        except Exception as e:
            await self.page.screenshot(path=f"{self.email_address}_login_error.png")
            self.logger.warning(f"save screenshot {self.email_address}_login_error.png,login error:{e}")
        try:
            cookies = await self.page.context.cookies()
            return next(filter(lambda x: x.get("name") == "__Secure-next-auth.session-token", cookies), None)
        except Exception as e:
            self.logger.warning(f"get cookie error:{e}")
        return None