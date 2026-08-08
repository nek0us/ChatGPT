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

# V6_UNKNOWN_UPSTREAM_MARKUP_REGRESSION
class UnknownUpstreamMarkupRegressionTests(unittest.TestCase):
    def test_buffered_renderer_preserves_unstructured_private_wrapper(self):
        body = "ordinary answer text that must remain visible"
        content = build_chat_content(f"before \ue200{body}\ue201 after")
        self.assertEqual(content.markdown, f"before {body} after")

    def test_incremental_normalizer_preserves_the_missing_middle(self):
        normalizer = UpstreamMarkupNormalizer()
        prefix = "[P01] Realtime API streaming enables applications to exchange"
        middle = (
            " data continuously between clients and servers. "
            "[P02] This middle section must not disappear. "
            "[P10] Successful implementations require thoughtful planning around performance"
        )
        suffix = (
            ", security, reliability, and user needs. As digital services evolve, "
            "streaming APIs will remain a core technology for modern interactive platforms.\n\n[END]"
        )

        self.assertEqual(normalizer.feed(prefix + "\ue200"), prefix)
        self.assertEqual(normalizer.feed(middle + "\ue201" + suffix), middle + suffix)

    def test_known_structured_tokens_remain_hidden(self):
        content = build_chat_content(
            "A\ue200cite\ue202turn0search0\ue201B"
            "\ue200genui\ue202payload\ue201C"
        )
        self.assertEqual(content.markdown, "ABC")

    def test_unknown_structured_token_is_not_leaked(self):
        content = build_chat_content("A\ue200future\ue202opaque\ue201B")
        self.assertEqual(content.markdown, "AB")
