"""Readable sections for a Training snapshot or a Session result: one section per rubric criterion and per metric.

The BE sends criteria as JSON (Training: label/description/metric only; Result: id, metric, value, operator, threshold,
mandatory, weight, passed, reason, plus label/description when it has them). Rendering each criterion as its own
Vietnamese sentence lets the model walk through them one by one and cite each, instead of reading one JSON blob.
"""
from __future__ import annotations

import json

# Same wording as the apps (mobile result-presentation.ts, web metric-labels.ts).
METRIC_LABELS: dict[str, str] = {
    "reached_exit": "Đến được lối thoát",
    "completion_time_seconds": "Thời gian thoát hiểm (giây)",
    "wrong_exits": "Số lần đi nhầm lối",
    "hazard_exposure": "Mức tiếp xúc nguy hiểm (khói, nhiệt, lửa)",
    "distance_meters": "Quãng đường di chuyển (mét)",
    "alarm_raised": "Kéo chuông báo cháy",
    "extinguisher_used": "Dùng bình chữa cháy",
    "extinguish_attempt_large_fire": "Cố dập đám cháy lớn",
    "item_wetted": "Làm ướt khăn che mặt",
    "nose_covered_in_smoke": "Che mũi miệng khi có khói",
    "checked_door_heat": "Kiểm tra nhiệt cửa trước khi mở",
    "closed_door": "Đóng cửa sau khi đi qua",
    "used_elevator": "Dùng thang máy",
    "went_back_for_belongings": "Quay lại lấy đồ",
    "npc_guided": "Hướng dẫn người khác thoát",
}

_OPERATORS = {"gte": "≥", "lte": "≤", "eq": "="}
_SNAPSHOT_KINDS = ("TrainingSnapshot", "SessionResult")


def metric_label(metric: object) -> str:
    if isinstance(metric, str):
        return METRIC_LABELS.get(metric, metric)
    return "Chỉ số"


def _num(value: object) -> str:
    if isinstance(value, bool):
        return "có" if value else "không"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, (int, float)):
        return f"{value:.2f}".rstrip("0").rstrip(".")
    return json.dumps(value, ensure_ascii=False)


def criterion_text(index: int, c: dict) -> str:
    """One criterion as a sentence; only the fields present are mentioned (Training has no threshold or result)."""
    name = c.get("label") if isinstance(c.get("label"), str) and c["label"].strip() else metric_label(c.get("metric"))
    parts = [f"Tiêu chí {index}: {name}"]
    if isinstance(c.get("description"), str) and c["description"].strip():
        parts.append(f"mô tả: {c['description'].strip()}")
    if isinstance(c.get("metric"), str):
        parts.append(f"đo bằng: {metric_label(c['metric'])} ({c['metric']})")
    if c.get("mandatory") is True:
        parts.append("bắt buộc")
    if "threshold" in c and c.get("operator") in _OPERATORS:
        parts.append(f"yêu cầu: {_OPERATORS[c['operator']]} {_num(c['threshold'])}")
    if c.get("reason") == "METRIC_UNAVAILABLE":
        parts.append("kết quả: chưa đủ dữ liệu để đánh giá (tính là chưa đạt)")
    elif "passed" in c:
        value = f", giá trị đạt được {_num(c['value'])}" if c.get("value") is not None else ""
        parts.append(f"kết quả: {'ĐẠT' if c['passed'] else 'CHƯA ĐẠT'}{value}")
    return "; ".join(parts) + "."


def snapshot_sections(content: dict) -> list[tuple[str, dict]]:
    """(text, locator) sections of a TrainingSnapshot / SessionResult."""
    sections: list[tuple[str, dict]] = []
    for key, val in content.items():
        if val is None:
            continue
        if key == "criteria" and isinstance(val, list):
            for i, c in enumerate(val):
                if isinstance(c, dict):
                    locator = {"field": "criteria", "criterion": c.get("id") or i + 1}
                    sections.append((criterion_text(i + 1, c), locator))
            continue
        if key == "metrics" and isinstance(val, dict):
            for name, value in val.items():
                if value is not None:
                    sections.append((f"Chỉ số đã đo: {metric_label(name)} ({name}) = {_num(value)}.", {"field": "metrics", "metric": name}))
            continue
        text = val if isinstance(val, str) else json.dumps(val, ensure_ascii=False, sort_keys=True)
        if text.strip():
            sections.append((f"{key}: {text}", {"field": key}))
    return sections


def is_context_snapshot(kind: str) -> bool:
    return kind in _SNAPSHOT_KINDS
