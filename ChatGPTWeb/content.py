"""Platform-neutral rich content hints derived from ChatGPT responses."""

import re

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List


_CODE_BLOCK = re.compile(r"^```(?P<language>[^\n`]*)\n(?P<code>.*?)^```[ \t]*$", re.MULTILINE | re.DOTALL)
_MARKDOWN_LINK = re.compile(r"(?<!!)\[(?P<label>[^\]]+)\]\((?P<url>[^\s)]+)(?:\s+['\"][^)]*['\"])?\)")
_IMAGE_LINK = re.compile(r"!\[(?P<label>[^\]]*)\]\((?P<url>[^\s)]+)(?:\s+['\"][^)]*['\"])?\)")


@dataclass
class ContentLink:
    label: str
    url: str


@dataclass
class CodeBlock:
    language: str
    code: str


@dataclass
class ChatContent:
    """Lossless Markdown plus optional hints for platform-specific renderers."""

    raw_markdown: str = ""
    plain_text: str = ""
    links: List[ContentLink] = field(default_factory=list)
    code_blocks: List[CodeBlock] = field(default_factory=list)
    citations: List[Any] = field(default_factory=list)
    image_urls: List[str] = field(default_factory=list)

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


def build_chat_content(
    markdown: str,
    image_urls: List[Any] | None = None,
    metadata: Dict[str, Any] | None = None,
) -> ChatContent:
    """Build rendering hints without discarding the original Markdown response."""
    raw_markdown = markdown.replace("\r\n", "\n").replace("\r", "\n")
    links = [ContentLink(label=match.group("label"), url=match.group("url")) for match in _MARKDOWN_LINK.finditer(raw_markdown)]
    code_blocks = [
        CodeBlock(language=match.group("language").strip(), code=match.group("code").strip("\n"))
        for match in _CODE_BLOCK.finditer(raw_markdown)
    ]
    return ChatContent(
        raw_markdown=raw_markdown,
        plain_text=_plain_text(raw_markdown),
        links=links,
        code_blocks=code_blocks,
        citations=_citation_values(metadata or {}),
        image_urls=_unique_strings(image_urls or []),
    )
