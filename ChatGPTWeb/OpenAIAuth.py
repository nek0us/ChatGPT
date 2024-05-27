# Credits to github.com/rawandahmad698/PyChatGPT
from logging import Logger
from typing import Literal
from playwright.async_api import Page
from playwright.async_api import Response
from playwright_stealth import stealth_async

from .config import url_check

import asyncio
import urllib.parse
import os
import re

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
            page: "Page",
            logger: Logger,
            browser_contexts,
            mode: Literal["openai", "google", "microsoft"] = "openai",
            help_email: str = "",
            loop=None
    ):
        self.email_address = email
        self.password = password
        self.page = page
        self.logger = logger
        self.browser_contexts = browser_contexts
        self.mode = mode
        self.help_email = help_email

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
    

    async def normal_begin(self,logger):
        EnterKey = "Enter"
        await self.browser_contexts.clear_cookies()
        await self.login_page.goto(
            url="https://chat.openai.com/auth/login",
            wait_until="load"
        )
        cf_locator = self.login_page.locator('//*[@id="cf-chl-widget-lpiae"]')
        if await cf_locator.count() > 0:
            logger.warning(f"cf checkbox in {self.email_address}")
        
        await asyncio.sleep(5)
        nologin_home_locator = self.login_page.locator('//html/body/div[1]/div[1]/div[1]/div/div/div/div/nav/div[2]/div[2]/button[2]')
        auth_login = self.login_page.locator('//html/body/div[1]/div[1]/div[2]/div[1]/div/div/button[1]')
        if await nologin_home_locator.count() > 0:
            await nologin_home_locator.click()
        # await self.login_page.wait_for_url("https://auth0.openai.com/**")
        elif await auth_login.count() > 0:
            await auth_login.click()
        else:
            await self.login_page.click('[data-testid="login-button"]')
        await asyncio.sleep(2)
        current_url = self.login_page.url
        use_url = "chat.openai.com"
        if "chatgpt.com" in current_url:
            use_url = "chatgpt.com"
        
        if "auth0" in current_url:
            await self.login_page.wait_for_url("https://auth0.openai.com/**")
        else:
            await self.login_page.wait_for_url("https://auth.openai.com/**")

        # Select Mode
        if self.mode == "google":
            try:
                if "auth0" in self.login_page.url:
                    await self.login_page.click('[data-provider="google"] button')
                else:
                    await self.login_page.click('//html/body/div/div/main/section/div[2]/div[3]/button[1]')
                    
            except Exception as e:
                self.logger.warning(f"google point error:{e}")
                raise e

        elif self.mode == "microsoft":
            try:
                if "auth0" in current_url:
                    await self.login_page.click('//html/body/div/main/section/div/div/div/div[4]/form[1]/button')
                else:
                    
                    await self.login_page.click('//html/body/div/div/main/section/div[2]/div[3]/button[2]')
            except Exception as e:
                self.logger.warning(f"microsoft point error:{e}")
                raise e

        await self.login_page.wait_for_load_state(state="domcontentloaded")

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
            # verify code 
            await self.login_page.wait_for_timeout(1000)
            try:
                await self.login_page.wait_for_url("https://login.live.com/**")
                # await self.login_page.wait_for_url("https://account.live.com/identity/**")
                locator = self.login_page.locator('//*[@id="iProof0"]')
                if await locator.count() > 0:
                    if self.help_email != "":
                        await self.login_page.click('//*[@id="iProof0"]')
                        await self.login_page.fill('//*[@id="iProofEmail"]', self.help_email.split("@")[0])
                        await self.login_page.keyboard.press(EnterKey)
                        await self.login_page.wait_for_load_state()
                        await self.login_page.wait_for_timeout(1000)
                        logger.info(f"please enter {self.email_address} -- help email {self.help_email}'s verify code to {self.email_address}_code.txt")
                        with open(f"{self.email_address}_code.txt","w") as code_file:
                            code_file.write("")
                        with open(f"{self.email_address}_code.txt","r") as code_file:
                            while 1:
                                await asyncio.sleep(1)
                                code = code_file.read()
                                if code != "":
                                    logger.info(f"get {self.email_address} verify code {code}")
                                    await self.login_page.fill('//*[@id="iOttText"]', code)
                                    await self.login_page.keyboard.press(EnterKey)
                                    await self.login_page.wait_for_load_state()
                                    await self.login_page.wait_for_timeout(1000)
                                    break
                        os.unlink(f"{self.email_address}_code.txt")
                    else:
                        logger.warning(f"{self.email_address} not input help_email,but it need help_email's verify code now")
            except Exception as e:
                if "Timeout" not in e.args[0]:
                    raise e
            # don't stay
            await self.login_page.wait_for_timeout(1000)
            await self.login_page.wait_for_url("https://login.live.com/**")
            # await self.page.click('//*[@id="idBtn_Back"]')
            await self.login_page.keyboard.press(EnterKey)
            await self.login_page.wait_for_load_state()


        elif self.mode == "google":
            # enter google email
            await self.login_page.fill('//*[@id="identifierId"]', self.email_address)
            await self.login_page.click('//html/body/div[1]/div[1]/div[2]/c-wiz/div/div[3]/div/div[1]/div/div/button/span')
            # await self.login_page.keyboard.press(EnterKey)
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
            if "auth0" in current_url:
                await self.login_page.fill('[name="username"]', self.email_address)
                await asyncio.sleep(1)
                await self.login_page.click('button[type="submit"]._button-login-id')
            
            else:
                await self.login_page.fill('//*[@id="email-input"]', self.email_address)
                await asyncio.sleep(1)
                await self.login_page.click('//html/body/div/div/main/section/div[2]/button')
            
            
            await self.login_page.wait_for_load_state(state="domcontentloaded")
            await self.login_page.locator('[name="password"]').first.fill(self.password)
            await asyncio.sleep(1)
            await self.login_page.click('button[type="submit"]._button-login-password')
            await self.login_page.wait_for_load_state()

        # go chatgpt
        try:
            await asyncio.sleep(3)
            await self.login_page.wait_for_url(f"https://{use_url}/")
        except Exception as e:
            self.logger.warning(e)
            # Try Again
            await self.login_page.keyboard.press(EnterKey)
            await self.login_page.wait_for_url(f"https://{use_url}/")

        async with self.login_page.expect_response(url_check, timeout=20000) as a:
            res = await self.login_page.goto(url_check, timeout=20000)
        res = await a.value
        if (res.status == 200 or res.status == 307)and res.url == url_check:
            await asyncio.sleep(3)
            await self.login_page.wait_for_load_state('load')
            json_data = await self.login_page.evaluate(
                '() => JSON.parse(document.querySelector("body").innerText)')
            access_token = json_data['accessToken']
            return access_token
        return None
    


    async def get_session_token(self,logger):
        self.login_page: Page = await self.browser_contexts.new_page()
        await stealth_async(self.login_page)
        access_token = None
        try:
            access_token = await self.normal_begin(logger)
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