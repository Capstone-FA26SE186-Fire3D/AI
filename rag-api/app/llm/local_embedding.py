"""Embeddings computed on this machine (ONNX via fastembed): no provider quota, no data sent out.

The model is multilingual-e5-small, int8-quantized (about 130 MB on disk, about 0.5 GB of RAM in use). It reads up
to 512 tokens, so a 900-character chunk is embedded whole. e5 expects "query: " before a question and "passage: "
before a document chunk; embed() is for chunks and embed_query() for the question.
"""
from __future__ import annotations

import threading
from pathlib import Path

from app.llm.base import LlmUsage, ProviderError

MODEL = "intfloat/multilingual-e5-small"
_SOURCE = "Xenova/multilingual-e5-small"
_FILE = "onnx/model_quantized.onnx"
# Stored with every vector: rows embedded by another model are never compared with these.
EMBEDDING_MODEL = "local:multilingual-e5-small-q8"
_registered = False
_register_lock = threading.Lock()


def _register() -> None:
    global _registered
    with _register_lock:
        if _registered:
            return
        from fastembed import TextEmbedding
        from fastembed.common.model_description import ModelSource, PoolingType

        if not any(m["model"] == MODEL for m in TextEmbedding.list_supported_models()):
            TextEmbedding.add_custom_model(
                model=MODEL, pooling=PoolingType.MEAN, normalization=True,
                sources=ModelSource(hf=_SOURCE), dim=384, model_file=_FILE,
            )
        _registered = True


def load_model(cache_dir: str, threads: int | None = None):
    """Loads the model, downloading it into cache_dir the first time (setup does that ahead of the service)."""
    _register()
    from fastembed import TextEmbedding

    Path(cache_dir).mkdir(parents=True, exist_ok=True)
    return TextEmbedding(MODEL, cache_dir=cache_dir, threads=threads)


class LocalEmbeddingProvider:
    name = "local"
    embedding_model = EMBEDDING_MODEL

    def __init__(self, cache_dir: str, threads: int | None = None, batch_size: int = 4, loader=load_model):
        self.cache_dir = cache_dir
        self.threads = threads
        self.batch_size = max(1, batch_size)
        self._loader = loader
        self._model = None
        self._lock = threading.Lock()

    def _get(self):
        if self._model is None:
            with self._lock:
                if self._model is None:
                    try:
                        self._model = self._loader(self.cache_dir, self.threads)
                    except Exception as exc:
                        raise ProviderError(f"local embedding model unavailable: {type(exc).__name__}") from exc
        return self._model

    def _run(self, texts: list[str]) -> list[list[float]]:
        model = self._get()
        try:
            with self._lock:  # one ONNX session; serialising keeps memory flat on a small machine
                return [vec.tolist() for vec in model.embed(texts, batch_size=self.batch_size)]
        except Exception as exc:
            raise ProviderError(f"local embedding failed: {type(exc).__name__}") from exc

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self._run([f"passage: {t}" for t in texts]) if texts else []

    def embed_query(self, text: str) -> list[float]:
        return self._run([f"query: {text}"])[0]

    def generate(self, system: str, payload: dict, schema: dict, max_output_tokens: int) -> tuple[dict, LlmUsage]:
        raise ProviderError("local embedding provider does not answer")
