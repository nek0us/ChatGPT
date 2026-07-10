import json
import unittest

from aiohttp.test_utils import TestClient, TestServer

from ChatGPTWeb.api import ChatStreamDecoder, ChatStreamEvent, ChatStreamParser
from ChatGPTWeb.config import MsgData
from ChatGPTWeb.http_api import chat_request_from_payload, create_http_app
from ChatGPTWeb.service import ChatRequest, ChatService


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
                    },
                },
            }
        )

        self.assertEqual([event.type for event in events], ["delta", "final"])
        final = events[-1]
        self.assertEqual(final.text, "Hello from ChatGPT.")
        self.assertEqual(final.conversation_id, "conversation-1")
        self.assertEqual(final.message_id, "message-1")
        self.assertEqual(final.model, "gpt-5-5-mini")
        self.assertEqual(final.usage, {"input_tokens": 12, "output_tokens": 5})
        self.assertEqual(final.metadata["default_model_slug"], "auto")
        self.assertEqual(final.metadata["citations"][0]["title"], "Example")

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

    def test_decoder_does_not_suppress_final_after_empty_early_final(self):
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
        self.assertEqual([event.type for event in events], ["final", "delta", "final"])
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

    async def continue_chat_stream(self, msg_data):
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
        return {"fetch_remote": fetch_remote}


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

    async def test_stream_forwards_normalized_request_to_backend(self):
        service = ChatService(_FakeBackend())

        events = [event async for event in service.stream(ChatRequest(prompt="stream me"))]

        self.assertEqual([event.type for event in events], ["delta", "final"])
        self.assertEqual(events[-1].raw["request"], "stream me")

    async def test_stream_to_callback_preserves_event_order_and_returns_result(self):
        service = ChatService(_FakeBackend())
        event_types = []

        async def callback(event):
            event_types.append(event.type)

        result = await service.stream_to_callback(ChatRequest(prompt="callback me"), callback)

        self.assertEqual(event_types, ["delta", "final"])
        self.assertTrue(result.ok)
        self.assertEqual(result.text, "stream response")
        self.assertEqual(result.conversation_id, "conversation-stream")
        self.assertEqual(result.used_model, "gpt-5-5-mini")


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


class HttpApiIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = TestClient(TestServer(create_http_app(ChatService(_FakeBackend()), api_key="test-key")))
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

        stream = await self.client.post(
            "/v1/chat/completions",
            json={"prompt": "hello", "stream": True},
            headers=headers,
        )
        stream_body = await stream.text()

        self.assertEqual(stream.status, 200)
        self.assertIn("stream response", stream_body)
        self.assertIn("event: chatgptweb.final", stream_body)
        self.assertTrue(stream_body.endswith("data: [DONE]\n\n"))

    async def test_auth_and_health_routes(self):
        unauthorized = await self.client.get("/v1/models")
        health = await self.client.get("/health")

        self.assertEqual(unauthorized.status, 401)
        self.assertEqual(health.status, 200)


if __name__ == "__main__":
    unittest.main()
