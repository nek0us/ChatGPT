import json
import unittest
from unittest.mock import AsyncMock, patch

from ChatGPTWeb.ChatGPTWeb import chatgpt
from ChatGPTWeb.config import MsgData, Session, Status


class _Logger:
    def debug(self, _message):
        pass


def _runtime_with_fake_send(fake_send):
    runtime = chatgpt.__new__(chatgpt)
    runtime.logger = _Logger()
    runtime._send_msg_once = fake_send
    return runtime


class SendRetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_transient_failure_retries_and_returns_next_success(self):
        attempts = []

        async def fake_send(msg_data, session, send_status=True, attempt=1):
            attempts.append(attempt)
            if attempt == 1:
                msg_data.add_error("send_message", "network timeout", retryable=True, attempt=attempt)
                raise RuntimeError("network timeout")
            msg_data.status = True
            msg_data.msg_recv = "recovered"
            return msg_data

        runtime = _runtime_with_fake_send(fake_send)
        session = Session(email="retry@example.com", status=Status.Ready.value)
        with patch("ChatGPTWeb.ChatGPTWeb.asyncio.sleep", new=AsyncMock()):
            result = await runtime.send_msg(MsgData(msg_send="hello"), session, retry=3)

        self.assertEqual(attempts, [1, 2])
        self.assertTrue(result.status)
        self.assertEqual(result.msg_recv, "recovered")
        self.assertFalse(any(error["kind"] == "send_retry_max" for error in result.error_list))

    async def test_retryable_failure_records_limit_only_after_last_attempt(self):
        attempts = []

        async def fake_send(msg_data, session, send_status=True, attempt=1):
            attempts.append(attempt)
            msg_data.add_error("send_message", "network timeout", retryable=True, attempt=attempt)
            raise RuntimeError("network timeout")

        runtime = _runtime_with_fake_send(fake_send)
        session = Session(email="retry@example.com", status=Status.Ready.value)
        with patch("ChatGPTWeb.ChatGPTWeb.asyncio.sleep", new=AsyncMock()):
            result = await runtime.send_msg(MsgData(msg_send="hello"), session, retry=2)

        self.assertEqual(attempts, [1, 2])
        retry_limit_errors = [error for error in result.error_list if error["kind"] == "send_retry_max"]
        self.assertEqual(len(retry_limit_errors), 1)
        self.assertEqual(retry_limit_errors[0]["attempt"], 2)

    async def test_updated_session_stops_retry_without_claiming_retry_limit(self):
        attempts = []

        async def fake_send(msg_data, session, send_status=True, attempt=1):
            attempts.append(attempt)
            session.status = Status.Update.value
            msg_data.add_error("token_expired", "refresh required", retryable=False, attempt=attempt)
            raise RuntimeError("token expired")

        runtime = _runtime_with_fake_send(fake_send)
        session = Session(email="expired@example.com", status=Status.Ready.value)
        result = await runtime.send_msg(MsgData(msg_send="hello"), session, retry=3)

        self.assertEqual(attempts, [1])
        self.assertEqual(session.status, Status.Update.value)
        self.assertFalse(any(error["kind"] == "send_retry_max" for error in result.error_list))


class ConversationPayloadTests(unittest.TestCase):
    def test_web_search_flag_reaches_new_and_existing_conversation_payloads(self):
        runtime = chatgpt.__new__(chatgpt)
        new_payload = json.loads(runtime._build_conversation_payload(MsgData(msg_send="search", web_search=True)))
        old_payload = json.loads(runtime._build_conversation_payload(MsgData(
            msg_send="search again",
            conversation_id="conversation-1",
            p_msg_id="message-1",
            web_search=True,
        )))

        self.assertTrue(new_payload["force_use_search"])
        self.assertEqual(new_payload["messages"][0]["metadata"]["system_hints"], ["search"])
        self.assertTrue(old_payload["force_use_search"])
        self.assertEqual(old_payload["messages"][0]["metadata"]["system_hints"], ["search"])

    def test_stream_controls_reach_message_data(self):
        from ChatGPTWeb.service import ChatRequest

        data = ChatRequest(
            prompt="wait",
            stream_idle_timeout_seconds=90,
            stream_status_interval_seconds=10,
        ).to_msg_data()

        self.assertEqual(data.stream_idle_timeout_seconds, 90)
        self.assertEqual(data.stream_status_interval_seconds, 10)
