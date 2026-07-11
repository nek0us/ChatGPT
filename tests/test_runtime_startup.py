import asyncio
import unittest
from unittest.mock import AsyncMock, patch
from pathlib import Path
import json
import tempfile

from aiohttp import ClientSession

from ChatGPTWeb.ChatGPTWeb import chatgpt
from ChatGPTWeb.config import Session, Status
from ChatGPTWeb.verification import VerificationBroker, VerificationCancelledError


class _Logger:
    def __init__(self):
        self.warnings = []

    def warning(self, message):
        self.warnings.append(message)

    def debug(self, _message):
        pass

    def info(self, _message):
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
        runtime.control_host = "127.0.0.1"
        runtime.control_port = None
        runtime.control_api_key = None
        runtime._control_runner = None
        runtime._control_site = None
        runtime.control_url = ""
        runtime.verification_broker = VerificationBroker()
        runtime.manage = {"control_url": ""}
        return runtime

    async def test_control_server_uses_runtime_lifecycle(self):
        runtime = self._runtime()
        runtime.control_port = 0
        runtime.control_api_key = "control-test-key"

        await runtime._start_control_server()
        self.assertTrue(runtime.control_url.startswith("http://127.0.0.1:"))
        self.assertIsNotNone(runtime._control_runner)
        async with ClientSession() as client:
            response = await client.get(runtime.control_url)
            body = await response.text()
        self.assertEqual(response.status, 200)
        self.assertIn("ChatGPTWeb Control", body)

        await runtime._close_control_server()
        self.assertIsNone(runtime._control_runner)
        self.assertEqual(runtime.control_url, "")
        self.assertEqual(runtime.manage["control_url"], "")

    async def test_context_creation_passes_storage_state_to_browser(self):
        runtime = self._runtime()
        runtime.headless = True
        context = object()
        runtime.browser = type("Browser", (), {"new_context": AsyncMock(return_value=context)})()

        created = await runtime._new_context_with_timeout("startup_state", storage_state="state.json")

        self.assertIs(created, context)
        runtime.browser.new_context.assert_awaited_once_with(storage_state="state.json")

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

    async def test_control_account_persists_manual_disable_and_cancels_verification(self):
        runtime = self._runtime()
        runtime.Sessions = [Session(email="control@example.com", status=Status.Ready.value, login_state=True)]
        with tempfile.TemporaryDirectory() as directory:
            runtime.chat_file = Path(directory)
            (runtime.chat_file / "sessions").mkdir()
            runtime.cc_map = runtime.chat_file / "map.json"
            runtime.cc_map.write_text("{}", "utf8")
            task = asyncio.create_task(runtime.verification_broker.request_code("control@example.com", "openai"))
            await asyncio.sleep(0)

            disabled = await runtime.control_account("control@example.com", "disable")
            self.assertTrue(disabled["manual_disabled"])
            self.assertTrue(runtime.Sessions[0].is_login_disabled())
            with self.assertRaises(VerificationCancelledError):
                await task

            enabled = await runtime.control_account("control@example.com", "enable")
            self.assertFalse(enabled["manual_disabled"])
            self.assertFalse(runtime.Sessions[0].is_login_disabled())

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
