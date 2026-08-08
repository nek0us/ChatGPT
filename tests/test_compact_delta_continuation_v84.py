import unittest

from ChatGPTWeb.api import ChatStreamParser


class CompactDeltaContinuationTests(unittest.TestCase):
    def test_pathless_string_values_continue_explicit_text_append(self):
        parser = ChatStreamParser()
        events = []
        events.extend(parser.feed({
            "p": "/message/content/parts/0",
            "o": "append",
            "v": "[P01] Realtime",
        }))
        events.extend(parser.feed({"v": " API streaming"}))
        events.extend(parser.feed({"v": " keeps the middle."}))

        self.assertEqual(
            [event.text for event in events],
            ["[P01] Realtime", " API streaming", " keeps the middle."],
        )
        self.assertEqual(
            parser.text,
            "[P01] Realtime API streaming keeps the middle.",
        )

    def test_pathless_string_without_active_text_target_is_ignored(self):
        parser = ChatStreamParser()
        events = parser.feed({"v": "not a known text continuation"})

        self.assertEqual(events, [])
        self.assertEqual(parser.text, "")

    def test_explicit_unrelated_patch_ends_text_continuation(self):
        parser = ChatStreamParser()
        parser.feed({
            "p": "/message/content/parts/0",
            "o": "append",
            "v": "visible",
        })
        parser.feed({
            "p": "/message/status",
            "o": "replace",
            "v": "in_progress",
        })
        events = parser.feed({"v": "must not leak"})

        self.assertEqual(events, [])
        self.assertEqual(parser.text, "visible")

    def test_root_patch_list_can_start_compact_text_run(self):
        parser = ChatStreamParser()
        events = parser.feed({
            "p": "",
            "o": "patch",
            "v": [{
                "p": "/message/content/parts/0",
                "o": "append",
                "v": "first",
            }],
        })
        events.extend(parser.feed({"v": " second"}))

        self.assertEqual([event.text for event in events], ["first", " second"])
        self.assertEqual(parser.text, "first second")


if __name__ == "__main__":
    unittest.main()
