import json
import logging
from datetime import datetime, timezone


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key in ("request_id", "duration_ms"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    handler = next((h for h in root.handlers if getattr(h, "_fire3d_json", False)), None)
    if handler is None:
        handler = logging.StreamHandler()
        handler._fire3d_json = True  # type: ignore[attr-defined]
        root.addHandler(handler)
    handler.setFormatter(JsonFormatter())
    root.setLevel(level.upper())
