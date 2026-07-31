"""Normalize file references emitted by ChatGPT response metadata."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Dict, Iterable, List
from urllib.parse import unquote, urlsplit


_FILE_REFERENCE_TYPES = {
    "attachment",
    "container_file",
    "file",
    "sandbox_file",
}
_INVALID_FILENAME_CHARS = '<>:"/\\|?*'


@dataclass(frozen=True)
class OutputFileReference:
    name: str
    file_id: str = ""
    url: str = ""
    mime_type: str = ""
    size: int | None = None


def safe_output_filename(value: Any, fallback: str = "attachment") -> str:
    name = PurePosixPath(unquote(str(value or "")).replace("\\", "/")).name
    name = "".join(
        "_" if char in _INVALID_FILENAME_CHARS or ord(char) < 32 else char
        for char in name
    ).strip(" .")
    if name in {"", ".", ".."}:
        name = fallback
    return name[:255]


def _first_string(value: Dict[str, Any], keys: Iterable[str]) -> str:
    for key in keys:
        item = value.get(key)
        if isinstance(item, str) and item.strip():
            return item.strip()
    return ""


def _file_id(value: Dict[str, Any]) -> str:
    result = _first_string(value, ("file_id", "fileId", "id", "asset_pointer"))
    for prefix in ("file-service://", "sandbox://"):
        if result.startswith(prefix):
            return result[len(prefix):]
    return result


def _reference(value: Any, *, require_file_type: bool) -> OutputFileReference | None:
    if not isinstance(value, dict):
        return None
    nested = value.get("file") or value.get("attachment")
    if isinstance(nested, dict):
        merged = dict(value)
        merged.update(nested)
        value = merged
    kind = _first_string(value, ("type", "kind")).lower()
    file_id = _file_id(value)
    url = _first_string(value, ("download_url", "downloadUrl", "file_url", "url"))
    if require_file_type and kind not in _FILE_REFERENCE_TYPES and not file_id:
        return None
    parsed = urlsplit(url)
    downloadable_url = url if parsed.scheme.lower() in {"http", "https"} else ""
    url_name = PurePosixPath(parsed.path).name if parsed.path else ""
    name = safe_output_filename(
        _first_string(value, ("name", "filename", "file_name", "title")) or url_name
    )
    if not file_id and not downloadable_url:
        return None
    size_value = value.get("size", value.get("size_bytes"))
    try:
        size = int(size_value) if size_value is not None else None
    except (TypeError, ValueError):
        size = None
    return OutputFileReference(
        name=name,
        file_id=file_id,
        url=downloadable_url,
        mime_type=_first_string(value, ("mime_type", "mimeType", "content_type")),
        size=size if size is None or size >= 0 else None,
    )


def output_file_references(metadata: Dict[str, Any]) -> List[OutputFileReference]:
    """Extract deduplicated downloadable files from known metadata containers."""
    result: List[OutputFileReference] = []
    seen: set[tuple[str, str]] = set()
    for key, require_file_type in (
        ("attachments", False),
        ("content_references", True),
    ):
        values = metadata.get(key)
        items = values if isinstance(values, list) else [values]
        for value in items:
            reference = _reference(value, require_file_type=require_file_type)
            if reference is None:
                continue
            identity = (reference.file_id, reference.url)
            if identity in seen:
                continue
            seen.add(identity)
            result.append(reference)
    return result
