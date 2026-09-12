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
