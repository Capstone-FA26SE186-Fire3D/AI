"""Chat through an OpenAI-compatible gateway; embeddings stay with the main provider.

Gateways that resell models behind the OpenAI chat API often drop `response_format`, so the JSON Schema goes into the
system prompt and the reply is parsed leniently (code fences and text around the object are tolerated). The pipeline
still validates the fields, so a reply that is valid JSON but the wrong shape ends as InsufficientEvidence, not a crash.
"""
import json
import logging

from openai import OpenAI, RateLimitError

from app.llm.base import LlmUsage, Provider, ProviderError, RateLimited, embed_query

log = logging.getLogger(__name__)

SCHEMA_RULE = (
    "\n\nChỉ trả về MỘT đối tượng JSON hợp lệ, không markdown, không giải thích thêm, đúng JSON Schema sau:\n"
)


def extract_json(text: str) -> dict:
    """The first JSON object in a reply, with or without ``` fences or surrounding prose."""
    body = text.strip()
    if body.startswith("```"):
        body = body.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        start, end = body.find("{"), body.rfind("}")
        if start < 0 or end <= start:
            raise
        data = json.loads(body[start:end + 1])
    if not isinstance(data, dict):
        raise json.JSONDecodeError("not an object", body, 0)
    return data


class CompatChatProvider:
    name = "openai_compat"

    def __init__(self, api_key: str, base_url: str, chat_model: str, timeout: float, reasoning_effort: str = ""):
        self.client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout, max_retries=0)
        self.chat_model = chat_model
        self.reasoning_effort = reasoning_effort

    def generate(self, system: str, payload: dict, schema: dict, max_output_tokens: int) -> tuple[dict, LlmUsage]:
        extra = {"reasoning_effort": self.reasoning_effort} if self.reasoning_effort else {}
        try:
            response = self.client.chat.completions.create(
                model=self.chat_model,
                messages=[
                    {"role": "system", "content": system + SCHEMA_RULE + json.dumps(schema, ensure_ascii=False)},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                max_tokens=max_output_tokens,
                **extra,
            )
            usage = response.usage
            llm = LlmUsage(
                int(getattr(usage, "prompt_tokens", 0) or 0),
                int(getattr(usage, "completion_tokens", 0) or 0),
                response.model or self.chat_model,
            )
            try:
                data = extract_json(response.choices[0].message.content or "")
            except (json.JSONDecodeError, IndexError, AttributeError):
                # The call ran and is billed: hand back an empty object with its usage so the pipeline settles it as
                # invalid output (InsufficientEvidence) instead of an unknown outcome. Typical cause: the reply was
                # cut off at max_tokens (finish_reason "length").
                finish = getattr(response.choices[0], "finish_reason", None) if response.choices else None
                log.warning("chat gateway returned unusable JSON (finish_reason=%s)", finish)
                data = {}
            return data, llm
        except RateLimitError as exc:
            raise RateLimited("chat gateway rate limited") from exc
        except (json.JSONDecodeError, IndexError, AttributeError) as exc:
            raise ProviderError("chat gateway returned non-JSON or empty output") from exc
        except Exception as exc:
            raise ProviderError(f"chat gateway request failed: {type(exc).__name__}") from exc

    def embed(self, texts: list[str]) -> list[list[float]]:
        raise ProviderError("chat gateway does not embed")


class SplitProvider:
    """Answers with `chat`, embeds with `embedder` (whose model names the stored vectors)."""

    def __init__(self, chat: Provider, embedder: Provider):
        self.chat = chat
        self.embedder = embedder
        self.name = f"{chat.name}+{embedder.name}"
        self.embedding_model = embedder.embedding_model

    def generate(self, system: str, payload: dict, schema: dict, max_output_tokens: int) -> tuple[dict, LlmUsage]:
        return self.chat.generate(system, payload, schema, max_output_tokens)

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self.embedder.embed(texts)

    def embed_query(self, text: str) -> list[float]:
        return embed_query(self.embedder, text)
