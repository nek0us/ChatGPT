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
            mode:Optional[Literal["openai", "google", "microsoft"]] = "openai",
            loop=None
    ):
        self.email_address = email
        self.password = password
        self.page = page
        self.logger = logger
        self.mode = mode

        self.access_token = None

    async def auth_error(self,response: Response|None):
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

    async def begin(self) -> None:
        """
        In part two, We make a request to https://chat.openai.com/api/auth/csrf and grab a fresh csrf token
        """
        url = "https://chat.openai.com/api/auth/csrf"

        response = await self.page.goto(
            url=url,
        )
        if not response:
            raise Error(self.__str__(),500,"openai start error")
        if response.status == 200 and "json" in response.headers['content-type']:
            csrf_token = (await response.json())["csrfToken"]
            # self.session.cookies.set("__Host-next-auth.csrf-token", csrf_token)
            await self.__part_one(token=csrf_token)
            

    async def __part_one(self, token: str) -> None:
        """
        We reuse the token from part to make a request to /api/auth/signin/auth0?prompt=login
        """
        url = "https://chat.openai.com/api/auth/signin/auth0?prompt=login"
        payload = f"callbackUrl=%2F&csrfToken={token}&json=true"
        data = {
            "callback_url": "/",
            "csrfToken": token,
            "json": "true",
        }
        payload = self.json_text(data)
        header = {
            "Host": "chat.openai.com",
            'content-type': "application/x-www-form-urlencoded",
            "Accept": "*/*",
            "Sec-Gpc": "1",
            "Accept-Language": "en-US,en;q=0.8",
            "Origin": "https://chat.openai.com",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
            "Referer": "https://chat.openai.com/auth/login",
            "Accept-Encoding": "gzip, deflate",
            #
        }

        async def route_handle(route: ARoute, request: ARequest):
            header["Cookie"] = request.headers["cookie"]
            header["User-Agent"] = request.headers["user-agent"]
            await route.continue_(method="POST", headers=header, post_data=payload)

        await self.page.route(url, route_handle)  # type: ignore
        response = await self.page.goto(url)
        if not response or response.status !=200 or "json" not in response.headers['content-type']:
            raise await self.auth_error(response)
        url = (await response.json())["url"]
        if (
                url == "https://chat.openai.com/api/auth/error?error=OAuthSignin"
                or "error" in url
        ):
            raise await self.auth_error(response)

        await self.__part_two(url=url)
        

    async def __part_two(self, url: str) -> None:
        """
        We make a GET request to url
        :param url:
        :return:
        """

        response = await self.page.goto(url)
        if not response or response.status not in [200, 302]:
            raise await self.auth_error(response)
        
        state = re.findall(r"state=(.*)", await response.text())[0]
        state = state.split('"')[0]

        await self.__part_three(state=state)


    async def __part_three(self, state: str) -> None:
        """
        We use the state to get the login page
        """
        url = f"https://auth0.openai.com/u/login/identifier?state={state}"

        if self.mode == "openai":
            response = await self.page.goto(url)
            if not response or response.status != 200:
                raise await self.auth_error(response)
        elif self.mode == "google":
            try:
                await self.page.click('xpath=/html/body/div/main/section/div/div/div/div[4]/form[2]/button/span[2]')
            except Exception as e:
                self.logger.warning(f"google point error:{e}")
                raise e
            await self.page.wait_for_load_state()
            
        elif self.mode == "microsoft":
            try:
                await self.page.click('xpath=/html/body/div/main/section/div/div/div/div[4]/form[1]/button/span[2]')
            except Exception as e:
                self.logger.warning(f"microsoft point error:{e}")
                raise e
            await self.page.wait_for_load_state()
                
        await self.__part_four(state=state)
        

    async def __part_four(self, state: str) -> None:
        """
        We make a POST request to the login page with the captcha, email
        :param state:
        :return:
        """
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
            # go chatgpt
            try:
                await self.page.wait_for_url("https://chat.openai.com/")
            except Exception as e :
                self.logger.warning(e)
        elif self.mode == "google":
            # enter google email
            EnterKey = "Enter"
            await self.page.fill('//*[@id="identifierId"]', self.email_address)
            await self.page.keyboard.press(EnterKey)
            await self.page.wait_for_load_state()
            # enter passwd
            await self.page.locator("#password > div:nth-child(1) > div:nth-child(1) > div:nth-child(1) > input:nth-child(1)").fill(self.password)
            
            # await self.page.locator("#password > div:nth-child(1) > div:nth-child(1) > div:nth-child(1) > input:nth-child(1)").first.fill(self.password)
            await asyncio.sleep(1)
            await self.page.keyboard.press(EnterKey)
            await self.page.wait_for_load_state()
            # go chatgpt
            try:
                await self.page.wait_for_url("https://chat.openai.com/")
            except Exception as e:
                self.logger.warning(e)
        else:
            url = f"https://auth0.openai.com/u/login/identifier?state={state}"
            email_url_encoded = self.url_encode(self.email_address)
            data = {
                "action": "default",
                "state": state,
                "username": email_url_encoded,
                "js_available": "true",
                "webauthn_available": "true",
                "is_brave": "false",
                "webauthn_platform_available": "false",
            }
            payload = self.json_text(data)
            header = {
                "Host": "auth0.openai.com",
                "Origin": "https://auth0.openai.com",
                "Connection": "keep-alive",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Referer": f"https://auth0.openai.com/u/login/identifier?state={state}",
                "Accept-Language": "en-US,en;q=0.9",
                'content-type': "application/x-www-form-urlencoded",
            }

            async def route_handle(route: ARoute, request: ARequest):
                header["Cookie"] = request.headers["cookie"]
                header["User-Agent"] = request.headers["user-agent"]
                await route.continue_(method="POST", headers=header, post_data=payload)

            await self.page.route(url, route_handle)  # type: ignore
            response = await self.page.goto(url)

            if not response or response.status not in [200, 302]:
                raise await self.auth_error(response)
            
            await self.__part_five(state=state)
            

    async def __part_five(self, state: str) -> None:
        try:
            await self.page.locator('[name="password"]').first.fill(self.password)
            await self.page.evaluate("()=>arkose.run()")
            await self.page.wait_for_url("https://chat.openai.com/")
        except Exception as e:
            cookies = await self.page.context.cookies()
            cookie = next(filter(lambda x: x.get("name") == "__Secure-next-auth.session-token", cookies), None)
            if not cookie:
                # self.logger.warning(f"login part five error:{e}")
                raise e
    async def get_access_token(self):
        """
        Gets access token
        """
        await self.begin()

        response = await self.page.goto(
            "https://chat.openai.com/api/auth/session",
        )
        if not response or response.status != 200:
            raise await self.auth_error(response)
        
        self.access_token = (await response.json()).get("accessToken")
        return self.access_token
        

    async def get_session_token(self):
        
        try:
            await self.begin()
        except Exception as e:
            await self.page.screenshot(path=f"{self.email_address}_login_error.png")
            self.logger.warning(f"save screenshot {self.email_address}_login_error.png,login error:{e}")
        try:
            cookies = await self.page.context.cookies()
            return next(filter(lambda x: x.get("name") == "__Secure-next-auth.session-token", cookies), None)
        except Exception as e:
            self.logger.warning(f"get cookie error:{e}")
        return None

