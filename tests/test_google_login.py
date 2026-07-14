import unittest
from unittest.mock import ANY, AsyncMock

from ChatGPTWeb.OpenAIAuth import AsyncAuth0, Error


class _Locator:
    def __init__(self, count=0):
        self._count = count
        self.waited = False
        self.value = ""
        self.clicked = False

    async def count(self):
        return self._count

    async def wait_for(self, **_kwargs):
        self.waited = True

    async def fill(self, value):
        self.value = value

    async def input_value(self):
        return self.value

    async def press(self, value):
        self.value = self.value

    async def click(self, **_kwargs):
        self.clicked = True

    @property
    def first(self):
        return self


class _Keyboard:
    def __init__(self):
        self.presses = []

    async def press(self, value):
        self.presses.append(value)


class _Page:
    def __init__(self, email_count=1, history_count=0):
        self.email = _Locator(email_count)
        self.password = _Locator(1)
        self.history = _Locator(history_count)
        self.keyboard = _Keyboard()

    def locator(self, selector):
        if "identifierId" in selector or selector == "input[type='email']":
            return self.email
        if selector == "input[type='password']":
            return self.password
        return self.history


class _ChatLoginPage:
    def __init__(self):
        self.test_id = _Locator(0)
        self.role = _Locator(1)
        self.text = _Locator(1)

    def locator(self, _selector):
        return self.test_id

    def get_by_role(self, _role, **_kwargs):
        return self.role

    def get_by_text(self, _text, **_kwargs):
        return self.text


class _ForceClickLocator(_Locator):
    def __init__(self):
        super().__init__(1)
        self.force_attempted = False

    async def click(self, **kwargs):
        if kwargs.get("force"):
            self.force_attempted = True
            self.clicked = True
            return
        raise RuntimeError("element never became stable")


class _ForceClickLoginPage(_ChatLoginPage):
    def __init__(self):
        super().__init__()
        self.test_id = _ForceClickLocator()
        self.role = _Locator(0)
        self.text = _Locator(0)


class _LoginDetailsPage:
    url = "https://accounts.google.com/v3/signin/identifier?client_id=private-value&scope=openid"

    async def evaluate(self, _script):
        return "Email or phone"


class _OneTapButton(_Locator):
    @property
    def last(self):
        return self


class _OneTapFrame:
    def __init__(self, button):
        self.button = button

    def locator(self, _selector):
        return self.button


class _OneTapPage:
    def __init__(self, iframe_count=1, button_count=1):
        self.iframe = _Locator(iframe_count)
        self.button = _OneTapButton(button_count)

    def locator(self, _selector):
        return self.iframe

    def frame_locator(self, _selector):
        return _OneTapFrame(self.button)


class _OneTapHomepage:
    url = "https://chatgpt.com/"

    def locator(self, selector):
        return _Locator(1 if selector == "#google-one-tap-anchor" else 0)


class _LoginButtonHomepage:
    url = "https://chatgpt.com/"

    def locator(self, selector):
        return _Locator(1 if selector == "button[data-testid='login-button']" else 0)


class _PopupInfo:
    def __init__(self, popup):
        self.value = self._resolve(popup)

    async def _resolve(self, popup):
        return popup


class _PopupWaiter:
    def __init__(self, popup):
        self.popup = popup

    async def __aenter__(self):
        return _PopupInfo(self.popup)

    async def __aexit__(self, _type, _value, _traceback):
        return False


class _PopupContext:
    def __init__(self, popup):
        self.popup = popup
        self.timeouts = []

    def expect_page(self, timeout):
        self.timeouts.append(timeout)
        return _PopupWaiter(self.popup)


class _PopupPage:
    def __init__(self):
        self.wait_for_load_state = AsyncMock()


class _SessionTokenPage:
    url = "https://chatgpt.com/auth/login"

    def __init__(self):
        self.close = AsyncMock()
        self.evaluate = AsyncMock(return_value="")


class _HomepagePage:
    def __init__(self):
        self.goto = AsyncMock()


class _MissingProviderPage:
    def __init__(self):
        self.wait_for_load_state = AsyncMock()

    def locator(self, _selector):
        return _Locator(0)

    def get_by_role(self, _role, **_kwargs):
        return _Locator(0)

    def get_by_text(self, _text, **_kwargs):
        return _Locator(0)


class _MicrosoftRedirectPage:
    url = "https://login.live.com/oauth20_authorize.srf"


class _EmailFirstMicrosoftPage:
    url = "https://auth.openai.com/log-in"

    def __init__(self):
        self.email = _Locator(1)
        self.submit = _Locator(1)
        self.keyboard = _Keyboard()

    def locator(self, selector):
        if "submit" in selector:
            return self.submit
        return self.email if "email" in selector or "username" in selector else _Locator(0)

    def get_by_role(self, _role, **_kwargs):
        return self.submit


