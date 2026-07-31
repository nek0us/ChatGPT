import base64
import unittest

from ChatGPTWeb.input_files import (
    InputFileError,
    InputFileLimitError,
    InputFileLimits,
    input_files_from_payload,
)


def _data_url(content: bytes, mime_type: str) -> str:
    encoded = base64.b64encode(content).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


class InputFileTests(unittest.TestCase):
    def test_custom_attachments_preserve_content_and_safe_name(self):
        files = input_files_from_payload({
            "attachments": [{
                "name": "../notes/readme.txt",
                "mime_type": "text/plain",
                "content_base64": base64.b64encode(b"hello").decode("ascii"),
            }],
        })

        self.assertEqual(files[0].name, "readme.txt")
        self.assertEqual(files[0].content, b"hello")
        self.assertEqual(files[0].mime_type, "text/plain")

    def test_chat_content_accepts_inline_image_and_file(self):
        files = input_files_from_payload({
            "messages": [{
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": _data_url(b"image", "image/png")},
                    },
                    {
                        "type": "file",
                        "file": {
                            "filename": "notes.txt",
                            "file_data": _data_url(b"notes", "text/plain"),
                        },
                    },
                ],
            }],
        }, mode="chat")

        self.assertEqual([file.name for file in files], ["image-1.png", "notes.txt"])
        self.assertEqual([file.content for file in files], [b"image", b"notes"])

    def test_responses_content_accepts_input_image_and_input_file(self):
        files = input_files_from_payload({
            "input": [{
                "role": "user",
                "content": [
                    {
                        "type": "input_image",
                        "image_url": _data_url(b"image", "image/jpeg"),
                    },
                    {
                        "type": "input_file",
                        "filename": "report.pdf",
                        "file_data": _data_url(b"pdf", "application/pdf"),
                    },
                ],
            }],
        }, mode="responses")

        self.assertEqual([file.name for file in files], ["image-1.jpg", "report.pdf"])
        self.assertEqual(files[1].mime_type, "application/pdf")

    def test_remote_urls_and_file_ids_are_rejected(self):
        with self.assertRaisesRegex(InputFileError, "remote URLs are not supported"):
            input_files_from_payload({
                "input": [{
                    "role": "user",
                    "content": [{
                        "type": "input_image",
                        "image_url": "https://example.com/private.png",
                    }],
                }],
            }, mode="responses")

        with self.assertRaisesRegex(InputFileError, "file_id inputs are not supported"):
            input_files_from_payload({
                "messages": [{
                    "role": "user",
                    "content": [{"type": "file", "file": {"file_id": "file-private"}}],
                }],
            }, mode="chat")

    def test_count_per_file_and_total_limits_are_enforced(self):
        encoded = base64.b64encode(b"1234").decode("ascii")
        attachments = [
            {"name": f"{index}.txt", "content_base64": encoded}
            for index in range(2)
        ]
        with self.assertRaises(InputFileLimitError):
            input_files_from_payload(
                {"attachments": attachments},
                limits=InputFileLimits(max_files=1, max_file_bytes=10, max_total_bytes=10),
            )
        with self.assertRaises(InputFileLimitError):
            input_files_from_payload(
                {"attachments": attachments[:1]},
                limits=InputFileLimits(max_files=2, max_file_bytes=3, max_total_bytes=10),
            )
        with self.assertRaises(InputFileLimitError):
            input_files_from_payload(
                {"attachments": attachments},
                limits=InputFileLimits(max_files=2, max_file_bytes=4, max_total_bytes=7),
            )

    def test_mime_type_must_match_data_url(self):
        with self.assertRaisesRegex(InputFileError, "does not match"):
            input_files_from_payload({
                "attachments": [{
                    "name": "image.png",
                    "mime_type": "image/png",
                    "content_base64": _data_url(b"image", "image/jpeg"),
                }],
            })


if __name__ == "__main__":
    unittest.main()
