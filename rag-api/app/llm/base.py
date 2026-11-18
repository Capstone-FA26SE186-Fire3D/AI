from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Iterator, Protocol

# Per-call reasoning effort for chat gateways that support it (None: the provider's own setting). Set by the answering
# pipeline around one generate() call, so the Provider interface stays the same for every provider.
_reasoning_effort: ContextVar[str | None] = ContextVar("fire3d_reasoning_effort", default=None)


@contextmanager
def reasoning_effort(value: str | None) -> Iterator[None]:
    token = _reasoning_effort.set(value)
    try:
        yield
    finally:
        _reasoning_effort.reset(token)


def current_reasoning_effort() -> str | None:
    return _reasoning_effort.get()


def answer_reasoning(operation: str, settings: object) -> str | None:
    """CHAT_ANSWER_REASONING_EFFORT for answers; None (the provider's setting) for drafts or when it is unset."""
    if operation == "ScenarioDraft":
        return None
    return getattr(settings, "chat_answer_reasoning_effort", None)


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


def embed_query(provider: object, text: str) -> list[float]:
    """The question's vector: providers whose model wants a query form (e5's \"query: \") define embed_query."""
    query = getattr(provider, "embed_query", None)
    return query(text) if callable(query) else provider.embed([text])[0]
