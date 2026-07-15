from logging import Logger
from typing import Literal
from playwright_firefox.stealth import Stealth
from playwright_firefox.async_api import Page
from playwright_firefox.async_api import Response,BrowserContext
from datetime import datetime
from .config import url_check
from .verification import VerificationBroker, VerificationError
from pathlib import Path

import asyncio
import re
import urllib.parse

class Error(Exception):
    """
    Base error class
    """

    location: str
    status_code: int
    details: str

    def __init__(self, location: str, status_code: int, details: str):
        super().__init__(details)
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
            verification_broker: VerificationBroker | None = None,
            loop=None
    ):
        self.email_address = email
        self.password = password
        self.page = page
        self.logger = logger
        self.browser_contexts: BrowserContext = browser_contexts
        self.mode = mode
        self.help_email = help_email
        self.verification_broker = verification_broker

        self.access_token = None
        self.last_error_details = ""

        self.EnterKey = "Enter"

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

    @staticmethod
    def is_login_surface_url(url: str) -> bool:
        parsed = urllib.parse.urlsplit(url)
        host = parsed.netloc.lower()
        path = parsed.path.rstrip("/") or "/"
        if host == "auth.openai.com":
            return True
        return host in {"chatgpt.com", "chat.openai.com"} and path.startswith("/auth")

    @staticmethod
    def is_chat_app_url(url: str) -> bool:
        parsed = urllib.parse.urlsplit(url)
        host = parsed.netloc.lower()
        path = parsed.path.rstrip("/") or "/"
        return host in {"chatgpt.com", "chat.openai.com"} and not path.startswith("/auth")

    @staticmethod
    def is_microsoft_identity_url(url: str) -> bool:
        host = urllib.parse.urlsplit(url).netloc.lower()
        return host in {"login.live.com", "account.live.com"}

    async def wait_for_login_surface(self, timeout: int = 10000) -> bool:
        """Wait for a usable login control, not merely an early auth URL.

        ChatGPT can redirect the top-level document to ``auth.openai.com``
        before Firefox has painted or initialized the actual sign-in form.
        Treating that URL change as readiness lets the credential flow race
        into a still-loading homepage or a stale dialog.
        """
        deadline = asyncio.get_running_loop().time() + timeout / 1000
        selectors = (
            "input#email:visible",
            "input[name='email']:visible",
            "input[autocomplete='username']:visible",
            "input[type='email']:visible",
        )
        while asyncio.get_running_loop().time() < deadline:
            try:
                for selector in selectors:
                    if await self.login_page.locator(selector).count() > 0:
                        return True
            except Exception as error:
                # A homepage login click can replace the execution context before
                # the destination document exposes its auth controls.  The next
                # polling iteration observes the new page instead of failing the
                # entire credential flow.
                self.logger.debug(f"{self.email_address} auth surface changed while navigating: {error}")
            await asyncio.sleep(0.25)
        return False

    async def wait_for_chat_app(self, timeout: int = 30000) -> bool:
        deadline = asyncio.get_running_loop().time() + timeout / 1000
        while asyncio.get_running_loop().time() < deadline:
            if self.is_chat_app_url(self.login_page.url):
                return True
            await asyncio.sleep(0.25)
        return False

    async def goto_chatgpt_home(self, timeout: int = 60000) -> None:
        """Enter the application without waiting for its long-lived load event."""
        await self.login_page.goto(
            "https://chatgpt.com/",
            wait_until="domcontentloaded",
            timeout=timeout,
        )

    async def _wait_for_document_ready(self, timeout: int = 5000) -> None:
        """Let navigation settle without treating persistent page traffic as a failure."""
        try:
            await self.login_page.wait_for_load_state("domcontentloaded", timeout=timeout)
        except TypeError:
            # Keep compatibility with the small page doubles used by downstream tests.
            await self.login_page.wait_for_load_state()
        except Exception as error:
            debug = getattr(self.logger, "debug", None)
            if debug:
                debug(f"{self.email_address} document did not settle quickly: {error}")
    
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

    async def point_login_button(self) -> bool:
        self.logger.debug(f"{self.email_address} login with {self.mode}")
        await self.find_cf(self.login_page)
        try:
            await self._wait_for_document_ready()
        except Exception as e:
            self.logger.warning(f"get auth page by {self.mode} error,will pass:{e}")
            await self.save_screen(path=f"{self.email_address}_get_auth0__{self.mode}_error",page=self.login_page)
        await asyncio.sleep(2)
        await self.find_cf(self.login_page)
        self.logger.debug(f"{self.email_address} will point {self.mode} button")
        try:
            if self.mode == "google" and await self._click_google_one_tap():
                return True
            provider = "Microsoft" if self.mode == "microsoft" else self.mode.capitalize()
            candidates = (
                self.login_page.get_by_role("button", name=re.compile(rf"continue with {provider}", re.I)),
                self.login_page.get_by_text(f"Continue with {provider}", exact=False),
                self.login_page.get_by_text(f"Continue with {provider} Account", exact=False),
                self.login_page.locator(f"button:has-text('{provider}')"),
                self.login_page.locator(f"[data-provider='{self.mode}']"),
            )
            for button in candidates:
                if await button.count() == 0:
                    continue
                await button.first.click(timeout=10000)
                self.logger.debug(f"{self.email_address} selected {provider} provider")
                return True
            self.logger.debug(
                f"{self.email_address} {provider} provider option was not found; "
                "trying the email-first hand-off"
            )
            return False
        except Exception as e:
            # self.logger.warning(f"{self.email_address} point button {self.mode} exception:{e}, will try old buttion")
            # text2 = f"Continue with {self.mode.capitalize() if self.mode != 'microsoft' else 'Microsoft Account'}"
            # button2 = self.login_page.get_by_text(f"button[data-dd-action-name='{text2}']")
            # await button2.click()
            self.logger.warning(f"{self.email_address} point button {self.mode} exception:{e} ,will skip")
            await self.save_screen(path=f"{self.email_address}_ point_login_button_{self.mode}_exception",page=self.login_page)
            return False

    async def _wait_for_microsoft_identity_page(self, timeout: int = 45000) -> None:
        """Confirm provider hand-off before entering Microsoft credentials."""
        deadline = asyncio.get_running_loop().time() + timeout / 1000
        while asyncio.get_running_loop().time() < deadline:
            if self.is_microsoft_identity_url(self.login_page.url):
                return
            blocked_message = await self._openai_account_block_message()
            if blocked_message:
                raise Error("OpenAI login error", 1, blocked_message)
            await asyncio.sleep(0.25)
        raise Error(
            "Microsoft login error",
            1,
            "Microsoft sign-in page was not reached after selecting the provider",
        )

    async def _submit_provider_email(self) -> bool:
        """Advance an email-first OpenAI login page without submitting a password."""
        inputs = (
            self.login_page.locator("input#email:visible"),
            self.login_page.locator("input[autocomplete='username']:visible"),
            self.login_page.locator("input[type='email']:visible"),
        )
        for email_input in inputs:
            if await email_input.count() == 0:
                continue
            try:
                await email_input.first.wait_for(state="visible", timeout=10000)
                await email_input.first.fill(self.email_address)
                if await email_input.first.input_value() != self.email_address:
                    continue
                submits = (
                    self.login_page.get_by_role("button", name=re.compile(r"^continue$", re.I)),
                    self.login_page.locator("button[type='submit']:visible"),
                    self.login_page.locator("input[type='submit']:visible"),
                )
                for submit in submits:
                    if await submit.count() == 0:
                        continue
                    await submit.first.click(timeout=10000)
                    break
                else:
                    # Older auth pages have no semantic submit button and still
                    # accept Enter from the focused email input.
                    await email_input.first.press(self.EnterKey)
                self.logger.debug(f"{self.email_address} submitted email to start {self.mode} hand-off")
                return True
            except Exception as error:
                self.logger.debug(f"{self.email_address} provider email input was not usable: {error}")
        return False

    async def _existing_session_access_token(self) -> str | None:
        """Use restored browser state before clearing cookies for a credential flow."""
        try:
            await self.goto_chatgpt_home(timeout=30000)
            await self._wait_for_document_ready()
            for _ in range(3):
                blocked_message = await self._openai_account_block_message()
                if blocked_message:
                    raise Error("OpenAI login error", 1, blocked_message)
                token = await self.login_page.evaluate(
                    """async () => {
                        const response = await fetch('/api/auth/session', {credentials: 'include'});
                        if (!response.ok) return {};
                        return await response.json();
                    }"""
                )
                if isinstance(token, dict) and isinstance(token.get("accessToken"), str):
                    return token["accessToken"]
                await asyncio.sleep(1)
        except Error:
            raise
        except Exception as error:
            self.logger.debug(f"{self.email_address} existing session probe did not complete: {error}")
        return None

    async def _click_chatgpt_login_entry(self) -> bool:
        """Enter the auth flow from the current signed-out ChatGPT homepage."""
        if self.mode != "google":
            await self._dismiss_google_one_tap()
        candidates = (
            self.login_page.locator("button[data-testid='login-button']"),
            self.login_page.get_by_role("button", name="Log in"),
            self.login_page.get_by_text("Log in", exact=True),
        )
        for button in candidates:
            if await button.count() == 0:
                continue
            try:
                await button.first.click(timeout=3000)
                self.logger.debug(f"{self.email_address} entered auth flow from ChatGPT homepage")
                return True
            except Exception as error:
                self.logger.debug(f"{self.email_address} ChatGPT login entry was not normally clickable: {error}")
                try:
                    await button.first.click(timeout=5000, force=True)
                    self.logger.debug(f"{self.email_address} forced ChatGPT homepage login entry click")
                    return True
                except Exception as force_error:
                    self.logger.debug(f"{self.email_address} ChatGPT login entry was not clickable: {force_error}")
        return False

    async def _dismiss_google_one_tap(self) -> bool:
        """Close Google One Tap before a non-Google ChatGPT login flow.

        One Tap is an optional Google overlay on the signed-out homepage.  It
        is useful only for Google accounts and can intercept the normal Log in
        button for OpenAI and Microsoft accounts.
        """
        iframe_selector = "iframe[src*='accounts.google.com/gsi/iframe']"
        try:
            iframe = self.login_page.locator(iframe_selector)
            if await iframe.count() == 0:
                return False
            frame_locator = getattr(self.login_page, "frame_locator", None)
            if not callable(frame_locator):
                return False
            frame = frame_locator(iframe_selector)
            close_selectors = (
                "#close",
                "button[aria-label='Close']",
                "button[aria-label='关闭']",
                "[role='button'][aria-label='Close']",
                "[role='button'][aria-label='关闭']",
            )
            for selector in close_selectors:
                close_button = frame.locator(selector).first
                if await close_button.count() == 0:
                    continue
                await close_button.click(timeout=5000)
                self.logger.debug(f"{self.email_address} dismissed Google One Tap for {self.mode} login")
                return True
            keyboard = getattr(self.login_page, "keyboard", None)
            if keyboard:
                await keyboard.press("Escape")
                await asyncio.sleep(0.25)
                if await iframe.count() == 0:
                    self.logger.debug(f"{self.email_address} dismissed Google One Tap with Escape")
                    return True
        except Exception as error:
            self.logger.debug(f"{self.email_address} could not dismiss Google One Tap: {error}")
        return False

    async def _click_google_one_tap(self) -> bool:
        """Use Google's own One Tap continuation button when it overlays the provider list."""
        iframe_selector = "iframe[src*='accounts.google.com/gsi/iframe']"
        iframe = self.login_page.locator(iframe_selector)
        if await iframe.count() == 0:
            return False
        button = self.login_page.frame_locator(iframe_selector).locator("button").last
        if await button.count() == 0:
            return False
        self.logger.debug(f"{self.email_address} Google One Tap is visible, continuing in its iframe")
        context = self.browser_contexts
        if not context or not hasattr(context, "expect_page"):
            await button.click(timeout=10000)
            return True
        try:
            async with context.expect_page(timeout=10000) as popup_info:
                await button.click(timeout=10000)
            popup = await popup_info.value
            await popup.wait_for_load_state("domcontentloaded")
            self.login_page = popup
            self.logger.debug(f"{self.email_address} Google One Tap opened an OAuth popup")
        except Exception as error:
            # Some One Tap versions complete in the current page instead of opening a popup.
            self.logger.debug(f"{self.email_address} Google One Tap did not open a popup: {error}")
        return True
        
    async def mc_help_email_verify(self):
        await self._wait_for_document_ready()
        await asyncio.sleep(1)
        if await self._choose_microsoft_help_email_delivery():
            await self._submit_microsoft_help_email_code()
            return
        select_verify_locator = self.login_page.locator('div[data-testid="tile"]')
        if await select_verify_locator.count() > 0:
            if await select_verify_locator.count() > 1:
                await select_verify_locator.nth(0).click()
            else:
                await select_verify_locator.click()
        await asyncio.sleep(2)
        await self._wait_for_document_ready()
        help_status = False
        verify_email_locator = self.login_page.locator("input[id='iProof0']")
        if await verify_email_locator.count() > 0:
            await verify_email_locator.click()
            self.logger.debug(f"{self.email_address} set help_email checkbox true")
            await asyncio.sleep(1)

            verify_iProofEmail_locator = self.login_page.locator('input[id="iProofEmail"]')
            if await verify_iProofEmail_locator.count() > 0:
                if self.help_email:
                    await verify_iProofEmail_locator.fill(self.help_email.split("@")[0])
                else:
                    self.logger.warning(f"{self.email_address} not input help_email,but it need help_email's verify code now")
                    raise Error("Microsoft login error",111,f"{self.email_address} need microsoft login help email")
                await self._wait_for_document_ready()
                await asyncio.sleep(1)
                help_status = True

            await self.login_page.keyboard.press(self.EnterKey)
            await self._wait_for_document_ready()
            await asyncio.sleep(1)

        verify_locator = self.login_page.locator('input[id="proof-confirmation-email-input"]')
        # verify_locator = self.login_page.get_by_text("Verify your email") # Help us secure your account # Help us secure your account # //*[@id="proofConfirmationText"]
        if await verify_locator.count() > 0 or help_status:
            help_status = True
                # await verify_locator.click()
                # await self.login_page.keyboard.press(EnterKey)
            

                # use passwd
            verify_user_passwd_locator = self.login_page.locator('span[role="button"]')
            # verify_user_passwd_locator = self.login_page.get_by_text("Use your password")
            if await verify_user_passwd_locator.count() > 0:
                await verify_user_passwd_locator.nth(-1).click()
            await asyncio.sleep(1)
            verify_check_passwd_locator = self.login_page.locator('//*[@id="passwordEntry"]')
            if await verify_check_passwd_locator.count() > 0:
                return
                    
            self.logger.debug(f"{self.email_address} need help_email code")
            if self.help_email != "":
                # help_us_protect_locator = 


                verify_email_input_locator = self.login_page.locator("//*[@id='proof-confirmation-email-input']") # ("input[id='iProofEmail']")
                if await verify_email_input_locator.count() > 0:
                    await verify_email_input_locator.fill(self.help_email) # .split("@")[0]
                    self.logger.debug(f"{self.email_address} fill help_email")
                
                # verify_email_submit_locator = self.login_page.locator("input[id='iSelectProofAction']")
                # if await verify_email_submit_locator.count() > 0:
                #     await verify_email_submit_locator.click()

                # await self.login_page.click('//*[@id="proofConfirmationText"]')
                # await self.login_page.fill('//*[@id="proofConfirmationText"]', self.help_email)
                await self.login_page.keyboard.press(self.EnterKey)
                await self._wait_for_document_ready()
                # await self.login_page.wait_for_timeout(1000)
                await self._submit_microsoft_help_email_code()
            else:
                self.logger.warning(f"{self.email_address} not input help_email,but it need help_email's verify code now")
                raise Error("Microsoft login error", 111, "Microsoft login requires a configured help email")

    async def _choose_microsoft_help_email_delivery(self) -> bool:
        """Advance Microsoft's newer security-method picker to its OTP screen.

        The picker has changed markup several times: older pages expose ``iProof0``
        while newer account.live.com pages expose ordinary radio inputs and a
        primary action.  Selecting the first radio is intentional: Microsoft
        orders the configured recovery method before the "I don't have these"
        escape route.
        """
        if await self.login_page.get_by_text("Help us protect your account", exact=False).count() == 0:
            return False

        recovery_choice = self.login_page.locator('input[type="radio"]').first
        if await recovery_choice.count() == 0:
            return False
        try:
            await recovery_choice.check(force=True, timeout=3000)
        except Exception:
            await recovery_choice.click(force=True, timeout=3000)
        self.logger.debug(f"{self.email_address} selected Microsoft help-email delivery")

        actions = (
            self.login_page.get_by_role("button", name="Send code", exact=False),
            self.login_page.get_by_role("button", name="Next", exact=False),
            self.login_page.get_by_role("button", name="Continue", exact=False),
            self.login_page.locator('input[type="submit"]'),
            self.login_page.locator('button[type="submit"]'),
        )
        action_clicked = False
        for action in actions:
            if await action.count() == 0:
                continue
            try:
                await action.first.click(timeout=3000)
                action_clicked = True
                break
            except Exception as error:
                self.logger.debug(f"{self.email_address} Microsoft delivery action was not clickable: {error}")
        if not action_clicked:
            # Some Microsoft picker variants submit immediately after selecting
            # the radio.  Give those pages the same chance to reveal their OTP.
            self.logger.debug(f"{self.email_address} Microsoft delivery selection has no explicit send action")

        for _ in range(40):
            if await self._microsoft_code_input().count() > 0:
                return True
            await asyncio.sleep(0.25)
        self.logger.warning(f"{self.email_address} Microsoft help-email delivery did not reach a code input")
        return False

    def _microsoft_code_input(self):
        return self.login_page.locator(
            "input[id^='codeEntry-'], input[aria-label*='security code' i], "
            "input[autocomplete='one-time-code']"
        ).first

    async def _submit_microsoft_help_email_code(self) -> None:
        """Submit a broker-provided Microsoft help-email code without disk polling."""
        if not self.verification_broker:
            raise Error(
                "Microsoft login error",
                1,
                "Microsoft login requires a help-email verification code",
            )
        self.logger.info(f"{self.email_address} waiting for a Microsoft help-email verification code")
        try:
            code = await self.verification_broker.request_code(
                self.email_address,
                "microsoft",
                kind="help_email_otp",
                message="Enter the security code sent to the configured Microsoft help email.",
            )
        except VerificationError as error:
            raise Error("Microsoft login error", 1, f"Microsoft verification: {error}") from error

        segmented_input = self.login_page.locator('input[id="codeEntry-0"]')
        if await segmented_input.count() > 0:
            for index, character in enumerate(code):
                field = self.login_page.locator(f'input[id="codeEntry-{index}"]')
                if await field.count() == 0:
                    break
                await field.fill(character)
        else:
            full_input = self.login_page.locator('input[aria-label="Enter your security code"]')
            if await full_input.count() == 0:
                full_input = self._microsoft_code_input()
            if await full_input.count() == 0:
                raise Error("Microsoft login error", 1, "Microsoft verification input is no longer available")
            await full_input.fill(code)

        await self.login_page.keyboard.press(self.EnterKey)
        await self._wait_for_document_ready()
        await self.login_page.wait_for_timeout(2000)
        verify_new_password_locator = self.login_page.locator("input[aria-label='New password']")
        if await verify_new_password_locator.count() > 0:
            self.logger.error(f"{self.email_address} Microsoft login requires a password change")
            raise Error(
                "Microsoft login error",
                1,
                "Microsoft login requires a password change. Change it manually and retry.",
            )
    
    async def openai_code_password_login(self):
        self.logger.debug(f"{self.email_address} openai login,will find email input")
        openai_email_input = await self._wait_for_openai_initial_email_input()
        await openai_email_input.fill(self.email_address)
        self.logger.debug(f"{self.email_address} openai login,will point email continue")
        await self._submit_openai_continue(openai_email_input, stage="email")
        state = await self._wait_for_openai_login_state(prefer_password=bool(self.password))
        if state == "password_choice":
            self.logger.debug(f"{self.email_address} openai login,will continue with password")
            await self.login_page.get_by_text("Continue with password", exact=True).click()
            state = await self._wait_for_openai_password_form()
        if state == "otp":
            await self._submit_openai_verification_code()
            return
        if state == "password":
            password_input = self.login_page.locator("input[type='password']")
            self.logger.debug(f"{self.email_address} openai login,will set password")
            await password_input.wait_for(state="visible", timeout=30000)
            await password_input.fill("")
            # Auth0's current password form can ignore a synthetic fill/click
            # pair while its client-side validation is still settling.  Typed
            # key events mirror the legacy successful flow and update it first.
            await password_input.type(self.password, delay=100)
            await self._submit_openai_password(password_input)
            state = await self._wait_for_openai_login_state(
                timeout=12000,
                allow_password=False,
                prefer_password=False,
            )
            if state == "unknown":
                details = await self.get_login_error_details()
                raise Error(
                    "OpenAI login error",
                    1,
                    "OpenAI password submission did not transition before timeout\n"
                    f"{details}",
                )
            if state == "otp":
                await self._submit_openai_verification_code()
                return
            if state == "authenticated":
                return
        if state == "authenticated":
            return
        await self.save_screen(path=f"{self.email_address}_openai_login_unknown", page=self.login_page)
        details = await self.get_login_error_details()
        raise Error("OpenAI login error", 1, f"OpenAI login state was not recognized\n{details}")

    async def _wait_for_openai_initial_email_input(self, timeout: int = 30000):
        """Wait for the visible initial email field instead of trusting an early URL change.

        ChatGPT may update the page URL before the login drawer or auth document
        has finished rendering, especially while Firefox is recovering a new page.
        Proceeding from a locator count alone can type into a later verification
        surface. This gate requires a visible email field before credentials move.
        """
        deadline = asyncio.get_running_loop().time() + timeout / 1000
        selectors = (
            "input#email:visible",
            "input[name='email']:visible",
            "input[autocomplete='username']:visible",
        )
        while asyncio.get_running_loop().time() < deadline:
            blocked_message = await self._openai_account_block_message()
            if blocked_message:
                raise Error("OpenAI login error", 1, blocked_message)
            url = getattr(self.login_page, "url", "")
            on_openai_auth = urllib.parse.urlsplit(url).netloc.lower() == "auth.openai.com"
            for selector in selectors:
                field = self.login_page.locator(selector).first
                try:
                    if await field.count() == 0:
                        continue
                    await field.wait_for(state="visible", timeout=1000)
                    # On ChatGPT's homepage only accept its explicit initial
                    # email controls.  A generic email input can belong to a
                    # late verification dialog from a stale navigation.
                    if not on_openai_auth and selector not in {
                        "input#email:visible",
                        "input[name='email']:visible",
                    }:
                        continue
                    return field
                except Exception as error:
                    self.logger.debug(f"{self.email_address} waiting for OpenAI email form: {error}")
            await asyncio.sleep(0.25)
        raise Error(
            "OpenAI login error",
            1,
            "OpenAI initial email form did not become ready before timeout",
        )

    async def _submit_openai_continue(self, field, *, stage: str) -> None:
        """Submit a stable OpenAI login form through its visible Continue action."""
        submits = (
            self.login_page.get_by_role("button", name=re.compile(r"^continue$", re.I)),
            self.login_page.locator("button[type='submit']:visible"),
            self.login_page.locator("input[type='submit']:visible"),
        )
        for submit in submits:
            if await submit.count() == 0:
                continue
            try:
                await submit.first.click(timeout=10000)
                self.logger.debug(f"{self.email_address} submitted OpenAI {stage}")
                return
            except Exception as error:
                self.logger.debug(f"{self.email_address} OpenAI {stage} submit was not clickable: {error}")
        await self.login_page.keyboard.press(self.EnterKey)

    async def _submit_openai_password(self, password_input) -> None:
        """Submit the password once through the enabled password-page button."""
        await password_input.wait_for(state="visible", timeout=10000)
        await asyncio.sleep(0.25)
        deadline = asyncio.get_running_loop().time() + 10000 / 1000
        buttons = []
        field_locator = getattr(password_input, "locator", None)
        if callable(field_locator):
            form = field_locator("xpath=ancestor::form").first
            buttons.append(form.locator("button[type='submit']:visible"))
        buttons.extend((
            self.login_page.get_by_role("button", name=re.compile(r"^continue$", re.I)),
            self.login_page.locator("button[type='submit']:visible"),
        ))
        last_error = None
        while asyncio.get_running_loop().time() < deadline:
            for button in buttons:
                if await button.count() == 0:
                    continue
                candidate = button.first
                try:
                    await candidate.wait_for(state="visible", timeout=1000)
                    if not await candidate.is_enabled():
                        continue
                    await candidate.click(timeout=5000)
                    self.logger.debug(f"{self.email_address} clicked enabled OpenAI password Continue")
                    return
                except Exception as error:
                    last_error = error
            await asyncio.sleep(0.25)
        raise Error(
            "OpenAI login error",
            1,
            f"OpenAI password Continue button did not become ready: {last_error}",
        )

    async def _wait_for_openai_login_state(
        self,
        timeout: int = 30000,
        *,
        allow_password: bool = True,
        prefer_password: bool = False,
    ) -> str:
        deadline = asyncio.get_running_loop().time() + timeout / 1000
        while asyncio.get_running_loop().time() < deadline:
            try:
                url = getattr(self.login_page, "url", "")
                if self._is_openai_email_verification_url(url):
                    password_choice = self.login_page.get_by_text("Continue with password", exact=True)
                    if prefer_password and await password_choice.count() > 0:
                        await password_choice.wait_for(state="visible", timeout=1000)
                        return "password_choice"
                    otp = self._openai_verification_input()
                    if await otp.count() > 0:
                        await otp.wait_for(state="visible", timeout=1000)
                        return "otp"
                    # Some current deployments expose an unlabelled Code input.
                    # A generic field is safe only on this exact, known page.
                    generic_otp = self.login_page.locator("input:visible").first
                    if await generic_otp.count() > 0:
                        await generic_otp.wait_for(state="visible", timeout=1000)
                        return "otp"
                    await asyncio.sleep(0.25)
                    continue
                otp = self._openai_verification_input()
                if await otp.count() > 0:
                    return "otp"
                password = self.login_page.locator("input[type='password']")
                if allow_password and await password.count() > 0:
                    return "password"
                if await self.login_page.get_by_text("Continue with password", exact=True).count() > 0:
                    return "password_choice"
                if urllib.parse.urlsplit(url).netloc.lower() == "auth.openai.com":
                    if "/log-in" in urllib.parse.urlsplit(url).path:
                        await asyncio.sleep(0.25)
                        continue
                # Clicking Continue from ChatGPT's homepage drawer does not
                # immediately replace the top-level URL.  The old condition
                # treated that still-signed-out homepage as authenticated and
                # skipped the OTP/password step altogether.  Only a concrete
                # account control may complete the OpenAI login state here.
                if self.is_chat_app_url(url):
                    authenticated_controls = (
                        "img[alt='User']",
                        "img[alt='Profile image']",
                        "button[data-testid='account-menu-button']",
                    )
                    for selector in authenticated_controls:
                        if await self.login_page.locator(selector).count() > 0:
                            return "authenticated"
                    await asyncio.sleep(0.25)
                    continue
                if not self.is_login_surface_url(url):
                    await asyncio.sleep(0.25)
                    continue
                # The current login drawer keeps the email input visible while its
                # continue action is loading. Do not mistake its background page
                # login button for a guest-state result during that transition.
                if await self.login_page.locator("input[id='email']").count() > 0:
                    await asyncio.sleep(0.25)
                    continue
                if await self.login_page.locator("button[data-testid='login-button']").count() > 0:
                    return "guest"
            except Exception as error:
                if "Execution context was destroyed" not in str(error):
                    raise
            await asyncio.sleep(0.25)
        return "unknown"

    async def _wait_for_openai_password_form(self, timeout: int = 30000) -> str:
        """Wait for the password page after selecting it from email verification.

        OpenAI leaves the email-verification page visible for a short period
        after the click.  Do not treat that transition as an OTP fallback until
        the password form has had a chance to render.
        """
        deadline = asyncio.get_running_loop().time() + timeout / 1000
        while asyncio.get_running_loop().time() < deadline:
            password = self.login_page.locator("input[type='password']")
            try:
                if await password.count() > 0:
                    await password.wait_for(state="visible", timeout=1000)
                    return "password"
                url = getattr(self.login_page, "url", "")
                if not self._is_openai_email_verification_url(url):
                    state = await self._wait_for_openai_login_state(
                        timeout=1000,
                        prefer_password=False,
                    )
                    if state != "unknown":
                        return state
            except Exception as error:
                if "Execution context was destroyed" not in str(error):
                    raise
            await asyncio.sleep(0.25)
        return "unknown"

    def _openai_verification_input(self):
        """Locate both legacy OTP fields and the current email-verification Code field."""
        return self.login_page.locator(
            "input[autocomplete='one-time-code'], input[name='code'], input#code, "
            "input[inputmode='numeric']"
        ).first

    @staticmethod
    def _is_openai_email_verification_url(url: str) -> bool:
        parsed = urllib.parse.urlsplit(url)
        return (
            parsed.netloc.lower() == "auth.openai.com"
            and parsed.path.rstrip("/") == "/email-verification"
        )

    async def _wait_for_openai_verification_input(self, timeout: int = 30000):
        """Wait for the Code field on the known OpenAI email-verification page."""
        deadline = asyncio.get_running_loop().time() + timeout / 1000
        while asyncio.get_running_loop().time() < deadline:
            verification_input = self._openai_verification_input()
            try:
                if await verification_input.count() > 0:
                    await verification_input.wait_for(state="visible", timeout=1000)
                    return verification_input
                # This page currently has a single plain text Code field in
                # some deployments, without a stable id/name/autocomplete.
                # The URL guard makes this generic fallback unambiguous.
                if self._is_openai_email_verification_url(getattr(self.login_page, "url", "")):
                    verification_input = self.login_page.locator("input:visible").first
                    if await verification_input.count() > 0:
                        await verification_input.wait_for(state="visible", timeout=1000)
                        return verification_input
            except Exception as error:
                self.logger.debug(f"{self.email_address} waiting for OpenAI verification field: {error}")
            await asyncio.sleep(0.25)
        raise Error("OpenAI login error", 1, "OpenAI verification input did not become ready before timeout")

    async def _submit_openai_verification_code(self) -> None:
        """Wait for an operator-supplied OTP without writing it to disk."""
        if not self.verification_broker:
            raise Error(
                "OpenAI login error",
                1,
                "OpenAI login requires an email verification code",
            )
        self.logger.info(f"{self.email_address} waiting for an OpenAI email verification code")
        try:
            code = await self.verification_broker.request_code(
                self.email_address,
                "openai",
                message="Enter the one-time code sent by OpenAI to continue this login.",
            )
        except VerificationError as error:
            raise Error("OpenAI login error", 1, f"OpenAI login verification: {error}") from error
        verification_input = await self._wait_for_openai_verification_input()
        await verification_input.fill(code)
        await self._submit_openai_continue(verification_input, stage="verification code")
        await asyncio.sleep(1)
    
    async def google_login(self, page: Page | None = None):
        """Complete the current OpenAI OAuth redirect without opening a second Google page."""
        page = page or getattr(self, "login_page", self.page)
        google_login_history = page.locator('//html/body/div[1]/div[1]/div[2]/div/div/div[2]/div/div/div[1]/form/span/section/div/div/div/div/ul/li[1]/div')
        # Google's current identifier page uses #identifierId with type="text".
        # Keep the older type=email selector for the provider variants still seen in
        # existing browser profiles.
        google_email_input = page.locator(
            "input#identifierId, input[name='identifier'], "
            "input[autocomplete='username'], input[type='email']"
        ).first
        if await google_email_input.count() > 0:
            self.logger.debug(f"{self.email_address} google login,will set email")
            await google_email_input.wait_for(state="visible", timeout=30000)
            await google_email_input.fill(self.email_address)
            await page.keyboard.press(self.EnterKey)
        elif await google_login_history.count() > 0:
            self.logger.debug(f"{self.email_address} google old login,will point email history")
            await google_login_history.click()
        else:
            raise Error("Google login error", 1, "Google account chooser and email input were not found")

        try:
            self.logger.debug(f"{self.email_address} google login,will set password")
            google_password_input = page.locator("input[type='password']")
            await google_password_input.wait_for(state="visible", timeout=30000)
            await google_password_input.fill(self.password)
        except Exception as e:
            self.logger.warning(f"{self.email_address} google set password error{e}")
            await self.save_screen(path=f"{self.email_address}_google_set_password_error", page=page)
            raise

        self.logger.debug(f"{self.email_address} google login,will point enter")
        await page.keyboard.press(self.EnterKey)

    async def normal_begin(self,logger,retry: int = 1):
        if retry < 0:
            return None
        retry -= 1
        access_token = None
        cookies = await self.browser_contexts.cookies()
        self.logger.debug(f"cookie num:{len(cookies)}")
        # cookies = [cookie for cookie in cookies if cookie['domain'] not in ('auth.openai.com','.auth.openai.com','auth0.openai.com','.auth0.openai.com','chatgpt.com','.chatgpt.com','.chat.openai.com','chat.openai.com','tcr9i.chat.openai.com','.tcr9i.chat.openai.com','oaistatic.com','.oaistatic.com')] # type: ignore
        # self.logger.debug(f"cookie num:{len(cookies)}")
        cookies = [cookie for cookie in cookies if cookie['name'] not in ('__Secure-next-auth.session-token', '__Secure-next-auth.session-token.0')] # type: ignore
        await self.browser_contexts.clear_cookies()
        await self.browser_contexts.add_cookies(cookies) # type: ignore
        self.logger.debug(f"{self.email_address} relogin clear cookie ")
        await self.goto_chatgpt_home()
        await asyncio.sleep(1)
        check_login = self.login_page.locator('img[alt="User"]')
        self.logger.debug(f"{self.email_address} goto auth and relogin homepage check")
        await asyncio.sleep(1)
        if await check_login.count() == 0:
            check_new_img = self.login_page.locator('img[alt="Profile image"]')
            if await check_new_img.count() > 0:
                await check_new_img.click()
                await asyncio.sleep(1)
            login_surface_detected = await self.wait_for_login_surface()
            if not login_surface_detected and await self._click_chatgpt_login_entry():
                login_surface_detected = await self.wait_for_login_surface(timeout=30000)
            if not login_surface_detected:
                self.logger.debug(f"{self.email_address} login surface was not detected, trying legacy entry controls")
                await self.login_page.keyboard.press(self.EnterKey)
                check_home_login_box = self.login_page.locator('input[id="email"]')
                if "chatgpt.com" in self.login_page.url and await check_home_login_box.count() > 0:
                    pass
                else:

                    self.logger.debug(f"{self.email_address}  relogin goto auth")
                    await self.find_cf(self.login_page)
                    cf_locator = self.login_page.locator('//*[@id="cf-chl-widget-lpiae"]')
                    if await cf_locator.count() > 0:
                        self.logger.warning(f"cf checkbox in {self.email_address}")
                    await self.find_cf(self.login_page)
                    # await asyncio.sleep(5)
                    check_login = self.login_page.locator('img[alt="User"]')
                    await self.find_cf(self.login_page)
                    self.logger.debug(f"{self.email_address} goto auth and relogin homepage check2")
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
                        
                        login_button_index3 = self.login_page.locator('button[data-testid="login-button"]')
                        login_button_index4 = self.login_page.locator('button[class="btn relative btn-primary btn-large"]')
                        try:
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
                            elif await login_button_index4.count() > 0:
                                await login_button_index4.first.click()
                            elif await login_button_index3.count() > 0:
                                await login_button_index3.first.click()
                            else:
                                self.logger.debug(f"{self.email_address} have no login butoon")
                        except Exception as e:
                            self.logger.debug(f"{self.email_address} point login button timeout {e}")
                    # await self.find_cf(self.login_page)
                    # await asyncio.sleep(2)
                    # await self.login_page.wait_for_load_state('networkidle')
                    # await self.find_cf(self.login_page)
                    # current_url = self.login_page.url
                    # if "chatgpt.com" in current_url:
                    #     use_url = "chatgpt.com"
                    # self.logger.debug(f"{self.email_address} check current_url ")
            if await check_login.count() == 0:
                await self.find_cf(self.login_page)
                await asyncio.sleep(2)
                # Select Mode
                if self.mode != "openai":
                    provider_selected = await self.point_login_button()
                    if not provider_selected and not await self._submit_provider_email():
                        raise Error(
                            "OpenAI login error",
                            1,
                            f"{self.mode.capitalize()} provider option and email entry were not available on the OpenAI login page",
                        )
                    if self.mode == "microsoft":
                        await self._wait_for_microsoft_identity_page()
                # await asyncio.sleep(2)
                if self.mode == "google":
                    self.logger.debug(f"{self.email_address} login with google")
                    self.logger.debug(f"{self.email_address} Google OAuth uses the current redirect page; no Google cookie import is attempted")
                await self.find_cf(self.login_page)
                await asyncio.sleep(2)
                # await self.login_page.wait_for_load_state('networkidle')
                cookies = await self.browser_contexts.cookies()
                cookies = [cookie for cookie in cookies if cookie['name'] in ('__Secure-next-auth.session-token', '__Secure-next-auth.session-token.0')] # type: ignore
                # if cookies == []:
                    # Start Fill
                    # TODO: SPlit Parts from select mode
                if self.mode == "microsoft":
                    if not self.password:
                        raise Error("Microsoft login error", 1, "Microsoft account password is empty")
                    # enter email_address
                    await self.find_cf(self.login_page)
                    # await asyncio.sleep(5)
                    
                    self.logger.debug(f"{self.email_address} microsoft login,will check help_email verify")
                    await self.mc_help_email_verify()
                    
                    self.logger.debug(f"{self.email_address} microsoft new login,will set email")
                    mc_username = self.login_page.locator("input[type='email']")
                    if await mc_username.count() > 0:
                        await mc_username.wait_for(state="visible")
                        await mc_username.fill(self.email_address)
                        await asyncio.sleep(1)
                        await self.login_page.keyboard.press(self.EnterKey)
                        await self._wait_for_document_ready()
                    else:
                        self.logger.debug(f"{self.email_address} microsoft old login,will skip email")
                    await asyncio.sleep(1)
                    # enter passwd
                    await self.mc_help_email_verify()
                    mc_password = self.login_page.locator("input[type='password']")
                    if await mc_password.count() > 0:
                        self.logger.debug(f"{self.email_address} microsoft new login,will set password")
                        await mc_password.wait_for(state="visible")
                        await mc_password.fill(self.password)
                        await asyncio.sleep(2)
                        await self.login_page.keyboard.press(self.EnterKey)
                        await asyncio.sleep(2)
                        blocked_message = await self._openai_account_block_message()
                        if blocked_message:
                            raise Error("OpenAI login error", 1, blocked_message)
                        await self._wait_for_document_ready()
                    else:
                        self.logger.debug(f"{self.email_address} microsoft old login,will skip email")
                    # verify code 
                    # await self.login_page.wait_for_timeout(1000)
                    await self.mc_help_email_verify()
                    await self._wait_for_document_ready()
                    await asyncio.sleep(3)
                    check_mc_next = self.login_page.locator('button[data-testid="primaryButton"]')
                    if await check_mc_next.count() > 0:
                        self.logger.debug(f"{self.email_address} microsoft old login,will try to point Next Button")
                        try:
                            await check_mc_next.click(timeout=3000)
                        except Exception as e:
                            self.logger.debug(f"{self.email_address} microsoft try to point Next Button exception:{e}")
                        await asyncio.sleep(1)
                        await self._wait_for_document_ready()
                        await asyncio.sleep(2)
                        await self._wait_for_document_ready()



                    try:
                        await self.login_page.wait_for_url("https://login.live.com/**")
                        # await self.login_page.wait_for_url("https://account.live.com/identity/**")
                        self.logger.debug(f"{self.email_address} microsoft login,will check help_email verify")
                        await self.mc_help_email_verify()
                    except Exception as e:
                        if "Timeout" not in e.args[0]:
                            raise e
                    # stay
                    self.logger.debug(f"{self.email_address} microsoft login,will point enter Yes")
                    # await self.login_page.wait_for_timeout(1000)
                    try:
                        await self.login_page.wait_for_url("https://login.live.com/**",timeout=500)
                        await asyncio.sleep(1)
                        await self._wait_for_document_ready()
                        stay_button = self.login_page.get_by_text("Yes")
                        if await stay_button.count() > 0:
                            await stay_button.click()
                    except:
                        pass
                    await self._wait_for_document_ready()


                elif self.mode == "google":
                    await self.login_page.wait_for_url("https://accounts.google.com/**", timeout=30000)
                    await self.google_login()

                    

                else:

                    await self.openai_code_password_login()
                    await self.login_page.wait_for_load_state('networkidle')
                    await asyncio.sleep(5)

                # Third-party OAuth can land on ChatGPT's terminal account page.
                # Capture it before the legacy login checks recurse into /api/auth/session.
                blocked_message = await self._openai_account_block_message()
                if blocked_message:
                    raise Error("OpenAI login error", 1, blocked_message)

                # Return to either supported ChatGPT application host before checking session state.
                try:
                    self.logger.debug(f"{self.email_address} wait goto chatgpt homepage ")
                    await asyncio.sleep(2)
                    if not await self.wait_for_chat_app():
                        self.logger.debug(f"{self.email_address} will re waitfor chatgpt homepage ")
                        await self.goto_chatgpt_home()
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
                    await self.goto_chatgpt_home()

        blocked_message = await self._openai_account_block_message()
        if blocked_message:
            raise Error("OpenAI login error", 1, blocked_message)
                
        async with self.login_page.expect_response(url_check, timeout=20000) as a:
            res = await self.login_page.goto(url_check, timeout=20000)
        res = await a.value
        if (res.status == 200 or res.status == 307 or res.status == 304)and res.url == url_check:
            await asyncio.sleep(3)
            await self.login_page.wait_for_load_state('networkidle')
            json_data = await self.login_page.evaluate(
                '() => JSON.parse(document.querySelector("body").innerText)')
            if 'accessToken' in json_data:
                access_token = json_data['accessToken']
            else:
                self.logger.warning(f"{self.email_address} login may not success,accessToken not in json_data, json_data: {json_data}")
            return access_token
        self.logger.warning(f"{self.email_address} login failed, status code: {res.status}, url: {res.url}, response text: {await res.text()}")
        return None

    async def _openai_account_block_message(self) -> str:
        """Capture a terminal ChatGPT account page before the session API replaces it."""
        try:
            text = await self.login_page.evaluate("() => document.body ? document.body.innerText : ''")
        except Exception:
            return ""
        normalized = " ".join(text.lower().split())
        markers = (
            "your account has been deactivated",
            "your account was deactivated",
            "account has been deleted or deactivated",
            "account was deleted or deactivated",
            "you do not have an account because it has been deleted or deactivated",
            "your account has been suspended",
            "your account was suspended",
            "account has been disabled",
            "account is disabled",
            "violation of our terms",
            "violated our terms",
        )
        if any(marker in normalized for marker in markers):
            return f"OpenAI account blocked: {text[:1000]}"
        return ""
    

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

    async def get_login_error_details(self) -> str:
        try:
            text = await self.login_page.evaluate(
                "() => document.body ? document.body.innerText : ''"
            )
        except Exception as e:
            text = f"failed to read login page text: {e}"
        parsed = urllib.parse.urlsplit(self.login_page.url)
        safe_url = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
        return f"url={safe_url}\n{text[:3000]}"

    def append_login_error_details(self, page_details: str):
        if self.last_error_details:
            self.last_error_details = f"{self.last_error_details}\n{page_details}"
        else:
            self.last_error_details = page_details

    def _login_timeout_seconds(self) -> int:
        """Keep the outer auth task alive longer than an interactive OTP challenge."""
        if not self.verification_broker:
            return 180
        return max(180, self.verification_broker.default_timeout_seconds + 60)

    async def get_session_token(self,logger):
        self.logger.debug(f"{self.email_address} will create self.login_page")
        self.login_page: Page = await self.browser_contexts.new_page()
        self.logger.debug(f"{self.email_address} create self.login_page over")
        if self.mode == "google":
            self.logger.debug(f"{self.email_address} {self.mode},will set stealth")
            await Stealth().apply_stealth_async(self.login_page)
        access_token = None
        try:
            # A credential flow may be waiting for a human verification code.
            # Do not restart it behind the operator's back when no session is
            # available yet; callers can explicitly request another login.
            access_token = await self._existing_session_access_token()
            if access_token:
                self.logger.debug(f"{self.email_address} restored an existing ChatGPT session")
            else:
                self.logger.debug(f"{self.email_address} will run one normal_begin attempt")
                access_token = await asyncio.wait_for(
                    self.normal_begin(logger, retry=0),
                    timeout=self._login_timeout_seconds(),
                )
            if access_token:
                self.logger.debug(f"{self.email_address} get access_token by normal_begin")
        except Exception as e:
            self.last_error_details = str(e)
            if isinstance(e, Error):
                self.logger.info(f"{self.email_address} login flow stopped at: {e.location}")
                self.logger.debug(f"{self.email_address} login details: {e}")
            else:
                self.logger.warning(f"save screenshot {self.email_address}_login_error.png,login error:{e}")
            await self.save_screen(path=f"{self.email_address}_login_error",page=self.login_page)
        finally:
            cookies = await self.browser_contexts.cookies()
            if not access_token:
                try:
                    page_details = await self.get_login_error_details()
                    self.append_login_error_details(page_details)
                except Exception as e:
                    self.last_error_details = self.last_error_details or str(e)
            await self.login_page.close()
            
        try:
            return next(filter(lambda x: x.get("name") in ("__Secure-next-auth.session-token.0", '__Secure-next-auth.session-token'), cookies), None),access_token,self.last_error_details
        except Exception as e:
            self.logger.warning(f"get cookie error:{e}")
        
        return None,None,self.last_error_details
    
