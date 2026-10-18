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
    llm_timeout_seconds: float = 45
    max_output_tokens: int = 1500
    request_stale_seconds: int = 300
    recovery_interval_seconds: int = 30
    recovery_max_attempts: int = 3
    source_max_bytes: int = 20_971_520
    source_fetch_timeout_seconds: float = 20
    source_total_deadline_seconds: float = 60
    legacy_routes_enabled: bool = False
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    @property
    def origins(self) -> list[str]: return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def image_mime_types(self) -> list[str]: return [item.strip() for item in self.allowed_image_mime_types.split(",") if item.strip()]

@lru_cache
def get_settings() -> Settings: return Settings()
