"""Capability hints and quota names shared by runtime adapters."""

from __future__ import annotations

import re
from typing import Iterable

from .config import IOFile


IMAGE_UPLOAD = "image_upload"
FILE_UPLOAD = "file_upload"
IMAGE_GENERATION = "image_generation"
CAPABILITIES = frozenset({IMAGE_UPLOAD, FILE_UPLOAD, IMAGE_GENERATION})

_IMAGE_GENERATION_PATTERNS = (
    re.compile(
        r"(?:生成|画|绘制|设计|制作|创建|做).{0,16}"
        r"(?:图片|图像|插画|海报|头像|壁纸|封面|logo|图标|视觉图)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:生成|画|绘制|设计|制作|创建|做).{0,24}(?:表情包|自画像|肖像|meme)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:^|[，。！？,;:\s])(?:请|帮我|给我|替我)?"
        r"(?:画|绘制)(?:一下|一个|一张|一幅|些|个|张|幅|只)?",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:^|[，。！？,;:\s])(?:请|帮我|给我|替我)?"
        r"生成(?:一张|一幅|几张|几幅)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:generate|create|draw|illustrate|design|render|make)\b.{0,40}"
        r"\b(?:image|picture|illustration|poster|avatar|wallpaper|cover|logo|icon)\b",
        re.IGNORECASE,
    ),
    # Image edits often refer to the previous turn instead of repeating "image".
    # Keep these forms narrow so ordinary wording changes are not charged as image work.
    re.compile(
        r"(?:改图|修图|编辑(?:这张|这个|上一张|上面的)?(?:图|图片|图像|照片)|"
        r"(?:把|将).{0,24}(?:这张|这个|上一张|上面的)?(?:图|图片|图像|照片|海报|头像|"
        r"上面的字|图片里的字|图中的字).{0,20}(?:改成|改为|替换成|替换为|换成|修改为))",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:edit|modify|retouch|replace)\b.{0,40}"
        r"\b(?:image|picture|photo|poster|avatar|text)\b|"
        r"\b(?:replace|change)\b.{0,40}\btext\b",
        re.IGNORECASE,
    ),
)


def normalize_capabilities(values: Iterable[str]) -> list[str]:
    """Return unique, recognized capability names in stable order."""
    normalized: list[str] = []
    for value in values:
        capability = str(value).strip().lower()
        if capability in CAPABILITIES and capability not in normalized:
            normalized.append(capability)
    return normalized


def infer_request_capabilities(
    prompt: str,
    files: Iterable[IOFile],
    explicit: Iterable[str] = (),
) -> list[str]:
    """Infer only capabilities that are safe to use for account routing."""
    capabilities = normalize_capabilities(explicit)
    for file in files:
        capability = (
            IMAGE_UPLOAD
            if file.content_type == "image_asset_pointer"
            or str(file.mime_type or "").lower().startswith("image/")
            else FILE_UPLOAD
        )
        if capability not in capabilities:
            capabilities.append(capability)
    if (
        IMAGE_GENERATION not in capabilities
        and any(pattern.search(prompt) for pattern in _IMAGE_GENERATION_PATTERNS)
    ):
        capabilities.append(IMAGE_GENERATION)
    return capabilities
