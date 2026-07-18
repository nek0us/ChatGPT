import asyncio
import json
import unittest

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from ChatGPTWeb.ChatGPTWeb import chatgpt
from ChatGPTWeb.api import ChatStreamDecoder, ChatStreamEvent, ChatStreamParser
from ChatGPTWeb.config import MsgData, Session
from ChatGPTWeb.http_api import chat_request_from_payload, create_control_app, create_http_app
from ChatGPTWeb.service import ChatRequest, ChatService, ConversationOperation
from ChatGPTWeb.verification import VerificationBroker, VerificationCancelledError


class ChatStreamParserTests(unittest.TestCase):
    def test_full_message_carries_model_usage_and_references(self):
        parser = ChatStreamParser()
        events = parser.feed(
            {
                "conversation_id": "conversation-1",
                "usage": {"input_tokens": 12, "output_tokens": 5},
                "message": {
                    "id": "message-1",
                    "author": {"role": "assistant"},
                    "content": {"parts": ["Hello from ChatGPT."]},
                    "status": "finished_successfully",
                    "metadata": {
                        "model_slug": "gpt-5-5-mini",
                        "default_model_slug": "auto",
                        "content_references": [{"url": "https://example.com"}],
                        "citations": [{"title": "Example"}],
                        "aggregate_result": {"type": "weather", "temperature": 22},
                    },
                },
            }
        )

        self.assertEqual([event.type for event in events], ["delta"])
        final = parser.final_event()
        self.assertEqual(final.text, "Hello from ChatGPT.")
        self.assertEqual(final.conversation_id, "conversation-1")
        self.assertEqual(final.message_id, "message-1")
        self.assertEqual(final.model, "gpt-5-5-mini")
        self.assertEqual(final.usage, {"input_tokens": 12, "output_tokens": 5})
        self.assertEqual(final.metadata["default_model_slug"], "auto")
        self.assertEqual(final.metadata["citations"][0]["title"], "Example")
        self.assertEqual(final.metadata["aggregate_result"]["type"], "weather")

    def test_patches_append_overlap_without_repeating_text(self):
        parser = ChatStreamParser()
        events = []
        for value in ("Hello", "Hello, world", "world!"):
            events.extend(
                parser.feed(
                    {
                        "path": "/message/content/parts/0",
                        "op": "append",
                        "value": value,
                    }
                )
            )

        self.assertEqual([event.text for event in events], ["Hello", ", world", "!"])
        self.assertEqual(parser.text, "Hello, world!")

    def test_older_full_snapshot_cannot_truncate_accumulated_text(self):
        parser = ChatStreamParser()
        parser.feed({
            "message": {
                "author": {"role": "assistant"},
                "content": {"parts": ["first paragraph\n\nsecond paragraph\n\nthird paragraph"]},
            }
        })

        events = parser.feed({
            "message": {
                "author": {"role": "assistant"},
                "content": {"parts": ["first paragraph\n\nsecond paragraph"]},
            }
        })

        self.assertEqual(events, [])
        self.assertEqual(parser.final_event().text, "first paragraph\n\nsecond paragraph\n\nthird paragraph")

    def test_decoder_waits_for_transport_completion_before_emitting_final(self):
        decoder = ChatStreamDecoder()
        early_final = {
            "p": "/message/status",
            "o": "replace",
            "v": "finished_successfully",
        }
        text_patch = {
            "p": "/message/content/parts/0",
            "o": "append",
            "v": "later response",
        }
        stream = "data: " + json.dumps(early_final) + "\n\n"
        stream += "data: " + json.dumps(text_patch) + "\n\n"
        stream += "data: [DONE]\n\n"

        events = decoder.feed(stream)
        self.assertEqual([event.type for event in events], ["delta", "final"])
        self.assertEqual(events[-1].text, "later response")

    def test_image_patch_emits_one_event_and_final_contains_urls(self):
        parser = ChatStreamParser()
        events = parser.feed(
            {
                "path": "/message/metadata/image_results",
                "op": "replace",
                "value": [
                    {"content_url": "https://images.example/one.png"},
                    {"url": "https://images.example/two.png"},
                ],
            }
        )

        self.assertEqual([event.type for event in events], ["image"])
        self.assertEqual(len(events[0].image_urls), 2)
        self.assertEqual(parser.final_event().image_urls, events[0].image_urls)


