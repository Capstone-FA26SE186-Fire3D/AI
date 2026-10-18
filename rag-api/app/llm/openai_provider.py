import json

from openai import OpenAI

from app.llm.base import LlmUsage, ProviderError


class OpenAIProvider:
    name = "openai"

    def __init__(self, api_key: str, chat_model: str, embedding_model: str, timeout: float):
        self.client = OpenAI(api_key=api_key, timeout=timeout, max_retries=0)
        self.chat_model = chat_model
        self.embedding_model = embedding_model

    def generate(self, system: str, payload: dict, schema: dict, max_output_tokens: int) -> tuple[dict, LlmUsage]:
        try:
            response = self.client.responses.create(
                model=self.chat_model,
                instructions=system,
                input=json.dumps(payload, ensure_ascii=False),
                text={"format": {"type": "json_schema", "name": "fet3d_ai", "strict": True, "schema": schema}},
                max_output_tokens=max_output_tokens,
                store=False,
            )
            data = json.loads(response.output_text)
            usage = response.usage
            return data, LlmUsage(int(usage.input_tokens), int(usage.output_tokens), response.model)
        except json.JSONDecodeError as exc:
            raise ProviderError("openai returned non-JSON output") from exc
        except Exception as exc:
            raise ProviderError(f"openai request failed: {type(exc).__name__}") from exc

    def embed(self, texts: list[str]) -> list[list[float]]:
        try:
            response = self.client.embeddings.create(model=self.embedding_model, input=texts)
            return [list(item.embedding) for item in response.data]
        except Exception as exc:
            raise ProviderError(f"openai embedding failed: {type(exc).__name__}") from exc
