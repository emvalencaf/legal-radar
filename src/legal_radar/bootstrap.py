"""Composition root: the only module that reads the environment and builds concrete adapters.

Everything else receives what it needs: a `Settings`, a store, a provider.
"""

import os
from pathlib import Path

from legal_radar.adapters.neo4j_store import Neo4jGraphStore
from legal_radar.application.enrichment import ENRICHMENT_PROMPT
from legal_radar.settings import Settings


def load_env(path: Path | None = None) -> None:
    """Export the KEY=VALUE lines of `.env` that the environment does not already set."""
    path = Settings().env_file if path is None else path
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition("=")
        if sep and not key.lstrip().startswith("#"):
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def load_settings() -> Settings:
    """`.env` first, then the environment's overrides over the checkout defaults."""
    load_env()
    return Settings.from_env()


def connect_store(settings: Settings) -> Neo4jGraphStore:
    return Neo4jGraphStore.connect(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password)


def enrich_config(settings: Settings, subject: str, prompt: str = ENRICHMENT_PROMPT):
    """The LLM phase of `ingest --enrich` and `ingest-jurisprudencia --enrich`, with the pinned
    `prompt` the phase needs; a missing vocabulary or provider is an error."""
    from legal_radar.adapters.prompt_lock import default_lock
    from legal_radar.adapters.router_config import (
        API_KEYS,
        DEFAULT_PRIORITY,
        build_router,
        enrichment_max_input_tokens,
        load_config,
        providers_without_credentials,
    )
    from legal_radar.adapters.sqlite_metadata import SqliteMetadataStore
    from legal_radar.application.concepts import VocabularyError, load_registered
    from legal_radar.application.ingest import EnrichConfig
    from legal_radar.domain.prompts import PromptError

    lock = default_lock()
    try:
        lock.prompt_hash(prompt)
        vocabulary = load_registered(subject)
        config = load_config("router.yaml")
        missing = providers_without_credentials(config)
        priority = config.get("providers") or DEFAULT_PRIORITY
        if set(missing) >= set(priority):
            raise ValueError(
                f"no provider has credentials (set {', '.join(API_KEYS[n] for n in missing)})"
            )
        config = {**config, "providers": [n for n in priority if n not in missing]}
        router = build_router(config)
        limit = enrichment_max_input_tokens(config)
    except (VocabularyError, PromptError, ValueError, OSError, KeyError) as error:
        raise SystemExit(
            f"--enrich needs a vocabulary, the {prompt} prompt and a provider: {error}"
        ) from error
    return EnrichConfig(
        vocabulary,
        router,
        SqliteMetadataStore(settings.metadata_db),
        lock,
        max_input_tokens=limit,
    )


def rag_index(settings: Settings, chunking: str, reader, provider):
    """The vector index of the whole graph for one chunking, built once and kept under `data/`."""
    from legal_radar.adapters.sqlite_vectors import SqliteVectorStore
    from legal_radar.application.rag import build_chunks, build_index, index_path

    provisions, case_law = reader.corpus()
    chunks = build_chunks(provisions, case_law, contextual=chunking == "contextual")
    store = SqliteVectorStore(index_path(chunking, settings.index_dir))
    try:
        return build_index(chunks, provider, store)
    finally:
        store.close()
