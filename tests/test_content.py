import unittest

from ChatGPTWeb.content import UpstreamMarkupNormalizer, build_chat_content
from ChatGPTWeb.service import ChatResult


class ChatContentTests(unittest.TestCase):
    def test_content_preserves_markdown_and_extracts_rendering_hints(self):
        markdown = "# Title\r\n\r\nSee [docs](https://example.com/docs).\r\n\r\n```python\nprint('hi')\n```"
        content = build_chat_content(
            markdown,
            image_urls=["https://images.example/result.png"],
            metadata={"citations": [{"title": "Docs"}]},
        )

        self.assertEqual(content.raw_markdown, markdown.replace("\r\n", "\n"))
        self.assertIn("docs (https://example.com/docs)", content.plain_text)
        self.assertEqual(content.links[0].url, "https://example.com/docs")
        self.assertEqual(content.code_blocks[0].language, "python")
        self.assertEqual(content.code_blocks[0].code, "print('hi')")
        self.assertEqual(content.citations[0]["title"], "Docs")
        self.assertEqual(content.image_urls, ["https://images.example/result.png"])

    def test_chat_result_keeps_content_optional_for_backwards_compatible_construction(self):
        result = ChatResult(ok=True, text="plain", conversation_id="c", message_id="m")

        self.assertEqual(result.content.raw_markdown, "")

    def test_search_markup_is_removed_and_source_reference_is_preserved(self):
        markup = "\ue200genui\ue202abc\ue201Sources: \ue200url\ue202Example source\ue202turn0search0\ue201 \ue200cite\ue202turn0search0\ue201"
        content = build_chat_content(markup)

        self.assertEqual(content.markdown, "Sources: Example source ")
        self.assertEqual(content.source_references[0].label, "Example source")
        self.assertEqual(content.source_references[0].source_id, "turn0search0")

    def test_stream_normalizer_handles_protocol_token_split_across_deltas(self):
        normalizer = UpstreamMarkupNormalizer()

        self.assertEqual(normalizer.feed("Sources: \ue200url\ue202Example"), "Sources: ")
        self.assertEqual(normalizer.feed(" source\ue202turn0search0"), "")
        self.assertEqual(normalizer.feed("\ue201 done"), "Example source done")
