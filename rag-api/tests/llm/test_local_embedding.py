import os

import numpy as np
import pytest

from app.core.config import Settings
from app.llm.base import ProviderError, embed_query
from app.llm.compat_provider import SplitProvider
from app.llm.factory import get_provider
from app.llm.fake import FakeProvider
from app.llm.local_embedding import EMBEDDING_MODEL, LocalEmbeddingProvider


class StubModel:
    def __init__(self):
        self.seen = []

    def embed(self, texts, batch_size):
        self.seen.append((list(texts), batch_size))
        return [np.array([float(len(t)), 1.0]) for t in texts]


def provider_with_stub():
    model = StubModel()
    loads = []

    def loader(cache_dir, threads):
        loads.append((cache_dir, threads))
        return model

    return LocalEmbeddingProvider("/models", 2, loader=loader), model, loads


def test_passage_and_query_prefixes_and_lazy_single_load():
    p, model, loads = provider_with_stub()
    assert loads == []
    assert p.embed(["a", "bc"]) == [[10.0, 1.0], [11.0, 1.0]]
    assert p.embed_query("xyz") == [10.0, 1.0]
    assert p.embed([]) == []
    assert model.seen[0] == (["passage: a", "passage: bc"], 4)
    assert model.seen[1][0] == ["query: xyz"]
    assert loads == [("/models", 2)]
    assert p.embedding_model == EMBEDDING_MODEL


def test_load_and_run_failures_are_provider_errors():
    def broken(cache_dir, threads):
        raise OSError("no disk")

    with pytest.raises(ProviderError):
        LocalEmbeddingProvider("/m", loader=broken).embed(["x"])

    class Boom:
        def embed(self, texts, batch_size):
            raise RuntimeError("onnx")

    with pytest.raises(ProviderError):
        LocalEmbeddingProvider("/m", loader=lambda *a: Boom()).embed(["x"])
    with pytest.raises(ProviderError):
        LocalEmbeddingProvider("/m", loader=lambda *a: Boom()).generate("s", {}, {}, 1)


def test_embed_query_helper_falls_back_to_embed():
    fake = FakeProvider()
    assert embed_query(fake, "lối thoát") == fake.embed(["lối thoát"])[0]
    p, model, _ = provider_with_stub()
    split = SplitProvider(FakeProvider(), p)
    assert embed_query(split, "q") == [8.0, 1.0] and model.seen[-1][0] == ["query: q"]


def test_factory_local_embedder_with_and_without_gateway():
    local = get_provider(Settings(llm_provider="fake", embed_provider="local", _env_file=None))
    assert isinstance(local, SplitProvider) and local.embedding_model == EMBEDDING_MODEL
    assert local.chat.name == "fake"
    both = get_provider(Settings(
        llm_provider="fake", embed_provider="local", chat_provider="openai_compat",
        chat_base_url="https://gw.example/v1", chat_api_key="k", chat_model="m", _env_file=None,
    ))
    assert both.name == "openai_compat+local" and both.embedding_model == EMBEDDING_MODEL
    assert get_provider(Settings(llm_provider="fake", _env_file=None)).embedding_model == "fake-embed-64"
    with pytest.raises(ProviderError, match="unknown embed provider"):
        get_provider(Settings(llm_provider="fake", embed_provider="other", _env_file=None))


@pytest.mark.skipif(not os.environ.get("FIRE3D_AI_TEST_LOCAL_MODEL_DIR"), reason="set FIRE3D_AI_TEST_LOCAL_MODEL_DIR to run the real model")
def test_real_model_ranks_the_evacuation_passage_first():
    p = LocalEmbeddingProvider(os.environ["FIRE3D_AI_TEST_LOCAL_MODEL_DIR"])
    docs = p.embed([
        "Bình chữa cháy CO2 dùng cho đám cháy loại B và thiết bị điện.",
        "Khi nghe chuông báo cháy, đi theo biển chỉ dẫn lối thoát nạn, không dùng thang máy.",
        "Học viên cần hoàn thành bài kiểm tra cuối khóa.",
    ])
    q = np.array(p.embed_query("có cháy thì thoát hiểm thế nào"))
    assert len(q) == 384
    assert int(np.argmax(np.array(docs) @ q)) == 1
