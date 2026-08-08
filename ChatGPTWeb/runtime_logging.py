"""Small logging helpers shared by the terminal and control console."""

from __future__ import annotations

from collections import deque
from datetime import datetime
import logging
import os
from pathlib import Path
import re
import sys
import traceback
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
_LOG_LEVELS = {"debug", "info", "warning", "error", "critical"}


def strip_ansi(value: str) -> str:
    return _ANSI_ESCAPE.sub("", value)


def log_level_from_text(value: str) -> str:
    match = _LEVEL_PATTERN.search(strip_ansi(value))
    if not match:
        return "info"
    level = match.group("level").lower()
    return "warning" if level == "warn" else "info" if level == "success" else level


def normalize_log_level(value: Any) -> str:
    """Normalize standard logging and Loguru level names for the control API."""
    level = str(getattr(value, "name", value) or "info").lower()
    if level == "warn":
        return "warning"
    if level == "success":
        return "info"
    return level if level in _LOG_LEVELS else "info"


def is_core_log_record(record: dict[str, Any], package_root: Path) -> bool:
    """Keep only records emitted from this package when attached to a host logger."""
    file_value = record.get("file")
    source = getattr(file_value, "path", "")
    if not source:
        return False
    try:
        Path(source).resolve().relative_to(package_root.resolve())
    except (OSError, ValueError):
        return False
    return True


def format_loguru_record(record: dict[str, Any]) -> tuple[str, str]:
    """Format a Loguru record once, without re-formatting its rendered message."""
    timestamp = record.get("time")
    if not isinstance(timestamp, datetime):
        timestamp = datetime.now()
    file_value = record.get("file")
    filename = getattr(file_value, "name", "runtime")
    level_value = record.get("level")
    display_level = str(getattr(level_value, "name", level_value) or "INFO").upper()
    message = str(record.get("message") or "")
    exception = record.get("exception")
    if exception is not None:
        exception_text = "".join(traceback.format_exception(
            getattr(exception, "type", None),
            getattr(exception, "value", None),
            getattr(exception, "traceback", None),
        )).strip()
        if exception_text:
            message = f"{message}\n{exception_text}" if message else exception_text
    return (
        f"{timestamp:%Y/%m/%d %H:%M:%S} {filename} {display_level} {message}",
        normalize_log_level(level_value),
    )


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
        self.entries: deque[dict[str, str]] = deque(maxlen=max(100, capacity))

    def append(self, value: str, *, level: str = "info") -> None:
        normalized = normalize_log_level(level)
        plain = strip_ansi(value)
        for line in plain.splitlines() or [plain]:
            self.entries.append({"text": line, "level": normalized})

    def emit(self, record: logging.LogRecord) -> None:
        try:
            value = strip_ansi(self.format(record))
        except Exception:
            self.handleError(record)
            return
        self.append(value, level=record.levelname)

    def snapshot(self, limit: int) -> list[dict[str, str]]:
        return [entry.copy() for entry in list(self.entries)[-max(1, limit):]]


def default_stream() -> Any:
    return sys.stderr
