"""Turn BE-pinned sources into searchable chunks (indexed or inline)."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from urllib.parse import unquote, urlsplit

import httpx

from app.core.config import Settings
from app.index.base import KnowledgeIndex
from app.llm.base import Provider
from app.sources.chunking import Chunk, chunk_sections
from app.sources.fetch import fetch_document
from app.sources.render import document_sections, inline_sections
from app.v2.errors import refuse
from app.v2.schemas import SourcePin


@dataclass
class PreparedSources:
    knowledge_ids: list[str] = field(default_factory=list)
    inline_chunks: list[Chunk] = field(default_factory=list)
    inline_embeddings: list[list[float]] = field(default_factory=list)
    pins: dict[str, SourcePin] = field(default_factory=dict)
    limitations: list[str] = field(default_factory=list)


def _filename(uri: str) -> str:
    return unquote(urlsplit(uri).path.rsplit("/", 1)[-1])


class SourceResolver:
    def __init__(
        self,
        index: KnowledgeIndex,
        provider: Provider,
        settings: Settings,
        http: httpx.Client | None = None,
    ) -> None:
        self.index = index
        self.provider = provider
        self.settings = settings
        self.http = http
        self.clock = time.monotonic

    def prepare(self, pins: list[SourcePin]) -> PreparedSources:
        prepared = PreparedSources()
        # Overall cap on source fetching so one request cannot hold BE's call past its timeout.
        deadline = self.clock() + self.settings.source_total_deadline_seconds
        for pin in pins:
            if pin.content_omitted:
                prepared.limitations.append(f"Nguồn {pin.title or pin.document_id} quá lớn, không được dùng.")
                continue
            if pin.kind == "KnowledgeSource":
                self._prepare_knowledge(pin, prepared, deadline)
            else:
                self._prepare_inline(pin, prepared)
        return prepared

    def _prepare_knowledge(self, pin: SourcePin, prepared: PreparedSources, deadline: float) -> None:
        if not pin.content_hash:
            raise refuse("AI_SOURCE_UNAVAILABLE", f"Source {pin.document_id} has no content hash to verify")
        model = self.provider.embedding_model
        if not self.index.has_current(pin.document_id, pin.content_hash, model):
            if not pin.source_uri:
                raise refuse("AI_SOURCE_UNAVAILABLE", f"Source {pin.document_id} has no source_uri")
            if self.clock() >= deadline:
                raise refuse("AI_SOURCE_UNAVAILABLE", "Source fetching exceeded the total time limit")
            data, content_type = fetch_document(
                pin.source_uri,
                pin.content_hash,
                max_bytes=self.settings.source_max_bytes,
                timeout=self.settings.source_fetch_timeout_seconds,
                client=self.http,
            )
            sections = document_sections(data, content_type, _filename(pin.source_uri))
            chunks = chunk_sections(sections, pin.document_id, pin.document_version)
            embeddings = self.provider.embed([c.content for c in chunks]) if chunks else []
            self.index.replace(pin.document_id, pin.document_version, pin.content_hash, model, chunks, embeddings)
        if pin.document_id not in prepared.knowledge_ids:
            prepared.knowledge_ids.append(pin.document_id)
        prepared.pins[pin.document_id] = pin

    def _prepare_inline(self, pin: SourcePin, prepared: PreparedSources) -> None:
        chunks = chunk_sections(inline_sections(pin), pin.document_id, pin.document_version)
        if not chunks:
            return
        prepared.inline_chunks.extend(chunks)
        prepared.inline_embeddings.extend(self.provider.embed([c.content for c in chunks]))
        prepared.pins[pin.document_id] = pin
