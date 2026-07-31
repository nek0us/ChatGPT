import logging
import base64
import unittest
from types import SimpleNamespace

from ChatGPTWeb.api import ChatStreamEvent
from ChatGPTWeb.ChatGPTWeb import chatgpt
from ChatGPTWeb.config import IOFile
from ChatGPTWeb.http_api import (
    _chat_result_payload,
    _response_payload,
    _stream_event_payload,
)
from ChatGPTWeb.output_files import output_file_references
from ChatGPTWeb.service import ChatResult


class OutputFileReferenceTests(unittest.TestCase):
    def test_known_attachment_shapes_are_normalized_and_deduplicated(self):
        references = output_file_references({
            "attachments": [
                {
                    "id": "file-report",
                    "name": "../../report?.csv",
                    "mime_type": "text/csv",
                    "size": 12,
                },
                {
                    "file_id": "file-report",
                    "filename": "duplicate.csv",
                },
            ],
            "content_references": [
                {
                    "type": "sandbox_file",
                    "file": {
                        "file_id": "file-notes",
                        "name": "notes.txt",
                    },
                },
                {
                    "type": "citation",
                    "url": "https://example.com/source",
                    "title": "not-an-output-file",
                },
            ],
        })

        self.assertEqual(
            [(item.file_id, item.name, item.mime_type) for item in references],
            [
                ("file-report", "report_.csv", "text/csv"),
                ("file-notes", "notes.txt", ""),
            ],
        )

    def test_public_download_url_is_kept_without_query_in_the_filename(self):
        references = output_file_references({
            "attachments": [{
                "download_url": "https://files.example/report.pdf?token=secret",
            }],
        })

        self.assertEqual(references[0].name, "report.pdf")
        self.assertEqual(
            references[0].url,
            "https://files.example/report.pdf?token=secret",
        )

    def test_http_payload_transports_output_file_content(self):
        result = ChatResult(
            ok=True,
            text="ready",
            conversation_id="conversation",
            message_id="message",
            files=[
                IOFile(
                    content=b"report",
                    name="report.txt",
                    mime_type="text/plain",
                )
            ],
        )
        payload = _chat_result_payload(result)
        response_payload = _response_payload(
            "response-1",
            model="auto",
            result=result,
        )
        stream_payload = _stream_event_payload(ChatStreamEvent(
            type="final",
            text="ready",
            files=result.files,
        ))

        self.assertEqual(payload["files"][0]["name"], "report.txt")
        self.assertEqual(
            base64.b64decode(payload["files"][0]["content_base64"]),
            b"report",
        )
        self.assertEqual(
            response_payload["chatgptweb"]["files"],
            payload["files"],
        )
        self.assertEqual(stream_payload["files"], payload["files"])


class _FakeResponse:
    def __init__(self, *, status=200, headers=None, body=b"", payload=None):
        self.status = status
        self.headers = headers or {}
        self._body = body
        self._payload = payload

    async def body(self):
        return self._body

    async def json(self):
        return self._payload


class _FakeRequestContext:
    def __init__(self, responses):
        self.responses = responses
        self.urls = []
        self.requests = []

    async def get(self, url, **kwargs):
        self.urls.append(url)
        self.requests.append((url, kwargs))
        for marker, response in self.responses:
            if marker in url:
                return response
        return _FakeResponse(status=404)


class OutputFileDownloadTests(unittest.IsolatedAsyncioTestCase):
    def _runtime(self):
        return SimpleNamespace(
            output_file_max_size=1024,
            output_file_max_total_size=2048,
            output_file_max_count=4,
            logger=logging.getLogger("test-output-files"),
            _safe_output_download_url=chatgpt._safe_output_download_url,
            _output_request_headers=chatgpt._output_request_headers,
            _output_filename_from_headers=chatgpt._output_filename_from_headers,
            _download_output_reference=chatgpt._download_output_reference,
        )

    async def test_file_id_is_resolved_then_downloaded_with_browser_credentials(self):
        request_context = _FakeRequestContext([
            (
                "/backend-api/files/download/",
                _FakeResponse(
                    headers={"content-type": "application/json"},
                    payload={
                        "download_url": "https://files.oaiusercontent.com/report",
                    },
                ),
            ),
            (
                "files.oaiusercontent.com",
                _FakeResponse(
                    headers={
                        "content-type": "text/csv",
                        "content-disposition": 'attachment; filename="scores.csv"',
                        "content-length": "12",
                    },
                    body=b"name,score\n",
                ),
            ),
        ])
        session = SimpleNamespace(
            email="account@example.com",
            access_token="token",
            browser_contexts=SimpleNamespace(request=request_context),
        )
        reference = output_file_references({
            "attachments": [{
                "id": "file-report",
                "name": "report.csv",
                "mime_type": "text/csv",
            }],
        })[0]

        file = await chatgpt._download_output_reference(
            self._runtime(),
            session,
            reference,
            "conversation",
        )

        self.assertEqual(file.name, "scores.csv")
        self.assertEqual(file.content, b"name,score\n")
        self.assertEqual(file.mime_type, "text/csv")
        self.assertEqual(len(request_context.urls), 2)
        self.assertEqual(
            request_context.requests[0][1]["headers"]["authorization"],
            "Bearer token",
        )
        self.assertNotIn(
            "authorization",
            request_context.requests[1][1]["headers"],
        )
        self.assertEqual(request_context.requests[0][1]["max_redirects"], 0)

    async def test_oversized_and_image_outputs_are_not_returned_as_files(self):
        runtime = self._runtime()
        session = SimpleNamespace(
            email="account@example.com",
            access_token="token",
            browser_contexts=SimpleNamespace(
                request=_FakeRequestContext([
                    (
                        "files.oaiusercontent.com",
                        _FakeResponse(
                            headers={
                                "content-type": "application/octet-stream",
                                "content-length": "2048",
                            },
                            body=b"x" * 2048,
                        ),
                    ),
                ])
            ),
        )
        oversized = output_file_references({
            "attachments": [{
                "download_url": "https://files.oaiusercontent.com/large.bin",
                "name": "large.bin",
            }],
        })[0]
        image = output_file_references({
            "attachments": [{
                "download_url": "https://files.oaiusercontent.com/image.png",
                "name": "image.png",
                "mime_type": "image/png",
            }],
        })[0]

        self.assertIsNone(
            await chatgpt._download_output_reference(
                runtime,
                session,
                oversized,
                "conversation",
            )
        )
        self.assertTrue(image.mime_type.startswith("image/"))
