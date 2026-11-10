"""General (ungrounded) answers for everyday questions the approved sources do not cover.

Used only after a KnowledgeAnswer ends InsufficientEvidence for lack of a fitting source (never after the safety gate,
a budget refusal or for ScenarioDraft). The model may greet, explain how to use the assistant and give general,
common-knowledge fire-safety guidance; anything else is declined as off-topic. The result stays InsufficientEvidence
(the BE accepts an Answered result only with citations) with a limitation saying it is not based on approved sources,
and the output safety check still applies.
"""
from __future__ import annotations

import json

from app.answering.safety import check_output
from app.answering.usage import estimate_tokens
from app.answering.validate import to_plain_text
from app.llm.base import LlmUsage
from app.v2.schemas import AdapterRequest

GENERAL_NOTE = "Câu trả lời chung, không dựa trên tài liệu đã duyệt của hệ thống; hãy đối chiếu với tài liệu chính thức."
OFF_TOPIC = (
    "Mình là trợ lý của FET3D, chỉ hỗ trợ các câu hỏi về phòng cháy chữa cháy, thoát nạn, thiết bị PCCC "
    "và cách dùng nền tảng huấn luyện. Bạn thử hỏi về những chủ đề đó nhé."
)

GENERAL_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["answered", "off_topic"]},
        "answer": {"type": "string"},
    },
    "required": ["status", "answer"],
    "additionalProperties": False,
}

GENERAL_PROMPT = (
    "Bạn là trợ lý của FET3D, nền tảng huấn luyện phòng cháy chữa cháy (PCCC) và thoát nạn trong toà nhà bằng mô phỏng 3D. "
    "Câu hỏi này không có tài liệu đã duyệt phù hợp, nên bạn chỉ được trả lời ở mức thông thường. "
    "ĐƯỢC trả lời (status answered): chào hỏi và giới thiệu ngắn về bản thân; cách dùng trợ lý và nền tảng FET3D ở mức chung; "
    "kiến thức PCCC phổ thông (phòng ngừa cháy, cách thoát nạn, dùng bình chữa cháy, ý nghĩa biển báo, kỹ năng khi có khói). "
    "KHÔNG được: trích dẫn hay nêu số liệu, điều khoản cụ thể của quy chuẩn, tiêu chuẩn, luật (TCVN, QCVN, NFPA, nghị định); "
    "chứng nhận, xác nhận đạt chuẩn hay tuân thủ; đưa số lượng hoặc vị trí thiết bị cụ thể cho một công trình; "
    "bịa thông tin về tổ chức, công trình hay tài khoản của người hỏi. "
    "Nếu câu hỏi không thuộc các chủ đề trên (ví dụ lập trình, bài tập, chính trị, giải trí, y tế, tài chính) "
    "thì đặt status off_topic và để answer rỗng. "
    "Nếu người hỏi đang gặp cháy thật, khuyên gọi ngay 114 và thoát ra nơi an toàn. "
    "Trả lời ngắn gọn bằng tiếng Việt, văn bản thuần, không Markdown; nhắc rằng đây là thông tin tham khảo chung khi phù hợp. "
    "Chỉ trả về JSON đúng theo schema đã cho."
)


def general_answer(
    req: AdapterRequest, provider, settings, used: LlmUsage | None, on_usage=None,
) -> tuple[str, str, LlmUsage] | None:
    """(kind, text, total usage) with kind "answered" or "off_topic"; None when it cannot or should not answer."""
    payload = {"question": req.input.text}
    if req.context:
        payload["context"] = req.context
    max_out = settings.max_output_tokens
    if req.limits.quota_unit == "tokens":
        spent = (used.input_tokens + used.output_tokens) if used else 0
        est_in = estimate_tokens(GENERAL_PROMPT + json.dumps(payload, ensure_ascii=False))
        max_out = min(max_out, req.limits.max_units - spent - est_in)
        if max_out < 1:
            return None
    raw, llm = provider.generate(GENERAL_PROMPT, payload, GENERAL_SCHEMA, max_out)
    if on_usage is not None:
        on_usage(llm)
    total = llm if used is None else LlmUsage(
        used.input_tokens + llm.input_tokens, used.output_tokens + llm.output_tokens, llm.model_version
    )
    if not isinstance(raw, dict) or raw.get("status") not in ("answered", "off_topic"):
        return None
    if raw["status"] == "off_topic":
        return "off_topic", OFF_TOPIC, total
    text = to_plain_text(raw.get("answer"), 4000)
    if not text or check_output(text):
        return None
    return "answered", text, total
