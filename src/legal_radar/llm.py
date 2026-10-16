"""Types shared by the provider port, its adapters and the router."""

import hashlib
import json
from dataclasses import dataclass, field


@dataclass(frozen=True)
class CompletionParams:
    pipeline_step: str = "unspecified"
    max_tokens: int | None = None
    temperature: float | None = None
    tools: tuple[dict, ...] = ()
    response_schema: dict | None = None  # JSON Schema the reply must conform to (structured output)
    prompt_snapshot: str | None = None  # hash of the prompt lockfile the prompt was rendered from
    complexity: str | None = None  # "simple" | "complex": which tier's providers to try first


@dataclass(frozen=True)
class Completion:
    text: str
    tokens_in: int = 0
    tokens_out: int = 0
    tokens_thinking: int = 0
    provider: str = ""
    model: str = ""
    retry_count: int = 0
    fallback_from: str | None = None
    extra: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Embedding:
    vectors: list[list[float]]
    tokens_in: int = 0
    provider: str = ""
    model: str = ""
    retry_count: int = 0
    fallback_from: str | None = None


class ProviderError(Exception):
    """Base class for failures a provider adapter reports to the router."""


class QuotaExhaustedError(ProviderError):
    """Daily (RPD-level) quota is spent: fall back to the next provider."""


class RateLimitedError(ProviderError):
    """RPM-level throttling: wait `retry_after` seconds and retry the same provider."""

    def __init__(self, retry_after: float = 1.0):
        super().__init__(f"rate limited, retry after {retry_after}s")
        self.retry_after = retry_after


class TransientError(ProviderError):
    """Timeout, 5xx or network failure: retry once, then fall back."""


class AllProvidersFailedError(ProviderError):
    """Every configured provider was exhausted or failed."""


def content_hash(value: str | dict | list) -> str:
    raw = value if isinstance(value, str) else json.dumps(value, sort_keys=True)
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()
