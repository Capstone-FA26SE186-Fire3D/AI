from app.rag.store import VectorStore


class FakeCollection:
    def __init__(self) -> None:
        self.upserts: list[dict] = []
        self.query_calls: list[dict] = []

    def count(self) -> int:
        return 1

    def upsert(self, **kwargs: object) -> None:
        self.upserts.append(kwargs)

    def query(self, **kwargs: object) -> dict:
        self.query_calls.append(kwargs)
        return {
            "documents": [["Đoạn quy chuẩn"]],
            "metadatas": [[{"document_name": "qcvn.pdf", "chunk_index": 0, "version": "2023"}]],
        }


def make_store() -> VectorStore:
    store = VectorStore.__new__(VectorStore)
    store.collection = FakeCollection()
    return store


def test_search_approved_uses_an_approved_where_filter() -> None:
    store = make_store()

    sources = store.search_approved("lối thoát", top_k=3, jurisdiction="VN")

    assert store.collection.query_calls[-1]["where"] == {
        "$and": [{"approved": True}, {"jurisdiction": "VN"}]
    }
    assert sources[0].source_id == "qcvn.pdf:0"


def test_upsert_knowledge_persists_version_and_approval() -> None:
    store = make_store()

    store.upsert_knowledge(
        "qcvn.pdf",
        ["đoạn 1"],
        {"approved": True, "jurisdiction": "VN", "version": "2023", "source_name": "BXD"},
    )

    assert store.collection.upserts[0]["metadatas"][0]["approved"] is True
    assert store.collection.upserts[0]["metadatas"][0]["version"] == "2023"
