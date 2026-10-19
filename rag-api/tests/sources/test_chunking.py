from app.sources.chunking import Section, chunk_sections, format_locator


def test_short_sections_keep_locators():
    secs = [Section("alpha", {"page": 1}), Section("beta", {"block": 2})]
    chunks = chunk_sections(secs, "d1", "v1")
    assert [c.chunk_id for c in chunks] == ["d1:v1:0", "d1:v1:1"]
    assert chunks[0].locator == {"page": 1} and chunks[0].excerpt_locator == "Trang 1"
    assert chunks[1].excerpt_locator == "Khối 2" and chunks[1].content == "beta"


def test_long_section_windows_with_overlap():
    chunks = chunk_sections([Section("a" * 2000, {"page": 3})], "d", "v", 900, 150)
    assert len(chunks) == 3
    assert chunks[0].content[-150:] == chunks[1].content[:150]
    assert chunks[1].content[-150:] == chunks[2].content[:150]
    assert [c.chunk_index for c in chunks] == [0, 1, 2]
    assert all(c.locator == {"page": 3} for c in chunks)


def test_whitespace_boundary_preferred():
    text = ("word " * 400).strip()
    chunks = chunk_sections([Section(text, {})], "d", "v", 900, 150)
    assert len(chunks) > 1
    assert all(c.content.endswith(" ") for c in chunks[:-1])


def test_format_locator_cases():
    assert format_locator({"page": 3}) == "Trang 3"
    assert format_locator({"heading": "H", "paragraph": 2}) == "Mục H, đoạn 2"
    assert format_locator({"paragraph": 4}) == "Đoạn 4"
    assert format_locator({"block": 3}) == "Khối 3"
    assert format_locator({"field": "learningObjectives"}) == "Trường learningObjectives"
    assert format_locator({}) == "Toàn văn"
