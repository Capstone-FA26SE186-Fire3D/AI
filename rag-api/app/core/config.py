from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    openai_api_key: str = ""
    openai_chat_model: str = "gpt-4.1-mini"
    openai_embedding_model: str = "text-embedding-3-small"
    openai_vision_model: str = "gpt-4.1-mini"
    chroma_path: str = "./data/chroma"
    cors_origins: str = "http://localhost:5173"
    max_bim_upload_bytes: int = 10_485_760
    allowed_image_mime_types: str = "image/png,image/jpeg"
    environment: str = "development"
    ai_api_key: str = ""
    database_url: str = "sqlite:///./data/ai_requests.db"
    knowledge_database_url: str = ""
    llm_provider: str = "openai"
    gemini_api_key: str = ""
    gemini_chat_model: str = "gemini-2.5-flash"
    gemini_embedding_model: str = "gemini-embedding-001"
    # Optional: answer through an OpenAI-compatible gateway (CHAT_PROVIDER=openai_compat) while LLM_PROVIDER keeps
    # embedding. Empty CHAT_PROVIDER means LLM_PROVIDER does both.
    chat_provider: str = ""
    chat_base_url: str = ""
    chat_api_key: str = ""
    chat_model: str = ""
    chat_reasoning_effort: str = "low"
    # Optional: EMBED_PROVIDER=local embeds with a model on this machine (no quota); stored vectors of another model
    # are re-embedded by the warmer. LOCAL_EMBED_THREADS=0 lets ONNX pick.
    embed_provider: str = ""
    local_model_dir: str = "./data/models"
    local_embed_threads: int = 0
    llm_timeout_seconds: float = 45
    max_output_tokens: int = 1500
    request_stale_seconds: int = 300
    recovery_interval_seconds: int = 30
    recovery_max_attempts: int = 3
    source_max_bytes: int = 20_971_520
    source_fetch_timeout_seconds: float = 20
    # Background embedding of knowledge sources: items and estimated tokens per minute it may send (Gemini's free tier
    # caps both per project; what is left stays free for question embeddings), items per call, and how long a failed
    # source waits before a retry.
    embed_items_per_minute: int = 80
    embed_tokens_per_minute: int = 20_000
    embed_batch_size: int = 20
    source_retry_seconds: int = 300
    # Inline content (lessons, library items) is embedded once per process and cached by chunk text. Up to
    # inline_sync_chunks missing chunks are embedded during the question; more go to the background warmer while the
    # question uses the chunks already cached.
    inline_sync_chunks: int = 20
    inline_cache_items: int = 5000
    legacy_routes_enabled: bool = False
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    @property
    def origins(self) -> list[str]: return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def image_mime_types(self) -> list[str]: return [item.strip() for item in self.allowed_image_mime_types.split(",") if item.strip()]

@lru_cache
def get_settings() -> Settings: return Settings()
