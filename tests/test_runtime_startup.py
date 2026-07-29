import asyncio
import unittest
from unittest.mock import AsyncMock, patch
from pathlib import Path
from datetime import datetime, timedelta
import json
import tempfile
from collections import deque

from aiohttp import ClientSession

from ChatGPTWeb.ChatGPTWeb import chatgpt
from ChatGPTWeb.api import flush_page
from ChatGPTWeb.config import MsgData, Session, Status
from ChatGPTWeb.storage import RuntimeStorage
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

    def error(self, _message):
        pass


class _Page:
    def __init__(self):
        self.goto = AsyncMock()


class _BlankPage:
    def __init__(self):
        self.url = "about:newtab"
        self.goto = AsyncMock(side_effect=TimeoutError("navigation stalled"))
        self.evaluate = AsyncMock()


class RuntimeStartupTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._storage_directory = tempfile.TemporaryDirectory()

    def tearDown(self):
        self._storage_directory.cleanup()

    def _runtime(self):
        runtime = chatgpt.__new__(chatgpt)
        runtime.logger = _Logger()
        runtime.js = ("first", "second")
        runtime.js_used = 0
        runtime.startup_timeout = 1
        runtime.ready_timeout = 1
        runtime.chat_rate_limit_cooldown_seconds = 5 * 60 * 60
        runtime.control_host = "127.0.0.1"
        runtime.control_port = None
        runtime.control_api_key = None
        runtime._control_runner = None
        runtime._control_site = None
        runtime.control_url = ""
        runtime.verification_broker = VerificationBroker()
        runtime.manage = {"control_url": ""}
        runtime.storage = RuntimeStorage(Path(self._storage_directory.name))
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

    async def test_client_cannot_continue_another_clients_conversation(self):
        runtime = self._runtime()
        runtime.manage["start"] = True
        runtime.storage.update_conversation_index(
            "conversation-owned", "account@example.com", "created", "updated", 1,
            client_id="api:key-one",
        )
        msg_data = MsgData(
            conversation_id="conversation-owned",
            client_id="api:key-two",
            enforce_client_ownership=True,
        )

        session = await runtime._prepare_chat_session(msg_data)

        self.assertIsNone(session)
        self.assertEqual(msg_data.error_list[0]["kind"], "conversation_client_mismatch")

    async def test_context_creation_passes_storage_state_to_browser(self):
        runtime = self._runtime()
        runtime.headless = True
        context = object()
        runtime.browser = type("Browser", (), {"new_context": AsyncMock(return_value=context)})()

        created = await runtime._new_context_with_timeout("startup_state", storage_state="state.json")

        self.assertIs(created, context)
        runtime.browser.new_context.assert_awaited_once_with(storage_state="state.json")

    def test_firefox_preferences_allow_persistent_storage_for_automation(self):
        self.assertEqual(
            chatgpt._firefox_user_prefs(),
            {
                "dom.storageManager.prompt.testing": True,
                "dom.storageManager.prompt.testing.allow": True,
            },
        )

    async def test_firefox_install_check_uses_executable_path_without_launching(self):
        runtime = self._runtime()
        playwright = type("Playwright", (), {
            "firefox": type("Firefox", (), {"executable_path": __file__})(),
        })()
        manager = type("Manager", (), {
            "start": AsyncMock(return_value=playwright),
            "__aexit__": AsyncMock(),
        })()

        with patch("ChatGPTWeb.ChatGPTWeb.async_playwright", return_value=manager):
            installed = await runtime.is_firefox_installed()

        self.assertTrue(installed)
        manager.start.assert_awaited_once()
        manager.__aexit__.assert_awaited_once()

    async def test_startup_page_creation_failure_is_transient_not_stop(self):
        runtime = self._runtime()
        context = object()
        session = Session(
            email="startup@example.com",
            password="password",
            browser_contexts=context,
        )
        runtime._new_page_with_timeout = AsyncMock(side_effect=TimeoutError("page create timeout"))

        await runtime._chatgpt__login(session)

        self.assertEqual(session.status, Status.Update.value)
        self.assertEqual(session.login_failure_kind, "transient")
        self.assertTrue(session.is_login_disabled())
        self.assertIsNone(session.browser_contexts)

    async def test_bridge_refuses_to_inject_into_a_blank_page(self):
        page = _BlankPage()

        with self.assertRaisesRegex(RuntimeError, "not on ChatGPT"):
            await flush_page(page, ("first", "second"), 0)

        page.evaluate.assert_not_awaited()

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

    async def test_bridge_initialization_recreates_one_context_before_marking_failure(self):
        runtime = self._runtime()
        session = Session(email="bridge@example.com")
        original_page = _Page()
        recovered_page = _Page()

        async def recover(_session):
            session.page = recovered_page
            return True

        runtime._recover_session_context_for_bridge = AsyncMock(side_effect=recover)
        runtime._initialize_page_bridge = AsyncMock(side_effect=[False, True])

        ready = await runtime._initialize_page_bridge_with_recovery(session, original_page)

        self.assertTrue(ready)
        runtime._recover_session_context_for_bridge.assert_awaited_once_with(session)
        recovered_page.goto.assert_awaited_once_with("https://chatgpt.com/", timeout=20000, wait_until="domcontentloaded")
        self.assertEqual(session.status, "")

    async def test_load_page_recreates_context_after_session_probe_exhaustion(self):
        runtime = self._runtime()
        runtime.begin_sleep_time = False
        runtime.save_screen = False
        runtime.httpx_status = False
        original_page = _Page()
        original_page.evaluate = AsyncMock(return_value="test-agent")
        recovered_page = _Page()
        session = Session(
            email="refresh@example.com",
            password="password",
            access_token="stale-token",
            page=original_page,
            browser_contexts=object(),
            status=Status.Update.value,
            session_refresh_recovery_needed=True,
        )

        async def recover(_session):
            session.page = recovered_page
            return True

        async def auth(*_args, **_kwargs):
            session.access_token = "new-token"
            session.mark_login_success()

        runtime._recover_session_context_for_bridge = AsyncMock(side_effect=recover)
        runtime._initialize_page_bridge_with_recovery = AsyncMock(return_value=True)
        runtime._refresh_account_plan = AsyncMock()
        runtime._save_auth_state = AsyncMock()
        runtime._schedule_session_health_probe = lambda _session: None

        with patch("ChatGPTWeb.ChatGPTWeb.retry_keep_alive", new=AsyncMock(return_value=session)), patch(
            "ChatGPTWeb.ChatGPTWeb.Auth", new=AsyncMock(side_effect=auth)
        ):
            await runtime.load_page(session, immediate=True)

        runtime._recover_session_context_for_bridge.assert_awaited_once_with(session)
        self.assertFalse(session.session_refresh_recovery_needed)
        self.assertEqual(session.status, Status.Ready.value)
        recovered_page.goto.assert_awaited_once_with(
            "https://chatgpt.com/", timeout=20000, wait_until="domcontentloaded"
        )

    async def test_context_recovery_suppresses_intentional_close_diagnostics(self):
        runtime = self._runtime()
        runtime._closing = False
        context = type("Context", (), {"close": AsyncMock()})()
        session = Session(email="recover@example.com", browser_contexts=context, page=object())
        runtime._ensure_session_runtime = AsyncMock(return_value=True)

        recovered = await runtime._recover_session_context_for_bridge(session)

        self.assertTrue(recovered)
        context.close.assert_awaited_once()
        self.assertIsNone(session.browser_contexts)
        self.assertIsNone(session.page)
        self.assertEqual(session.status, "")

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
        runtime.Sessions[0].runtime_last_closed_at = datetime.now()
        runtime.Sessions[0].runtime_recovery_count = 2
        runtime.storage.update_conversation_index(
            "conversation-1", "runtime@example.com", "2026-01-01T00:00:00", "2026-01-01T00:00:00", 1,
        )
        status = await runtime.token_status()

        account = status["accounts"][0]
        self.assertFalse(account["available"])
        self.assertEqual(account["mode"], "openai")
        self.assertEqual(account["conversation_count"], 1)
        self.assertEqual(account["runtime"]["last_closed_source"], "context")
        self.assertEqual(account["runtime"]["recovery_count"], 2)
        self.assertEqual(account["operational_state"], "browser_runtime_recovery_needed")
        self.assertEqual(account["recommended_action"], "wait_then_retry")

    async def test_token_status_explains_manual_retry_for_a_permanent_login_failure(self):
        runtime = self._runtime()
        runtime.Sessions = [Session(
            email="locked@example.com", status=Status.Stop.value,
            login_failure_kind="account_locked",
        )]
        with tempfile.TemporaryDirectory() as directory:
            runtime.cc_map = Path(directory) / "map.json"
            runtime.cc_map.write_text("{}", "utf8")
            account = (await runtime.token_status())["accounts"][0]

        self.assertEqual(account["retry_mode"], "manual")
        self.assertIn("permanently unavailable", account["login_guidance"])
        self.assertEqual(account["retry_after_seconds"], 0)
        self.assertEqual(account["operational_state"], "account_unavailable")
        self.assertEqual(account["recommended_action"], "restore_account")

    async def test_token_status_distinguishes_bridge_and_reauthentication_failures(self):
        runtime = self._runtime()
        runtime.Sessions = [
            Session(
                email="bridge@example.com",
                status=Status.Update.value,
                login_failure_kind="transient",
                last_login_error="browser bridge initialization failed",
            ),
            Session(
                email="reauth@example.com",
                status=Status.Update.value,
                login_failure_kind="transient",
                force_fresh_login=True,
            ),
        ]

        accounts = (await runtime.token_status())["accounts"]

        self.assertEqual(accounts[0]["operational_state"], "browser_bridge_unavailable")
        self.assertEqual(accounts[0]["recommended_action"], "wait_then_retry")
        self.assertEqual(accounts[1]["operational_state"], "session_reauthentication_required")
        self.assertEqual(accounts[1]["recommended_action"], "retry_login")

    async def test_token_status_exposes_process_local_usage_by_model(self):
        runtime = self._runtime()
        runtime.Sessions = [Session(email="usage@example.com")]
        runtime._usage_by_account = {
            "usage@example.com": {
                "gpt-5-mini": {"requests": 2, "input_tokens": 10, "output_tokens": 4},
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            runtime.cc_map = Path(directory) / "map.json"
            runtime.cc_map.write_text("{}", "utf8")
            status = await runtime.token_status()

        usage = status["accounts"][0]["usage"]
        self.assertEqual(usage["source"], "observed_upstream")
        self.assertEqual(usage["requests"], 2)
        self.assertEqual(usage["models"]["gpt-5-mini"]["output_tokens"], 4)
        self.assertIsNone(usage["quota"])

    async def test_activity_is_bounded_and_excludes_message_payloads(self):
        runtime = self._runtime()
        for index in range(205):
            runtime._record_activity("activity@example.com", "control", f"event {index}")

        activity = await runtime.get_activity(limit=300)

        self.assertEqual(len(activity["events"]), 200)
        self.assertEqual(activity["events"][0]["message"], "event 204")

    async def test_billing_plan_refresh_updates_only_explicit_plan_evidence(self):
        runtime = self._runtime()
        page = type("Page", (), {
            "is_closed": lambda self: False,
            "evaluate": AsyncMock(return_value={
                "status": 200,
                "payload": {"subscription": {"plan": "go"}},
                "modelSlugs": ["gpt-5-5", "auto"],
            }),
        })()
        session = Session(email="plan@example.com", access_token="token", device_id="device", page=page)

        await runtime._refresh_account_plan(session)

        self.assertEqual(session.account_plan, "go")
        self.assertEqual(session.account_plan_source, "fetch:/backend-api/pageConfigs/billing")
        self.assertIsNotNone(session.account_plan_observed_at)
        self.assertEqual(session.observed_models, ["auto", "gpt-5-5"])
        self.assertEqual(session.observed_models_source, "localStorage:models")

    async def test_control_account_can_refresh_capabilities_without_relogin(self):
        runtime = self._runtime()
        runtime.Sessions = [Session(email="refresh@example.com")]
        runtime._refresh_account_plan = AsyncMock()
        with tempfile.TemporaryDirectory() as directory:
            runtime.chat_file = Path(directory)
            (runtime.chat_file / "sessions").mkdir()
            runtime.cc_map = runtime.chat_file / "map.json"
            runtime.cc_map.write_text("{}", "utf8")

            await runtime.control_account("refresh@example.com", "refresh_capabilities")

        runtime._refresh_account_plan.assert_awaited_once_with(runtime.Sessions[0])

    async def test_paid_model_selection_prefers_observed_plan_over_legacy_flag(self):
        runtime = self._runtime()
        runtime.manage["start"] = True
        runtime._ensure_session_runtime = AsyncMock(return_value=True)
        legacy_plus_but_free = Session(
            email="free@example.com", gptplus=True, account_plan="free",
            status=Status.Ready.value, login_state=True,
        )
        observed_pro = Session(
            email="pro@example.com", gptplus=False, account_plan="pro",
            status=Status.Ready.value, login_state=True,
        )
        runtime.Sessions = [legacy_plus_but_free, observed_pro]
        with tempfile.TemporaryDirectory() as directory:
            runtime.cc_map = Path(directory) / "map.json"
            runtime.cc_map.write_text("{}", "utf8")
            selected = await runtime._prepare_chat_session(MsgData(msg_send="hello", gpt_model="gpt-4"))

        self.assertIs(selected, observed_pro)

    async def test_go_account_requires_an_observed_model_match(self):
        runtime = self._runtime()
        runtime.manage["start"] = True
        runtime._ensure_session_runtime = AsyncMock(return_value=True)
        go = Session(
            email="go@example.com", gptplus=False, account_plan="go",
            observed_models=["gpt-4"], status=Status.Ready.value, login_state=True,
        )
        runtime.Sessions = [go]
        with tempfile.TemporaryDirectory() as directory:
            runtime.cc_map = Path(directory) / "map.json"
            runtime.cc_map.write_text("{}", "utf8")
            selected = await runtime._prepare_chat_session(MsgData(msg_send="hello", gpt_model="gpt-4"))

        self.assertIs(selected, go)

    async def test_new_conversation_prefers_least_recently_reserved_account(self):
        runtime = self._runtime()
        runtime.manage["start"] = True
        runtime._ensure_session_runtime = AsyncMock(return_value=True)
        older = Session(
            email="older@example.com", status=Status.Ready.value,
            login_state=True, last_active=datetime.now() - timedelta(minutes=10),
        )
        newer = Session(
            email="newer@example.com", status=Status.Ready.value,
            login_state=True, last_active=datetime.now() - timedelta(minutes=1),
        )
        runtime.Sessions = [newer, older]
        before = datetime.now()
        with tempfile.TemporaryDirectory() as directory:
            runtime.cc_map = Path(directory) / "map.json"
            runtime.cc_map.write_text("{}", "utf8")
            selected = await runtime._prepare_chat_session(MsgData(msg_send="hello"))

        self.assertIs(selected, older)
        self.assertEqual(older.status, Status.Working.value)
        self.assertGreaterEqual(older.last_active, before)

    async def test_balanced_new_conversation_prefers_lower_recent_assignment_count(self):
        runtime = self._runtime()
        runtime.manage["start"] = True
        runtime.account_selection_strategy = "usage_balanced"
        runtime.account_selection_window_seconds = 60 * 60
        runtime._ensure_session_runtime = AsyncMock(return_value=True)
        now = datetime.now()
        busy_but_older = Session(
            email="busy@example.com", status=Status.Ready.value,
            login_state=True, last_active=now - timedelta(minutes=10),
        )
        less_used = Session(
            email="less-used@example.com", status=Status.Ready.value,
            login_state=True, last_active=now - timedelta(minutes=1),
        )
        runtime.Sessions = [busy_but_older, less_used]
        runtime._account_selection_history = {
            busy_but_older.email: deque([now - timedelta(minutes=2)] * 3),
            less_used.email: deque([now - timedelta(minutes=2)]),
        }
        with tempfile.TemporaryDirectory() as directory:
            runtime.cc_map = Path(directory) / "map.json"
            runtime.cc_map.write_text("{}", "utf8")
            selected = await runtime._prepare_chat_session(MsgData(msg_send="hello"))

        self.assertIs(selected, less_used)
        self.assertEqual(runtime._recent_account_assignment_count(less_used.email), 2)

    def test_balanced_assignment_window_discards_stale_reservations(self):
        runtime = self._runtime()
        runtime.account_selection_window_seconds = 60
        now = datetime.now()
        runtime._account_selection_history = {
            "stale@example.com": deque([now - timedelta(seconds=61)]),
        }

        self.assertEqual(runtime._recent_account_assignment_count("stale@example.com", now), 0)

    async def test_existing_conversation_does_not_create_a_new_assignment_reservation(self):
        runtime = self._runtime()
        runtime.manage["start"] = True
        runtime._ensure_session_runtime = AsyncMock(return_value=True)
        owner = Session(
            email="owner@example.com", status=Status.Ready.value,
            login_state=True,
        )
        runtime.Sessions = [owner]
        runtime._account_selection_history = {}

        selected = await runtime._prepare_chat_session(MsgData(
            msg_send="continue", conversation_id="conversation-1",
            p_msg_id="parent-1", account_hint=owner.email,
        ))

        self.assertIs(selected, owner)
        self.assertNotIn(owner.email, runtime._account_selection_history)

    async def test_new_conversation_releases_its_reservation_when_runtime_is_unavailable(self):
        runtime = self._runtime()
        runtime.manage["start"] = True
        runtime._ensure_session_runtime = AsyncMock(return_value=False)
        session = Session(
            email="unavailable@example.com", status=Status.Ready.value,
            login_state=True,
        )
        runtime.Sessions = [session]

        selected = await runtime._prepare_chat_session(MsgData(msg_send="hello"))

        self.assertIsNone(selected)
        self.assertEqual(session.status, Status.Ready.value)
        self.assertNotIn(session.email, getattr(runtime, "_account_selection_history", {}))

    async def test_new_conversation_skips_a_chat_rate_limited_account(self):
        runtime = self._runtime()
        runtime.manage["start"] = True
        runtime._ensure_session_runtime = AsyncMock(return_value=True)
        limited = Session(
            email="limited@example.com", status=Status.Ready.value,
            login_state=True, last_active=datetime.now() - timedelta(minutes=10),
        )
        limited.mark_chat_rate_limited("hourly message limit")
        available = Session(
            email="available@example.com", status=Status.Ready.value,
            login_state=True, last_active=datetime.now() - timedelta(minutes=1),
        )
        runtime.Sessions = [limited, available]
        with tempfile.TemporaryDirectory() as directory:
            runtime.cc_map = Path(directory) / "map.json"
            runtime.cc_map.write_text("{}", "utf8")
            selected = await runtime._prepare_chat_session(MsgData(msg_send="hello"))

        self.assertIs(selected, available)

    async def test_all_chat_rate_limited_accounts_report_a_retryable_error(self):
        runtime = self._runtime()
        runtime.manage["start"] = True
        limited = Session(email="limited@example.com", status=Status.Ready.value, login_state=True)
        limited.mark_chat_rate_limited("hourly message limit")
        runtime.Sessions = [limited]
        with tempfile.TemporaryDirectory() as directory:
            runtime.cc_map = Path(directory) / "map.json"
            runtime.cc_map.write_text("{}", "utf8")
            data = MsgData(msg_send="hello")
            selected = await runtime._prepare_chat_session(data)

        self.assertIsNone(selected)
        self.assertEqual(data.error_list[0]["kind"], "rate_limited")
        self.assertTrue(data.error_list[0]["retryable"])

    def test_upstream_message_limit_is_not_retried_as_a_transport_failure(self):
        runtime = self._runtime()
        session = Session(email="limited@example.com")
        error = RuntimeError("You've reached our limit of messages per hour. Please try again later.")

        self.assertTrue(runtime._is_upstream_rate_limit_error(error))
        self.assertFalse(runtime._is_retryable_send_error(error, session))

    def test_chat_rate_limit_prefers_an_upstream_retry_hint(self):
        runtime = self._runtime()
        session = Session(email="limited@example.com")
        before = datetime.now()

        runtime._mark_chat_rate_limited(
            session,
            'Too many requests. Please try again in 12 minutes.',
        )

        self.assertEqual(session.chat_rate_limit_source, "upstream_retry_hint")
        self.assertGreaterEqual(
            (session.chat_rate_limited_until - before).total_seconds(),
            719,
        )
        self.assertLessEqual(
            (session.chat_rate_limited_until - before).total_seconds(),
            721,
        )

    def test_chat_rate_limit_uses_the_configured_fallback_window(self):
        runtime = self._runtime()
        runtime.chat_rate_limit_cooldown_seconds = 321
        session = Session(email="limited@example.com")
        before = datetime.now()

        runtime._mark_chat_rate_limited(session, "rate limit reached")

        self.assertEqual(session.chat_rate_limit_source, "configured_cooldown")
        self.assertGreaterEqual(
            (session.chat_rate_limited_until - before).total_seconds(),
            320,
        )
        self.assertLessEqual(
            (session.chat_rate_limited_until - before).total_seconds(),
            322,
        )

    async def test_token_status_identifies_chat_quota_cooldown(self):
        runtime = self._runtime()
        session = Session(email="limited@example.com", status=Status.Ready.value, login_state=True)
        session.mark_chat_rate_limited(
            "rate limit reached",
            cooldown_seconds=300,
            source="configured_cooldown",
        )
        runtime.Sessions = [session]

        status = await runtime.token_status()
        account = status["accounts"][0]

        self.assertFalse(account["available"])
        self.assertTrue(account["chat_rate_limited"])
        self.assertEqual(account["chat_rate_limit_source"], "configured_cooldown")
        self.assertEqual(account["retry_mode"], "quota_wait")

    async def test_manual_disable_excludes_a_ready_session_from_new_requests(self):
        runtime = self._runtime()
        runtime.manage["start"] = True
        disabled = Session(
            email="disabled@example.com", status=Status.Ready.value,
            login_state=True, manual_disabled=True,
        )
        runtime.Sessions = [disabled]
        with tempfile.TemporaryDirectory() as directory:
            runtime.cc_map = Path(directory) / "map.json"
            runtime.cc_map.write_text("{}", "utf8")
            data = MsgData(msg_send="hello")
            selected = await runtime._prepare_chat_session(data)

        self.assertIsNone(selected)
        self.assertEqual(data.error_list[0]["kind"], "no_available_session")

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

    async def test_control_account_retries_openai_verification_without_repeating_password(self):
        runtime = self._runtime()
        runtime.begin_sleep_time = True
        runtime.Sessions = [Session(
            email="retry@example.com",
            password="configured-password",
            status=Status.Stop.value,
            login_failure_kind="need_verification",
        )]
        started = asyncio.Event()
        release = asyncio.Event()

        async def controlled_load_page(*_args, **_kwargs):
            started.set()
            await release.wait()

        runtime.load_page = AsyncMock(side_effect=controlled_load_page)
        with tempfile.TemporaryDirectory() as directory:
            runtime.chat_file = Path(directory)
            (runtime.chat_file / "sessions").mkdir()
            runtime.cc_map = runtime.chat_file / "map.json"
            runtime.cc_map.write_text("{}", "utf8")

            account = await runtime.control_account("retry@example.com", "retry_login")
            await started.wait()

        self.assertEqual(runtime.Sessions[0].status, Status.Update.value)
        self.assertEqual(runtime.Sessions[0].last_login_error, "manual login retry requested")
        self.assertTrue(account["login_retry_pending"])
        runtime.load_page.assert_awaited_once_with(
            runtime.Sessions[0],
            immediate=True,
            prefer_openai_otp=True,
        )
        release.set()
        await asyncio.sleep(0)

    async def test_auth_state_uses_a_hashed_per_account_path_and_restores_it(self):
        runtime = self._runtime()
        session = Session(email="state@example.com", persist_auth_state=True)
        state_path = runtime._auth_state_path(session)
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
        context = type("Context", (), {"storage_state": AsyncMock()})()
        session = Session(email="state@example.com", persist_auth_state=True, browser_contexts=context)

        await runtime._save_auth_state(session)

        state_path = runtime._auth_state_path(session)
        context.storage_state.assert_awaited_once_with(path=str(state_path))
