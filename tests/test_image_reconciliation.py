import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from ChatGPTWeb.ChatGPTWeb import chatgpt
from ChatGPTWeb.api import ChatStreamEvent
from ChatGPTWeb.config import IOFile


class _Logger:
    def debug(self, *_args):
        pass

    def warning(self, *_args):
        pass


class _SequencePage:
    def __init__(self, values):
        self.values = list(values)
        self.calls = 0

    async def evaluate(self, *_args, **_kwargs):
        value = self.values[min(self.calls, len(self.values) - 1)]
        self.calls += 1
        return value


class ImageReconciliationTests(unittest.IsolatedAsyncioTestCase):
    async def test_current_tool_image_pointer_is_recovered_from_active_branch(self):
        page = _SequencePage([{
            "text": "",
            "messageId": "assistant-final",
            "metadata": {},
            "imageUrls": [
                "https://chatgpt.com/backend-api/files/download/"
                "file_00000000abc123?conversation_id=conversation-1&inline=false"
            ],
            "imagePending": False,
        }])
        runtime = object.__new__(chatgpt)
        runtime.logger = _Logger()
        runtime._download_generated_images = AsyncMock(return_value=(
            [IOFile(content=b"png", name="generated.png", mime_type="image/png")],
            {
                "https://chatgpt.com/backend-api/files/download/"
                "file_00000000abc123?conversation_id=conversation-1&inline=false"
            },
        ))
        runtime._download_output_files = AsyncMock(return_value=[])
        session = SimpleNamespace(
            page=page,
            access_token="token",
            email="account@example.com",
        )

        result = await runtime._reconcile_stream_final(
            session,
            ChatStreamEvent(type="final", conversation_id="conversation-1"),
            settle=True,
        )

        self.assertEqual(result.image_urls, [])
        self.assertEqual(result.files[0].content, b"png")
        self.assertEqual(result.metadata["generated_image_count"], 1)

    async def test_settling_does_not_stop_at_text_before_image_asset(self):
        page = _SequencePage([
            {
                "text": "Image ready.",
                "messageId": "assistant-1",
                "metadata": {},
                "imageUrls": [],
                "imagePending": True,
            },
            {
                "text": "Image ready.",
                "messageId": "assistant-1",
                "metadata": {},
                "imageUrls": ["https://files.example/generated.png"],
                "imagePending": False,
            },
        ])
        runtime = object.__new__(chatgpt)
        runtime.logger = _Logger()
        runtime._generated_image_urls_from_bootstrap = AsyncMock(return_value=[])
        runtime._download_generated_images = AsyncMock(return_value=([], set()))
        session = SimpleNamespace(
            page=page,
            access_token="token",
            email="account@example.com",
        )
        event = ChatStreamEvent(
            type="final",
            conversation_id="conversation-1",
            text="",
            files=[
                IOFile(
                    content=b"already handled",
                    name="result.txt",
                    mime_type="text/plain",
                )
            ],
        )

        with patch("ChatGPTWeb.ChatGPTWeb.asyncio.sleep", new=AsyncMock()):
            result = await runtime._reconcile_stream_final(
                session,
                event,
                settle=True,
            )

        self.assertEqual(
            result.image_urls,
            ["https://files.example/generated.png"],
        )
        self.assertEqual(page.calls, 2)

    async def test_bootstrap_retries_until_download_url_is_available(self):
        page = _SequencePage([
            {"urls": []},
            {"urls": []},
            {"urls": ["https://files.example/generated.png"]},
        ])
        runtime = object.__new__(chatgpt)
        runtime.logger = _Logger()
        session = SimpleNamespace(
            page=page,
            access_token="token",
            email="account@example.com",
        )

        with patch("ChatGPTWeb.ChatGPTWeb.asyncio.sleep", new=AsyncMock()):
            result = await runtime._generated_image_urls_from_bootstrap(
                session,
                "conversation-1",
            )

        self.assertEqual(result, ["https://files.example/generated.png"])
        self.assertEqual(page.calls, 3)

    async def test_private_generated_url_is_returned_as_an_image_file(self):
        private_url = (
            "https://chatgpt.com/backend-api/estuary/content"
            "?id=file_123&fn=generated.png"
        )
        page = _SequencePage([{
            "text": "Image ready.",
            "messageId": "assistant-1",
            "metadata": {},
            "imageUrls": [private_url],
            "imagePending": False,
        }])
        runtime = object.__new__(chatgpt)
        runtime.logger = _Logger()
        runtime._download_generated_images = AsyncMock(return_value=(
            [IOFile(content=b"png", name="generated.png", mime_type="image/png")],
            {private_url},
        ))
        runtime._download_output_files = AsyncMock(return_value=[])
        session = SimpleNamespace(
            page=page,
            access_token="token",
            email="account@example.com",
        )

        result = await runtime._reconcile_stream_final(
            session,
            ChatStreamEvent(
                type="final",
                conversation_id="conversation-1",
                text="",
            ),
            settle=True,
        )

        self.assertEqual(result.image_urls, [])
        self.assertEqual(result.files[0].content, b"png")
        self.assertEqual(result.metadata["generated_image_count"], 1)
        runtime._download_generated_images.assert_awaited_once_with(
            session,
            [private_url],
            "conversation-1",
        )

    def test_image_limit_text_is_not_treated_as_a_generated_image(self):
        self.assertTrue(chatgpt._is_image_generation_limit_response(
            "Image creation will be available again when your Instant limit resets."
        ))
        self.assertFalse(chatgpt._is_image_generation_limit_response("Image ready."))
