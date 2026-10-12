"""Builds a `Router` from `router.yaml` and environment secrets."""

import os
from collections.abc import Mapping
from pathlib import Path

import yaml

from legal_radar.adapters.http_providers import (
    GeminiProvider,
    GroqProvider,
    LMStudioProvider,
    Transport,
    urllib_transport,
)
from legal_radar.enricher import MAX_INPUT_TOKENS
from legal_radar.ports import Provider
from legal_radar.router import Router
from legal_radar.wide_events import WideEventLog

DEFAULT_PRIORITY = ["groq", "gemini", "lmstudio"]
DEFAULT_MODELS = {
    "groq": "openai/gpt-oss-120b",
    "gemini": "gemini-3.1-flash-lite",
    "lmstudio": "local-model",
}
DEFAULT_EMBEDDING_MODELS = {
    "gemini": "gemini-embedding-001",
    "lmstudio": "text-embedding-bge-m3",
}
DEFAULT_DAILY_LIMITS = {"gemini": 500}
DEFAULT_LOG_PATH = "logs/llm_calls.jsonl"


def load_config(path: Path | str | None) -> dict:
    if path is None or not Path(path).exists():
        return {}
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}


def enrichment_max_input_tokens(config: dict) -> int:
    """The per-call input-token ceiling of the enricher (`enrichment.max_input_tokens`)."""
    value = (config.get("enrichment") or {}).get("max_input_tokens", MAX_INPUT_TOKENS)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"enrichment.max_input_tokens must be a positive integer, got {value!r}")
    return value


def build_router(
    config: dict,
    env: Mapping[str, str] | None = None,
    transport: Transport = urllib_transport,
) -> Router:
    env = os.environ if env is None else env
    models = {**DEFAULT_MODELS, **(config.get("models") or {})}
    embedding_models = {**DEFAULT_EMBEDDING_MODELS, **(config.get("embedding_models") or {})}
    priority = config.get("providers") or DEFAULT_PRIORITY
    providers: list[Provider] = []
    for name in priority:
        if name == "groq":
            providers.append(GroqProvider(models[name], env.get("GROQ_API_KEY", ""), transport))
        elif name == "gemini":
            providers.append(
                GeminiProvider(
                    models[name], env.get("GEMINI_API_KEY", ""), transport, embedding_models[name]
                )
            )
        elif name == "lmstudio":
            base_url = env.get("LMSTUDIO_BASE_URL", "http://localhost:1234/v1")
            providers.append(
                LMStudioProvider(models[name], base_url, transport, embedding_models[name])
            )
        else:
            raise ValueError(f"unknown provider {name!r} in router.yaml")
    logging_config = config.get("logging") or {}
    log = WideEventLog(
        logging_config.get("path", DEFAULT_LOG_PATH),
        log_full_content=bool(logging_config.get("log_full_content", False)),
    )
    return Router(
        providers, log, daily_limits={**DEFAULT_DAILY_LIMITS, **(config.get("daily_limits") or {})}
    )
