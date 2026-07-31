"""Standalone, OpenAI-compatible ChatGPTWeb core service.

This module is deliberately independent from NoneBot.  It is the stable process
entry point for a shared core used by a bot, OpenCode, or other local clients.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from aiohttp import web

from . import ChatService, chatgpt, create_http_app


def _env_enabled(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def load_env_file(path: Path, *, override: bool = False) -> None:
    """Load the small, portable KEY=value subset used by core env files.

    This intentionally does not implement shell expansion.  Secrets and paths
    are treated literally, which makes the same file usable by Windows,
    launchd, and systemd service wrappers.
    """

    if not path.is_file():
        raise FileNotFoundError(f"Missing core environment file: {path}")
    for line_number, raw_line in enumerate(path.read_text("utf8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise ValueError(f"Invalid environment entry at {path}:{line_number}")
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            raise ValueError(f"Invalid empty environment key at {path}:{line_number}")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if override or key not in os.environ:
            os.environ[key] = value


@dataclass(frozen=True)
class CoreServerSettings:
    sessions_file: Path
    storage_dir: Path
    host: str
    port: int
    api_key: str
    control_host: str
    control_port: int
    control_api_key: str
    runtime_log_path: str | None
    headless: bool
    local_js: bool
    log_level: str
    max_attachment_bytes: int
    max_attachment_count: int
    remote_input_enabled: bool
    remote_input_timeout_seconds: float
    remote_input_max_redirects: int
    capability_quota_enabled: bool = True
    free_upload_daily_limit: int = 2
    free_image_generation_daily_limit: int = 2
    capability_rate_limit_cooldown_seconds: int = 24 * 60 * 60

    @classmethod
    def from_environment(cls) -> "CoreServerSettings":
        sessions_file = Path(os.getenv("CHATGPTWEB_SESSIONS_FILE", "example/local_sessions.json"))
        storage_dir = Path(os.getenv("CHATGPTWEB_STORAGE_DIR", "data/chatgptweb"))
        api_key = os.getenv("CHATGPTWEB_HTTP_API_KEY", "")
        if not api_key:
            raise ValueError(
                "Set CHATGPTWEB_HTTP_API_KEY to a local administrator secret before starting the API"
            )
        runtime_log_path = os.getenv("CHATGPTWEB_RUNTIME_LOG_PATH", "").strip()
        if not runtime_log_path:
            runtime_log_path = str(storage_dir / "runtime.log")
        return cls(
            sessions_file=sessions_file,
            storage_dir=storage_dir,
            host=os.getenv("CHATGPTWEB_HTTP_HOST", "127.0.0.1"),
            port=int(os.getenv("CHATGPTWEB_HTTP_PORT", "8000")),
            api_key=api_key,
            control_host=os.getenv("CHATGPTWEB_CONTROL_HOST", "127.0.0.1"),
            control_port=int(os.getenv("CHATGPTWEB_CONTROL_PORT", "8765")),
            control_api_key=os.getenv("CHATGPTWEB_CONTROL_API_KEY", api_key),
            runtime_log_path=runtime_log_path,
            headless=_env_enabled("CHATGPTWEB_HEADLESS", False),
            local_js=_env_enabled("CHATGPTWEB_LOCAL_JS", False),
            log_level=os.getenv("CHATGPTWEB_LOG_LEVEL", "INFO"),
            max_attachment_bytes=int(
                os.getenv("CHATGPTWEB_MAX_ATTACHMENT_BYTES", str(20 * 1024 * 1024))
            ),
            max_attachment_count=int(os.getenv("CHATGPTWEB_MAX_ATTACHMENT_COUNT", "8")),
            remote_input_enabled=_env_enabled("CHATGPTWEB_REMOTE_INPUT_ENABLED", True),
            remote_input_timeout_seconds=float(
                os.getenv("CHATGPTWEB_REMOTE_INPUT_TIMEOUT_SECONDS", "15")
            ),
            remote_input_max_redirects=int(
                os.getenv("CHATGPTWEB_REMOTE_INPUT_MAX_REDIRECTS", "3")
            ),
            capability_quota_enabled=_env_enabled(
                "CHATGPTWEB_CAPABILITY_QUOTA_ENABLED",
                True,
            ),
            free_upload_daily_limit=int(
                os.getenv("CHATGPTWEB_FREE_UPLOAD_DAILY_LIMIT", "2")
            ),
            free_image_generation_daily_limit=int(
                os.getenv(
                    "CHATGPTWEB_FREE_IMAGE_GENERATION_DAILY_LIMIT",
                    "2",
                )
            ),
            capability_rate_limit_cooldown_seconds=int(
                os.getenv(
                    "CHATGPTWEB_CAPABILITY_RATE_LIMIT_COOLDOWN_SECONDS",
                    str(24 * 60 * 60),
                )
            ),
        )


def load_sessions(path: Path) -> list[dict]:
    if not path.is_file():
        raise FileNotFoundError(f"Missing local sessions file: {path}")
    sessions = json.loads(path.read_text("utf8"))
    if not isinstance(sessions, list) or not sessions:
        raise ValueError(f"{path} must contain at least one account")
    if not all(isinstance(session, dict) for session in sessions):
        raise ValueError(f"{path} must contain a JSON list of account objects")
    return sessions


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="chatgptweb-core",
        description="Run ChatGPTWeb as a local OpenAI-compatible shared core.",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        help="Load portable KEY=value settings before starting. Existing process environment wins.",
    )
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="Validate environment and session JSON, then exit without launching Firefox.",
    )
    return parser


def validate_settings(settings: CoreServerSettings) -> None:
    load_sessions(settings.sessions_file)
    if settings.port < 1 or settings.port > 65535:
        raise ValueError("CHATGPTWEB_HTTP_PORT must be between 1 and 65535")
    if settings.control_port < 1 or settings.control_port > 65535:
        raise ValueError("CHATGPTWEB_CONTROL_PORT must be between 1 and 65535")
    if settings.max_attachment_bytes <= 0:
        raise ValueError("CHATGPTWEB_MAX_ATTACHMENT_BYTES must be positive")
    if settings.max_attachment_count <= 0:
        raise ValueError("CHATGPTWEB_MAX_ATTACHMENT_COUNT must be positive")
    if settings.remote_input_timeout_seconds <= 0:
        raise ValueError("CHATGPTWEB_REMOTE_INPUT_TIMEOUT_SECONDS must be positive")
    if (
        settings.remote_input_max_redirects < 0
        or settings.remote_input_max_redirects > 10
    ):
        raise ValueError("CHATGPTWEB_REMOTE_INPUT_MAX_REDIRECTS must be between 0 and 10")
    if not 0 <= settings.free_upload_daily_limit <= 1000:
        raise ValueError("CHATGPTWEB_FREE_UPLOAD_DAILY_LIMIT must be between 0 and 1000")
    if not 0 <= settings.free_image_generation_daily_limit <= 1000:
        raise ValueError(
            "CHATGPTWEB_FREE_IMAGE_GENERATION_DAILY_LIMIT must be between 0 and 1000"
        )
    if not 60 <= settings.capability_rate_limit_cooldown_seconds <= 7 * 24 * 60 * 60:
        raise ValueError(
            "CHATGPTWEB_CAPABILITY_RATE_LIMIT_COOLDOWN_SECONDS must be between 60 and 604800"
        )


def create_core_application(settings: CoreServerSettings) -> web.Application:
    runtime = chatgpt(
        sessions=load_sessions(settings.sessions_file),
        storage_dir=settings.storage_dir,
        begin_sleep_time=False,
        headless=settings.headless,
        logger_level=settings.log_level,
        stdout_flush=True,
        local_js=settings.local_js,
        control_host=settings.control_host,
        control_port=settings.control_port,
        control_api_key=settings.control_api_key,
        control_log_path=settings.runtime_log_path,
        capability_quota_enabled=settings.capability_quota_enabled,
        free_upload_daily_limit=settings.free_upload_daily_limit,
        free_image_generation_daily_limit=(
            settings.free_image_generation_daily_limit
        ),
        capability_rate_limit_cooldown_seconds=(
            settings.capability_rate_limit_cooldown_seconds
        ),
    )
    app = create_http_app(
        ChatService(runtime),
        api_key=settings.api_key,
        api_key_store=runtime.api_key_store,
        runtime_log_path=settings.runtime_log_path,
        max_attachment_bytes=settings.max_attachment_bytes,
        max_attachment_count=settings.max_attachment_count,
        remote_input_enabled=settings.remote_input_enabled,
        remote_input_timeout_seconds=settings.remote_input_timeout_seconds,
        remote_input_max_redirects=settings.remote_input_max_redirects,
    )

    async def start_runtime(_: web.Application) -> None:
        # chatgpt(plugin=False) schedules browser startup on the active loop.
        # aiohttp must use that loop too, or the startup task never gets CPU.
        if runtime._start_task is not None:
            print("Starting ChatGPTWeb browser runtime before accepting API requests...")
            await asyncio.wrap_future(runtime._start_task)
        if not runtime.manage.get("start"):
            raise RuntimeError("ChatGPTWeb browser runtime did not finish starting")
        health = await ChatService(runtime).get_runtime_health()
        if health["readiness"] != "ready":
            print(
                "ChatGPTWeb runtime started in degraded mode: no account is ready yet. "
                "The HTTP API stays online while login recovery continues."
            )

    async def close_runtime(_: web.Application) -> None:
        await runtime.close()

    app.on_startup.append(start_runtime)
    app.on_cleanup.append(close_runtime)
    return app


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_argument_parser()
    arguments = parser.parse_args(argv)
    if arguments.env_file is not None:
        load_env_file(arguments.env_file)

    settings = CoreServerSettings.from_environment()
    validate_settings(settings)
    if arguments.check_config:
        print(f"ChatGPTWeb core configuration is valid: {settings.sessions_file}")
        return

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    app = create_core_application(settings)
    web.run_app(app, host=settings.host, port=settings.port, loop=loop)


if __name__ == "__main__":
    main()
