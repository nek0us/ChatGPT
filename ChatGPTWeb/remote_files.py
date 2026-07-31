"""Safe remote file retrieval for public API attachment inputs."""

from __future__ import annotations

import base64
import copy
from dataclasses import dataclass
import ipaddress
from pathlib import PurePosixPath
from typing import Any, Mapping, MutableMapping, Sequence
from urllib.parse import unquote

import aiohttp
from aiohttp.abc import AbstractResolver
from aiohttp.resolver import DefaultResolver
from yarl import URL

from .config import IOFile
from .input_files import InputFileError, InputFileLimitError, InputFileLimits


class RemoteFileError(InputFileError):
    """Raised when a remote attachment cannot be fetched safely."""


@dataclass(frozen=True)
class RemoteFilePolicy:
    enabled: bool = True
    timeout_seconds: float = 15.0
    max_redirects: int = 3

    def validate(self) -> None:
        if self.timeout_seconds <= 0:
            raise ValueError("remote file timeout must be positive")
        if self.max_redirects < 0 or self.max_redirects > 10:
            raise ValueError("remote file max redirects must be between 0 and 10")


@dataclass(frozen=True)
class RemoteFile:
    content: bytes
    mime_type: str | None
    name: str


def _is_public_address(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    return address.is_global


def _validated_url(value: str) -> URL:
    if not isinstance(value, str) or not value or len(value) > 4096:
        raise RemoteFileError("remote attachment URL must be a non-empty URL up to 4096 characters")
    try:
        url = URL(value)
    except ValueError as error:
        raise RemoteFileError("remote attachment URL is invalid") from error
    if url.scheme not in {"http", "https"}:
        raise RemoteFileError("remote attachment URL must use http or https")
    if not url.host:
        raise RemoteFileError("remote attachment URL requires a host")
    if url.user is not None or url.password is not None:
        raise RemoteFileError("remote attachment URL must not contain credentials")
    try:
        address = ipaddress.ip_address(url.host)
    except ValueError:
        address = None
    if address is not None and not _is_public_address(str(address)):
        raise RemoteFileError("remote attachment URL resolves to a non-public address")
    return url.with_fragment(None)


class PublicNetworkResolver(AbstractResolver):
    """Validate the addresses actually returned to aiohttp's connector."""

    def __init__(self, delegate: AbstractResolver | None = None):
        self._delegate = delegate or DefaultResolver()

    async def resolve(self, host: str, port: int = 0, family: int = 0):
        results = await self._delegate.resolve(host, port, family)
        if not results:
            raise OSError("remote attachment host did not resolve")
        if any(not _is_public_address(str(item.get("host", ""))) for item in results):
            raise OSError("remote attachment host resolved to a non-public address")
        return results

    async def close(self) -> None:
        await self._delegate.close()


def _response_mime_type(response: aiohttp.ClientResponse) -> str | None:
    value = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
    return value or None


def _name_from_url(url: URL, fallback: str) -> str:
    candidate = unquote(PurePosixPath(url.path).name).strip()
    if not candidate or candidate in {".", ".."} or len(candidate) > 255:
        return fallback
    return candidate.replace("\\", "_").replace("/", "_")


def _redirect_target(current: URL, location: str) -> URL:
    if not location:
        raise RemoteFileError("remote attachment redirect has no location")
    try:
        redirected = current.join(URL(location))
    except ValueError as error:
        raise RemoteFileError("remote attachment redirect URL is invalid") from error
    if current.scheme == "https" and redirected.scheme == "http":
        raise RemoteFileError("remote attachment redirect cannot downgrade HTTPS")
    return _validated_url(str(redirected))


async def _read_limited_content(
    response: aiohttp.ClientResponse,
    *,
    max_bytes: int,
) -> bytes:
    content_length = response.headers.get("Content-Length")
    if content_length:
        try:
            advertised_size = int(content_length)
        except ValueError:
            advertised_size = 0
        if advertised_size > max_bytes:
            raise InputFileLimitError(
                "remote attachment exceeds the size limit",
                maximum=max_bytes,
                actual=advertised_size,
            )
    content = bytearray()
    async for chunk in response.content.iter_chunked(64 * 1024):
        content.extend(chunk)
        if len(content) > max_bytes:
            raise InputFileLimitError(
                "remote attachment exceeds the size limit",
                maximum=max_bytes,
                actual=len(content),
            )
    return bytes(content)


class RemoteFileDownloader:
    """Fetch public URLs without allowing the host to become an SSRF proxy."""

    def __init__(self, policy: RemoteFilePolicy | None = None):
        self.policy = policy or RemoteFilePolicy()
        self.policy.validate()

    async def fetch(
        self,
        value: str,
        *,
        max_bytes: int,
        fallback_name: str,
        require_image: bool = False,
    ) -> RemoteFile:
        if not self.policy.enabled:
            raise RemoteFileError("remote attachment URLs are disabled")
        if max_bytes <= 0:
            raise InputFileLimitError(
                "attachments exceed the total size limit",
                maximum=0,
                actual=1,
            )

        current = _validated_url(value)
        timeout = aiohttp.ClientTimeout(total=self.policy.timeout_seconds)
        resolver = PublicNetworkResolver()
        connector = aiohttp.TCPConnector(
            resolver=resolver,
            use_dns_cache=False,
            ttl_dns_cache=0,
        )
        try:
            async with aiohttp.ClientSession(
                connector=connector,
                timeout=timeout,
                trust_env=False,
                headers={"User-Agent": "ChatGPTWeb/remote-input"},
            ) as session:
                for redirect_count in range(self.policy.max_redirects + 1):
                    async with session.get(current, allow_redirects=False) as response:
                        if 300 <= response.status < 400:
                            location = response.headers.get("Location")
                            if redirect_count >= self.policy.max_redirects:
                                raise RemoteFileError("remote attachment exceeded the redirect limit")
                            current = _redirect_target(current, location or "")
                            continue
                        if response.status != 200:
                            raise RemoteFileError(
                                f"remote attachment returned HTTP {response.status}"
                            )
                        content = await _read_limited_content(response, max_bytes=max_bytes)
                        file = IOFile(
                            content=content,
                            name=_name_from_url(current, fallback_name),
                            mime_type=_response_mime_type(response),
                        )
                        if require_image and not (file.mime_type or "").startswith("image/"):
                            raise RemoteFileError("remote image URL did not return a supported image")
                        return RemoteFile(
                            content=file.content,
                            mime_type=file.mime_type,
                            name=file.name,
                        )
        except InputFileError:
            raise
        except (aiohttp.ClientError, TimeoutError, OSError) as error:
            raise RemoteFileError("remote attachment could not be fetched safely") from error
        finally:
            if not connector.closed:
                await connector.close()
        raise RemoteFileError("remote attachment could not be fetched")


def _is_remote_url(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(("http://", "https://"))


def _attachment_slot_count(payload: Mapping[str, Any], mode: str) -> int:
    attachments = payload.get("attachments")
    count = len(attachments) if isinstance(attachments, list) else 0
    entries = payload.get("messages") if mode == "chat" else payload.get("input")
    if mode not in {"chat", "responses"} or not isinstance(entries, list):
        return count
    supported_types = (
        {"image_url", "file"}
        if mode == "chat"
        else {"input_image", "input_file"}
    )
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        content = entry.get("content")
        parts: Sequence[Any] = content if isinstance(content, list) else (entry,)
        count += sum(
            1
            for part in parts
            if isinstance(part, Mapping) and part.get("type") in supported_types
        )
    return count


def _encoded_data_url(file: RemoteFile) -> str:
    mime_type = file.mime_type or "application/octet-stream"
    encoded = base64.b64encode(file.content).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


async def _resolve_custom_attachments(
    attachments: Any,
    downloader: RemoteFileDownloader,
    limits: InputFileLimits,
    downloaded_size: int,
) -> int:
    if not isinstance(attachments, list):
        return downloaded_size
    for index, item in enumerate(attachments):
        if not isinstance(item, MutableMapping):
            continue
        url = item.get("url")
        if not _is_remote_url(url):
            continue
        if item.get("content_base64") is not None:
            raise RemoteFileError(f"attachment {index} must not contain both url and base64 content")
        file = await downloader.fetch(
            url,
            max_bytes=min(
                limits.max_file_bytes,
                limits.max_total_bytes - downloaded_size,
            ),
            fallback_name=f"attachment-{index + 1}.bin",
        )
        downloaded_size += len(file.content)
        item["name"] = item.get("name") or file.name
        item["mime_type"] = item.get("mime_type") or file.mime_type
        item["content_base64"] = base64.b64encode(file.content).decode("ascii")
        item.pop("url", None)
    return downloaded_size


async def _resolve_content_parts(
    entries: Any,
    mode: str,
    downloader: RemoteFileDownloader,
    limits: InputFileLimits,
    downloaded_size: int,
) -> int:
    if not isinstance(entries, list):
        return downloaded_size
    image_index = 1
    for entry in entries:
        if not isinstance(entry, MutableMapping):
            continue
        content = entry.get("content")
        parts: Sequence[Any] = content if isinstance(content, list) else (entry,)
        for part in parts:
            if not isinstance(part, MutableMapping):
                continue
            part_type = part.get("type")
            if mode == "chat" and part_type == "image_url":
                image_value = part.get("image_url")
                url = image_value.get("url") if isinstance(image_value, MutableMapping) else image_value
                if not _is_remote_url(url):
                    continue
                file = await downloader.fetch(
                    url,
                    max_bytes=min(
                        limits.max_file_bytes,
                        limits.max_total_bytes - downloaded_size,
                    ),
                    fallback_name=f"image-{image_index}.bin",
                    require_image=True,
                )
                downloaded_size += len(file.content)
                if isinstance(image_value, MutableMapping):
                    image_value["url"] = _encoded_data_url(file)
                else:
                    part["image_url"] = _encoded_data_url(file)
                part["filename"] = part.get("filename") or file.name
                image_index += 1
            elif mode == "responses" and part_type == "input_image":
                url = part.get("image_url")
                if not _is_remote_url(url):
                    continue
                file = await downloader.fetch(
                    url,
                    max_bytes=min(
                        limits.max_file_bytes,
                        limits.max_total_bytes - downloaded_size,
                    ),
                    fallback_name=f"image-{image_index}.bin",
                    require_image=True,
                )
                downloaded_size += len(file.content)
                part["image_url"] = _encoded_data_url(file)
                part["filename"] = part.get("filename") or file.name
                image_index += 1
            elif mode == "responses" and part_type == "input_file":
                url = part.get("file_url")
                if not _is_remote_url(url):
                    continue
                file = await downloader.fetch(
                    url,
                    max_bytes=min(
                        limits.max_file_bytes,
                        limits.max_total_bytes - downloaded_size,
                    ),
                    fallback_name="attachment.bin",
                )
                downloaded_size += len(file.content)
                part["file_data"] = _encoded_data_url(file)
                part["filename"] = part.get("filename") or file.name
                part.pop("file_url", None)
    return downloaded_size


async def resolve_remote_input_payload(
    payload: Mapping[str, Any],
    *,
    mode: str,
    limits: InputFileLimits,
    downloader: RemoteFileDownloader,
) -> dict[str, Any]:
    """Return a copy with safe remote references replaced by inline data."""
    attachment_count = _attachment_slot_count(payload, mode)
    if attachment_count > limits.max_files:
        raise InputFileLimitError(
            "attachment count exceeds the configured limit",
            maximum=limits.max_files,
            actual=attachment_count,
        )
    resolved = copy.deepcopy(dict(payload))
    downloaded_size = await _resolve_custom_attachments(
        resolved.get("attachments"),
        downloader,
        limits,
        0,
    )
    if mode == "chat":
        await _resolve_content_parts(
            resolved.get("messages"),
            mode,
            downloader,
            limits,
            downloaded_size,
        )
    elif mode == "responses":
        await _resolve_content_parts(
            resolved.get("input"),
            mode,
            downloader,
            limits,
            downloaded_size,
        )
    return resolved
