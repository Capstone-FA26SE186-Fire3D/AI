"""Turn BE-pinned sources into searchable chunks (indexed or inline).

Knowledge sources are used only once fully embedded; others are handed to the SourceWarmer and skipped for this
question with a limitation. Inline content with a content hash and a UUID id is treated the same way (embedded once,
kept in the index), except that small content is embedded on the spot; inline content without both is embedded per
question. A question fails only when none of its knowledge sources is ready and it has no inline
source: AI_SOURCES_PREPARING (503, BE retries) while some are still being embedded, else the failure of the first.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field

import httpx

from app.core.config import Settings
from app.index.base import KnowledgeIndex
from app.llm.base import Provider, ProviderError
from app.sources.chunking import Chunk, chunk_sections
from app.sources.render import inline_sections
from app.sources.warmer import QUEUED, READY, SourceWarmer
from app.v2.errors import AdapterRefusal, refuse
from app.v2.schemas import SourcePin


@dataclass
class PreparedSources:
    knowledge_ids: list[str] = field(default_factory=list)
    inline_chunks: list[Chunk] = field(default_factory=list)
    inline_embeddings: list[list[float]] = field(default_factory=list)
    pins: dict[str, SourcePin] = field(default_factory=dict)
    limitations: list[str] = field(default_factory=list)


log = logging.getLogger(__name__)


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(str(value))
    except ValueError:
        return False
    return True


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
                if pin.content_hash and _is_uuid(pin.document_id):
                    state = self._prepare_stored_inline(pin)
                    if isinstance(state, AdapterRefusal):
                        failed.append((pin, state))
                    elif state == QUEUED:
                        preparing.append(pin)
                    elif state == READY:
                        if pin.document_id not in prepared.knowledge_ids:
                            prepared.knowledge_ids.append(pin.document_id)
                        prepared.pins[pin.document_id] = pin
                else:
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

    def _prepare_stored_inline(self, pin: SourcePin) -> str | AdapterRefusal | None:
        """Inline content with a hash is embedded once and kept in the index like a knowledge source.

        READY when stored (searched by id), None when it has no text, QUEUED while the warmer embeds a large one, or a
        refusal. Small content (a lesson) is embedded right here so the first question about it does not wait.
        """
        model = self.provider.embedding_model
        content_hash = pin.content_hash or ""
        if self.index.has_current(pin.document_id, content_hash, model):
            return READY
        chunks = chunk_sections(inline_sections(pin), pin.document_id, pin.document_version)
        if not chunks:
            return None
        if len(chunks) <= self.settings.inline_sync_chunks:
            try:
                embeddings = self.provider.embed([c.content for c in chunks])
            except ProviderError:
                log.info("inline source %s queued after a failed direct embed", pin.document_id)
            else:
                self.index.add_chunks(
                    pin.document_id, pin.document_version, content_hash, model, len(chunks), chunks, embeddings,
                    title=pin.title,
                )
                return READY
        return self.warmer.request(pin)

    def _prepare_inline(self, pin: SourcePin, prepared: PreparedSources) -> None:
        chunks = chunk_sections(inline_sections(pin), pin.document_id, pin.document_version)
        if not chunks:
            return
        prepared.inline_chunks.extend(chunks)
        prepared.inline_embeddings.extend(self.provider.embed([c.content for c in chunks]))
        prepared.pins[pin.document_id] = pin
