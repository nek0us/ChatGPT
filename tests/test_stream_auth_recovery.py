import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from ChatGPTWeb.ChatGPTWeb import chatgpt
from ChatGPTWeb.api import ChatStreamEvent
from ChatGPTWeb.capability_quota import IMAGE_GENERATION
from ChatGPTWeb.config import MsgData, Session, Status


class _Logger:
    def debug(self, _message):
        pass

    def info(self, _message):
        pass

    def warning(self, _message):
        pass

    def error(self, _message):
        pass


class StreamAuthRecoveryTests(unittest.IsolatedAsyncioTestCase):
    def test_empty_existing_turn_without_sse_final_uses_conversation(self):
        message = MsgData(
            msg_send="继续刚才的话题",
            conversation_id="conversation-image-edit",
            next_msg_id="previous-assistant-message",
        )
        parser = SimpleNamespace(
            conversation_id="",
            message_id="",
            text="",
            image_urls=[],
            model="",
            usage={},
            metadata={},
        )

        event = chatgpt._stream_final_candidate(message, parser, None)

        self.assertIsNotNone(event)
        self.assertEqual(event.conversation_id, "conversation-image-edit")
        self.assertEqual(event.message_id, "")
        self.assertEqual(event.type, "final")

    def test_image_result_marks_observed_capability(self):
        runtime = chatgpt.__new__(chatgpt)
        message = MsgData(msg_send="继续处理上一张图")

        runtime._apply_stream_event(
            message,
            ChatStreamEvent(
                type="final",
                metadata={"image_generation_pending": True},
            ),
        )

        self.assertTrue(message.image_gen)
        self.assertEqual(message.required_capabilities, [IMAGE_GENERATION])

    async def test_sentinel_health_probe_schedules_relogin_on_401(self):
        runtime = chatgpt.__new__(chatgpt)
        runtime.logger = _Logger()
        runtime.session_health_check_interval = 300
        runtime._session_health_checked_at = {}
        runtime._record_activity = MagicMock()
        runtime._schedule_stream_reauthentication = MagicMock()
        page = MagicMock()
        page.is_closed.return_value = False
        page.evaluate = AsyncMock(return_value={"status": 401})
        session = Session(
            email="refresh@example.com",
            access_token="expired-token",
            status=Status.Ready.value,
            login_state=True,
            page=page,
        )

        healthy = await runtime._probe_stream_authorization(session, force=True)

        self.assertFalse(healthy)
        self.assertEqual(session.status, Status.Update.value)
        self.assertFalse(session.login_state)
        runtime._schedule_stream_reauthentication.assert_called_once_with(session)

    async def test_sentinel_health_probe_keeps_session_for_transient_failure(self):
        runtime = chatgpt.__new__(chatgpt)
        runtime.logger = _Logger()
        runtime.session_health_check_interval = 300
        runtime._session_health_checked_at = {}
        runtime._schedule_stream_reauthentication = MagicMock()
        page = MagicMock()
        page.is_closed.return_value = False
        page.evaluate = AsyncMock(return_value={"status": 0, "error": "NetworkError"})
        session = Session(
            email="refresh@example.com",
            access_token="current-token",
            status=Status.Ready.value,
            login_state=True,
            page=page,
        )

        healthy = await runtime._probe_stream_authorization(session, force=True)

        self.assertTrue(healthy)
        self.assertEqual(session.status, Status.Ready.value)
        self.assertTrue(session.login_state)
        runtime._schedule_stream_reauthentication.assert_not_called()

    async def test_repeated_expired_token_marks_session_for_relogin(self):
        runtime = chatgpt.__new__(chatgpt)
        runtime.logger = _Logger()
        session = Session(
            email="refresh@example.com",
            access_token="expired-token",
            status=Status.Ready.value,
            login_state=True,
        )

        runtime._mark_stream_authorization_unavailable(session, "token_expired")

        self.assertEqual(session.status, Status.Update.value)
        self.assertFalse(session.login_state)
        self.assertEqual(session.access_token, "")
        self.assertEqual(session.login_failure_kind, "transient")
        self.assertTrue(session.force_fresh_login)

    async def test_keep_alive_does_not_restore_a_sentinel_rejected_session(self):
        runtime = chatgpt.__new__(chatgpt)
        runtime.logger = _Logger()
        runtime.verification_broker = None
        runtime.Sessions = []
        runtime._ensure_session_runtime = AsyncMock(return_value=True)
        session = Session(
            email="refresh@example.com",
            status=Status.Update.value,
            force_fresh_login=True,
        )

        with (
            patch("ChatGPTWeb.ChatGPTWeb.asyncio.sleep", AsyncMock()),
            patch("ChatGPTWeb.ChatGPTWeb.retry_keep_alive", AsyncMock()) as refresh,
            patch.object(runtime, "load_page", AsyncMock()) as load_page,
        ):
            await runtime.__keep_alive__(session)

        refresh.assert_not_awaited()
        load_page.assert_awaited_once_with(session, immediate=True)

    async def test_keep_alive_does_not_compete_with_controlled_login(self):
        runtime = chatgpt.__new__(chatgpt)
        runtime.logger = _Logger()
        runtime._control_login_tasks = {"refresh@example.com": MagicMock(done=MagicMock(return_value=False))}
        runtime._ensure_session_runtime = AsyncMock(return_value=True)
        session = Session(email="refresh@example.com", status=Status.Update.value, force_fresh_login=True)

        with patch.object(runtime, "load_page", AsyncMock()) as load_page:
            await runtime.__keep_alive__(session)

        load_page.assert_not_awaited()

    async def test_keep_alive_yields_when_controlled_login_starts_during_delay(self):
        runtime = chatgpt.__new__(chatgpt)
        runtime.logger = _Logger()
        runtime.Sessions = []
        runtime._control_login_tasks = {}
        session = Session(email="refresh@example.com", status=Status.Update.value)

        async def delay(_seconds):
            runtime._control_login_tasks[session.email] = MagicMock(done=MagicMock(return_value=False))

        with (
            patch("ChatGPTWeb.ChatGPTWeb.asyncio.sleep", delay),
            patch.object(runtime, "load_page", AsyncMock()) as load_page,
        ):
            await runtime.__keep_alive__(session)

        load_page.assert_not_awaited()

    async def test_refresh_bypasses_cached_session_document_and_rebuilds_bridge(self):
        runtime = chatgpt.__new__(chatgpt)
        runtime.logger = _Logger()
        runtime.storage = object()
        runtime.js = ("first bridge", "second bridge")
        runtime.js_used = 0
        runtime.save_screen = False
        session = Session(
            email="refresh@example.com",
            access_token="expired-token",
            status=Status.Ready.value,
            login_state=True,
            page=object(),
        )
        refresh = AsyncMock()
        rebuild = AsyncMock(return_value=1)

        async def refresh_session(refreshed, _url, *_args):
            refreshed.access_token = "fresh-token"
            refreshed.mark_login_success()
            return refreshed

        refresh.side_effect = refresh_session
        with (
            patch("ChatGPTWeb.ChatGPTWeb.retry_keep_alive", refresh),
            patch("ChatGPTWeb.ChatGPTWeb.flush_page", rebuild),
        ):
            self.assertTrue(await runtime._recover_expired_stream_session(session))

        refresh_url = refresh.await_args.args[1]
        self.assertTrue(refresh_url.startswith("https://chatgpt.com/api/auth/session?"))
        self.assertIn("_chatgptweb_refresh=", refresh_url)
        rebuild.assert_awaited_once_with(session.page, runtime.js, 0)
        self.assertEqual(runtime.js_used, 1)

    async def test_expired_requirements_token_is_refreshed_before_error_reaches_caller(self):
        runtime = chatgpt.__new__(chatgpt)
        runtime.logger = _Logger()
        session = Session(email="refresh@example.com", status=Status.Ready.value, login_state=True)
        runtime._prepare_chat_session = AsyncMock(return_value=session)
        runtime._recover_expired_stream_session = AsyncMock(return_value=True)
        runtime._record_usage = lambda *_args: None
        attempts = []

        async def stream_once(data, _session, attempt=1):
            attempts.append(attempt)
            if attempt == 1:
                yield ChatStreamEvent(
                    type="error",
                    text="requirements token unavailable: token_expired",
                )
                raise RuntimeError("requirements token unavailable: token_expired")
            data.status = True
            data.msg_recv = "recovered answer"
            yield ChatStreamEvent(type="final", text="recovered answer")

        runtime._stream_msg_by_browser_fetch = stream_once
        data = MsgData(msg_send="hello", persist_history=False)

        events = [event async for event in runtime.continue_chat_stream(data)]

        self.assertEqual([event.type for event in events], ["final"])
        self.assertEqual(attempts, [1, 2])
        runtime._recover_expired_stream_session.assert_awaited_once_with(session)
        self.assertEqual(data.error_list, [])

    async def test_unready_proof_provider_is_warmed_up_before_stream_retry(self):
        runtime = chatgpt.__new__(chatgpt)
        runtime.logger = _Logger()
        session = Session(email="refresh@example.com", status=Status.Ready.value, login_state=True)
        runtime._prepare_chat_session = AsyncMock(return_value=session)
        runtime._recover_unready_stream_bridge = AsyncMock(return_value=True)
        runtime._record_usage = lambda *_args: None
        attempts = []

        async def stream_once(data, _session, attempt=1):
            attempts.append(attempt)
            if attempt == 1:
                yield ChatStreamEvent(type="error", text="proof provider is not ready")
                raise RuntimeError("proof provider is not ready")
            data.status = True
            data.msg_recv = "warmed answer"
            yield ChatStreamEvent(type="final", text="warmed answer")

        runtime._stream_msg_by_browser_fetch = stream_once
        data = MsgData(msg_send="hello", persist_history=False)

        events = [event async for event in runtime.continue_chat_stream(data)]

        self.assertEqual([event.type for event in events], ["final"])
        self.assertEqual(attempts, [1, 2])
        runtime._recover_unready_stream_bridge.assert_awaited_once_with(session)
        self.assertEqual(data.error_list, [])

    async def test_unrecoverable_expired_session_schedules_login_and_exposes_a_typed_error(self):
        runtime = chatgpt.__new__(chatgpt)
        runtime.logger = _Logger()
        session = Session(email="refresh@example.com", status=Status.Ready.value, login_state=True)
        runtime._prepare_chat_session = AsyncMock(return_value=session)
        runtime._recover_expired_stream_session = AsyncMock(return_value=False)
        runtime._record_activity = MagicMock()
        runtime._schedule_stream_reauthentication = MagicMock()

        async def stream_once(_data, _session, attempt=1):
            yield ChatStreamEvent(type="error", text="requirements token unavailable: token_expired")
            raise RuntimeError("requirements token unavailable: token_expired")

        runtime._stream_msg_by_browser_fetch = stream_once
        events = [event async for event in runtime.continue_chat_stream(MsgData(msg_send="hello"))]

        self.assertEqual(events[-1].type, "error")
        self.assertEqual(events[-1].metadata["error_kind"], "session_reauthentication_pending")
        self.assertTrue(events[-1].metadata["retryable"])
        runtime._schedule_stream_reauthentication.assert_called_once_with(session)

    async def test_image_generation_without_an_image_returns_a_typed_error(self):
        runtime = chatgpt.__new__(chatgpt)
        runtime.logger = _Logger()
        runtime._record_activity = MagicMock()
        session = Session(
            email="image@example.com",
            status=Status.Ready.value,
            login_state=True,
        )
        runtime._prepare_chat_session = AsyncMock(return_value=session)

        async def stream_once(data, _session, attempt=1):
            data.status = True
            data.msg_recv = "The image task finished."
            yield ChatStreamEvent(type="final", text=data.msg_recv)

        runtime._stream_msg_by_browser_fetch = stream_once
        data = MsgData(
            msg_send="draw an image",
            required_capabilities=[IMAGE_GENERATION],
            persist_history=False,
        )

        events = [event async for event in runtime.continue_chat_stream(data)]

        self.assertEqual([event.type for event in events], ["final", "error"])
        self.assertEqual(
            events[-1].metadata["error_kind"],
            "image_generation_no_result",
        )
        self.assertTrue(events[-1].metadata["retryable"])

    async def test_non_auth_stream_error_is_returned_without_refresh_retry(self):
        runtime = chatgpt.__new__(chatgpt)
        runtime.logger = _Logger()
        session = Session(email="refresh@example.com", status=Status.Ready.value, login_state=True)
        runtime._prepare_chat_session = AsyncMock(return_value=session)
        runtime._recover_expired_stream_session = AsyncMock(return_value=True)

        async def stream_once(_data, _session, attempt=1):
            yield ChatStreamEvent(type="error", text="network interrupted")
            raise RuntimeError("network interrupted")

        runtime._stream_msg_by_browser_fetch = stream_once
        events = [event async for event in runtime.continue_chat_stream(MsgData(msg_send="hello"))]

        self.assertEqual([event.type for event in events], ["error", "error"])
        runtime._recover_expired_stream_session.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
