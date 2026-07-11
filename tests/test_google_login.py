import unittest
from unittest.mock import AsyncMock

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


class _Logger:
    def debug(self, _message):
        pass

    def warning(self, _message):
        pass


class GoogleLoginTests(unittest.IsolatedAsyncioTestCase):
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
