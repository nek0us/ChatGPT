import unittest
from unittest.mock import AsyncMock, patch
from pathlib import Path
import json
import tempfile

from ChatGPTWeb.ChatGPTWeb import chatgpt
from ChatGPTWeb.config import Session, Status


class _Logger:
    def __init__(self):
        self.warnings = []

    def warning(self, message):
        self.warnings.append(message)

    def debug(self, _message):
        pass


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

    def test_runtime_close_records_diagnostics(self):
        runtime = self._runtime()
        runtime._closing = False
        session = Session(email="runtime@example.com", status=Status.Ready.value, login_state=True)

        runtime._mark_session_runtime_closed(session, "page crash")

        self.assertEqual(session.status, Status.Update.value)
        self.assertFalse(session.login_state)
        self.assertEqual(session.runtime_last_closed_source, "page crash")
        self.assertIsNotNone(session.runtime_last_closed_at)

    async def test_token_status_exposes_structured_runtime_account_diagnostics(self):
        runtime = self._runtime()
        runtime.Sessions = [Session(email="runtime@example.com", status=Status.Update.value)]
        runtime.Sessions[0].runtime_last_closed_source = "context"
        runtime.Sessions[0].runtime_recovery_count = 2
        with tempfile.TemporaryDirectory() as directory:
            runtime.cc_map = Path(directory) / "map.json"
            runtime.cc_map.write_text(json.dumps({"runtime@example.com": ["conversation-1"]}), "utf8")
            status = await runtime.token_status()

        account = status["accounts"][0]
        self.assertFalse(account["available"])
        self.assertEqual(account["conversation_count"], 1)
        self.assertEqual(account["runtime"]["last_closed_source"], "context")
        self.assertEqual(account["runtime"]["recovery_count"], 2)

    async def test_auth_state_uses_a_hashed_per_account_path_and_restores_it(self):
        runtime = self._runtime()
        with tempfile.TemporaryDirectory() as directory:
            runtime.chat_file = Path(directory)
            session = Session(email="state@example.com", persist_auth_state=True)
            state_path = runtime._auth_state_path(session)
            state_path.parent.mkdir(parents=True)
            state_path.write_text("{}", "utf8")
            context = object()
            runtime._new_context_with_timeout = AsyncMock(return_value=context)

            restored = await runtime._new_session_context(session, "startup_state")

        self.assertIs(restored, context)
        self.assertTrue(session.auth_state_loaded)
        self.assertNotIn("state@example.com", state_path.name)
        runtime._new_context_with_timeout.assert_awaited_once_with("startup_state", storage_state=str(state_path))

    async def test_auth_state_is_written_only_when_enabled(self):
        runtime = self._runtime()
        with tempfile.TemporaryDirectory() as directory:
            runtime.chat_file = Path(directory)
            context = type("Context", (), {"storage_state": AsyncMock()})()
            session = Session(email="state@example.com", persist_auth_state=True, browser_contexts=context)

            await runtime._save_auth_state(session)

            state_path = runtime._auth_state_path(session)
        context.storage_state.assert_awaited_once_with(path=str(state_path))
