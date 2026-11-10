from app.core.config import Settings
from app.llm.base import Provider, ProviderError


def get_provider(settings: Settings) -> Provider:
    """LLM_PROVIDER answers and embeds; CHAT_PROVIDER=openai_compat moves only the answering to a gateway."""
    base = _base_provider(settings)
    chat = settings.chat_provider.lower()
    if not chat:
        return base
    if chat != "openai_compat":
        raise ProviderError(f"unknown chat provider: {chat}")
    if not (settings.chat_api_key and settings.chat_base_url and settings.chat_model):
        raise ProviderError("openai_compat chat provider not configured")
    from app.llm.compat_provider import CompatChatProvider, SplitProvider

    gateway = CompatChatProvider(
        settings.chat_api_key, settings.chat_base_url, settings.chat_model, settings.llm_timeout_seconds,
        settings.chat_reasoning_effort,
    )
    return SplitProvider(gateway, base)


def _base_provider(settings: Settings) -> Provider:
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
