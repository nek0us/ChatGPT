import io
import logging
import os
import unittest
from unittest.mock import patch

from ChatGPTWeb.runtime_logging import (
    BoundedLogHandler,
    ColorFormatter,
    color_output_enabled,
    log_level_from_text,
    strip_ansi,
)


class _TTY(io.StringIO):
    def isatty(self):
        return True


class RuntimeLoggingTests(unittest.TestCase):
    def test_bounded_handler_returns_structured_plain_entries(self):
        handler = BoundedLogHandler(capacity=100)
        handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
        logger = logging.Logger("runtime-test")
        logger.addHandler(handler)
        logger.warning("upload unavailable")
        logger.error("image generation failed")

        entries = handler.snapshot(20)

        self.assertEqual(
            [entry["level"] for entry in entries],
            ["warning", "error"],
        )
        self.assertEqual(entries[0]["text"], "WARNING upload unavailable")

    def test_color_formatter_only_adds_ansi_for_supported_terminal(self):
        base = logging.Formatter("%(levelname)s %(message)s")
        record = logging.LogRecord(
            "test",
            logging.ERROR,
            __file__,
            1,
            "failed",
            (),
            None,
        )

        colored = ColorFormatter(base, enabled=True).format(record)
        plain = ColorFormatter(base, enabled=False).format(record)

        self.assertIn("\x1b[", colored)
        self.assertEqual(strip_ansi(colored), plain)
        self.assertEqual(plain, "ERROR failed")

    def test_no_color_disables_terminal_color(self):
        with patch.dict(os.environ, {"NO_COLOR": "1"}, clear=False):
            self.assertFalse(color_output_enabled(_TTY()))

    def test_success_is_presented_as_info_in_web_console(self):
        self.assertEqual(log_level_from_text("SUCCESS account ready"), "info")
