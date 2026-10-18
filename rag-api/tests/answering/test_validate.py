import re as _re

import pytest

from app.answering.validate import build_citations, clean_list, to_plain_text
from app.index.base import ScoredChunk
from app.sources.chunking import Chunk
from app.v2.schemas import SourcePin


def _retrieved(score=0.7):
    chunk = Chunk("d:v1:0", "d", "v1", 0, "nội dung", {"page": 2}, "Trang 2")
    return {"d:v1:0": ScoredChunk(chunk, score)}


def test_plain_text_strips_markdown_and_html():
    text = "# Tiêu đề\n- **đậm** và __nữa__ `code`\n* [liên kết](http://x.y) <b>tag</b>\n\n\n\nhết   rồi"
    out = to_plain_text(text, 1000)
    assert out == "Tiêu đề\nđậm và nữa code\nliên kết tag\n\nhết rồi"
    assert to_plain_text("a" * 50, 10) == "a" * 10


def test_clean_list_limits():
    items = ["**x**", "", "   "] + [f"i{n}" for n in range(30)]
    out = clean_list(items)
    assert out[0] == "x" and len(out) == 20
    assert len(clean_list(["y" * 900])[0]) == 500


def test_citation_unknown_chunk_dropped():
    raw = [{"chunk_id": "nope"}, {"chunk_id": None}, {"chunk_id": 5}, "junk", {"chunk_id": "d:v1:0"}]
    cites = build_citations(raw, _retrieved())
    assert [c.chunk_id for c in cites] == ["d:v1:0"]


def test_citation_uses_pinned_version():
    raw = [{"chunk_id": "d:v1:0", "document_id": "evil", "document_version": "fake",
            "excerpt_locator": "x", "relevance": 0.4}]
    (c,) = build_citations(raw, _retrieved())
    assert (c.document_id, c.document_version, c.excerpt_locator, c.relevance) == ("d", "v1", "Trang 2", 0.4)


def test_citation_relevance_fallback_and_dedupe():
    raw = [{"chunk_id": "d:v1:0", "relevance": 7}, {"chunk_id": "d:v1:0", "relevance": 0.1}]
    cites = build_citations(raw, _retrieved(0.7))
    assert len(cites) == 1 and cites[0].relevance == 0.7


# BE OrganizationAiInput.Text: Markup regex `<\s*[a-zA-Z/!?]` and char.IsControl except \n \t \r.
_BE_MARKUP = _re.compile(r"<\s*[a-zA-Z/!?]")


def _be_accepts(text: str) -> bool:
    if _BE_MARKUP.search(text):
        return False
    return not any((ord(c) < 0x20 or 0x7F <= ord(c) <= 0x9F) and c not in "\n\t\r" for c in text)


NASTY = [
    "Khoảng cách < quy định thì phải bổ sung",
    "a <  b và <!-- x --> rồi <?php ?> và </ div",
    "nhiệt độ <\nCao",
    "<[liên kết](http://x)",
    "<**đậm**",
    "<`code`",
    "ký tự\x00điều\x07khiển\x1b[0m và \x85 \x7f",
    "bảng <b>đậm</b> <br/> <img src=x onerror=y>",
    "<\ta",
]


@pytest.mark.parametrize("text", NASTY)
def test_plain_text_passes_be_text_rule(text):
    out = to_plain_text(text, 1000)
    assert _be_accepts(out), repr(out)
    assert all(_be_accepts(i) for i in clean_list([text]))


def test_plain_text_keeps_non_tag_angle_brackets():
    assert to_plain_text("<5 m va >2 m", 100) == "<5 m va >2 m"
    assert to_plain_text("a<b>c</b>d", 100) == "acd"
    assert "quy định" in to_plain_text("Khoảng cách < quy định", 100)
    assert to_plain_text("dòng 1\n\tdòng 2\r\n", 100).startswith("dòng 1")


def test_citation_version_comes_from_pin():
    pin = SourcePin(kind="KnowledgeSource", document_id="d", document_version="v9", content_hash="a" * 64)
    (c,) = build_citations([{"chunk_id": "d:v1:0"}], _retrieved(), pins={"d": pin})
    assert c.document_version == "v9"
    (c,) = build_citations([{"chunk_id": "d:v1:0"}], _retrieved(), pins={})
    assert c.document_version == "v1"