class _FakeBackend:
    def __init__(self):
        self.sent = []

    async def continue_chat(self, msg_data):
        self.sent.append(msg_data)
        msg_data.status = True
        msg_data.msg_recv = "service response"
        msg_data.conversation_id = "conversation-service"
        msg_data.next_msg_id = "message-service"
        msg_data.model_requested = msg_data.gpt_model
        msg_data.model_used = "gpt-5-5-mini"
        msg_data.usage = {"output_tokens": 3}
        msg_data.response_metadata = {"finish_details": {"type": "stop"}}
        return msg_data

    async def init_personality(self, msg_data):
        msg_data.msg_send = f"persona:{msg_data.msg_send}"
        return await self.continue_chat(msg_data)

    async def get_persona_prompt(self, name):
        return {"assistant": "stay concise"}.get(name, "")

    async def back_chat_from_input(self, msg_data):
        msg_data.msg_send = f"rewind:{msg_data.msg_send}"
        return await self.continue_chat(msg_data)

    async def back_init_personality(self, msg_data):
        msg_data.msg_send = "reset_to_persona"
        return await self.continue_chat(msg_data)

    async def continue_chat_stream(self, msg_data):
        yield ChatStreamEvent(type="status", metadata={"phase": "waiting_for_upstream", "idle_seconds": 15})
        yield ChatStreamEvent(type="delta", text="stream response", raw={"request": msg_data.msg_send})
        parser = ChatStreamParser()
        parser.feed({"conversation_id": "conversation-stream", "message_id": "message-stream"})
        parser.text = "stream response"
        parser.model = "gpt-5-5-mini"
        yield parser.final_event({"request": msg_data.msg_send})

    async def show_chat_history(self, msg_data):
        return [{"index": "1", "Q": "question", "A": msg_data.conversation_id, "next_msg_id": "m"}]

    async def token_status(self):
        return {"account": ["account@example.com"]}

    async def get_model_catalog(self, fetch_remote=True):
        return {
            "fetch_remote": fetch_remote,
            "accounts": [{
                "email": "account@example.com",
                "remote": {
                    "source": "fetch:models",
                    "models": [{"slug": "gpt-5-5-mini", "contextWindow": 100}],
                },
                "cached": [],
            }],
        }

    async def control_account(self, account, action):
        if account != "account@example.com":
            raise KeyError("account was not found")
        if action not in {"disable", "enable", "retry_login", "refresh_capabilities"}:
            raise ValueError("action must be 'disable', 'enable', 'retry_login', or 'refresh_capabilities'")
        return {"email": account, "manual_disabled": action == "disable"}

    async def get_activity(self, limit=50):
        return {"events": [{"at": "2026-01-01T00:00:00", "account": "account@example.com", "event": "test", "message": "safe"}][:limit]}


class _Logger:
    def debug(self, _message):
        pass


class _ClosableStreamBackend(_FakeBackend):
    def __init__(self):
        super().__init__()
        self.stream_closed = False
        self.release = asyncio.Event()

    async def continue_chat_stream(self, msg_data):
        try:
            yield ChatStreamEvent(type="delta", text="first")
            await self.release.wait()
        finally:
            self.stream_closed = True


class _SilentPage:
    def __init__(self):
        self.release = asyncio.Event()

    async def expose_binding(self, _name, _callback):
        return None

    async def evaluate(self, _script, argument=None):
        if isinstance(argument, dict) and "streamId" in argument and "abort" in argument:
            return True
        await self.release.wait()
        return {"ok": True}


class _ReconcilePage:
    async def evaluate(self, _script, argument=None):
        if not isinstance(argument, dict) or "conversationId" not in argument:
            return None
        return {
            "text": "complete answer from the conversation node",
            "messageId": "message-final",
            "metadata": {"citations": [{"title": "Source"}]},
        }


class _DelayedReconcilePage:
    def __init__(self):
        self.calls = 0

    async def evaluate(self, _script, argument=None):
        self.calls += 1
        if self.calls == 1:
            return {
                "text": "partial answer",
                "messageId": "message-partial",
                "metadata": {},
            }
        return {
            "text": "complete answer after the conversation node settled",
            "messageId": "message-final",
            "metadata": {"citations": [{"title": "Source"}]},
        }


class _ShortReconcilePage:
    async def evaluate(self, _script, argument=None):
        return {
            "text": "short answer",
            "messageId": "message-final",
            "metadata": {},
        }


class _CoreStreamRuntime(chatgpt):
    pass


class ChatServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_send_converts_request_and_normalizes_response(self):
        backend = _FakeBackend()
        service = ChatService(backend)

        result = await service.send(ChatRequest(prompt="hello", model="auto"))

        self.assertEqual(backend.sent[0].msg_send, "hello")
        self.assertEqual(result.text, "service response")
        self.assertEqual(result.used_model, "gpt-5-5-mini")
        self.assertEqual(result.usage, {"output_tokens": 3})
        self.assertTrue(result.ok)

    async def test_status_and_history_do_not_expose_backend_details(self):
        service = ChatService(_FakeBackend())

        history = await service.get_history("conversation-history")
        usage = await service.get_usage_status()

        self.assertEqual(history[0]["A"], "conversation-history")
        self.assertEqual(usage["accounts"][0]["email"], "account@example.com")
        self.assertIsNone(usage["accounts"][0]["usage"])

    async def test_context_estimate_is_explicitly_local_and_non_authoritative(self):
        service = ChatService(_FakeBackend())

        estimate = await service.estimate_context(
            "conversation-history",
            model="gpt-5-5-mini",
            account="account@example.com",
        )

        self.assertEqual(estimate.conversation_id, "conversation-history")
        self.assertEqual(estimate.source, "local_history_heuristic")
        self.assertEqual(estimate.message_count, 1)
        self.assertGreater(estimate.estimated_tokens, 0)
        self.assertEqual(estimate.context_window_tokens, 100)
        self.assertIsNotNone(estimate.estimated_utilization)

    async def test_persona_prompt_is_read_through_the_public_service(self):
        service = ChatService(_FakeBackend())

        self.assertEqual(await service.get_persona_prompt("assistant"), "stay concise")
        self.assertEqual(await service.get_persona_prompt("missing"), "")

    async def test_stream_forwards_normalized_request_to_backend(self):
        service = ChatService(_FakeBackend())

        events = [event async for event in service.stream(ChatRequest(prompt="stream me"))]

        self.assertEqual([event.type for event in events], ["status", "delta", "final"])
        self.assertEqual(events[-1].raw["request"], "stream me")

    async def test_service_routes_typed_conversation_operations(self):
        backend = _FakeBackend()
        service = ChatService(backend)

        persona_result = await service.send(ChatRequest(
            prompt="assistant",
            operation=ConversationOperation.START_PERSONA,
        ))
        rewind_result = await service.send(ChatRequest(
            prompt="ignored",
            conversation_id="conversation-service",
            operation=ConversationOperation.REWIND,
            reference="3",
        ))
        reset_result = await service.send(ChatRequest(
            prompt="ignored",
            conversation_id="conversation-service",
            operation=ConversationOperation.RESET_TO_PERSONA,
        ))

        self.assertTrue(persona_result.ok)
        self.assertEqual(backend.sent[0].msg_send, "persona:assistant")
        self.assertEqual(backend.sent[1].msg_send, "rewind:3")
        self.assertEqual(backend.sent[1].msg_type, "back_loop")
        self.assertEqual(reset_result.text, "service response")

    async def test_stream_rejects_non_send_conversation_operations(self):
        service = ChatService(_FakeBackend())

        with self.assertRaises(ValueError):
            await anext(service.stream(ChatRequest(
                prompt="assistant",
                operation=ConversationOperation.START_PERSONA,
            )))

    async def test_stream_to_callback_preserves_event_order_and_returns_result(self):
        service = ChatService(_FakeBackend())
        event_types = []

        async def callback(event):
            event_types.append(event.type)

        result = await service.stream_to_callback(ChatRequest(prompt="callback me"), callback)

        self.assertEqual(event_types, ["status", "delta", "final"])
        self.assertTrue(result.ok)
        self.assertEqual(result.text, "stream response")
        self.assertEqual(result.conversation_id, "conversation-stream")
        self.assertEqual(result.used_model, "gpt-5-5-mini")

    async def test_closing_service_stream_closes_backend_stream(self):
        backend = _ClosableStreamBackend()
        stream = ChatService(backend).stream(ChatRequest(prompt="cancel me"))

        event = await anext(stream)
        await stream.aclose()

        self.assertEqual(event.text, "first")
        self.assertTrue(backend.stream_closed)

    async def test_core_stream_emits_status_then_aborts_after_idle_timeout(self):
        runtime = _CoreStreamRuntime.__new__(_CoreStreamRuntime)
        runtime.logger = _Logger()
        page = _SilentPage()
        session = Session(email="silent@example.com", page=page)
        data = MsgData(
            msg_send="wait",
            stream_idle_timeout_seconds=2,
            stream_status_interval_seconds=1,
        )
        stream = runtime._stream_msg_by_browser_fetch(data, session)

        status = await anext(stream)
        error = await anext(stream)

        self.assertEqual(status.type, "status")
        self.assertEqual(status.metadata["phase"], "waiting_for_upstream")
        self.assertEqual(error.type, "error")
        self.assertIn("no upstream chunks", error.text)
        with self.assertRaises(TimeoutError):
            await anext(stream)

    async def test_stream_final_reconciles_from_the_conversation_node(self):
        runtime = _CoreStreamRuntime.__new__(_CoreStreamRuntime)
        runtime.logger = _Logger()
        session = Session(email="final@example.com", access_token="token", page=_ReconcilePage())
        event = ChatStreamEvent(
            type="final",
            text="partial answer",
            conversation_id="conversation-final",
            message_id="message-partial",
            metadata={"model_slug": "gpt-5-5"},
        )

        reconciled = await runtime._reconcile_stream_final(session, event)

        self.assertEqual(reconciled.text, "complete answer from the conversation node")
        self.assertEqual(reconciled.message_id, "message-final")
        self.assertEqual(reconciled.metadata["model_slug"], "gpt-5-5")
        self.assertEqual(reconciled.metadata["citations"][0]["title"], "Source")

    async def test_nonstream_final_waits_for_the_settled_conversation_node(self):
        runtime = _CoreStreamRuntime.__new__(_CoreStreamRuntime)
        runtime.logger = _Logger()
        page = _DelayedReconcilePage()
        session = Session(email="settled@example.com", access_token="token", page=page)
        data = MsgData(
            msg_recv="partial answer",
            conversation_id="conversation-final",
            next_msg_id="message-partial",
        )

        await runtime._reconcile_nonstream_final(session, data)

        self.assertEqual(data.msg_recv, "complete answer after the conversation node settled")
        self.assertEqual(data.next_msg_id, "message-final")
        self.assertGreaterEqual(page.calls, 2)

    async def test_reconciliation_never_truncates_a_longer_stream_result(self):
        runtime = _CoreStreamRuntime.__new__(_CoreStreamRuntime)
        runtime.logger = _Logger()
        session = Session(email="longer@example.com", access_token="token", page=_ShortReconcilePage())
        event = ChatStreamEvent(
            type="final",
            text="this answer is already longer than the stale conversation node",
            conversation_id="conversation-final",
            message_id="message-final",
        )

        reconciled = await runtime._reconcile_stream_final(session, event)

        self.assertEqual(reconciled.text, event.text)


