from app.answering.validate import build_citations, clean_list, to_plain_text
from app.index.base import ScoredChunk
from app.sources.chunking import Chunk


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
