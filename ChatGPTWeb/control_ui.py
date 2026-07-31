"""Static assets for the optional local operations console."""

from __future__ import annotations

from importlib.resources import files


CONTROL_UI_VERSION = "2026.07.31.2"
_ASSET_PACKAGE = "ChatGPTWeb.control"
_ASSETS = {
    "index.html": "text/html; charset=utf-8",
    "app.css": "text/css; charset=utf-8",
    "app.js": "text/javascript; charset=utf-8",
}


def control_asset(name: str) -> tuple[bytes, str]:
    """Return a packaged control-console asset from a fixed allowlist."""
    content_type = _ASSETS.get(name)
    if content_type is None:
        raise KeyError(name)
    content = files(_ASSET_PACKAGE).joinpath(name).read_bytes()
    if name == "index.html":
        content = content.replace(
            b"__CONTROL_UI_VERSION__",
            CONTROL_UI_VERSION.encode("ascii"),
        )
    return content, content_type
