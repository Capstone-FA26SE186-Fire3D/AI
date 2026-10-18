"""Token estimation and quota-unit accounting."""
from __future__ import annotations

import math

from app.llm.base import LlmUsage
from app.v2.errors import refuse
from app.v2.schemas import Limits, Usage

_HUGE = 10**12


def estimate_tokens(text: str) -> int:
    return math.ceil(len(text) / 4)


def context_budget(limits: Limits, max_output_tokens: int) -> int | None:
    if limits.quota_unit == "tokens":
        budget = limits.max_units - max_output_tokens
        return budget if budget > 200 else None
    if limits.quota_unit == "requests":
        return _HUGE
    raise refuse("AI_QUOTA_UNIT_UNSUPPORTED", f"Quota unit {limits.quota_unit} is not supported")


def to_usage(llm: LlmUsage | None, limits: Limits) -> Usage:
    if limits.quota_unit not in ("tokens", "requests"):
        raise refuse("AI_QUOTA_UNIT_UNSUPPORTED", f"Quota unit {limits.quota_unit} is not supported")
    if llm is None:
        return Usage(provider_units=0, input_tokens=0, output_tokens=0, model_version="none")
    units = llm.input_tokens + llm.output_tokens if limits.quota_unit == "tokens" else 1
    return Usage(
        provider_units=units, input_tokens=llm.input_tokens, output_tokens=llm.output_tokens,
        model_version=llm.model_version,
    )
