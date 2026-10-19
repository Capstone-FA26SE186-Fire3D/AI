from app.core.config import Settings
from app.llm.base import Provider, ProviderError


def get_provider(settings: Settings) -> Provider:
    name = settings.llm_provider.lower()
    if name == "fake":
        from app.llm.fake import FakeProvider

        return FakeProvider()
    if name == "openai":
        if not settings.openai_api_key:
            raise ProviderError("openai provider not configured")
        from app.llm.openai_provider import OpenAIProvider

        return OpenAIProvider(settings.openai_api_key, settings.openai_chat_model, settings.openai_embedding_model, settings.llm_timeout_seconds)
    if name == "gemini":
        if not settings.gemini_api_key:
            raise ProviderError("gemini provider not configured")
        from app.llm.gemini_provider import GeminiProvider

        return GeminiProvider(settings.gemini_api_key, settings.gemini_chat_model, settings.gemini_embedding_model, settings.llm_timeout_seconds)
    raise ProviderError(f"unknown llm provider: {name}")
