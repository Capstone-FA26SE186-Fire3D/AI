import pytest

from app.rag.chunker import chunk_text
from app.rag.loaders import extract_text


def test_chunker_preserves_overlap() -> None:
    chunks = chunk_text("alpha " * 400, chunk_size=100, overlap=20)

    assert len(chunks) > 1
    assert chunks[0][-20:] in chunks[1]


def test_rejects_unknown_document_extension() -> None:
    with pytest.raises(ValueError, match="Unsupported"):
        extract_text("notes.docx", b"not used")
