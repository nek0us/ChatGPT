# Credits to github.com/rawandahmad698/PyChatGPT
import json
from logging import Logger
from typing import Literal
from playwright.async_api import Page
from playwright.async_api import Response,BrowserContext
from datetime import datetime
from .config import url_check
from pathlib import Path

import asyncio
import urllib.parse
import os

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
        self.browser_contexts: BrowserContext = browser_contexts
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
    
    async def find_cf(self,page: Page):
        # cf_check_box1 = page.locator("//html/body/div/div[2]/form/div/div/div")
        # await cf_check_box1.wait_for(state="attached")  # 确保 iframe 加载完毕
        # if await cf_check_box1.count() > 0:
            # viewport_size = page.viewport_size
            # width = viewport_size['width']
            # height = viewport_size['height']
            # center_x = width // 2
            # center_y = height // 2
            # await page.mouse.move(center_x, center_y)
            # await page.wait_for_timeout(2000)  # 等待 2 秒
            # await page.mouse.click(center_x, center_y)
            # await page.wait_for_timeout(2000)  # 等待 2 秒
            # cf_check_box1.
            # turnstile_frame = page.frame_locator('//html/body/div/div[2]/form/div/div/div/iframe')
            # a = turnstile_frame.get_by_test_id("content")
            # await a.click()
            # cf_check_box1_1 = turnstile_frame.locator("//div/div/div[1]/div/label/input")
            # if await cf_check_box1_1.count() > 0:
            #     await cf_check_box1_1.click()
            #     await asyncio.sleep(10)
        # cf_check_box2 = await page.query_selector("/html/body/div/div[2]/form/div/div/div")
        pass
        
        # self.login_page.locator('//html/body/div[5]/div/div/div/div/div/button[1]/div')
        
    

    async def normal_begin(self,logger,retry: int = 1):
        if retry < 0:
            return None
        retry -= 1
        access_token = None
        EnterKey = "Enter"
        cookies = await self.browser_contexts.cookies()
        cookies = [cookie for cookie in cookies if cookie['name'] not in ('__Secure-next-auth.session-token', '__Secure-next-auth.session-token.0')] # type: ignore
        await self.browser_contexts.clear_cookies()
        await self.browser_contexts.add_cookies(cookies) # type: ignore
        self.logger.debug(f"{self.email_address} relogin clear cookie ")
        await self.login_page.goto(
            url="https://chatgpt.com/auth/login",
            wait_until='load'
        )
        await asyncio.sleep(3)
        self.logger.debug(f"{self.email_address}  relogin goto auth")
        await self.find_cf(self.login_page)
        cf_locator = self.login_page.locator('//*[@id="cf-chl-widget-lpiae"]')
        if await cf_locator.count() > 0:
            self.logger.warning(f"cf checkbox in {self.email_address}")
        await self.find_cf(self.login_page)
        await asyncio.sleep(5)
        check_login = self.login_page.locator('//html/body/div[1]/div/div[1]/div[2]/main/div[1]/div/div[1]/div[3]/button/div/div/div/img')
        await self.find_cf(self.login_page)
        self.logger.debug(f"{self.email_address} goto auth and relogin homepage check")
        if await check_login.count() == 0:
            self.logger.debug(f"{self.email_address} check box count == 0 ")
            await self.find_cf(self.login_page)
            alert_login_box = self.login_page.locator('//html/body/div[3]/div/div/div/div/div/button[1]/div')
            alert_login_box2 = self.login_page.locator('//html/body/div[5]/div/div/div/div/div/button[1]/div')
            
            nologin_home_locator = self.login_page.locator('//html/body/div[1]/div[1]/div[1]/div/div/div/div/nav/div[2]/div[2]/button[2]')
            auth_login = self.login_page.locator('//html/body/div[1]/div[1]/div[2]/div[1]/div/div/button[1]')
            login_button = self.login_page.locator('//html/body/div[1]/div[1]/div[2]/main/div[1]/div[1]/div/div[1]/div/div[3]/div/button[2]/div')
            login_button2 = self.login_page.locator('//html/body/div[1]/div/div/main/div[1]/div[1]/div/div[1]/div/div[3]/div/button[1]/div')
            login_button3 = self.login_page.locator('//html/body/div[1]/div/main/div[1]/div[1]/div/div[1]/div/div[3]/div/button[1]/div')
            login_button_index = self.login_page.locator('//html/body/div/div[2]/div[1]/div/div/button[1]/div')
            login_button_index2 = self.login_page.locator('//html/body/div/div[2]/div[1]/div/div/button[1]')
            if await alert_login_box.count() > 0:
                await alert_login_box.click()
            elif await alert_login_box2.count() > 0:
                await alert_login_box2.click()
            elif await nologin_home_locator.count() > 0:
                await nologin_home_locator.click()
            elif await auth_login.count() > 0:
                await auth_login.click()
            elif await login_button.count() > 0:
                await login_button.first.click()
            elif await login_button2.count() > 0:
                await login_button2.first.click()
            elif await login_button3.count() > 0:
                await login_button3.first.click()
            elif await login_button_index.count() > 0:
                await login_button_index.first.click()
            elif await login_button_index2.count() > 0:
                await login_button_index2.first.click()
            else:
                pass
            await self.find_cf(self.login_page)
            await asyncio.sleep(2)
            await self.login_page.wait_for_load_state('networkidle')
            await self.find_cf(self.login_page)
            current_url = self.login_page.url
            use_url = "chat.openai.com"
            if "chatgpt.com" in current_url:
                use_url = "chatgpt.com"
            self.logger.debug(f"{self.email_address} check current_url ")
            await self.find_cf(self.login_page)
            try:
                if "auth0" in current_url:
                    await self.login_page.wait_for_url("https://auth0.openai.com/**",wait_until='networkidle')
                else:
                    await self.login_page.wait_for_url("https://auth.openai.com/**",wait_until='networkidle')
            except Exception as e:
                self.logger.warning(f"{self.email_address} get auth0 page error,will pass:{e}")
                await self.save_screen(path=f"{self.email_address}_get_auth0_error",page=self.login_page)
            self.logger.debug(f"{self.email_address} check auth0 url")
            await self.find_cf(self.login_page)
            # Select Mode
            await asyncio.sleep(2)
            if self.mode == "google":
                self.logger.debug(f"{self.email_address} login with google")
                new_login = True
                for cookie in cookies:
                    if cookie['name'] == '__Secure-1PSIDTS': # type: ignore
                        new_login = False
                        break
                
                if new_login:
                    self.logger.debug(f"{self.email_address} google new login,will set cookies json")
                    with open(f"{self.email_address}_google_cookie.txt","w") as code_file:
                        code_file.write("")
                        logger.info(f"please input google cookie to {self.email_address}_google_cookie.txt")
                    with open(f"{self.email_address}_google_cookie.txt","r") as code_file:
                        while 1:
                            await asyncio.sleep(1)
                            code = code_file.read()
                            if code != "":
                                tmp = json.loads(code)
                                tmp1 = []
                                for cookie in tmp:
                                    if "sameSite" in cookie:
                                        del cookie["sameSite"]
                                    if 'firstPartyDomain' in cookie:
                                        del cookie['firstPartyDomain']
                                    if 'partitionKey' in cookie:
                                        del cookie['partitionKey']
                                    if 'storeId' in cookie:
                                        del cookie['storeId']
                                    tmp1.append(cookie)
                                await self.browser_contexts.add_cookies(tmp1)
                                break
                    os.unlink(f"{self.email_address}_google_cookie.txt")
                
                
                try:
                    self.logger.debug(f"{self.email_address} google login will point google button")
                    if "auth0" in self.login_page.url:
                        await self.login_page.click('[data-provider="google"] button')
                    else:
                        await self.login_page.click('//html/body/div/main/section/div[2]/div[3]/button[1]')
                        
                except Exception as e:
                    self.logger.warning(f"{self.email_address} google point error:{e}")
                    raise e

            elif self.mode == "microsoft":
                try:
                    self.logger.debug(f"{self.email_address} login with microsoft")
                    await self.find_cf(self.login_page)
                    try:
                        await self.login_page.wait_for_load_state('networkidle')
                    except Exception as e:
                        self.logger.warning(f"get auth0 page by microsoft error,will pass:{e}")
                        await self.save_screen(path=f"{self.email_address}_get_auth0__microsoft_error",page=self.login_page)
                    await asyncio.sleep(2)
                    await self.find_cf(self.login_page)
                    self.logger.debug(f"{self.email_address} will point microsoft button")
                    if "auth0" in current_url:
                        await self.login_page.click('//html/body/div/main/section/div/div/div/div[4]/form[1]/button')
                    else:
                        
                        await self.login_page.click('//html/body/div/main/section/div[2]/div[3]/button[2]')
                except Exception as e:
                    self.logger.warning(f"microsoft point error:{e}")
                    raise e
            await self.find_cf(self.login_page)
            await asyncio.sleep(2)
            await self.login_page.wait_for_load_state('networkidle')
            cookies = await self.browser_contexts.cookies()
            cookies = [cookie for cookie in cookies if cookie['name'] in ('__Secure-next-auth.session-token', '__Secure-next-auth.session-token.0')] # type: ignore
            if cookies == []:
                # Start Fill
                # TODO: SPlit Parts from select mode
                if self.mode == "microsoft":
                    # enter email_address
                    await self.find_cf(self.login_page)
                    await asyncio.sleep(5)
                    self.logger.debug(f"{self.email_address} microsoft new login,will set email")
                    mc_username = self.login_page.locator('//*[@id="i0116"]')
                    if await mc_username.count() > 0:
                        await self.login_page.fill('//*[@id="i0116"]', self.email_address)
                        await asyncio.sleep(1)
                        await self.login_page.click('//*[@id="idSIButton9"]')
                        await self.login_page.wait_for_load_state()
                    else:
                        self.logger.debug(f"{self.email_address} microsoft old login,will skip email")
                    await asyncio.sleep(1)
                    # enter passwd
                    mc_password = self.login_page.locator('//*[@id="i0118"]')
                    if await mc_password.count() > 0:
                        self.logger.debug(f"{self.email_address} microsoft new login,will set password")
                        await self.login_page.fill('//*[@id="i0118"]', self.password)
                        await asyncio.sleep(1)
                        await self.login_page.click('//*[@id="idSIButton9"]')
                        await self.login_page.wait_for_load_state()
                    else:
                        self.logger.debug(f"{self.email_address} microsoft old login,will skip email")
                    # verify code 
                    await self.login_page.wait_for_timeout(1000)
                    try:
                        await self.login_page.wait_for_url("https://login.live.com/**")
                        # await self.login_page.wait_for_url("https://account.live.com/identity/**")
                        locator = self.login_page.locator('//*[@id="proofConfirmationText"]')
                        if await locator.count() > 0:
                            if self.help_email != "":
                                await self.login_page.click('//*[@id="proofConfirmationText"]')
                                await self.login_page.fill('//*[@id="proofConfirmationText"]', self.help_email)
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
                                            await self.login_page.fill('//*[@id="idTxtBx_OTC_Password"]', code)
                                            await self.login_page.keyboard.press(EnterKey)
                                            await self.login_page.wait_for_load_state()
                                            await self.login_page.wait_for_timeout(1000)
                                            break
                                os.unlink(f"{self.email_address}_code.txt")
                            else:
                                self.logger.warning(f"{self.email_address} not input help_email,but it need help_email's verify code now")
                    except Exception as e:
                        if "Timeout" not in e.args[0]:
                            raise e
                    # don't stay
                    self.logger.debug(f"{self.email_address} microsoft login,will point enter")
                    await self.login_page.wait_for_timeout(1000)
                    try:
                        await self.login_page.wait_for_url("https://login.live.com/**",timeout=500)
                    except:
                        pass
                    # await self.page.click('//*[@id="idBtn_Back"]')
                    await self.login_page.keyboard.press(EnterKey)
                    await self.login_page.wait_for_load_state()


                elif self.mode == "google":
                    # enter google email
                    await self.login_page.wait_for_load_state('networkidle')
                    google_login_history = self.login_page.locator('//html/body/div[1]/div[1]/div[2]/div/div/div[2]/div/div/div[1]/form/span/section/div/div/div/div/ul/li[1]/div')
                    await self.login_page.wait_for_load_state('networkidle')
                    if await google_login_history.count() > 0:
                        self.logger.debug(f"{self.email_address} google old login,will point email history")
                        await google_login_history.click()
                        await self.login_page.wait_for_load_state('networkidle')
                    else:
                    
                        self.logger.debug(f"{self.email_address} google new login,will set email")
                        await self.login_page.fill('//*[@id="identifierId"]', self.email_address)
                        await self.login_page.click('//html/body/div[1]/div[1]/div[2]/c-wiz/div/div[3]/div/div[1]/div/div/button/span')
                        # await self.login_page.keyboard.press(EnterKey)
                    await self.login_page.wait_for_load_state()
                    try:
                        # enter passwd
                        self.logger.debug(f"{self.email_address} google login,will set password")
                        await self.login_page.locator(
                            "#password > div:nth-child(1) > div:nth-child(1) > div:nth-child(1) > input:nth-child(1)").fill(
                            self.password)
                    except Exception as e:
                        self.logger.warning(f"{self.email_address} google set password error{e}")
                        await self.save_screen(path=f"{self.email_address}_google_set_password_error",page=self.login_page)

                    # await self.page.locator("#password > div:nth-child(1) > div:nth-child(1) > div:nth-child(1) > input:nth-child(1)").first.fill(self.password)
                    await asyncio.sleep(1)
                    self.logger.debug(f"{self.email_address} google login,will point enter")
                    await self.login_page.keyboard.press(EnterKey)
                    await self.login_page.wait_for_load_state()

                else:
                    await asyncio.sleep(1)
                    await self.login_page.wait_for_load_state('networkidle')
                    self.logger.debug(f"{self.email_address} openai login,will check auth url")
                    if "auth0" in current_url:
                        self.logger.debug(f"{self.email_address} openai auth0 will set email")
                        await self.login_page.fill('[name="username"]', self.email_address)
                        await asyncio.sleep(1)
                        self.logger.debug(f"{self.email_address} openai auth0 will point email button ")
                        await self.login_page.click('button[type="submit"]._button-login-id')
                    
                    else:
                        self.logger.debug(f"{self.email_address} openai will set email")
                        await self.login_page.fill('//*[@id="email-input"]', self.email_address)
                        await asyncio.sleep(1)
                        self.logger.debug(f"{self.email_address} openai will point email button ")
                        await self.login_page.click('//html/body/div/main/section/div[2]/div[1]/form/div/input')
                    
                    
                    await self.login_page.wait_for_load_state(state="domcontentloaded")
                    self.logger.debug(f"{self.email_address} openai will set password")
                    await self.login_page.locator('[name="password"]').first.fill(self.password)
                    await asyncio.sleep(1)
                    self.logger.debug(f"{self.email_address} openai will point password button ")
                    await self.login_page.click('button[type="submit"]._button-login-password')
                    await self.login_page.wait_for_load_state()
                    await self.login_page.wait_for_load_state('networkidle')
                    
                    try:
                        verification_code_locator = self.login_page.locator('//html/body/div/h1')
                        await self.login_page.wait_for_load_state('networkidle')
                        if await verification_code_locator.count() > 0:
                            self.logger.debug(f"{self.email_address} openai Check your inbox,please input your code to {self.email_address}_openai_code.txt by your email")
                            with open(f"{self.email_address}_openai_code.txt","w") as code_file:
                                code_file.write("")
                            with open(f"{self.email_address}_openai_code.txt","r") as code_file:
                                while 1:
                                    await asyncio.sleep(1)
                                    code = code_file.read()
                                    if code != "":
                                        logger.info(f"get {self.email_address} verify code openai {code}")
                                        await self.login_page.fill('//html/body/div/form/input', code)
                                        await self.login_page.click('//html/body/div/form/button')
                                        await self.login_page.wait_for_load_state()
                                        await self.login_page.wait_for_timeout(1000)
                                        break
                            os.unlink(f"{self.email_address}_openai_code.txt")
                    except Exception as e:
                        logger.info(f"{self.email_address} verify code openai exception: {e}")
                        raise e
                        

                
                # go chatgpt
                try:
                    self.logger.debug(f"{self.email_address} wait goto chatgpt homepage ")
                    await asyncio.sleep(2)
                    await self.login_page.wait_for_load_state('networkidle')
                    try:
                        self.logger.debug(f"{self.email_address} will waitfor chatgpt homepage ")
                        await self.login_page.wait_for_url(f"https://{use_url}/",timeout=30000)
                    except Exception:
                        self.logger.debug(f"{self.email_address} will re waitfor chatgpt homepage ")
                        await self.login_page.goto(f"https://{use_url}/")
                    await self.login_page.wait_for_load_state('networkidle')
                    self.logger.debug(f"{self.email_address} will check login status")
                    nologin_home_locator = self.login_page.locator('//html/body/div[1]/div[1]/div[1]/div/div/div/div/nav/div[2]/div[2]/button[2]')
                    auth_login = self.login_page.locator('//html/body/div[1]/div[1]/div[2]/div[1]/div/div/button[1]')
                    if await nologin_home_locator.count() > 0:
                        self.logger.debug(f"{self.email_address} nologin_home_locator.count() > 0,will re login ")
                        access_token = await self.normal_begin(logger,retry)
                    elif await auth_login.count() > 0:
                        self.logger.debug(f"{self.email_address} auth_login.count() > 0,will re login ")
                        access_token = await self.normal_begin(logger,retry)
                    # else:
                    #     await self.login_page.click('[data-testid="login-button"]')
                    if access_token:
                        self.logger.debug(f"{self.email_address} login get access_token ")
                        return access_token
                    self.logger.debug(f"{self.email_address} login not get access_token,will check again ")
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
            await self.login_page.wait_for_load_state('networkidle')
            json_data = await self.login_page.evaluate(
                '() => JSON.parse(document.querySelector("body").innerText)')
            access_token = json_data['accessToken']
            return access_token
        return None
    

    async def save_screen(self,path: str,page: Page):
        screen_path = Path("screen")
        screen_path.mkdir(parents=True, exist_ok=True)
        now = datetime.now()
        time_str = now.strftime("%Y_%m_%d_%H_%M_%S")
        screenshot_path = screen_path / f"{path}_{time_str}.png"
        await page.screenshot(path=screenshot_path)
        screenshots = list(screen_path.glob(f"{path}_*.png"))
        max_files = 10
        if len(screenshots) > max_files:
            screenshots.sort(key=lambda f: f.stat().st_ctime)
            files_to_delete = screenshots[:len(screenshots) - max_files]
            
            for file in files_to_delete:
                print(f"Deleting old screenshot: {file}")
                file.unlink()

    async def get_session_token(self,logger):
        self.logger.debug(f"{self.email_address} will create self.login_page")
        self.login_page: Page = await self.browser_contexts.new_page()
        self.logger.debug(f"{self.email_address} create self.login_page over")
        access_token = None
        try:
            try_num = 3
            while try_num > 0:
                self.logger.debug(f"{self.email_address} will run normal_begin,try_num: {try_num}")
                access_token = await asyncio.wait_for(self.normal_begin(logger),timeout=180)
                if access_token:
                    self.logger.debug(f"{self.email_address} get access_token by normal_begin,try_num: {try_num}")
                    break
                try_num -= 1
        except Exception as e:
            self.logger.warning(f"save screenshot {self.email_address}_login_error.png,login error:{e}")
            await self.save_screen(path=f"{self.email_address}_login_error",page=self.login_page)
        finally:
            cookies = await self.browser_contexts.cookies()
            await self.login_page.close()
            
        try:
            return next(filter(lambda x: x.get("name") in ("__Secure-next-auth.session-token.0", '__Secure-next-auth.session-token'), cookies), None),access_token
        except Exception as e:
            self.logger.warning(f"get cookie error:{e}")
        
        return None,None
    