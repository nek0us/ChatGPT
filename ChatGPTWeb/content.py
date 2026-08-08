"""Platform-neutral rich content hints derived from ChatGPT responses."""

from __future__ import annotations

import json
import re

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List

# V8_6_RICH_STREAM_NORMALIZATION

_CODE_BLOCK = re.compile(r"^```(?P<language>[^\n`]*)\n(?P<code>.*?)^```[ \t]*$", re.MULTILINE | re.DOTALL)
_MARKDOWN_LINK = re.compile(r"(?<!!)\[(?P<label>[^\]]+)\]\((?P<url>[^\s)]+)(?:\s+['\"][^)]*['\"])?\)")
_IMAGE_LINK = re.compile(r"!\[(?P<label>[^\]]*)\]\((?P<url>[^\s)]+)(?:\s+['\"][^)]*['\"])?\)")
_UPSTREAM_OPEN = "\ue200"
_UPSTREAM_CLOSE = "\ue201"
_UPSTREAM_FIELD_SEP = "\ue202"
_UPSTREAM_ITEM_SEP = "\ue203"
_UPSTREAM_MARKUP = re.compile(f"{_UPSTREAM_OPEN}(?P<body>.*?){_UPSTREAM_CLOSE}", re.DOTALL)
_UPSTREAM_KIND = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,63}")

# These kinds come from ChatGPT's renderer contract. Their visual payload is
# supplemental: callers that cannot render the widget must still receive the
# ordinary surrounding answer text, so the token itself is safely suppressed.
_WIDGET_ONLY_UPSTREAM_KINDS = {
    "finance",
    "forecast",
    "genui",
    "i",
    "navlist",
    "products",
    "schedule",
    "standing",
}

# Inline tokens affect readable prose and therefore need a deterministic text
# fallback rather than being discarded as a generic widget.
_INLINE_UPSTREAM_KINDS = {
    "cite",
    "entity",
    "filecite",
    "url",
}

_KNOWN_UPSTREAM_KINDS = _WIDGET_ONLY_UPSTREAM_KINDS | _INLINE_UPSTREAM_KINDS
_READABLE_KEYS = (
    "name",
    "title",
    "text",
    "label",
    "alt",
    "display_name",
    "displayName",
    "caption",
)

_RICH_TAG = re.compile(r"<(?P<close>/)?(?P<name>Text|Bold|Strong|Italic|Emphasis|Code|Strikethrough|LineBreak|br|Paragraph|List|OrderedList|UnorderedList|ListItem|Item)(?:\s[^>]*)?/?>", re.IGNORECASE)
_RICH_TAG_REPLACEMENTS = {
    "bold": "**",
    "strong": "**",
    "italic": "*",
    "emphasis": "*",
    "code": "`",
    "strikethrough": "~~",
    "linebreak": "\n",
    "br": "\n",
    "text": "",
    "paragraph": "",
    "list": "",
    "orderedlist": "",
    "unorderedlist": "",
    "listitem": "",
    "item": "",
}


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
class RichContentItem:
    """An upstream UI payload kept intact for a caller-specific renderer."""

    kind: str
    payload: Any


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
    rich_items: List[RichContentItem] = field(default_factory=list)

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


def _inline_rich_content_items(markdown: str) -> List[RichContentItem]:
    items: List[RichContentItem] = []
    for match in _UPSTREAM_MARKUP.finditer(markdown):
        body = match.group("body")
        kind, fields = _split_upstream_body(body)
        if not kind:
            continue
        payload: Any = fields
        if kind == "entity":
            payload = body[len("entity"):]
        items.append(RichContentItem(kind=kind, payload=payload))
    return items


def _rich_content_items(metadata: Dict[str, Any], markdown: str = "") -> List[RichContentItem]:
    """Expose known non-Markdown payloads without imposing a display format."""
    items = _inline_rich_content_items(markdown)
    for key in ("aggregate_result", "tool_calls", "tool_results", "attachments"):
        value = metadata.get(key)
        if isinstance(value, list):
            items.extend(RichContentItem(kind=key, payload=item) for item in value)
        elif isinstance(value, (dict, str, int, float, bool)):
            items.append(RichContentItem(kind=key, payload=value))
    return items


