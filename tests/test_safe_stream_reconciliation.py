from __future__ import annotations

import unittest

from ChatGPTWeb.api import ChatStreamEvent, ChatStreamParser
from ChatGPTWeb.service import ChatRequest, ChatService


class _Backend:
    def __init__(self, events):
        self.events = events

    async def continue_chat_stream(self, msg_data):
        for event in self.events:
            yield event


class SafeStreamReconciliationTests(unittest.IsolatedAsyncioTestCase):
    async def _collect(self, events):
        service = ChatService(_Backend(events))
        output = []
        async for event in service.stream(ChatRequest(prompt="test")):
            output.append(event)
        return output

    async def test_known_cite_markup_streams_without_canonical_fallback(self):
        cite = "\ue200cite\ue202turn0search0\ue201"
        metadata = {
            "content_references": [{
                "matched_text": cite,
                "items": [{"url": "https://example.com", "title": "Example"}],
            }]
        }
        raw = "Beginning " + cite + " ending"
        events = [
            ChatStreamEvent(type="delta", text="Beginning "),
            ChatStreamEvent(type="delta", text=cite, metadata=metadata),
            ChatStreamEvent(type="delta", text=" ending", metadata=metadata),
            ChatStreamEvent(type="final", text=raw, metadata=metadata),
        ]

        output = await self._collect(events)
        deltas = [event.text for event in output if event.type == "delta"]
        final = next(event for event in output if event.type == "final")

        expected = "Beginning [[1]](https://example.com) ending"
        self.assertEqual("".join(deltas), expected)
        self.assertEqual(final.text, expected)
        self.assertNotIn("stream_fallback", final.metadata)

    async def test_clean_append_only_answer_remains_incremental(self):
        events = [
            ChatStreamEvent(type="delta", text="first "),
            ChatStreamEvent(type="delta", text="second"),
            ChatStreamEvent(type="final", text="first second"),
        ]
        output = await self._collect(events)
        self.assertEqual(
            [event.text for event in output if event.type == "delta"],
            ["first ", "second"],
        )
        final = next(event for event in output if event.type == "final")
        self.assertNotIn("stream_fallback", final.metadata)

    async def test_replacement_event_prevents_irreversible_mixed_answer(self):
        complete = "authoritative replacement answer"
        events = [
            ChatStreamEvent(type="reconcile", text=complete, metadata={"stream_replacement": True}),
            ChatStreamEvent(type="final", text=complete),
        ]
        output = await self._collect(events)
        self.assertEqual(
            [event.text for event in output if event.type == "delta"],
            [complete],
        )


class ParserReplacementTests(unittest.TestCase):
    def test_explicit_replace_emits_reconcile_instead_of_append(self):
        parser = ChatStreamParser()
        parser.feed({
            "path": "/message/content/parts/0",
            "op": "append",
            "value": "old answer",
        })
        events = parser.feed({
            "path": "/message/content/parts/0",
            "op": "replace",
            "value": "new authoritative answer",
        })

        self.assertEqual([event.type for event in events], ["reconcile"])
        self.assertTrue(events[0].metadata["stream_replacement"])
        self.assertEqual(parser.final_event().text, "new authoritative answer")

    def test_disjoint_full_snapshot_emits_reconcile(self):
        parser = ChatStreamParser()
        parser.feed({
            "message": {
                "author": {"role": "assistant"},
                "content": {"parts": ["temporary node"]},
            }
        })
        events = parser.feed({
            "message": {
                "author": {"role": "assistant"},
                "content": {"parts": ["settled authoritative node"]},
            }
        })

        self.assertEqual([event.type for event in events], ["reconcile"])
        self.assertEqual(parser.final_event().text, "settled authoritative node")
