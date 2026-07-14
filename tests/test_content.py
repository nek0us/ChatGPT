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

    def test_content_keeps_structured_rich_items_for_callers_to_render(self):
        content = build_chat_content(
            "Forecast follows.",
            metadata={
                "aggregate_result": {"type": "weather", "temperature": 22},
                "tool_results": [{"tool": "search", "count": 3}],
                "attachments": [{"name": "report.pdf"}],
            },
        )

        self.assertEqual(
            [(item.kind, item.payload) for item in content.rich_items],
            [
                ("aggregate_result", {"type": "weather", "temperature": 22}),
                ("tool_results", {"tool": "search", "count": 3}),
                ("attachments", {"name": "report.pdf"}),
            ],
        )

    def test_chat_result_keeps_content_optional_for_backwards_compatible_construction(self):
        result = ChatResult(ok=True, text="plain", conversation_id="c", message_id="m")

        self.assertEqual(result.content.raw_markdown, "")

    def test_live_search_markup_is_removed_and_source_reference_is_preserved(self):
        # Sanitized from a live ChatGPT web-search stream on the browser-fetch route.
        markup = (
            "Paris \ue200cite\ue202turn0search0\ue201  \n"
            "Source: \ue200url\ue202European Union - France overview\ue202turn0search0\ue201"
        )
        content = build_chat_content(markup)

        self.assertEqual(content.markdown, "Paris   \nSource: European Union - France overview")
        self.assertNotIn("\ue200cite", content.markdown)
        self.assertIn("\ue200cite", content.raw_markdown)
        self.assertEqual(content.source_references[0].label, "European Union - France overview")
        self.assertEqual(content.source_references[0].source_id, "turn0search0")

    def test_stream_normalizer_handles_protocol_token_split_across_deltas(self):
        normalizer = UpstreamMarkupNormalizer()

        self.assertEqual(normalizer.feed("Sources: \ue200url\ue202Example"), "Sources: ")
        self.assertEqual(normalizer.feed(" source\ue202turn0search0"), "")
        self.assertEqual(normalizer.feed("\ue201 done"), "Example source done")
