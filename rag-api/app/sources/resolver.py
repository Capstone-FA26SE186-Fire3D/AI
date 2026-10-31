"""Turn BE-pinned sources into searchable chunks (indexed or inline).

Knowledge sources are used only once fully embedded; others are handed to the SourceWarmer and skipped for this
question with a limitation. A question fails only when none of its knowledge sources is ready and it has no inline
source: AI_SOURCES_PREPARING (503, BE retries) while some are still being embedded, else the failure of the first.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import httpx

from app.core.config import Settings
from app.index.base import KnowledgeIndex
from app.llm.base import Provider
from app.sources.chunking import Chunk, chunk_sections
from app.sources.render import inline_sections
from app.sources.warmer import QUEUED, SourceWarmer
from app.v2.errors import AdapterRefusal, refuse
from app.v2.schemas import SourcePin


@dataclass
class PreparedSources:
    knowledge_ids: list[str] = field(default_factory=list)
    inline_chunks: list[Chunk] = field(default_factory=list)
    inline_embeddings: list[list[float]] = field(default_factory=list)
    pins: dict[str, SourcePin] = field(default_factory=dict)
    limitations: list[str] = field(default_factory=list)


def _name(pin: SourcePin) -> str:
    return pin.title or pin.document_id


class SourceResolver:
    def __init__(
        self,
        index: KnowledgeIndex,
        provider: Provider,
        settings: Settings,
        http: httpx.Client | None = None,
        warmer: SourceWarmer | None = None,
    ) -> None:
        self.index = index
        self.provider = provider
        self.settings = settings
        # Without an injected warmer sources are embedded inside prepare() (tests, local scripts).
        self.warmer = warmer or SourceWarmer(index, provider, settings, http, background=False)

    def prepare(self, pins: list[SourcePin]) -> PreparedSources:
        prepared = PreparedSources()
        preparing: list[SourcePin] = []
        failed: list[tuple[SourcePin, AdapterRefusal]] = []
        for pin in pins:
            if pin.content_omitted:
                prepared.limitations.append(f"Nguồn {_name(pin)} quá lớn, không được dùng.")
                continue
            if pin.kind != "KnowledgeSource":
                self._prepare_inline(pin, prepared)
                continue
            if not pin.content_hash:
                raise refuse("AI_SOURCE_UNAVAILABLE", f"Source {pin.document_id} has no content hash to verify")
            state = (
                "ready" if self.index.has_current(pin.document_id, pin.content_hash, self.provider.embedding_model)
                else self.warmer.request(pin)
            )
            if isinstance(state, AdapterRefusal):
                failed.append((pin, state))
            elif state == QUEUED:
                preparing.append(pin)
            else:
                if pin.document_id not in prepared.knowledge_ids:
                    prepared.knowledge_ids.append(pin.document_id)
                prepared.pins[pin.document_id] = pin

        if (preparing or failed) and not prepared.knowledge_ids and not prepared.inline_chunks:
            if preparing:
                raise refuse(
                    "AI_SOURCES_PREPARING",
                    f"{len(preparing)} source(s) are being prepared; retry in a few minutes",
                    status=503,
                )
            raise failed[0][1]
        prepared.limitations.extend(f"Nguồn {_name(pin)} đang được chuẩn bị, chưa dùng cho câu hỏi này." for pin in preparing)
        prepared.limitations.extend(f"Nguồn {_name(pin)} hiện không dùng được." for pin, _ in failed)
        return prepared

    def _prepare_inline(self, pin: SourcePin, prepared: PreparedSources) -> None:
        chunks = chunk_sections(inline_sections(pin), pin.document_id, pin.document_version)
        if not chunks:
            return
        prepared.inline_chunks.extend(chunks)
        prepared.inline_embeddings.extend(self.provider.embed([c.content for c in chunks]))
        prepared.pins[pin.document_id] = pin
