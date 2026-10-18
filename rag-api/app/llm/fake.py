import hashlib
import json
import math
import re
from typing import Callable

from app.llm.base import LlmUsage, ProviderError

DEFAULT_RESPONSE = {"status": "insufficient", "answer": "", "citations": [], "assumptions": [], "limitations": []}


class FakeProvider:
    name = "fake"

    def __init__(self, responder: Callable[[dict], dict] | list[dict] | None = None, embedding_dim: int = 64):
        self.responder = responder
        self.embedding_dim = embedding_dim
        self.embedding_model = f"fake-embed-{embedding_dim}"
        self.calls: list[dict] = []

    def generate(self, system: str, payload: dict, schema: dict, max_output_tokens: int) -> tuple[dict, LlmUsage]:
        self.calls.append(payload)
        if callable(self.responder):
            result = self.responder(payload)
        elif isinstance(self.responder, list):
            if not self.responder:
                raise ProviderError("fake responses exhausted")
            result = self.responder.pop(0)
        else:
            result = dict(DEFAULT_RESPONSE)
        tokens_in = math.ceil(len(json.dumps(payload, ensure_ascii=False)) / 4)
        tokens_out = math.ceil(len(json.dumps(result, ensure_ascii=False)) / 4)
        return result, LlmUsage(tokens_in, tokens_out, "fake-1")

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vec = [0.0] * self.embedding_dim
        for token in re.findall(r"\w+", text.lower()):
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            vec[int.from_bytes(digest, "big") % self.embedding_dim] += 1.0
        norm = math.sqrt(sum(v * v for v in vec))
        return [v / norm for v in vec] if norm else vec
