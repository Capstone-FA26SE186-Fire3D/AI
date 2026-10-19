import pytest

from app.sources.render import document_sections, inline_sections
from app.v2.errors import AdapterRefusal
from app.v2.schemas import SourcePin


def test_markdown_headings():
    md = b"intro\n\n# Alpha\n\nfirst\n\nsecond\n\n## Beta\n\nthird"
    secs = document_sections(md, "text/markdown", "a.md")
    assert [s.locator for s in secs] == [
        {"paragraph": 1},
        {"heading": "Alpha", "paragraph": 1},
        {"heading": "Alpha", "paragraph": 2},
        {"heading": "Beta", "paragraph": 1},
    ]


def test_html_strips_script_and_style():
    html = b"<html><style>x{}</style><script>evil()</script><p>Hello</p><p>World</p></html>"
    secs = document_sections(html, "text/html", "a.html")
    assert [s.text for s in secs] == ["Hello", "World"]


def test_learnpost_blocks_locator():
    pin = SourcePin(kind="LearnPost", document_id="d", document_version="1",
                    content={"title": "T", "summary": "S",
                             "blocks": [{"text": "one", "items": ["a", {"x": "b"}]}, {"text": "two"}]})
    blocks = [s for s in inline_sections(pin) if "block" in s.locator]
    assert [s.locator for s in blocks] == [{"block": 1}, {"block": 2}]
    assert blocks[0].text.split("\n") == ["one", "a", "b"]


def test_library_and_snapshot():
    lib = SourcePin(kind="LibraryVersion", document_id="d", document_version="1",
                    content={"kind": "k", "code": "c", "name": "n", "payload": {"a": {"b": 1}, "l": ["x"]}})
    fields = [s.locator["field"] for s in inline_sections(lib)]
    assert "payload.a.b" in fields and "payload.l[0]" in fields
    snap = SourcePin(kind="TrainingSnapshot", document_id="d", document_version="1", content={"score": 5, "note": "hi"})
    assert [s.locator for s in inline_sections(snap)] == [{"field": "score"}, {"field": "note"}]


def test_unsupported_type_refused():
    with pytest.raises(AdapterRefusal) as e:
        document_sections(b"\x00", "application/zip", "a.zip")
    assert e.value.code == "AI_SOURCE_UNAVAILABLE"
