"""Routes `complete()` across providers: fallback on quota, wait on RPM, one transient retry."""

import time
import uuid
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from typing import TypeVar

from legal_radar.application.ports import Provider
from legal_radar.domain.complexity import COMPLEX, SIMPLE
from legal_radar.domain.llm import (
    AllProvidersFailedError,
    Completion,
    CompletionParams,
    Embedding,
    ProviderError,
    RateLimitedError,
    TransientError,
    content_hash,
)
from legal_radar.wide_events import WideEventLog

T = TypeVar("T", Completion, Embedding)

MAX_RATE_LIMIT_WAITS = 3
TRANSIENT_BACKOFF_SECONDS = 1.5


class Router:
    """Tries providers in priority order and emits one wide event per call."""

    name = "router"
    model = "routed"
    embedding_model = "routed"

    def __init__(
        self,
        providers: list[Provider],
        events: WideEventLog,
        daily_limits: dict[str, int] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        complex_providers: list[Provider] | None = None,
    ):
        if not providers:
            raise ValueError("Router needs at least one provider")
        self.providers = providers
        self.events = events
        self.daily_limits = daily_limits or {}
        self.sleep = sleep
        self.clock = clock
        self.complex_providers = complex_providers or []  # empty: tiers are off

    def complete(self, prompt: str, params: CompletionParams | None = None) -> Completion:
        params = params or CompletionParams()
        started = time.monotonic()
        event = {
            "event": "llm_call",
            "timestamp": self.clock().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "request_id": uuid.uuid4().hex,
            "provider": None,
            "model": None,
            "pipeline_step": params.pipeline_step,
            "prompt_id": content_hash(prompt),
            "prompt_snapshot": params.prompt_snapshot,
            "tool_schema_ids": [content_hash(tool) for tool in params.tools],
            "response_schema_id": (
                content_hash(params.response_schema) if params.response_schema else None
            ),
            "prompt_text": prompt if self.events.log_full_content else None,
            "output_text": None,
            "tokens_in": 0,
            "tokens_out": 0,
            "tokens_thinking": 0,
            "latency_ms": 0,
            "outcome": "failed",
            "fallback_from": None,
            "retry_count": 0,
            "complexity": params.complexity if self.complex_providers else None,
            "downgraded_from": None,
        }
        try:
            result = self._route(lambda provider: provider.complete(prompt, params), event)
            event.update(
                provider=result.provider,
                model=result.model,
                outcome="success",
                tokens_in=result.tokens_in,
                tokens_out=result.tokens_out,
                tokens_thinking=result.tokens_thinking,
                output_text=result.text if self.events.log_full_content else None,
            )
            return result
        finally:
            event["latency_ms"] = round((time.monotonic() - started) * 1000)
            self.events.emit(event)

    def embed(self, texts: list[str], params: CompletionParams | None = None) -> Embedding:
        """Embeds `texts` with the first provider that has an embedding model and quota."""
        params = params or CompletionParams()
        started = time.monotonic()
        event = {
            "event": "embed_call",
            "timestamp": self.clock().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "request_id": uuid.uuid4().hex,
            "provider": None,
            "model": None,
            "pipeline_step": params.pipeline_step,
            "prompt_id": content_hash(texts),
            "input_count": len(texts),
            "prompt_text": texts if self.events.log_full_content else None,
            "tokens_in": 0,
            "latency_ms": 0,
            "outcome": "failed",
            "fallback_from": None,
            "retry_count": 0,
        }
        try:
            result = self._route(
                lambda provider: provider.embed(texts, params),
                event,
                lambda provider: provider.embedding_model,
            )
            event.update(
                provider=result.provider,
                model=result.model,
                outcome="success",
                tokens_in=result.tokens_in,
            )
            return result
        finally:
            event["latency_ms"] = round((time.monotonic() - started) * 1000)
            self.events.emit(event)

    def _route(
        self,
        call: Callable[[Provider], T],
        event: dict,
        model_of: Callable[[Provider], str] = lambda provider: provider.model,
    ) -> T:
        if event.get("complexity") == COMPLEX:
            try:
                return self._route_among(self.complex_providers, call, event, model_of)
            except AllProvidersFailedError:
                event["complexity"] = SIMPLE
                event["downgraded_from"] = COMPLEX
        return self._route_among(self.providers, call, event, model_of)

    def _route_among(
        self,
        providers: list[Provider],
        call: Callable[[Provider], T],
        event: dict,
        model_of: Callable[[Provider], str],
    ) -> T:
        fallback_from = None
        reasons: list[str] = []
        for provider in providers:
            if self._over_daily_limit(provider, model_of(provider)):
                fallback_from = provider.name
                reasons.append(f"{provider.name}: over its daily limit")
                continue
            try:
                result, retries = self._attempt(call, provider)
            except ProviderError as error:  # quota, throttling, transient, or a rejected request
                fallback_from = provider.name
                reasons.append(f"{provider.name}: {error}")
                continue
            event["fallback_from"] = fallback_from
            event["retry_count"] = retries
            return replace(
                result,
                provider=provider.name,
                model=model_of(provider),
                retry_count=retries,
                fallback_from=fallback_from,
            )
        raise AllProvidersFailedError(
            "every provider was exhausted or failed (" + "; ".join(reasons) + ")"
        )

    def _attempt(self, call: Callable[[Provider], T], provider: Provider) -> tuple[T, int]:
        waits = 0
        transient_retried = False
        retries = 0
        while True:
            try:
                return call(provider), retries
            except RateLimitedError as error:
                if waits >= MAX_RATE_LIMIT_WAITS:
                    raise
                waits += 1
                retries += 1
                self.sleep(error.retry_after)
            except TransientError:
                if transient_retried:
                    raise
                transient_retried = True
                retries += 1
                self.sleep(TRANSIENT_BACKOFF_SECONDS)

    def _over_daily_limit(self, provider: Provider, model: str) -> bool:
        limit = self.daily_limits.get(provider.name)
        if limit is None:
            return False
        return self.events.usage_today(provider.name, model, self.clock()) >= limit
