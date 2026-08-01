import unittest
from types import SimpleNamespace

from ChatGPTWeb.api import _blob_upload_headers, _exact_url_pattern
from ChatGPTWeb.config import IOFile


class UploadRouteTests(unittest.TestCase):
    def test_signed_upload_route_matches_the_full_url(self):
        url = (
            "https://sdmntprjapaneast.oaiusercontent.com/files/abc/raw?"
            "sp=w&sig=a%2Bb"
        )
        pattern = _exact_url_pattern(url)

        self.assertIsNotNone(pattern.fullmatch(url))
        self.assertIsNone(pattern.fullmatch(url.replace("sig=a%2Bb", "sig=other")))

    def test_blob_headers_do_not_override_signed_url_host_or_credentials(self):
        request = SimpleNamespace(
            headers={
                "host": "sdmntprjapaneast.oaiusercontent.com",
                "cookie": "session=private",
                "content-length": "0",
                "origin": "https://chatgpt.com",
                "user-agent": "test-browser",
            }
        )
        file = IOFile(content=b"image", name="image.png", mime_type="image/png")

        headers = _blob_upload_headers(request, file)

        self.assertNotIn("host", {key.lower() for key in headers})
        self.assertNotIn("cookie", {key.lower() for key in headers})
        self.assertNotIn("content-length", {key.lower() for key in headers})
        self.assertEqual(headers["Content-Type"], "image/png")
        self.assertEqual(headers["x-ms-blob-type"], "BlockBlob")
        self.assertEqual(headers["x-ms-version"], "2020-04-08")


if __name__ == "__main__":
    unittest.main()
