"""Durable request table: dedupe BE requests by request_id."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from sqlalchemy import (
    CHAR,
    JSON,
    Column,
    DateTime,
    Engine,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    delete,
    insert,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError

POSTGRES_SCHEMA = "ai_service"

_JSON = JSON().with_variant(JSONB(), "postgresql")


@dataclass
class RequestRecord:
    request_id: str
    operation: str
    audience: str
    input_hash: str
    payload: dict
    status: Literal["Received", "Processing", "Completed"]
    attempts: int
    response: dict | None
    usage_total: dict | None
    processing_started_at: datetime | None
    created_at: datetime


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class RequestStore:
    def __init__(self, engine: Engine, schema: str | None = None) -> None:
        self._engine = engine
        self._metadata = MetaData(schema=schema)
        self._t = Table(
            "requests",
            self._metadata,
            Column("request_id", Text, primary_key=True),
            Column("operation", Text, nullable=False),
            Column("audience", Text, nullable=False),
            Column("input_hash", CHAR(64), nullable=False),
            Column("payload", _JSON, nullable=False),
            Column("status", String, nullable=False),
            Column("attempts", Integer, nullable=False, default=0),
            Column("response", _JSON),
            Column("usage_total", _JSON),
            Column("created_at", DateTime(timezone=True), nullable=False),
            Column("updated_at", DateTime(timezone=True), nullable=False),
            Column("processing_started_at", DateTime(timezone=True)),
            Column("completed_at", DateTime(timezone=True)),
            Index("ix_requests_status_started", "status", "processing_started_at"),
        )

    def create_tables(self) -> None:
        self._metadata.create_all(self._engine)

    def _record(self, row) -> RequestRecord:
        return RequestRecord(
            request_id=row.request_id,
            operation=row.operation,
            audience=row.audience,
            input_hash=row.input_hash,
            payload=row.payload,
            status=row.status,
            attempts=row.attempts,
            response=row.response,
            usage_total=row.usage_total,
            processing_started_at=_utc(row.processing_started_at),
            created_at=_utc(row.created_at),
        )

    def get(self, request_id: str) -> RequestRecord | None:
        with self._engine.connect() as conn:
            row = conn.execute(
                select(self._t).where(self._t.c.request_id == request_id)
            ).first()
        return self._record(row) if row else None

    def insert_received(
        self, request_id: str, operation: str, audience: str, input_hash: str, payload: dict
    ) -> bool:
        now = _now()
        try:
            with self._engine.begin() as conn:
                conn.execute(
                    insert(self._t).values(
                        request_id=request_id,
                        operation=operation,
                        audience=audience,
                        input_hash=input_hash,
                        payload=payload,
                        status="Received",
                        attempts=0,
                        created_at=now,
                        updated_at=now,
                    )
                )
        except IntegrityError:
            return False
        return True

    def mark_processing(self, request_id: str) -> bool:
        """Received -> Processing; False when the row is missing or not Received."""
        now = _now()
        with self._engine.begin() as conn:
            result = conn.execute(
                update(self._t)
                .where(self._t.c.request_id == request_id, self._t.c.status == "Received")
                .values(
                    status="Processing",
                    processing_started_at=now,
                    attempts=self._t.c.attempts + 1,
                    updated_at=now,
                )
            )
        return result.rowcount == 1

    def complete(self, request_id: str, response: dict, usage_total: dict) -> bool:
        """Processing -> Completed; False when someone else already completed (or the row is gone)."""
        now = _now()
        with self._engine.begin() as conn:
            result = conn.execute(
                update(self._t)
                .where(self._t.c.request_id == request_id, self._t.c.status == "Processing")
                .values(
                    status="Completed",
                    response=response,
                    usage_total=usage_total,
                    completed_at=now,
                    updated_at=now,
                )
            )
        return result.rowcount == 1

    def delete(self, request_id: str) -> None:
        with self._engine.begin() as conn:
            conn.execute(delete(self._t).where(self._t.c.request_id == request_id))

    def claim_stale(self, cutoff: datetime) -> RequestRecord | None:
        """Atomically take over one stale Processing row (compare-and-set)."""
        cutoff = _utc(cutoff)
        t = self._t
        with self._engine.connect() as conn:
            candidates = conn.execute(
                select(t.c.request_id, t.c.processing_started_at)
                .where(t.c.status == "Processing", t.c.processing_started_at < cutoff)
                .order_by(t.c.processing_started_at)
            ).all()
        for cand in candidates:
            now = _now()
            with self._engine.begin() as conn:
                result = conn.execute(
                    update(t)
                    .where(
                        t.c.request_id == cand.request_id,
                        t.c.status == "Processing",
                        t.c.processing_started_at == cand.processing_started_at,
                    )
                    .values(
                        processing_started_at=now,
                        attempts=t.c.attempts + 1,
                        updated_at=now,
                    )
                )
            if result.rowcount == 1:
                return self.get(cand.request_id)
        return None

    def purge_stale_received(self, cutoff: datetime) -> int:
        t = self._t
        with self._engine.begin() as conn:
            result = conn.execute(
                delete(t).where(t.c.status == "Received", t.c.created_at < _utc(cutoff))
            )
        return result.rowcount


def make_store(database_url: str) -> RequestStore:
    if database_url.startswith("sqlite"):
        store = RequestStore(create_engine(database_url), None)
        store.create_tables()
        return store
    if database_url.startswith(("postgresql://", "postgres://")):
        database_url = "postgresql+psycopg://" + database_url.split("://", 1)[1]
    return RequestStore(create_engine(database_url, pool_pre_ping=True), POSTGRES_SCHEMA)
