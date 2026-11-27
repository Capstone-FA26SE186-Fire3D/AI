import json
import logging

from app.core.logging import JsonFormatter, configure_logging


def test_json_formatter_preserves_correlation_and_unicode():
    record = logging.LogRecord("ai", logging.INFO, __file__, 1, "cửa thoát %s", ("A",), None)
    record.request_id = "req-1"
    record.duration_ms = 12
    payload = json.loads(JsonFormatter().format(record))
    assert payload["logger"] == "ai"
    assert payload["msg"] == "cửa thoát A"
    assert payload["request_id"] == "req-1"
    assert payload["duration_ms"] == 12


def test_configure_logging_reuses_owned_handler_and_restores_root_state():
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    try:
        configure_logging("WARNING")
        configure_logging("ERROR")
        owned = [handler for handler in root.handlers if getattr(handler, "_fire3d_json", False)]
        assert len(owned) == 1
        assert root.level == logging.ERROR
    finally:
        for handler in root.handlers:
            if handler not in handlers:
                root.removeHandler(handler)
                handler.close()
        root.setLevel(level)
