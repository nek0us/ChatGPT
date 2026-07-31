"""Transport-neutral decoding for inline chat input files."""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
import mimetypes
import re
from typing import Any, Iterable, Literal, Mapping, Sequence

from .config import IOFile


_DATA_URL = re.compile(
    r"^data:(?P<mime>[A-Za-z0-9][A-Za-z0-9!#$&^_.+\-/]*);base64,(?P<data>[A-Za-z0-9+/]*={0,2})$"
)
_MIME_TYPE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9!#$&^_.+\-]*/[A-Za-z0-9][A-Za-z0-9!#$&^_.+\-]*$")
_IMAGE_EXTENSIONS = {
    "image/gif": ".gif",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


class InputFileError(ValueError):
    """Raised when a public attachment payload is malformed or unsupported."""


class InputFileLimitError(InputFileError):
    """Raised before an attachment allocation would exceed configured limits."""

    def __init__(self, message: str, *, maximum: int, actual: int):
        super().__init__(message)
        self.maximum = maximum
        self.actual = actual


@dataclass(frozen=True)
class InputFileLimits:
    max_files: int = 8
    max_file_bytes: int = 20 * 1024 * 1024
    max_total_bytes: int = 20 * 1024 * 1024

    def validate(self) -> None:
        if self.max_files <= 0:
            raise ValueError("max_files must be positive")
        if self.max_file_bytes <= 0:
            raise ValueError("max_file_bytes must be positive")
        if self.max_total_bytes <= 0:
            raise ValueError("max_total_bytes must be positive")


@dataclass(frozen=True)
class _EncodedInputFile:
    name: str
    encoded: str
    mime_type: str | None
    label: str


def _safe_name(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise InputFileError(f"{label} requires a file name")
    name = value.replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not name or name in {".", ".."} or "\x00" in name or len(name) > 255:
        raise InputFileError(f"{label} requires a file name up to 255 characters")
    return name


def _safe_mime_type(value: Any, label: str) -> str | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str) or not _MIME_TYPE.fullmatch(value):
        raise InputFileError(f"{label} has an invalid MIME type")
    return value.lower()


def _image_name(index: int, mime_type: str | None) -> str:
    extension = _IMAGE_EXTENSIONS.get(mime_type or "")
    if not extension and mime_type:
        extension = mimetypes.guess_extension(mime_type, strict=False)
    return f"image-{index}{extension or '.bin'}"


def _data_url(value: str, label: str) -> tuple[str, str]:
    match = _DATA_URL.fullmatch(value)
    if not match:
        if value.startswith(("http://", "https://")):
            raise InputFileError(
                f"{label} remote URLs are not supported; provide an inline base64 data URL"
            )
        raise InputFileError(f"{label} requires an inline base64 data URL")
    mime_type = _safe_mime_type(match.group("mime"), label)
    if mime_type is None:
        raise InputFileError(f"{label} data URL requires a MIME type")
    return match.group("data"), mime_type


def _custom_specs(value: Any) -> list[_EncodedInputFile]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise InputFileError("attachments must be an array")
    specs: list[_EncodedInputFile] = []
    for index, item in enumerate(value):
        label = f"attachment {index}"
        if not isinstance(item, Mapping):
            raise InputFileError(f"{label} must be an object")
        encoded = item.get("content_base64")
        if not isinstance(encoded, str):
            raise InputFileError(f"{label} requires base64 content")
        specs.append(_EncodedInputFile(
            name=_safe_name(item.get("name"), label),
            encoded=encoded,
            mime_type=_safe_mime_type(item.get("mime_type"), label),
            label=label,
        ))
    return specs


def _chat_part_specs(part: Mapping[str, Any], image_index: int) -> list[_EncodedInputFile]:
    part_type = part.get("type")
    if part_type == "image_url":
        image = part.get("image_url")
        url = image.get("url") if isinstance(image, Mapping) else image
        if not isinstance(url, str):
            raise InputFileError("image_url content requires a URL")
        encoded, mime_type = _data_url(url, "image_url content")
        return [_EncodedInputFile(
            name=_safe_name(part.get("filename") or _image_name(image_index, mime_type), "image_url content"),
            encoded=encoded,
            mime_type=mime_type,
            label="image_url content",
        )]
    if part_type != "file":
        return []
    file_value = part.get("file")
    if not isinstance(file_value, Mapping):
        raise InputFileError("file content requires a file object")
    if file_value.get("file_id"):
        raise InputFileError("file_id inputs are not supported; provide inline file_data")
    encoded = file_value.get("file_data")
    if not isinstance(encoded, str):
        raise InputFileError("file content requires inline file_data")
    return [_EncodedInputFile(
        name=_safe_name(file_value.get("filename"), "file content"),
        encoded=encoded,
        mime_type=_safe_mime_type(file_value.get("mime_type"), "file content"),
        label="file content",
    )]


def _response_part_specs(part: Mapping[str, Any], image_index: int) -> list[_EncodedInputFile]:
    part_type = part.get("type")
    if part_type == "input_image":
        if part.get("file_id"):
            raise InputFileError("input_image file_id is not supported; provide image_url data")
        url = part.get("image_url")
        if not isinstance(url, str):
            raise InputFileError("input_image requires image_url")
        encoded, mime_type = _data_url(url, "input_image")
        return [_EncodedInputFile(
            name=_safe_name(part.get("filename") or _image_name(image_index, mime_type), "input_image"),
            encoded=encoded,
            mime_type=mime_type,
            label="input_image",
        )]
    if part_type != "input_file":
        return []
    if part.get("file_id"):
        raise InputFileError("input_file file_id is not supported; provide inline file_data")
    if part.get("file_url"):
        raise InputFileError(
            "input_file remote URLs are not supported; provide inline file_data"
        )
    encoded = part.get("file_data")
    if not isinstance(encoded, str):
        raise InputFileError("input_file requires inline file_data")
    return [_EncodedInputFile(
        name=_safe_name(part.get("filename"), "input_file"),
        encoded=encoded,
        mime_type=_safe_mime_type(part.get("mime_type"), "input_file"),
        label="input_file",
    )]


def _content_specs(value: Any, mode: Literal["chat", "responses"]) -> list[_EncodedInputFile]:
    if not isinstance(value, list):
        return []
    specs: list[_EncodedInputFile] = []
    image_index = 1
    for item in value:
        if not isinstance(item, Mapping):
            continue
        parts: Iterable[Any]
        content = item.get("content")
        if isinstance(content, list):
            parts = content
        else:
            parts = (item,)
        for part in parts:
            if not isinstance(part, Mapping):
                continue
            extracted = (
                _chat_part_specs(part, image_index)
                if mode == "chat"
                else _response_part_specs(part, image_index)
            )
            specs.extend(extracted)
            if extracted and (
                part.get("type") == "image_url"
                or part.get("type") == "input_image"
            ):
                image_index += 1
    return specs


def _decode_spec(
    spec: _EncodedInputFile,
    limits: InputFileLimits,
    total_size: int,
) -> IOFile:
    encoded = spec.encoded
    mime_type = spec.mime_type
    if encoded.startswith("data:"):
        encoded, data_mime_type = _data_url(encoded, spec.label)
        if mime_type and mime_type != data_mime_type:
            raise InputFileError(f"{spec.label} MIME type does not match its data URL")
        mime_type = data_mime_type
    estimated_size = (len(encoded) * 3) // 4
    if estimated_size > limits.max_file_bytes + 2:
        raise InputFileLimitError(
            f"{spec.label} exceeds the per-file size limit",
            maximum=limits.max_file_bytes,
            actual=estimated_size,
        )
    if total_size + estimated_size > limits.max_total_bytes + 2:
        raise InputFileLimitError(
            "attachments exceed the total size limit",
            maximum=limits.max_total_bytes,
            actual=total_size + estimated_size,
        )
    try:
        content = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as error:
        raise InputFileError(f"{spec.label} has invalid base64 content") from error
    if len(content) > limits.max_file_bytes:
        raise InputFileLimitError(
            f"{spec.label} exceeds the per-file size limit",
            maximum=limits.max_file_bytes,
            actual=len(content),
        )
    return IOFile(content=content, name=spec.name, mime_type=mime_type)


def input_files_from_payload(
    payload: Mapping[str, Any],
    *,
    mode: Literal["custom", "chat", "responses"] = "custom",
    limits: InputFileLimits | None = None,
) -> list[IOFile]:
    """Decode custom and OpenAI-compatible inline file inputs."""
    selected_limits = limits or InputFileLimits()
    selected_limits.validate()
    specs = _custom_specs(payload.get("attachments"))
    if mode == "chat":
        specs.extend(_content_specs(payload.get("messages"), "chat"))
    elif mode == "responses":
        specs.extend(_content_specs(payload.get("input"), "responses"))

    if len(specs) > selected_limits.max_files:
        raise InputFileLimitError(
            "attachment count exceeds the configured limit",
            maximum=selected_limits.max_files,
            actual=len(specs),
        )

    files: list[IOFile] = []
    total_size = 0
    for spec in specs:
        file = _decode_spec(spec, selected_limits, total_size)
        total_size += len(file.content)
        if total_size > selected_limits.max_total_bytes:
            raise InputFileLimitError(
                "attachments exceed the total size limit",
                maximum=selected_limits.max_total_bytes,
                actual=total_size,
            )
        files.append(file)
    return files


def input_files_from_attachments(
    attachments: Sequence[Mapping[str, Any]] | None,
    *,
    limits: InputFileLimits | None = None,
) -> list[IOFile]:
    """Decode the transport-neutral attachment shape used by MCP and bot APIs."""
    return input_files_from_payload(
        {"attachments": list(attachments) if attachments is not None else None},
        limits=limits,
    )
