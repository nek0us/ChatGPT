# Credits to github.com/rawandahmad698/PyChatGPT
import re
import urllib
from playwright.sync_api import sync_playwright, Route, Request


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


class Auth0:
    """
    OpenAI Authentication Reverse Engineered
    """

    def __init__(
            self,
            email_address: str,
            password: str,
            proxy: str = None,
            headless: bool = True
    ):
        self.email_address = email_address
        self.password = password
        self.proxy = proxy
        playwright_manager = sync_playwright()
        playwright = playwright_manager.start()
        browser = playwright.firefox.launch(headless=headless, slow_mo=50)
        self.context = browser.new_context()
        self.page = self.context.new_page()

        self.access_token = None
        self.begin()

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

    def begin(self) -> None:
        """
        In part two, We make a request to https://chat.openai.com/api/auth/csrf and grab a fresh csrf token
        """
        url = "https://chat.openai.com/api/auth/csrf"
        response = self.page.goto(
            url=url,
        )
        if response.status == 200 and "json" in response.headers['content-type']:
            csrf_token = response.json()["csrfToken"]
            # self.session.cookies.set("__Host-next-auth.csrf-token", csrf_token)
            self.__part_one(token=csrf_token)

    def __part_one(self, token: str) -> None:
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

        def route_handle(route: Route, request: Request):
            header["Cookie"] = request.headers.get("cookie")
            header["User-Agent"] = request.headers["user-agent"]
            route.continue_(method="POST", headers=header, post_data=payload)

        self.page.route(url, route_handle)  # type: ignore
        response = self.page.goto(url)
        if response.status == 200 and "json" in response.headers['content-type']:
            url = response.json()["url"]
            if (
                    url == "https://chat.openai.com/api/auth/error?error=OAuthSignin"
                    or "error" in url
            ):
                error = Error(
                    location="__part_one",
                    status_code=response.status,
                    details="You have been rate limited. Please try again later.",
                )
                raise error

            self.__part_two(url=url)
        else:
            error = Error(
                location="__part_one",
                status_code=response.status,
                details=response.text(),
            )
            raise error

    def __part_two(self, url: str) -> None:
        """
        We make a GET request to url
        :param url:
        :return:
        """

        response = self.page.goto(url)

        if response.status == 302 or response.status == 200:
            state = re.findall(r"state=(.*)", response.text())[0]
            state = state.split('"')[0]

            self.__part_three(state=state)
        else:
            error = Error(
                location="__part_two",
                status_code=response.status,
                details=response.text(),
            )
            raise error

    def __part_three(self, state: str) -> None:
        """
        We use the state to get the login page
        """
        url = f"https://auth0.openai.com/u/login/identifier?state={state}"

        response = self.page.goto(url)
        if response.status == 200:
            self.__part_four(state=state)
        else:
            error = Error(
                location="__part_three",
                status_code=response.status,
                details=response.text(),
            )
            raise error

    def __part_four(self, state: str) -> None:
        """
        We make a POST request to the login page with the captcha, email
        :param state:
        :return:
        """
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

        def route_handle(route: Route, request: Request):
            header["Cookie"] = request.headers.get("cookie")
            header["User-Agent"] = request.headers["user-agent"]
            route.continue_(method="POST", headers=header, post_data=payload)

        self.page.route(url, route_handle)  # type: ignore
        response = self.page.goto(url)

        if response.status == 302 or response.status == 200:
            # pass
            self.__part_five(state=state)
        else:
            error = Error(
                location="__part_four",
                status_code=response.status,
                details="Your email address is invalid.",
            )
            raise error

    def __part_five(self, state: str) -> None:
        self.page.locator('[name="password"]').first.fill(self.password)
        self.page.evaluate("()=>arkose.run()")
        self.page.wait_for_url("https://chat.openai.com/")

    def get_access_token(self):
        """
        Gets access token
        """

        response = self.page.goto(
            "https://chat.openai.com/api/auth/session",
        )
        if response.status == 200:
            self.access_token = response.json().get("accessToken")
            return self.access_token
        else:
            error = Error(
                location="get_access_token",
                status_code=response.status,
                details=response.text(),
            )
            raise error

    def get_session_token(self):
        cookies = self.page.context.cookies()
        return next(filter(lambda x: x.get("name") == "__Secure-next-auth.session-token", cookies), None)