class _BlockedPage:
    async def evaluate(self, _script):
        return "You do not have an account because it has been deleted or deactivated."


class _SessionTokenContext:
    def __init__(self, page):
        self.new_page = AsyncMock(return_value=page)
        self.cookies = AsyncMock(return_value=[])


class _Logger:
    def debug(self, _message):
        pass

    def warning(self, _message):
        pass


class GoogleLoginTests(unittest.IsolatedAsyncioTestCase):
    async def test_auth_error_keeps_its_details_in_exception_text(self):
        error = Error("OpenAI login error", 1, "account has been deleted or deactivated")

        self.assertEqual(str(error), "account has been deleted or deactivated")

    async def test_google_one_tap_homepage_is_not_an_auth_surface(self):
        page = _OneTapHomepage()
        auth = AsyncAuth0("account@example.com", "password", page, _Logger(), browser_contexts=None)
        auth.login_page = page

        self.assertFalse(await auth.wait_for_login_surface(timeout=1))

    async def test_chatgpt_login_button_is_not_an_auth_surface(self):
        page = _LoginButtonHomepage()
        auth = AsyncAuth0("account@example.com", "password", page, _Logger(), browser_contexts=None)
        auth.login_page = page

        self.assertFalse(await auth.wait_for_login_surface(timeout=1))

    async def test_chatgpt_homepage_login_entry_prefers_semantic_button(self):
        page = _ChatLoginPage()
        auth = AsyncAuth0("account@example.com", "password", page, _Logger(), browser_contexts=None)
        auth.login_page = page

        self.assertTrue(await auth._click_chatgpt_login_entry())
        self.assertTrue(page.role.clicked)
        self.assertFalse(page.text.clicked)

    async def test_chatgpt_homepage_login_entry_force_clicks_after_stability_timeout(self):
        page = _ForceClickLoginPage()
        auth = AsyncAuth0("account@example.com", "password", page, _Logger(), browser_contexts=None)
        auth.login_page = page

        self.assertTrue(await auth._click_chatgpt_login_entry())
        self.assertTrue(page.test_id.force_attempted)

    async def test_session_token_attempts_browser_login_once_without_token(self):
        page = _SessionTokenPage()
        context = _SessionTokenContext(page)
        auth = AsyncAuth0("account@example.com", "password", page, _Logger(), browser_contexts=context)
        auth.normal_begin = AsyncMock(return_value=None)

        cookie, token, _details = await auth.get_session_token(_Logger())

        self.assertIsNone(cookie)
        self.assertIsNone(token)
        auth.normal_begin.assert_awaited_once_with(ANY, retry=0)
        page.close.assert_awaited_once()

    async def test_chatgpt_home_navigation_uses_dom_content_loaded(self):
        page = _HomepagePage()
        auth = AsyncAuth0("account@example.com", "password", page, _Logger(), browser_contexts=None)
        auth.login_page = page

        await auth.goto_chatgpt_home()

        page.goto.assert_awaited_once_with(
            "https://chatgpt.com/", wait_until="domcontentloaded", timeout=60000,
        )

    async def test_missing_microsoft_provider_does_not_continue_into_credentials(self):
        page = _MissingProviderPage()
        auth = AsyncAuth0("account@example.com", "password", page, _Logger(), browser_contexts=None, mode="microsoft")
        auth.login_page = page

        self.assertFalse(await auth.point_login_button())

    async def test_microsoft_provider_waits_for_the_identity_host(self):
        page = _MicrosoftRedirectPage()
        auth = AsyncAuth0("account@example.com", "password", page, _Logger(), browser_contexts=None, mode="microsoft")
        auth.login_page = page

        await auth._wait_for_microsoft_identity_page()

        self.assertTrue(auth.is_microsoft_identity_url(page.url))

    async def test_email_first_microsoft_handoff_submits_only_the_email(self):
        page = _EmailFirstMicrosoftPage()
        auth = AsyncAuth0("account@example.com", "password", page, _Logger(), browser_contexts=None, mode="microsoft")
        auth.login_page = page

        self.assertTrue(await auth._submit_provider_email())

        self.assertEqual(page.email.value, "account@example.com")
        self.assertTrue(page.submit.clicked)
        self.assertEqual(page.keyboard.presses, [])

    async def test_existing_session_is_used_before_credential_flow(self):
        page = _SessionTokenPage()
        page.evaluate = AsyncMock(side_effect=["", {"accessToken": "existing-token"}])
        auth = AsyncAuth0("account@example.com", "password", page, _Logger(), browser_contexts=None)
        auth.login_page = page
        auth.goto_chatgpt_home = AsyncMock()
        auth._wait_for_document_ready = AsyncMock()

        token = await auth._existing_session_access_token()

        self.assertEqual(token, "existing-token")
        auth.goto_chatgpt_home.assert_awaited_once_with(timeout=30000)

    async def test_openai_block_message_catches_current_deactivation_wording(self):
        page = _BlockedPage()
        auth = AsyncAuth0("account@example.com", "password", page, _Logger(), browser_contexts=None)
        auth.login_page = page

        self.assertIn("OpenAI account blocked", await auth._openai_account_block_message())

    async def test_login_route_detection_accepts_current_and_legacy_hosts(self):
        self.assertTrue(AsyncAuth0.is_login_surface_url("https://chatgpt.com/auth/login"))
        self.assertTrue(AsyncAuth0.is_login_surface_url("https://auth.openai.com/u/login"))
        self.assertTrue(AsyncAuth0.is_login_surface_url("https://chat.openai.com/auth/login"))
        self.assertFalse(AsyncAuth0.is_login_surface_url("https://chatgpt.com/"))

    async def test_chat_app_route_detection_accepts_current_and_legacy_hosts(self):
        self.assertTrue(AsyncAuth0.is_chat_app_url("https://chatgpt.com/"))
        self.assertTrue(AsyncAuth0.is_chat_app_url("https://chat.openai.com/c/example"))
        self.assertFalse(AsyncAuth0.is_chat_app_url("https://chatgpt.com/auth/login"))
        self.assertFalse(AsyncAuth0.is_chat_app_url("https://auth.openai.com/u/login"))

    async def test_current_oauth_page_is_used_for_google_credentials(self):
        page = _Page()
        auth = AsyncAuth0("account@example.com", "password", page, _Logger(), browser_contexts=None, mode="google")

        await auth.google_login()

        self.assertTrue(page.email.waited)
        self.assertEqual(page.email.value, "account@example.com")
        self.assertTrue(page.password.waited)
        self.assertEqual(page.password.value, "password")
        self.assertEqual(page.keyboard.presses, ["Enter", "Enter"])

    async def test_missing_google_identity_controls_fails_without_opening_another_page(self):
        page = _Page(email_count=0, history_count=0)
        auth = AsyncAuth0("account@example.com", "password", page, _Logger(), browser_contexts=None, mode="google")

        with self.assertRaises(Error):
            await auth.google_login()

    async def test_login_error_details_strip_oauth_query_parameters(self):
        page = _LoginDetailsPage()
        auth = AsyncAuth0("account@example.com", "password", page, _Logger(), browser_contexts=None, mode="google")
        auth.login_page = page

        details = await auth.get_login_error_details()

        self.assertIn("url=https://accounts.google.com/v3/signin/identifier", details)
        self.assertNotIn("client_id", details)
        self.assertIn("Email or phone", details)

    async def test_google_one_tap_uses_the_iframe_button(self):
        page = _OneTapPage()
        auth = AsyncAuth0("account@example.com", "password", page, _Logger(), browser_contexts=None, mode="google")
        auth.login_page = page

        clicked = await auth._click_google_one_tap()

        self.assertTrue(clicked)
        self.assertTrue(page.button.clicked)

    async def test_google_one_tap_falls_back_when_no_iframe_is_present(self):
        page = _OneTapPage(iframe_count=0)
        auth = AsyncAuth0("account@example.com", "password", page, _Logger(), browser_contexts=None, mode="google")
        auth.login_page = page

        self.assertFalse(await auth._click_google_one_tap())

    async def test_google_one_tap_switches_to_oauth_popup(self):
        page = _OneTapPage()
        popup = _PopupPage()
        context = _PopupContext(popup)
        auth = AsyncAuth0("account@example.com", "password", page, _Logger(), browser_contexts=context, mode="google")
        auth.login_page = page

        self.assertTrue(await auth._click_google_one_tap())

        self.assertIs(auth.login_page, popup)
        popup.wait_for_load_state.assert_awaited_once_with("domcontentloaded")
        self.assertEqual(context.timeouts, [10000])

    async def test_login_error_details_keep_exception_and_sanitized_page_context(self):
        page = _LoginDetailsPage()
        auth = AsyncAuth0("account@example.com", "password", page, _Logger(), browser_contexts=None, mode="google")
        auth.login_page = page
        auth.last_error_details = "Timeout 30000ms exceeded"

        page_details = await auth.get_login_error_details()
        auth.append_login_error_details(page_details)

        self.assertIn("Timeout 30000ms exceeded", auth.last_error_details)
        self.assertIn("Email or phone", auth.last_error_details)
        self.assertNotIn("client_id", auth.last_error_details)
