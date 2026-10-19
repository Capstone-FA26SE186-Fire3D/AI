from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from app.core.config import get_settings
from app.rag.chunker import chunk_text
from app.rag.loaders import extract_text
from app.rag.openai_client import answer_question
from app.rag.store import VectorStore
from app.schemas.rag import ChatRequest, ChatResponse, DocumentIngestResponse
from app.bim.normalizer import inspect_bim_upload
from app.pccc.advisory import OpenAIAdvisoryModel, create_pccc_advisory
from app.schemas.pccc import BimInspectionResponse, PcccAnalysisRequest, PcccAnalysisResponse

router = APIRouter()
_store: VectorStore | None = None


def get_store() -> VectorStore:
    global _store
    if _store is None:
        _store = VectorStore()
    return _store


@router.post("/documents", response_model=DocumentIngestResponse, status_code=201)
async def ingest_document(file: UploadFile = File(...)) -> DocumentIngestResponse:
    try:
        chunks = chunk_text(extract_text(file.filename or "upload", await file.read()))
        get_store().upsert(file.filename or "upload", chunks)
        return DocumentIngestResponse(document_name=file.filename or "upload", chunks_indexed=len(chunks))
    except ValueError as error: raise HTTPException(status_code=400, detail=str(error)) from error

@router.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    sources = get_store().search(request.question, request.top_k)
    if not sources: raise HTTPException(status_code=400, detail="Upload a document before asking questions.")
    try: return ChatResponse(answer=answer_question(request.question, sources), sources=sources)
    except RuntimeError as error: raise HTTPException(status_code=503, detail=str(error)) from error


@router.post("/pccc/knowledge-documents", response_model=DocumentIngestResponse, status_code=201)
async def ingest_pccc_knowledge_document(
    file: UploadFile = File(...),
    approved: bool = Form(...),
    jurisdiction: str = Form("VN"),
    version: str = Form(...),
    source_name: str = Form(...),
) -> DocumentIngestResponse:
    if not approved:
        raise HTTPException(status_code=400, detail="PCCC knowledge must be approved before indexing.")
    try:
        chunks = chunk_text(extract_text(file.filename or "upload", await file.read()))
        get_store().upsert_knowledge(
            file.filename or "upload",
            chunks,
            {"approved": True, "jurisdiction": jurisdiction, "version": version, "source_name": source_name},
        )
        return DocumentIngestResponse(document_name=file.filename or "upload", chunks_indexed=len(chunks))
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/pccc/bim/inspect", response_model=BimInspectionResponse)
async def inspect_bim(file: UploadFile = File(...)) -> BimInspectionResponse:
    try:
        settings = get_settings()
        content = await file.read(settings.max_bim_upload_bytes + 1)
        return inspect_bim_upload(file.filename or "upload", content, settings.max_bim_upload_bytes)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/pccc/analyses", response_model=PcccAnalysisResponse)
def analyse_pccc(request: PcccAnalysisRequest) -> PcccAnalysisResponse:
    sources = get_store().search_approved(request.question, top_k=4, jurisdiction=request.building.jurisdiction)
    try:
        return create_pccc_advisory(request, sources, OpenAIAdvisoryModel())
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
