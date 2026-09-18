from pydantic import BaseModel, Field

class SourceChunk(BaseModel):
    document_name: str
    chunk_index: int
    content: str
    source_id: str | None = None
    version: str | None = None
class ChatRequest(BaseModel): question: str = Field(min_length=1, max_length=4000); top_k: int = Field(default=4, ge=1, le=10)
class ChatResponse(BaseModel): answer: str; sources: list[SourceChunk]
class DocumentIngestResponse(BaseModel): document_name: str; chunks_indexed: int
