from __future__ import annotations

import unittest

from ChatGPTWeb.api import ChatStreamEvent
from ChatGPTWeb.content import UpstreamMarkupNormalizer, build_chat_content
from ChatGPTWeb.service import ChatRequest, ChatService

OPEN = "\ue200"
CLOSE = "\ue201"
FIELD = "\ue202"
ITEM = "\ue203"


def entity(kind: str, name: str, subtitle: str = "") -> str:
    return f'{OPEN}entity["{kind}","{name}","{subtitle}"]{CLOSE}'


class _Backend:
    def __init__(self, events):
        self.events = events

    async def continue_chat_stream(self, msg_data):
        for event in self.events:
            yield event


class RichContentV86Tests(unittest.TestCase):
    def test_entity_array_keeps_visible_name(self):
        raw = f"东汉太守{entity('person', '陈蕃', '东汉名臣')}敬重徐孺子。"
        self.assertEqual(build_chat_content(raw).markdown, "东汉太守陈蕃敬重徐孺子。")

    def test_entity_object_keeps_visible_name(self):
        raw = f'{OPEN}entity{{"name":"OpenAI","type":"organization"}}{CLOSE}'
        self.assertEqual(build_chat_content(raw).markdown, "OpenAI")

    def test_malformed_entity_keeps_readable_name(self):
        raw = f'{OPEN}entity["organization","OpenAI",]{CLOSE}'
        self.assertEqual(build_chat_content(raw).markdown, "OpenAI")

    def test_split_entity_buffers_only_token(self):
        raw = entity("person", "陶渊明", "诗人")
        normalizer = UpstreamMarkupNormalizer()
        self.assertEqual(normalizer.feed("彭泽指" + raw[:11]), "彭泽指")
        self.assertTrue(normalizer.has_pending_markup)
        self.assertEqual(normalizer.feed(raw[11:] + "，曾任县令"), "陶渊明，曾任县令")
        self.assertFalse(normalizer.has_pending_markup)
        self.assertFalse(normalizer.requires_final_reconciliation)

    def test_url_and_cite_have_generic_client_fallbacks(self):
        url = f"{OPEN}url{FIELD}Example source{FIELD}turn0search0{CLOSE}"
        cite = f"{OPEN}cite{FIELD}turn0search0{ITEM}turn0search1{CLOSE}"
        metadata = {
            "content_references": [{
                "matched_text": cite,
                "items": [{"url": "https://example.com", "title": "Example"}],
            }]
        }
        raw = f"来源：{url}。事实。{cite}"
        self.assertEqual(
            build_chat_content(raw, metadata=metadata).markdown,
            "来源：Example source。事实。[[1]](https://example.com)",
        )

    def test_system_prompt_widgets_are_supplemental_not_blocking(self):
        for kind in ("finance", "forecast", "genui", "i", "navlist", "products", "schedule", "standing"):
            with self.subTest(kind=kind):
                token = f"{OPEN}{kind}{FIELD}opaque-payload{CLOSE}"
                content = build_chat_content("前文" + token + "后文")
                self.assertEqual(content.markdown, "前文后文")
                self.assertEqual(content.rich_items[0].kind, kind)

    def test_rich_text_tags_become_markdown_across_frames(self):
        normalizer = UpstreamMarkupNormalizer()
        self.assertEqual(normalizer.feed("<Text><Bo"), "")
        self.assertEqual(
            normalizer.feed("ld>开发方：</Bold> OpenAI<LineBreak/>下一行</Text>"),
            "**开发方：** OpenAI\n下一行",
        )

    def test_malformed_visible_wrapper_does_not_leak_pua(self):
        normalizer = UpstreamMarkupNormalizer()
        self.assertEqual(normalizer.feed("前" + OPEN + "01] Real"), "前01] Real")
        self.assertEqual(normalizer.feed("time" + FIELD + " API" + CLOSE + "后"), "time API后")
        self.assertFalse(normalizer.requires_final_reconciliation)

    def test_unknown_unreadable_structure_requests_reconciliation(self):
        token = f"{OPEN}future_widget{FIELD}opaque-id{CLOSE}"
        normalizer = UpstreamMarkupNormalizer()
        self.assertEqual(normalizer.feed("前" + token + "后"), "前后")
        self.assertTrue(normalizer.requires_final_reconciliation)


class RichStreamServiceV86Tests(unittest.IsolatedAsyncioTestCase):
    async def collect(self, events):
        result = []
        service = ChatService(_Backend(events))
        async for event in service.stream(ChatRequest(prompt="test")):
            result.append(event)
        return result

    async def test_entity_rich_answer_remains_incremental(self):
        token = entity("person", "陈蕃", "东汉名臣")
        raw = "东汉太守" + token + "非常敬重徐孺子。"
        events = [
            ChatStreamEvent(type="delta", text="东汉太守" + token[:12]),
            ChatStreamEvent(type="delta", text=token[12:] + "非常敬重"),
            ChatStreamEvent(type="delta", text="徐孺子。"),
            ChatStreamEvent(type="final", text=raw),
        ]
        output = await self.collect(events)
        deltas = [event.text for event in output if event.type == "delta"]
        final = next(event for event in output if event.type == "final")
        self.assertEqual(deltas, ["东汉太守", "陈蕃非常敬重", "徐孺子。"])
        self.assertEqual("".join(deltas), "东汉太守陈蕃非常敬重徐孺子。")
        self.assertEqual(final.text, "东汉太守陈蕃非常敬重徐孺子。")
        self.assertNotIn("stream_fallback", final.metadata)

    async def test_known_widget_does_not_stop_following_deltas(self):
        token = f"{OPEN}forecast{FIELD}turn0forecast0{CLOSE}"
        raw = "天气说明" + token + "继续正文"
        output = await self.collect([
            ChatStreamEvent(type="delta", text="天气说明" + token),
            ChatStreamEvent(type="delta", text="继续正文"),
            ChatStreamEvent(type="final", text=raw),
        ])
        self.assertEqual(
            [event.text for event in output if event.type == "delta"],
            ["天气说明", "继续正文"],
        )
        final = next(event for event in output if event.type == "final")
        self.assertNotIn("stream_fallback", final.metadata)

    async def test_unknown_structure_still_uses_canonical_reconciliation(self):
        token = f"{OPEN}future_widget{FIELD}opaque-id{CLOSE}"
        output = await self.collect([
            ChatStreamEvent(type="delta", text="稳定前缀 "),
            ChatStreamEvent(type="delta", text=token),
            ChatStreamEvent(type="delta", text="临时内容"),
            ChatStreamEvent(type="final", text="稳定前缀 最终内容"),
        ])
        self.assertEqual(
            [event.text for event in output if event.type == "delta"],
            ["稳定前缀 ", "最终内容"],
        )
        final = next(event for event in output if event.type == "final")
        self.assertEqual(final.metadata["stream_fallback"], "canonical_final")


if __name__ == "__main__":
    unittest.main()
