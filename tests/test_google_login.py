import unittest

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

    async def click(self):
        self.clicked = True


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
        if selector == "input[type='email']":
            return self.email
        if selector == "input[type='password']":
            return self.password
        return self.history


class _LoginDetailsPage:
    url = "https://accounts.google.com/v3/signin/identifier?client_id=private-value&scope=openid"

    async def evaluate(self, _script):
        return "Email or phone"


class _Logger:
    def debug(self, _message):
        pass

    def warning(self, _message):
        pass


class GoogleLoginTests(unittest.IsolatedAsyncioTestCase):
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