class HttpApiRequestTests(unittest.TestCase):
    def test_prompt_request_converts_to_chat_request(self):
        request = chat_request_from_payload({
            "prompt": "hello",
            "model": "gpt-5-mini",
            "web_search": True,
        })

        self.assertEqual(request.prompt, "hello")
        self.assertEqual(request.model, "gpt-5-mini")
        self.assertTrue(request.web_search)

    def test_messages_request_keeps_only_latest_user_message_for_existing_conversation(self):
        request = chat_request_from_payload({
            "conversation_id": "conversation-1",
            "messages": [
                {"role": "system", "content": "be brief"},
                {"role": "user", "content": "old question"},
                {"role": "assistant", "content": "old answer"},
                {"role": "user", "content": [{"type": "text", "text": "new question"}]},
            ],
        })

        self.assertEqual(request.prompt, "new question")
        self.assertEqual(request.conversation_id, "conversation-1")

    def test_base64_attachment_becomes_iofile_and_respects_limit(self):
        request = chat_request_from_payload({
            "prompt": "read this",
            "attachments": [{"name": "note.txt", "content_base64": "aGVsbG8="}],
        })

        self.assertEqual(request.files[0].name, "note.txt")
        self.assertEqual(request.files[0].content, b"hello")
        with self.assertRaises(web.HTTPRequestEntityTooLarge):
            chat_request_from_payload({
                "prompt": "too large",
                "attachments": [{"name": "note.txt", "content_base64": "aGVsbG8="}],
            }, max_attachment_bytes=4)

class HttpApiIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.backend = _FakeBackend()
        self.verification_broker = VerificationBroker()
        self.client = TestClient(TestServer(create_http_app(
            ChatService(self.backend),
            api_key="test-key",
            verification_broker=self.verification_broker,
        )))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()

    async def test_completion_and_stream_routes(self):
        headers = {"Authorization": "Bearer test-key"}
        completion = await self.client.post("/v1/chat/completions", json={"prompt": "hello"}, headers=headers)
        completion_body = await completion.json()

        self.assertEqual(completion.status, 200)
        self.assertEqual(completion_body["choices"][0]["message"]["content"], "service response")
        self.assertEqual(completion_body["chatgptweb"]["used_model"], "gpt-5-5-mini")
        self.assertEqual(completion_body["chatgptweb"]["content"]["raw_markdown"], "service response")

        attachment = await self.client.post(
            "/v1/chat/completions",
            json={
                "prompt": "read attachment",
                "attachments": [{"name": "note.txt", "content_base64": "aGVsbG8="}],
            },
            headers=headers,
        )
        self.assertEqual(attachment.status, 200)
        self.assertEqual(self.backend.sent[-1].upload_file[0].content, b"hello")

        stream = await self.client.post(
            "/v1/chat/completions",
            json={"prompt": "hello", "stream": True},
            headers=headers,
        )
        stream_body = await stream.text()

        self.assertEqual(stream.status, 200)
        self.assertIn("stream response", stream_body)
        self.assertIn("event: chatgptweb.status", stream_body)
        self.assertIn("event: chatgptweb.final", stream_body)
        self.assertTrue(stream_body.endswith("data: [DONE]\n\n"))

    async def test_auth_and_health_routes(self):
        unauthorized = await self.client.get("/v1/models")
        health = await self.client.get("/health")

        self.assertEqual(unauthorized.status, 401)
        self.assertEqual(health.status, 200)

    async def test_activity_route_is_authenticated_and_bounded(self):
        headers = {"Authorization": "Bearer test-key"}
        unauthorized = await self.client.get("/v1/activity")
        response = await self.client.get("/v1/activity?limit=1", headers=headers)

        self.assertEqual(unauthorized.status, 401)
        self.assertEqual(response.status, 200)
        self.assertEqual((await response.json())["events"][0]["event"], "test")

    async def test_account_control_requires_auth_and_valid_action(self):
        headers = {"Authorization": "Bearer test-key"}
        unauthorized = await self.client.post(
            "/v1/accounts/account@example.com/control", json={"action": "disable"}
        )
        invalid = await self.client.post(
            "/v1/accounts/account@example.com/control", json={"action": "restart"}, headers=headers
        )
        disabled = await self.client.post(
            "/v1/accounts/account@example.com/control", json={"action": "disable"}, headers=headers
        )

        self.assertEqual(unauthorized.status, 401)
        self.assertEqual(invalid.status, 400)
        self.assertTrue((await disabled.json())["account"]["manual_disabled"])

    async def test_control_console_page_loads_without_exposing_protected_status(self):
        console = TestClient(TestServer(create_control_app(
            ChatService(self.backend),
            self.verification_broker,
            api_key="test-key",
        )))
        await console.start_server()
        try:
            page = await console.get("/")
            protected = await console.get("/v1/account/status")
            body = await page.text()
        finally:
            await console.close()

        self.assertEqual(page.status, 200)
        self.assertIn("ChatGPTWeb Control", body)
        self.assertIn("chatgptweb-control-language", body)
        self.assertIn("本地运维控制台", body)
        self.assertNotIn("test-key", body)
        self.assertEqual(protected.status, 401)

    async def test_verification_routes_submit_and_cancel_pending_challenges(self):
        task = asyncio.create_task(
            self.verification_broker.request_code("account@example.com", "openai", timeout_seconds=1)
        )
        for _ in range(10):
            challenges = await self.verification_broker.snapshot()
            if challenges:
                break
            await asyncio.sleep(0)
        else:
            self.fail("verification challenge was not registered")
        challenge_id = challenges[0]["id"]
        headers = {"Authorization": "Bearer test-key"}

        unauthorized = await self.client.get("/v1/verification")
        listed = await self.client.get("/v1/verification", headers=headers)
        invalid = await self.client.post(f"/v1/verification/{challenge_id}", json={"code": "bad"}, headers=headers)
        submitted = await self.client.post(f"/v1/verification/{challenge_id}", json={"code": "123456"}, headers=headers)

        self.assertEqual(unauthorized.status, 401)
        self.assertEqual(listed.status, 200)
        self.assertEqual((await listed.json())["challenges"][0]["id"], challenge_id)
        self.assertEqual(invalid.status, 400)
        self.assertEqual(submitted.status, 200)
        self.assertEqual(await task, "123456")

        cancel_task = asyncio.create_task(
            self.verification_broker.request_code("cancel@example.com", "openai", timeout_seconds=1)
        )
        for _ in range(10):
            challenges = await self.verification_broker.snapshot()
            if challenges:
                break
            await asyncio.sleep(0)
        cancelled = await self.client.delete(f"/v1/verification/{challenges[0]['id']}", headers=headers)

        self.assertEqual(cancelled.status, 200)
        with self.assertRaises(VerificationCancelledError):
            await cancel_task


if __name__ == "__main__":
    unittest.main()
