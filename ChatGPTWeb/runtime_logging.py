"""Small logging helpers shared by the terminal and control console."""

from __future__ import annotations

from collections import deque
import logging
import os
import re
import sys
from typing import Any


_ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_LEVEL_PATTERN = re.compile(
    r"(?:^|[\s|])(?P<level>DEBUG|INFO|WARNING|WARN|ERROR|CRITICAL|SUCCESS)(?:[\s|:]|$)",
    re.IGNORECASE,
)
_LEVEL_COLORS = {
    "DEBUG": "\x1b[38;5;111m",
    "INFO": "\x1b[38;5;78m",
    "SUCCESS": "\x1b[38;5;78m",
    "WARNING": "\x1b[38;5;221m",
    "WARN": "\x1b[38;5;221m",
    "ERROR": "\x1b[38;5;203m",
    "CRITICAL": "\x1b[1;38;5;203m",
}
_RESET = "\x1b[0m"


def strip_ansi(value: str) -> str:
    return _ANSI_ESCAPE.sub("", value)


def log_level_from_text(value: str) -> str:
    match = _LEVEL_PATTERN.search(strip_ansi(value))
    if not match:
        return "info"
    level = match.group("level").lower()
    return "warning" if level == "warn" else "info" if level == "success" else level


def color_output_enabled(stream: Any) -> bool:
    if os.getenv("NO_COLOR") is not None:
        return False
    if os.getenv("FORCE_COLOR", "").strip().lower() not in {"", "0", "false", "no"}:
        return True
    is_tty = getattr(stream, "isatty", None)
    return bool(callable(is_tty) and is_tty())


class ColorFormatter(logging.Formatter):
    """Apply one restrained ANSI color per terminal line when supported."""

    def __init__(self, base: logging.Formatter, *, enabled: bool) -> None:
        super().__init__()
        self._base = base
        self._enabled = enabled

    def format(self, record: logging.LogRecord) -> str:
        value = self._base.format(record)
        if not self._enabled:
            return value
        color = _LEVEL_COLORS.get(record.levelname.upper(), "")
        return f"{color}{value}{_RESET}" if color else value


class BoundedLogHandler(logging.Handler):
    """Keep a safe current-process log tail for embedded runtimes."""

    def __init__(self, *, capacity: int = 2000) -> None:
        super().__init__()
        self.lines: deque[str] = deque(maxlen=max(100, capacity))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            value = strip_ansi(self.format(record))
        except Exception:
            self.handleError(record)
            return
        self.lines.extend(value.splitlines() or [value])

    def snapshot(self, limit: int) -> list[dict[str, str]]:
        selected = list(self.lines)[-max(1, limit):]
        return [
            {"text": line, "level": log_level_from_text(line)}
            for line in selected
        ]


def default_stream() -> Any:
    return sys.stderr
