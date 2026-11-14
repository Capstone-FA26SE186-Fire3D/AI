from app.core.config import Settings
from app.index.memory import MemoryIndex
from app.llm.fake import FakeProvider
from app.sources.warmer import SourceWarmer
from app.v2.errors import AdapterRefusal
from app.v2.schemas import SourcePin


def pin(doc="d1", h="h1"):
    return SourcePin(kind="KnowledgeSource", document_id=doc, document_version="1", content_hash=h,
                     source_uri="https://example.invalid/doc.pdf")


def test_stored_failures_are_bare_copies_and_expire():
    now = [100.0]
    warmer = SourceWarmer(MemoryIndex(), FakeProvider(), Settings(_env_file=None, source_retry_seconds=60), clock=lambda: now[0])
    warmer.start = lambda: None

    def boom(p):
        try:
            raise ValueError("big local data")
        except ValueError as cause:
            raise AdapterRefusal(503, "AI_SOURCE_UNAVAILABLE", "nope") from cause

    warmer._warm = boom
    warmer.run_one(("d1", "h1"), pin())
    stored = warmer._failed[("d1", "h1")][0]
    assert stored.__traceback__ is None and stored.__cause__ is None
    first, second = warmer.request(pin()), warmer.request(pin())
    assert (first.status_code, first.code, first.message) == (503, "AI_SOURCE_UNAVAILABLE", "Source d1: nope"), "names the source"
    assert first is not second and first is not stored, "each request gets its own copy"

    # A failure of a key that is never asked again is dropped once expired, when another failure is stored.
    now[0] += 61
    warmer.run_one(("d2", "h2"), pin("d2", "h2"))
    assert ("d1", "h1") not in warmer._failed and ("d2", "h2") in warmer._failed
