import unittest

from yarl import URL

from ChatGPTWeb.input_files import InputFileLimitError, InputFileLimits
from ChatGPTWeb.remote_files import (
    PublicNetworkResolver,
    RemoteFile,
    RemoteFileError,
    _read_limited_content,
    _redirect_target,
    _validated_url,
    resolve_remote_input_payload,
)


class _Resolver:
    def __init__(self, host: str):
        self.host = host
        self.closed = False

    async def resolve(self, host: str, port: int = 0, family: int = 0):
        return [{
            "hostname": host,
            "host": self.host,
            "port": port,
            "family": family,
            "proto": 0,
            "flags": 0,
        }]

    async def close(self):
        self.closed = True


class _Content:
    def __init__(self, chunks):
        self.chunks = chunks

    async def iter_chunked(self, _size):
        for chunk in self.chunks:
            yield chunk


class _Response:
    def __init__(self, chunks, content_length=None):
        self.headers = {}
        if content_length is not None:
            self.headers["Content-Length"] = str(content_length)
        self.content = _Content(chunks)


class _Downloader:
    def __init__(self):
        self.calls = []

    async def fetch(self, url, **options):
        self.calls.append((url, options))
        if options.get("require_image"):
            return RemoteFile(b"image", "image/png", "picture.png")
        return RemoteFile(b"hello", "text/plain", "note.txt")


class RemoteFileSecurityTests(unittest.IsolatedAsyncioTestCase):
    def test_url_validation_rejects_local_credentials_and_non_http_schemes(self):
        rejected = (
            "http://127.0.0.1/private",
            "http://[::1]/private",
            "http://user:pass@example.com/file",
            "file:///etc/passwd",
        )
        for value in rejected:
            with self.subTest(value=value), self.assertRaises(RemoteFileError):
                _validated_url(value)

        self.assertEqual(str(_validated_url("https://example.com/file#part")), "https://example.com/file")

    async def test_resolver_rejects_private_dns_answers(self):
        resolver = PublicNetworkResolver(_Resolver("192.168.1.20"))

        with self.assertRaisesRegex(OSError, "non-public"):
            await resolver.resolve("example.com", 443)
        await resolver.close()

        self.assertTrue(resolver._delegate.closed)

    async def test_resolver_accepts_public_dns_answers(self):
        resolver = PublicNetworkResolver(_Resolver("8.8.8.8"))

        result = await resolver.resolve("example.com", 443)
        await resolver.close()

        self.assertEqual(result[0]["host"], "8.8.8.8")

    def test_redirect_revalidates_target_and_blocks_https_downgrade(self):
        current = URL("https://example.com/start")

        self.assertEqual(
            str(_redirect_target(current, "/download")),
            "https://example.com/download",
        )
        with self.assertRaisesRegex(RemoteFileError, "downgrade"):
            _redirect_target(current, "http://example.com/download")
        with self.assertRaisesRegex(RemoteFileError, "non-public"):
            _redirect_target(current, "https://127.0.0.1/private")

    async def test_limited_reader_checks_advertised_and_streamed_sizes(self):
        with self.assertRaises(InputFileLimitError):
            await _read_limited_content(_Response([], content_length=11), max_bytes=10)
        with self.assertRaises(InputFileLimitError):
            await _read_limited_content(_Response([b"123456", b"78901"]), max_bytes=10)

        content = await _read_limited_content(_Response([b"hello"]), max_bytes=10)
        self.assertEqual(content, b"hello")

    async def test_payload_resolution_supports_custom_chat_and_responses_urls(self):
        limits = InputFileLimits(max_files=4, max_file_bytes=100, max_total_bytes=100)
        downloader = _Downloader()

        custom = await resolve_remote_input_payload(
            {"attachments": [{"url": "https://example.com/note.txt"}]},
            mode="custom",
            limits=limits,
            downloader=downloader,
        )
        chat = await resolve_remote_input_payload(
            {"messages": [{"role": "user", "content": [{
                "type": "image_url",
                "image_url": {"url": "https://example.com/picture.png"},
            }]}]},
            mode="chat",
            limits=limits,
            downloader=downloader,
        )
        responses = await resolve_remote_input_payload(
            {"input": [{"role": "user", "content": [{
                "type": "input_file",
                "file_url": "https://example.com/note.txt",
            }]}]},
            mode="responses",
            limits=limits,
            downloader=downloader,
        )

        self.assertNotIn("url", custom["attachments"][0])
        self.assertEqual(custom["attachments"][0]["content_base64"], "aGVsbG8=")
        image_url = chat["messages"][0]["content"][0]["image_url"]["url"]
        self.assertEqual(image_url, "data:image/png;base64,aW1hZ2U=")
        response_file = responses["input"][0]["content"][0]
        self.assertNotIn("file_url", response_file)
        self.assertEqual(response_file["file_data"], "data:text/plain;base64,aGVsbG8=")
        self.assertTrue(downloader.calls[1][1]["require_image"])

    async def test_attachment_count_is_rejected_before_any_download(self):
        downloader = _Downloader()
        attachments = [
            {"url": f"https://example.com/{index}.txt"}
            for index in range(3)
        ]

        with self.assertRaises(InputFileLimitError):
            await resolve_remote_input_payload(
                {"attachments": attachments},
                mode="custom",
                limits=InputFileLimits(
                    max_files=2,
                    max_file_bytes=100,
                    max_total_bytes=100,
                ),
                downloader=downloader,
            )

        self.assertEqual(downloader.calls, [])
