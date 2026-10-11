"""Groq, Gemini and LM Studio adapters over plain HTTP (stdlib only)."""

import json
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

from legal_radar.llm import (
    Completion,
    CompletionParams,
    ProviderError,
    QuotaExhaustedError,
    RateLimitedError,
    TransientError,
)

Response = tuple[int, dict[str, str], dict]
Transport = Callable[[str, dict[str, str], dict], Response]

DAILY_MARKERS = ("per day", "perday", "(rpd)", "(tpd)")
DEFAULT_RETRY_AFTER = 2.0
TIMEOUT_SECONDS = 60


def urllib_transport(url: str, headers: dict[str, str], body: dict) -> Response:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return response.status, dict(response.headers), json.load(response)
    except urllib.error.HTTPError as error:
        try:
            payload = json.load(error)
        except ValueError:
            payload = {}
        return error.code, dict(error.headers), payload


@dataclass
class HttpProvider:
    """Template for one provider; subclasses define the request and response shapes."""

    name: str
    model: str
    api_key: str = ""
    base_url: str = ""
    transport: Transport = urllib_transport

    def complete(self, prompt: str, params: CompletionParams | None = None) -> Completion:
        url, headers, body = self.build_request(prompt, params or CompletionParams())
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
        return self.parse_response(payload)

    def build_request(self, prompt: str, params: CompletionParams) -> tuple[str, dict, dict]:
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
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        return f"{self.base_url}/chat/completions", headers, body

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
    def __init__(self, model: str, api_key: str = "", transport: Transport = urllib_transport):
        super().__init__("groq", model, api_key, "https://api.groq.com/openai/v1", transport)


class LMStudioProvider(OpenAICompatibleProvider):
    def __init__(
        self,
        model: str,
        base_url: str = "http://localhost:1234/v1",
        transport: Transport = urllib_transport,
    ):
        super().__init__("lmstudio", model, "", base_url.rstrip("/"), transport)


class GeminiProvider(HttpProvider):
    def __init__(self, model: str, api_key: str = "", transport: Transport = urllib_transport):
        super().__init__(
            "gemini", model, api_key, "https://generativelanguage.googleapis.com/v1beta", transport
        )

    def build_request(self, prompt: str, params: CompletionParams):
        config = {}
        if params.max_tokens is not None:
            config["maxOutputTokens"] = params.max_tokens
        if params.temperature is not None:
            config["temperature"] = params.temperature
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
