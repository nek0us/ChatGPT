import io
from datetime import datetime
import logging
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from ChatGPTWeb.runtime_logging import (
    BoundedLogHandler,
    ColorFormatter,
    color_output_enabled,
    log_level_from_text,
    format_loguru_record,
    is_core_log_record,
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

    def test_explicit_level_is_preserved_without_parsing_message_text(self):
        handler = BoundedLogHandler(capacity=100)

        handler.append("INFO upstream returned ERROR as plain text", level="warning")

        self.assertEqual(handler.snapshot(1), [{
            "text": "INFO upstream returned ERROR as plain text",
            "level": "warning",
        }])

    def test_loguru_records_are_filtered_to_the_core_package_and_formatted_once(self):
        package_root = Path(__file__).resolve().parents[1] / "ChatGPTWeb"
        record = {
            "time": datetime(2026, 8, 9, 1, 2, 3),
            "file": type("File", (), {
                "path": str(package_root / "ChatGPTWeb.py"),
                "name": "ChatGPTWeb.py",
            })(),
            "level": type("Level", (), {"name": "WARNING"})(),
            "message": "bridge recovery started",
        }

        text, level = format_loguru_record(record)

        self.assertTrue(is_core_log_record(record, package_root))
        self.assertEqual(level, "warning")
        self.assertEqual(
            text,
            "2026/08/09 01:02:03 ChatGPTWeb.py WARNING bridge recovery started",
        )
        self.assertEqual(text.count("ChatGPTWeb.py WARNING"), 1)

        record["file"] = type("File", (), {
            "path": str(package_root.parent / "plugins" / "message.py"),
            "name": "message.py",
        })()
        self.assertFalse(is_core_log_record(record, package_root))
