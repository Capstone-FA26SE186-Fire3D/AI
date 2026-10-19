import json

from google import genai
from google.genai import types

from app.llm.base import LlmUsage, ProviderError


# Gemini embed_content accepts at most 100 inputs per call.
EMBED_BATCH = 100


class GeminiProvider:
    name = "gemini"

    def __init__(self, api_key: str, chat_model: str, embedding_model: str, timeout: float):
        # HttpOptions.timeout is in milliseconds. google-genai 1.75 never retries when retry_options is
        # None; attempts=1 pins that explicitly (a retried generate would be a second billed call).
        self.client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=int(timeout * 1000), retry_options=types.HttpRetryOptions(attempts=1)),
        )
        self.chat_model = chat_model
        self.embedding_model = embedding_model

    def generate(self, system: str, payload: dict, schema: dict, max_output_tokens: int) -> tuple[dict, LlmUsage]:
        try:
            response = self.client.models.generate_content(
                model=self.chat_model,
                contents=json.dumps(payload, ensure_ascii=False),
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    response_mime_type="application/json",
                    response_json_schema=schema,
                    max_output_tokens=max_output_tokens,
                    # 2.5 models think by default and thinking tokens eat max_output_tokens and quota.
                    thinking_config=(
                        types.ThinkingConfig(thinking_budget=0) if self.chat_model.startswith("gemini-2.5") else None
                    ),
                ),
            )
            data = json.loads(response.text)
            meta = response.usage_metadata
            return data, LlmUsage(
                int(getattr(meta, "prompt_token_count", 0) or 0),
                int(getattr(meta, "candidates_token_count", 0) or 0) + int(getattr(meta, "thoughts_token_count", 0) or 0),
                response.model_version or self.chat_model,
            )
        except (json.JSONDecodeError, TypeError) as exc:
            raise ProviderError("gemini returned non-JSON or empty output") from exc
        except Exception as exc:
            raise ProviderError(f"gemini request failed: {type(exc).__name__}") from exc

    def embed(self, texts: list[str]) -> list[list[float]]:
        try:
            out: list[list[float]] = []
            for start in range(0, len(texts), EMBED_BATCH):
                response = self.client.models.embed_content(
                    model=self.embedding_model, contents=texts[start:start + EMBED_BATCH]
                )
                out.extend(list(item.values) for item in response.embeddings)
            return out
        except Exception as exc:
            raise ProviderError(f"gemini embedding failed: {type(exc).__name__}") from exc