def _plain_text(markdown: str) -> str:
    text = _IMAGE_LINK.sub(lambda match: f"{match.group('label')} ({match.group('url')})".strip(), markdown)
    text = _MARKDOWN_LINK.sub(lambda match: f"{match.group('label')} ({match.group('url')})", text)
    text = _CODE_BLOCK.sub(lambda match: match.group("code").strip("\n"), text)
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s+", "", text)
    text = re.sub(r"(?m)^\s*[-*+]\s+", "- ", text)
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _valid_upstream_kind(value: str) -> bool:
    return bool(_UPSTREAM_KIND.fullmatch(value))


def _valid_upstream_kind_prefix(value: str) -> bool:
    if not value:
        return True
    if len(value) > 64 or not value[0].isalpha():
        return False
    return all(character.isalnum() or character in "_-" for character in value[1:])


def _first_readable(values: List[Any]) -> str:
    for value in values:
        if isinstance(value, (dict, list, tuple)):
            nested = _readable_json_value(value)
            if nested:
                return nested
            continue
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _readable_json_value(value: Any) -> str:
    if isinstance(value, dict):
        direct = _first_readable([value.get(key) for key in _READABLE_KEYS])
        if direct:
            return direct
        for nested in value.values():
            if isinstance(nested, (dict, list, tuple)):
                text = _readable_json_value(nested)
                if text:
                    return text
        return ""
    if isinstance(value, (list, tuple)):
        # ChatGPT entity arrays conventionally store a type/slug first and the
        # human-readable display name second.
        ordered = list(value[1:]) + list(value[:1]) if value else []
        return _first_readable(ordered)
    if isinstance(value, (str, int, float)):
        return str(value).strip()
    return ""


def _render_entity(body: str) -> str:
    payload = body[len("entity"):]
    if payload.startswith(_UPSTREAM_FIELD_SEP):
        payload = payload[1:]
    payload = payload.strip()
    if not payload:
        return ""
    try:
        parsed = json.loads(payload)
    except (json.JSONDecodeError, TypeError, ValueError):
        # Tolerate a trailing comma or other minor upstream corruption while
        # preferring the second quoted field, which is the display name in the
        # known entity-array protocol.
        quoted = re.findall(r'"((?:\\.|[^"\\])*)"', payload)
        decoded: List[str] = []
        for item in quoted:
            try:
                decoded.append(json.loads(f'"{item}"'))
            except json.JSONDecodeError:
                decoded.append(item)
        return _first_readable(decoded[1:] + decoded[:1])
    return _readable_json_value(parsed)


def _split_upstream_body(body: str) -> tuple[str, List[str]]:
    if body.startswith("entity[") or body.startswith("entity{"):
        return "entity", [body[len("entity"):]]
    parts = body.split(_UPSTREAM_FIELD_SEP)
    if len(parts) == 1:
        return "", [body]
    kind = parts[0]
    if not _valid_upstream_kind(kind):
        return "", parts
    fields: List[str] = []
    for part in parts[1:]:
        fields.extend(part.split(_UPSTREAM_ITEM_SEP))
    return kind, fields


