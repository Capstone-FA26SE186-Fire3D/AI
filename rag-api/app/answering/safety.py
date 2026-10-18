"""Rule-based safety gate (accent-insensitive phrase matching)."""
from __future__ import annotations

import re
import unicodedata

SAFETY_RULES_VERSION = "1"

CERTIFICATION_PHRASES = (
    "xac nhan dat chuan", "co dat quy chuan", "cap chung nhan dat", "cap chung nhan cho",
    "certify that", "certify this", "certify the", "certify my", "certify our", "certify compliance",
    "is compliant", "approve the design",
)
FINAL_EQUIPMENT_PHRASES = (
    "so luong binh chua chay chinh xac", "bo tri cuoi cung", "final number of",
)
REAL_INCIDENT_PHRASES = (
    "dang chay that", "dang co chay", "chay ngay bay gio",
    "there is a fire now", "real emergency",
)
OUTPUT_PHRASES = (
    "dat chuan pccc", "tuan thu day du", "is compliant", "certified",
)

_REQUEST_RULES = (
    ("chứng nhận hoặc xác nhận tuân thủ", CERTIFICATION_PHRASES),
    ("số lượng hoặc vị trí thiết bị cuối cùng", FINAL_EQUIPMENT_PHRASES),
    ("sự cố cháy thật đang xảy ra", REAL_INCIDENT_PHRASES),
)


def normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text.lower())
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    stripped = stripped.replace("đ", "d")
    return re.sub(r"\s+", " ", stripped).strip()


def _contains(norm: str, phrases: tuple[str, ...]) -> bool:
    return any(re.search(rf"(?<!\w){re.escape(p)}(?!\w)", norm) for p in phrases)


def check_request(text: str) -> str | None:
    norm = normalize(text)
    for category, phrases in _REQUEST_RULES:
        if _contains(norm, phrases):
            return f"Yêu cầu thuộc nhóm bị chặn: {category}. Hệ thống chỉ cung cấp thông tin tham khảo."
    return None


def check_output(text: str) -> str | None:
    if _contains(normalize(text), OUTPUT_PHRASES):
        return "Nội dung trả lời chứa kết luận chứng nhận hoặc tuân thủ, không được phép."
    return None
