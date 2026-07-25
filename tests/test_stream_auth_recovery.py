import unittest
from unittest.mock import AsyncMock, patch

from ChatGPTWeb.ChatGPTWeb import chatgpt
from ChatGPTWeb.api import ChatStreamEvent
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
