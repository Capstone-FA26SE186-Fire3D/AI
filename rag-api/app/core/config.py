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
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    @property
    def origins(self) -> list[str]: return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def image_mime_types(self) -> list[str]: return [item.strip() for item in self.allowed_image_mime_types.split(",") if item.strip()]

@lru_cache
def get_settings() -> Settings: return Settings()
