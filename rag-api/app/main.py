from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import get_settings
from app.rag.chunker import chunk_text
from app.rag.loaders import extract_text
from app.rag.openai_client import answer_question
from app.rag.store import VectorStore
from app.schemas.rag import ChatRequest, ChatResponse, DocumentIngestResponse

app = FastAPI(title="Local RAG API")
app.add_middleware(CORSMiddleware, allow_origins=get_settings().origins, allow_methods=["GET", "POST"], allow_headers=["*"], allow_credentials=False)
store = VectorStore()

@app.get("/health")
def health() -> dict[str, str]: return {"status": "ok"}

@app.post("/documents", response_model=DocumentIngestResponse, status_code=201)
async def ingest_document(file: UploadFile = File(...)) -> DocumentIngestResponse:
    try:
        chunks = chunk_text(extract_text(file.filename or "upload", await file.read()))
        store.upsert(file.filename or "upload", chunks)
        return DocumentIngestResponse(document_name=file.filename or "upload", chunks_indexed=len(chunks))
    except ValueError as error: raise HTTPException(status_code=400, detail=str(error)) from error

@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    sources = store.search(request.question, request.top_k)
    if not sources: raise HTTPException(status_code=400, detail="Upload a document before asking questions.")
    try: return ChatResponse(answer=answer_question(request.question, sources), sources=sources)
    except RuntimeError as error: raise HTTPException(status_code=503, detail=str(error)) from error
