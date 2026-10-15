"""Groq, Gemini and LM Studio adapters over plain HTTP (stdlib only)."""

import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

from legal_radar.llm import (
    Completion,
    CompletionParams,
    Embedding,
    ProviderError,
    QuotaExhaustedError,
    RateLimitedError,
    TransientError,
)

Response = tuple[int, dict[str, str], dict]
Transport = Callable[[str, dict[str, str], dict], Response]

DAILY_MARKERS = ("per day", "perday", "(rpd)", "(tpd)")
DEFAULT_RETRY_AFTER = 2.0
# Cloudflare-fronted APIs (Groq) refuse the default `Python-urllib` agent with a 403 / error 1010.
USER_AGENT = "legal-radar/0.1"
TIMEOUT_SECONDS = 60  # `LLM_TIMEOUT_SECONDS` overrides it: local models can take minutes


def _closed(schema):
    """The schema with `additionalProperties: false` on every object, which strict mode requires,
    and without `uniqueItems`, which it does not support (Groq rejects the request otherwise).
    Replies are validated against the full schema locally."""
    if isinstance(schema, dict):
        closed = {key: _closed(value) for key, value in schema.items() if key != "uniqueItems"}
        if closed.get("type") == "object":
            closed.setdefault("additionalProperties", False)
        return closed
    if isinstance(schema, list):
        return [_closed(item) for item in schema]
    return schema


def urllib_transport(url: str, headers: dict[str, str], body: dict) -> Response:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT, **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(
            request, timeout=float(os.environ.get("LLM_TIMEOUT_SECONDS", TIMEOUT_SECONDS))
        ) as response:
            return response.status, dict(response.headers), json.load(response)
    except urllib.error.HTTPError as error:
        raw = error.read()
        try:
            payload = json.loads(raw)
        except ValueError:
            payload = {"error": raw.decode("utf-8", "replace").strip()[:200]}
        return error.code, dict(error.headers), payload


@dataclass
class HttpProvider:
    """Template for one provider; subclasses define the request and response shapes."""

    name: str
    model: str
    api_key: str = ""
    base_url: str = ""
    transport: Transport = urllib_transport
    embedding_model: str = ""

    def complete(self, prompt: str, params: CompletionParams | None = None) -> Completion:
        url, headers, body = self.build_request(prompt, params or CompletionParams())
        return self.parse_response(self._post(url, headers, body))

    def embed(self, texts: list[str], params: CompletionParams | None = None) -> Embedding:
        if not self.embedding_model:
            raise ProviderError(f"{self.name} has no embedding model")
        url, headers, body = self.build_embed_request(texts)
        return self.parse_embed_response(self._post(url, headers, body), len(texts))

    def _post(self, url: str, headers: dict, body: dict) -> dict:
        try:
            status, response_headers, payload = self.transport(url, headers, body)
        except (TimeoutError, urllib.error.URLError, ConnectionError, OSError) as error:
            raise TransientError(str(error)) from error
        if status == 429:
            raise self._classify_429(response_headers, payload)
        if status == 408 or status >= 500:
            raise TransientError(f"{self.name} returned {status}")
        if status >= 400:
            raise ProviderError(f"{self.name} returned {status}: {payload}")
        return payload

    def build_request(self, prompt: str, params: CompletionParams) -> tuple[str, dict, dict]:
        raise NotImplementedError

    def build_embed_request(self, texts: list[str]) -> tuple[str, dict, dict]:
        raise NotImplementedError

    def parse_embed_response(self, payload: dict, expected: int) -> Embedding:
        raise NotImplementedError

    def parse_response(self, payload: dict) -> Completion:
        raise NotImplementedError

    def _classify_429(self, headers: dict[str, str], payload: dict) -> ProviderError:
        if any(marker in json.dumps(payload).lower() for marker in DAILY_MARKERS):
            return QuotaExhaustedError(f"{self.name} daily quota exhausted")
        lowered = {key.lower(): value for key, value in headers.items()}
        try:
            return RateLimitedError(float(lowered["retry-after"]))
        except (KeyError, ValueError):
            return RateLimitedError(DEFAULT_RETRY_AFTER)


