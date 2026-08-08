import unittest

from ChatGPTWeb.api import ChatStreamParser


class ExactCompactAppendTests(unittest.TestCase):
    def test_pathless_compact_append_does_not_trim_word_boundary_overlap(self):
        parser = ChatStreamParser()
        events = []
        events.extend(parser.feed({
            "p": "/message/content/parts/0",
            "o": "append",
            "v": "Organizations will be",
        }))
        events.extend(parser.feed({"v": " better positioned"}))

        self.assertEqual(
            [event.text for event in events],
            ["Organizations will be", " better positioned"],
        )
        self.assertEqual(
            parser.text,
            "Organizations will be better positioned",
        )

    def test_terminal_explicit_append_after_compact_run_is_exact(self):
        parser = ChatStreamParser()
        parser.feed({
            "p": "/message/content/parts/0",
            "o": "append",
            "v": "[P01] Systems",
        })
        parser.feed({"v": " will be"})
        events = parser.feed({
            "p": "",
            "o": "patch",
            "v": [
                {
                    "p": "/message/content/parts/0",
                    "o": "append",
                    "v": " better positioned.\n\n[END]",
                },
                {
                    "p": "/message/status",
                    "o": "replace",
                    "v": "finished_successfully",
                },
            ],
        })

        self.assertEqual(
            [event.text for event in events],
            [" better positioned.\n\n[END]"],
        )
        self.assertEqual(
            parser.text,
            "[P01] Systems will be better positioned.\n\n[END]",
        )

    def test_legacy_explicit_overlap_replay_still_deduplicates(self):
        parser = ChatStreamParser()
        events = []
        for value in ("Hello", "Hello, world", "world!"):
            events.extend(parser.feed({
                "path": "/message/content/parts/0",
                "op": "append",
                "value": value,
            }))

        self.assertEqual(
            [event.text for event in events],
            ["Hello", ", world", "!"],
        )
        self.assertEqual(parser.text, "Hello, world!")

    def test_unrelated_explicit_patch_clears_exact_compact_state(self):
        parser = ChatStreamParser()
        parser.feed({
            "p": "/message/content/parts/0",
            "o": "append",
            "v": "visible",
        })
        parser.feed({"v": " text"})
        parser.feed({
            "p": "/message/status",
            "o": "replace",
            "v": "in_progress",
        })
        events = parser.feed({"v": " must not leak"})

        self.assertEqual(events, [])
        self.assertEqual(parser.text, "visible text")


if __name__ == "__main__":
    unittest.main()
