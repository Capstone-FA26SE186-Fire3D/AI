from dataclasses import dataclass
from typing import Protocol


@dataclass
class LlmUsage:
    input_tokens: int
    output_tokens: int
    model_version: str


class ProviderError(RuntimeError):
    pass


class RateLimited(ProviderError):
    """The provider refused for quota (HTTP 429); retry_after is its requested wait in seconds, when given."""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class Provider(Protocol):
    name: str
    embedding_model: str

    def generate(self, system: str, payload: dict, schema: dict, max_output_tokens: int) -> tuple[dict, LlmUsage]: ...

    def embed(self, texts: list[str]) -> list[list[float]]: ...
