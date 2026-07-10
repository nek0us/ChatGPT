import unittest
from unittest.mock import AsyncMock, patch

from ChatGPTWeb.ChatGPTWeb import chatgpt
from ChatGPTWeb.config import Session, Status


class _Logger:
    def __init__(self):
        self.warnings = []

    def warning(self, message):
        self.warnings.append(message)


class _Page:
    def __init__(self):
        self.goto = AsyncMock()


class RuntimeStartupTests(unittest.IsolatedAsyncioTestCase):
    def _runtime(self):
        runtime = chatgpt.__new__(chatgpt)
        runtime.logger = _Logger()
        runtime.js = ("first", "second")
        runtime.js_used = 0
        runtime.startup_timeout = 1
        return runtime

    async def test_bridge_initialization_retries_once_before_succeeding(self):
        runtime = self._runtime()
        session = Session(email="bridge@example.com")
        page = _Page()

        with patch(
            "ChatGPTWeb.ChatGPTWeb.flush_page",
            new=AsyncMock(side_effect=[RuntimeError("first failure"), 1]),
        ) as flush:
            ready = await runtime._initialize_page_bridge(session, page)

        self.assertTrue(ready)
        self.assertEqual(flush.await_count, 2)
        page.goto.assert_awaited_once()
        self.assertEqual(session.status, "")

    async def test_bridge_initialization_marks_session_transient_after_two_failures(self):
        runtime = self._runtime()
        session = Session(email="bridge@example.com")
        page = _Page()

        with patch(
            "ChatGPTWeb.ChatGPTWeb.flush_page",
            new=AsyncMock(side_effect=RuntimeError("bridge unavailable")),
        ):
            ready = await runtime._initialize_page_bridge(session, page)

        self.assertFalse(ready)
        self.assertEqual(session.status, Status.Update.value)
        self.assertEqual(session.login_failure_kind, "transient")
        self.assertTrue(session.is_login_disabled())