class OpenAICompatibleProvider(HttpProvider):
    """Chat-completions shape shared by Groq and LM Studio."""

    def build_request(self, prompt: str, params: CompletionParams):
        body: dict = {"model": self.model, "messages": [{"role": "user", "content": prompt}]}
        if params.max_tokens is not None:
            body["max_tokens"] = params.max_tokens
        if params.temperature is not None:
            body["temperature"] = params.temperature
        if params.response_schema is not None:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "response",
                    "strict": True,
                    "schema": _closed(params.response_schema),
                },
            }
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        return f"{self.base_url}/chat/completions", headers, body

    def build_embed_request(self, texts: list[str]):
        body = {"model": self.embedding_model, "input": texts}
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        return f"{self.base_url}/embeddings", headers, body

    def parse_embed_response(self, payload: dict, expected: int) -> Embedding:
        try:
            rows = sorted(payload["data"], key=lambda row: row["index"])
            vectors = [[float(x) for x in row["embedding"]] for row in rows]
        except (KeyError, TypeError, ValueError) as error:
            raise TransientError(f"{self.name} returned a malformed embedding") from error
        if len(vectors) != expected:
            raise TransientError(f"{self.name} returned {len(vectors)} of {expected} embeddings")
        return Embedding(
            vectors,
            tokens_in=(payload.get("usage") or {}).get("prompt_tokens", 0),
            provider=self.name,
            model=self.embedding_model,
        )

    def parse_response(self, payload: dict) -> Completion:
        usage = payload.get("usage", {})
        details = usage.get("completion_tokens_details") or {}
        try:
            text = payload["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as error:
            raise TransientError(f"{self.name} returned a malformed response") from error
        return Completion(
            text,
            tokens_in=usage.get("prompt_tokens", 0),
            tokens_out=usage.get("completion_tokens", 0),
            tokens_thinking=details.get("reasoning_tokens", 0),
            provider=self.name,
            model=self.model,
        )


class GroqProvider(OpenAICompatibleProvider):
    """Groq serves no embedding model, so `embed()` always falls through to the next provider."""

    def __init__(self, model: str, api_key: str = "", transport: Transport = urllib_transport):
        super().__init__("groq", model, api_key, "https://api.groq.com/openai/v1", transport)


class LMStudioProvider(OpenAICompatibleProvider):
    def __init__(
        self,
        model: str,
        base_url: str = "http://localhost:1234/v1",
        transport: Transport = urllib_transport,
        embedding_model: str = "",
    ):
        super().__init__("lmstudio", model, "", base_url.rstrip("/"), transport, embedding_model)


class GeminiProvider(HttpProvider):
    def __init__(
        self,
        model: str,
        api_key: str = "",
        transport: Transport = urllib_transport,
        embedding_model: str = "",
    ):
        super().__init__(
            "gemini",
            model,
            api_key,
            "https://generativelanguage.googleapis.com/v1beta",
            transport,
            embedding_model,
        )

    def build_embed_request(self, texts: list[str]):
        name = f"models/{self.embedding_model}"
        body = {
            "requests": [{"model": name, "content": {"parts": [{"text": text}]}} for text in texts]
        }
        url = f"{self.base_url}/{name}:batchEmbedContents"
        return url, {"x-goog-api-key": self.api_key}, body

    def parse_embed_response(self, payload: dict, expected: int) -> Embedding:
        try:
            vectors = [[float(x) for x in row["values"]] for row in payload["embeddings"]]
        except (KeyError, TypeError, ValueError) as error:
            raise TransientError("gemini returned a malformed embedding") from error
        if len(vectors) != expected:
            raise TransientError(f"gemini returned {len(vectors)} of {expected} embeddings")
        return Embedding(vectors, provider=self.name, model=self.embedding_model)

    def build_request(self, prompt: str, params: CompletionParams):
        config = {}
        if params.max_tokens is not None:
            config["maxOutputTokens"] = params.max_tokens
        if params.temperature is not None:
            config["temperature"] = params.temperature
        if params.response_schema is not None:
            config["responseMimeType"] = "application/json"
            config["responseJsonSchema"] = params.response_schema
        body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}]}
        if config:
            body["generationConfig"] = config
        url = f"{self.base_url}/models/{self.model}:generateContent"
        return url, {"x-goog-api-key": self.api_key}, body

    def parse_response(self, payload: dict) -> Completion:
        usage = payload.get("usageMetadata", {})
        try:
            parts = payload["candidates"][0]["content"]["parts"]
        except (KeyError, IndexError, TypeError) as error:
            raise TransientError("gemini returned a malformed response") from error
        return Completion(
            "".join(part.get("text", "") for part in parts),
            tokens_in=usage.get("promptTokenCount", 0),
            tokens_out=usage.get("candidatesTokenCount", 0),
            tokens_thinking=usage.get("thoughtsTokenCount", 0),
            provider=self.name,
            model=self.model,
        )