def _reference_lookup(metadata: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    result: Dict[str, Dict[str, Any]] = {}
    for key in ("content_references", "citations"):
        raw = metadata.get(key)
        values = raw if isinstance(raw, list) else [raw] if isinstance(raw, dict) else []
        for value in values:
            if not isinstance(value, dict):
                continue
            matched = value.get("matched_text")
            if isinstance(matched, str) and matched:
                result[matched] = value
    return result


def _reference_urls(reference: Dict[str, Any]) -> List[str]:
    urls: List[str] = []
    direct = reference.get("url")
    if isinstance(direct, str) and direct.strip():
        urls.append(direct.strip())
    items = reference.get("items")
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            url = item.get("url")
            if isinstance(url, str) and url.strip() and url.strip() not in urls:
                urls.append(url.strip())
    return urls


def _render_rich_tag(match: re.Match[str]) -> str:
    name = match.group("name").lower()
    replacement = _RICH_TAG_REPLACEMENTS.get(name, "")
    if name in {"linebreak", "br"} and match.group("close"):
        return ""
    return replacement


def _render_rich_text_tags(text: str) -> str:
    return _RICH_TAG.sub(_render_rich_tag, text)


def _strip_orphan_upstream_chars(text: str) -> str:
    return (
        text.replace(_UPSTREAM_OPEN, "")
        .replace(_UPSTREAM_CLOSE, "")
        .replace(_UPSTREAM_FIELD_SEP, "")
        .replace(_UPSTREAM_ITEM_SEP, "")
    )


def _upstream_markup_value(
    body: str,
    *,
    token: str = "",
    metadata: Dict[str, Any] | None = None,
    cite_numbers: Dict[str, int] | None = None,
    cite_counter: List[int] | None = None,
) -> tuple[str, bool]:
    """Return ``(visible_text, safe)`` for one closed private token.

    ``safe`` means the token has a deterministic generic-client rendering and
    does not require canonical-final fallback.
    """
    if body.startswith("entity[") or body.startswith("entity{"):
        return _render_entity(body), True

    kind, fields = _split_upstream_body(body)
    if not kind:
        # A malformed private wrapper around ordinary prose is visible content.
        return _strip_orphan_upstream_chars(body), True

    if kind == "entity":
        return _render_entity(body), True
    if kind == "url":
        return (fields[0] if fields else ""), True
    if kind in {"cite", "filecite"}:
        reference = _reference_lookup(metadata or {}).get(token)
        urls = _reference_urls(reference or {})
        if not urls:
            return "", True
        numbers = cite_numbers if cite_numbers is not None else {}
        counter = cite_counter if cite_counter is not None else [0]
        if token not in numbers:
            counter[0] += 1
            numbers[token] = counter[0]
        return f"[[{numbers[token]}]]({urls[0]})", True
    if kind in _WIDGET_ONLY_UPSTREAM_KINDS:
        return "", True

    # Unknown structured tokens occasionally carry a readable inline label.
    # Preserve it when it is unambiguous; otherwise stop irreversible streaming
    # and let the canonical final node reconcile the response.
    for field in fields:
        candidate = field.strip()
        if not candidate:
            continue
        try:
            parsed = json.loads(candidate)
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
        readable = _readable_json_value(parsed)
        if readable:
            return readable, True
    return "", False


def _source_references(markdown: str) -> List[SourceReference]:
    references = []
    for match in _UPSTREAM_MARKUP.finditer(markdown):
        kind, fields = _split_upstream_body(match.group("body"))
        if kind != "url" or len(fields) < 2:
            continue
        reference = SourceReference(label=fields[0], source_id=fields[1])
        if reference not in references:
            references.append(reference)
    return references


class UpstreamMarkupNormalizer:
    """Incrementally normalize ChatGPT rich-UI and rich-text markup.

    The renderer contract distinguishes three categories:

    * inline semantic annotations such as ``entity`` and ``url`` become visible
      text immediately;
    * supplemental widgets such as finance/forecast/genui are removed from a
      generic Markdown client because the surrounding textual answer is required
      to stand on its own;
    * unknown structures remain conservative and request canonical reconciliation.

    A private token or rich-text tag may span several SSE deltas. Only that small
    incomplete fragment is buffered; ordinary text before and after it continues
    to stream.
    """

    def __init__(self, metadata: Dict[str, Any] | None = None):
        self._buffer = ""
        self._tag_buffer = ""
        self._visible_wrapper = False
        self._requires_final_reconciliation = False
        self._metadata: Dict[str, Any] = dict(metadata or {})
        self._cite_numbers: Dict[str, int] = {}
        self._cite_counter = [0]

    @property
    def has_pending_markup(self) -> bool:
        return bool(self._buffer or self._tag_buffer)

    @property
    def requires_final_reconciliation(self) -> bool:
        return self._requires_final_reconciliation

    def update_metadata(self, metadata: Dict[str, Any] | None) -> None:
        if isinstance(metadata, dict):
            self._metadata.update(metadata)

    @staticmethod
    def _looks_like_rich_tag_prefix(value: str) -> bool:
        if not value.startswith("<") or ">" in value:
            return False
        body = value[1:]
        if body.startswith("/"):
            body = body[1:]
        body = body.strip().lower()
        if not body:
            return True
        names = {name.lower() for name in _RICH_TAG_REPLACEMENTS}
        return any(name.startswith(body) for name in names)

    def _normalize_tags(self, text: str, *, final: bool = False) -> str:
        self._tag_buffer += text
        if not self._tag_buffer:
            return ""
        if not final:
            last_open = self._tag_buffer.rfind("<")
            last_close = self._tag_buffer.rfind(">")
            if last_open > last_close and self._looks_like_rich_tag_prefix(self._tag_buffer[last_open:]):
                stable = self._tag_buffer[:last_open]
                self._tag_buffer = self._tag_buffer[last_open:]
            else:
                stable = self._tag_buffer
                self._tag_buffer = ""
        else:
            stable = self._tag_buffer
            self._tag_buffer = ""
            if self._looks_like_rich_tag_prefix(stable):
                self._requires_final_reconciliation = True
                return ""
        return _render_rich_text_tags(stable)

    def feed(self, text: str, metadata: Dict[str, Any] | None = None) -> str:
        self.update_metadata(metadata)
        self._buffer += text
        output: List[str] = []
        while self._buffer:
            if self._visible_wrapper:
                token_end = self._buffer.find(_UPSTREAM_CLOSE)
                if token_end < 0:
                    output.append(
                        self._buffer.replace(_UPSTREAM_OPEN, "")
                        .replace(_UPSTREAM_FIELD_SEP, "")
                        .replace(_UPSTREAM_ITEM_SEP, "")
                    )
                    self._buffer = ""
                    break
                output.append(
                    self._buffer[:token_end]
                    .replace(_UPSTREAM_OPEN, "")
                    .replace(_UPSTREAM_FIELD_SEP, "")
                    .replace(_UPSTREAM_ITEM_SEP, "")
                )
                self._buffer = self._buffer[token_end + 1:]
                self._visible_wrapper = False
                continue

            start = self._buffer.find(_UPSTREAM_OPEN)
            if start < 0:
                output.append(_strip_orphan_upstream_chars(self._buffer))
                self._buffer = ""
                break
            if start:
                output.append(_strip_orphan_upstream_chars(self._buffer[:start]))
                self._buffer = self._buffer[start:]

            token_end = self._buffer.find(_UPSTREAM_CLOSE, 1)
            if token_end < 0:
                # Buffer only the incomplete token. Once the body cannot be a
                # compact kind or an entity prefix, release it as malformed prose.
                body = self._buffer[1:]
                entity_prefix = "entity".startswith(body) or body.startswith("entity[") or body.startswith("entity{")
                compact_prefix = _valid_upstream_kind_prefix(body.split(_UPSTREAM_FIELD_SEP, 1)[0])
                if not entity_prefix and not compact_prefix:
                    output.append(body.replace(_UPSTREAM_FIELD_SEP, "").replace(_UPSTREAM_ITEM_SEP, ""))
                    self._buffer = ""
                    self._visible_wrapper = True
                break

            token = self._buffer[:token_end + 1]
            body = self._buffer[1:token_end]
            visible, safe = _upstream_markup_value(
                body,
                token=token,
                metadata=self._metadata,
                cite_numbers=self._cite_numbers,
                cite_counter=self._cite_counter,
            )
            if not safe:
                self._requires_final_reconciliation = True
            output.append(visible)
            self._buffer = self._buffer[token_end + 1:]

        return self._normalize_tags("".join(output))

    def close(self) -> str:
        output = ""
        if self._buffer:
            if self._visible_wrapper:
                output += (
                    self._buffer.replace(_UPSTREAM_OPEN, "")
                    .replace(_UPSTREAM_FIELD_SEP, "")
                    .replace(_UPSTREAM_ITEM_SEP, "")
                    .replace(_UPSTREAM_CLOSE, "")
                )
            else:
                # A truly incomplete structured token is ambiguous. Do not leak
                # private control bytes; canonical reconciliation restores it.
                self._requires_final_reconciliation = True
            self._buffer = ""
        self._visible_wrapper = False
        output += self._normalize_tags("", final=True)
        return output


def build_chat_content(
    markdown: str,
    image_urls: List[Any] | None = None,
    metadata: Dict[str, Any] | None = None,
) -> ChatContent:
    """Build rendering hints while preserving readable Markdown semantics."""
    raw_markdown = markdown.replace("\r\n", "\n").replace("\r", "\n")
    normalizer = UpstreamMarkupNormalizer(metadata)
    display_markdown = normalizer.feed(raw_markdown, metadata) + normalizer.close()
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
        rich_items=_rich_content_items(metadata or {}, raw_markdown),
    )
