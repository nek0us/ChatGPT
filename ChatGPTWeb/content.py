"""Platform-neutral rich content hints derived from ChatGPT responses."""

import re

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List


_CODE_BLOCK = re.compile(r"^```(?P<language>[^\n`]*)\n(?P<code>.*?)^```[ \t]*$", re.MULTILINE | re.DOTALL)
_MARKDOWN_LINK = re.compile(r"(?<!!)\[(?P<label>[^\]]+)\]\((?P<url>[^\s)]+)(?:\s+['\"][^)]*['\"])?\)")
_IMAGE_LINK = re.compile(r"!\[(?P<label>[^\]]*)\]\((?P<url>[^\s)]+)(?:\s+['\"][^)]*['\"])?\)")
_UPSTREAM_MARKUP = re.compile("\\ue200(?P<body>.*?)\\ue201", re.DOTALL)


@dataclass
class ContentLink:
    label: str
    url: str


@dataclass
class CodeBlock:
    language: str
    code: str


@dataclass
class SourceReference:
    label: str
    source_id: str


@dataclass
class ChatContent:
    """Lossless Markdown plus optional hints for platform-specific renderers."""

    raw_markdown: str = ""
    markdown: str = ""
    plain_text: str = ""
    links: List[ContentLink] = field(default_factory=list)
    code_blocks: List[CodeBlock] = field(default_factory=list)
    citations: List[Any] = field(default_factory=list)
    image_urls: List[str] = field(default_factory=list)
    source_references: List[SourceReference] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _unique_strings(values: List[Any]) -> List[str]:
    result = []
    for value in values:
        if isinstance(value, str) and value and value not in result:
            result.append(value)
    return result


def _citation_values(metadata: Dict[str, Any]) -> List[Any]:
    citations = []
    for key in ("citations", "content_references"):
        value = metadata.get(key)
        if isinstance(value, list):
            citations.extend(value)
        elif isinstance(value, dict):
            citations.append(value)
    return citations


def _plain_text(markdown: str) -> str:
    text = _IMAGE_LINK.sub(lambda match: f"{match.group('label')} ({match.group('url')})".strip(), markdown)
    text = _MARKDOWN_LINK.sub(lambda match: f"{match.group('label')} ({match.group('url')})", text)
    text = _CODE_BLOCK.sub(lambda match: match.group("code").strip("\n"), text)
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s+", "", text)
    text = re.sub(r"(?m)^\s*[-*+]\s+", "- ", text)
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _upstream_markup_value(body: str) -> str:
    parts = body.split("\ue202")
    kind = parts[0] if parts else ""
    if kind == "url" and len(parts) >= 2:
        return parts[1]
    if kind in ("genui", "cite"):
        return ""
    return ""


def _source_references(markdown: str) -> List[SourceReference]:
    references = []
    for match in _UPSTREAM_MARKUP.finditer(markdown):
        parts = match.group("body").split("\ue202")
        if len(parts) < 3 or parts[0] != "url":
            continue
        reference = SourceReference(label=parts[1], source_id=parts[2])
        if reference not in references:
            references.append(reference)
    return references


class UpstreamMarkupNormalizer:
    """Incrementally remove ChatGPT private rich-UI tokens from stream deltas."""

    def __init__(self):
        self._buffer = ""

    def feed(self, text: str) -> str:
        self._buffer += text
        output = []
        while self._buffer:
            start = self._buffer.find("\ue200")
            if start < 0:
                output.append(self._buffer)
                self._buffer = ""
                break
            if start:
                output.append(self._buffer[:start])
                self._buffer = self._buffer[start:]
            end = self._buffer.find("\ue201", 1)
            if end < 0:
                break
            output.append(_upstream_markup_value(self._buffer[1:end]))
            self._buffer = self._buffer[end + 1:]
        return "".join(output)

    def close(self) -> str:
        # Preserve malformed/incomplete text rather than silently dropping it.
        result = self._buffer
        self._buffer = ""
        return result


def build_chat_content(
    markdown: str,
    image_urls: List[Any] | None = None,
    metadata: Dict[str, Any] | None = None,
) -> ChatContent:
    """Build rendering hints without discarding the original Markdown response."""
    raw_markdown = markdown.replace("\r\n", "\n").replace("\r", "\n")
    display_markdown = _UPSTREAM_MARKUP.sub(lambda match: _upstream_markup_value(match.group("body")), raw_markdown)
    links = [ContentLink(label=match.group("label"), url=match.group("url")) for match in _MARKDOWN_LINK.finditer(display_markdown)]
    code_blocks = [
        CodeBlock(language=match.group("language").strip(), code=match.group("code").strip("\n"))
        for match in _CODE_BLOCK.finditer(display_markdown)
    ]
    return ChatContent(
        raw_markdown=raw_markdown,
        markdown=display_markdown,
        plain_text=_plain_text(display_markdown),
        links=links,
        code_blocks=code_blocks,
        citations=_citation_values(metadata or {}),
        image_urls=_unique_strings(image_urls or []),
        source_references=_source_references(raw_markdown),
    )
