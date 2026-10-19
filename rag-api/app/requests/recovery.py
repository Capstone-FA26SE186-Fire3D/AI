"""Background loop that reconciles stale requests (runs once at start, then every interval)."""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Callable, Union

from app.requests.service import RequestService

log = logging.getLogger(__name__)

ServiceSource = Union[RequestService, Callable[[], RequestService]]


class RecoveryLoop:
    """Daemon thread calling `service.recover_once(now)`.

    `service` may be a RequestService or a zero-arg callable returning one (a lazily built
    default service); a failing callable just skips that tick. The stale threshold comes from
    the service's settings (`request_stale_seconds`).
    """

    def __init__(self, service: ServiceSource, interval_seconds: float) -> None:
        self._service = service
        self.interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _resolve(self) -> RequestService:
        if isinstance(self._service, RequestService):
            return self._service
        return self._service()

    def tick(self) -> int:
        try:
            return self._resolve().recover_once(datetime.now(timezone.utc))
        except Exception:
            log.exception("recovery tick failed")
            return 0

    def _run(self) -> None:
        while not self._stop.is_set():
            self.tick()
            self._stop.wait(self.interval_seconds)

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="ai-request-recovery", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)
            self._thread = None
