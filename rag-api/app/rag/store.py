import chromadb
from app.core.config import get_settings
from app.schemas.rag import SourceChunk

class VectorStore:
    def __init__(self):
        settings = get_settings(); self.client = chromadb.PersistentClient(path=settings.chroma_path); self.collection = self.client.get_or_create_collection("documents")
    def upsert(self, document_name: str, chunks: list[str]) -> None:
        ids = [f"{document_name}:{index}" for index in range(len(chunks))]
        self.collection.upsert(ids=ids, documents=chunks, metadatas=[{"document_name": document_name, "chunk_index": index} for index in range(len(chunks))])
    def search(self, question: str, top_k: int) -> list[SourceChunk]:
        result = self.collection.query(query_texts=[question], n_results=min(top_k, max(self.collection.count(), 1)))
        return [SourceChunk(document_name=m["document_name"], chunk_index=m["chunk_index"], content=d) for d, m in zip(result["documents"][0], result["metadatas"][0])]

    def upsert_knowledge(self, document_name: str, chunks: list[str], metadata: dict[str, object]) -> None:
        if metadata.get("approved") is not True:
            raise ValueError("PCCC knowledge documents must be approved before indexing")
        required = ("jurisdiction", "version", "source_name")
        if any(not isinstance(metadata.get(key), str) or not metadata[key] for key in required):
            raise ValueError("Knowledge metadata requires jurisdiction, version and source_name")
        ids = [f"{document_name}:{index}" for index in range(len(chunks))]
        metadatas = [
            {"document_name": document_name, "chunk_index": index, **metadata}
            for index in range(len(chunks))
        ]
        self.collection.upsert(ids=ids, documents=chunks, metadatas=metadatas)

    def search_approved(self, question: str, top_k: int, jurisdiction: str) -> list[SourceChunk]:
        if self.collection.count() == 0:
            return []
        result = self.collection.query(
            query_texts=[question],
            n_results=min(top_k, self.collection.count()),
            where={"$and": [{"approved": True}, {"jurisdiction": jurisdiction}]},
        )
        documents = result.get("documents", [[]])[0] or []
        metadatas = result.get("metadatas", [[]])[0] or []
        return [
            SourceChunk(
                document_name=metadata["document_name"],
                chunk_index=metadata["chunk_index"],
                content=document,
                source_id=f"{metadata['document_name']}:{metadata['chunk_index']}",
            )
            for document, metadata in zip(documents, metadatas)
        ]
