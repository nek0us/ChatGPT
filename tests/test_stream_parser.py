import json
import unittest

from ChatGPTWeb.api import ChatStreamDecoder, ChatStreamParser


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


if __name__ == "__main__":
    unittest.main()
