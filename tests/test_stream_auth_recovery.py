import unittest
from unittest.mock import AsyncMock

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
