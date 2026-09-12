from openai import OpenAI
from app.core.config import get_settings
from app.schemas.rag import SourceChunk

def answer_question(question: str, sources: list[SourceChunk]) -> str:
    settings = get_settings()
    if not settings.openai_api_key: raise RuntimeError("OPENAI_API_KEY is not configured")
    context = "\n\n".join(f"[{s.document_name} #{s.chunk_index}] {s.content}" for s in sources)
    response = OpenAI(api_key=settings.openai_api_key).responses.create(model=settings.openai_chat_model, input=f"Answer only from this context. If insufficient, say so.\n\nContext:\n{context}\n\nQuestion: {question}")
    return response.output_text
