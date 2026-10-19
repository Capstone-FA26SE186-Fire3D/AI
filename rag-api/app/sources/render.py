"""Turn raw documents and inline pinned content into located sections."""
from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from io import BytesIO

from pypdf import PdfReader

from app.sources.chunking import Section
from app.v2.errors import refuse
from app.v2.schemas import SourcePin

_BLOCK_TAGS = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "ul", "ol", "table"}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip = max(0, self._skip - 1)
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n\n")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def _html_to_text(raw: str) -> str:
    parser = _TextExtractor()
    parser.feed(raw)
    parser.close()
    return "".join(parser.parts)


def _decode(content: bytes) -> str:
    return content.decode("utf-8", errors="replace")


def _paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", text.replace("\r\n", "\n")) if p.strip()]


def _text_sections(text: str) -> list[Section]:
    return [Section(p, {"paragraph": i}) for i, p in enumerate(_paragraphs(text), 1)]


_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$")


def _markdown_sections(text: str) -> list[Section]:
    sections: list[Section] = []
    heading: str | None = None
    buf: list[str] = []
    count = 0

    def flush() -> None:
        nonlocal count
        for para in _paragraphs("\n".join(buf)):
            count += 1
            loc = {"paragraph": count} if heading is None else {"heading": heading, "paragraph": count}
            sections.append(Section(para, loc))
        buf.clear()

    for line in text.replace("\r\n", "\n").split("\n"):
        m = _HEADING.match(line)
        if m:
            flush()
            heading = m.group(1).strip()
            count = 0
        else:
            buf.append(line)
    flush()
    return sections


def document_sections(content: bytes, content_type: str, filename: str) -> list[Section]:
    ctype = (content_type or "").split(";")[0].strip().lower()
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ctype == "application/pdf" or suffix == "pdf":
        try:
            reader = PdfReader(BytesIO(content))
            pages = [(page.extract_text() or "").strip() for page in reader.pages]
        except Exception:
            raise refuse("AI_SOURCE_UNAVAILABLE", "PDF source could not be read") from None
        return [Section(t, {"page": i}) for i, t in enumerate(pages, 1) if t]
    if ctype == "text/markdown" or suffix in ("md", "markdown"):
        return _markdown_sections(_decode(content))
    if ctype in ("text/html", "application/xhtml+xml") or suffix in ("html", "htm"):
        return _text_sections(_html_to_text(_decode(content)))
    if ctype == "text/plain" or suffix == "txt":
        return _text_sections(_decode(content))
    raise refuse("AI_SOURCE_UNAVAILABLE", "Unsupported source document type")


def _strings(value) -> list[str]:
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, dict):
        return [s for v in value.values() for s in _strings(v)]
    if isinstance(value, (list, tuple)):
        return [s for v in value for s in _strings(v)]
    return []


def _scalar_text(value) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _flatten(value, path: str) -> list[tuple[str, str]]:
    if isinstance(value, dict):
        return [item for k, v in value.items() for item in _flatten(v, f"{path}.{k}" if path else str(k))]
    if isinstance(value, list):
        return [item for i, v in enumerate(value) for item in _flatten(v, f"{path}[{i}]")]
    if value is None:
        return []
    return [(path, _scalar_text(value))]


def inline_sections(pin: SourcePin) -> list[Section]:
    content = pin.content or {}
    sections: list[Section] = []
    if pin.kind == "LearnPost":
        for key in ("title", "summary"):
            val = content.get(key)
            if isinstance(val, str) and val.strip():
                sections.append(Section(val, {"field": key}))
        blocks = content.get("blocks")
        if isinstance(blocks, list):
            for i, block in enumerate(blocks):
                text = "\n".join(_strings(block))
                if text.strip():
                    sections.append(Section(text, {"block": i + 1}))
    elif pin.kind == "LibraryVersion":
        head = [f"{k}: {_scalar_text(content[k])}" for k in ("kind", "code", "name") if content.get(k) is not None]
        if head:
            sections.append(Section("\n".join(head), {"field": "identity"}))
        if content.get("payload") is not None:
            for path, text in _flatten(content["payload"], "payload"):
                sections.append(Section(f"{path}: {text}", {"field": path}))
    else:
        for key, val in content.items():
            if val is None:
                continue
            text = _scalar_text(val)
            if text.strip():
                sections.append(Section(f"{key}: {text}", {"field": key}))
    return sections
