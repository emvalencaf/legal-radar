"""CLI: `legal-radar run [fixture]` runs the skeleton pipeline with a fake provider;
`legal-radar ingest <assunto>` ingests the assunto's anchor leis from LexML/Planalto;
`legal-radar ingest-jurisprudencia` ingests the seed precedents and top STF/STJ hits;
`legal-radar draft-concepts <assunto>` has an LLM draft concept candidates from the graph's corpus;
`legal-radar ask "<query>"` resolves the assunto, traverses the graph and prints a cited answer;
`legal-radar refresh-prompts` re-snapshots the pinned LangSmith Hub prompts into prompts/lock.json;
`legal-radar export-seed [path]` / `legal-radar seed [path]` write / rebuild the versioned seed."""

import argparse
import logging
import os
from pathlib import Path

from legal_radar.adapters.fake_provider import FakeProvider
from legal_radar.adapters.neo4j_store import Neo4jGraphStore
from legal_radar.anchors import ANCHORS
from legal_radar.concepts import VOCABULARY_PATHS
from legal_radar.ingest import ingest
from legal_radar.pipeline import run

ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
DEFAULT_SEED = Path(__file__).resolve().parents[2] / "seed" / "graph.jsonl"
DEFAULT_METADATA = Path(__file__).resolve().parents[2] / "data" / "ingestion.sqlite"
DEFAULT_FIXTURE = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "mini_lei.txt"


def load_env(path: Path = ENV_PATH) -> None:
    """Export the KEY=VALUE lines of `.env` that the environment does not already set."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition("=")
        if sep and not key.lstrip().startswith("#"):
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def enrich_config(assunto: str):
    """The LLM phase of `ingest --enrich`; a missing vocabulary or provider is an error."""
    from legal_radar.adapters.sqlite_metadata import SqliteMetadataStore
    from legal_radar.concepts import VocabularyError, load_registered
    from legal_radar.enrichment import ENRICHMENT_PROMPT
    from legal_radar.ingest import EnrichConfig
    from legal_radar.prompts import PromptError, default_lock
    from legal_radar.router_config import build_router, enrichment_max_input_tokens, load_config

    try:
        default_lock().prompt_hash(ENRICHMENT_PROMPT)
        vocabulary = load_registered(assunto)
        config = load_config("router.yaml")
        router = build_router(config)
        limit = enrichment_max_input_tokens(config)
    except (VocabularyError, PromptError, ValueError, OSError, KeyError) as error:
        raise SystemExit(
            f"ingest --enrich needs a vocabulary, the enrichment prompt and a provider: {error}"
        ) from error
    return EnrichConfig(
        vocabulary,
        router,
        SqliteMetadataStore(os.environ.get("METADATA_DB", DEFAULT_METADATA)),
        max_input_tokens=limit,
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="legal-radar")
    commands = parser.add_subparsers(dest="command", required=True)
    run_cmd = commands.add_parser("run")
    run_cmd.add_argument("fixture", nargs="?", type=Path, default=DEFAULT_FIXTURE)
    run_cmd.add_argument(
        "--assunto",
        choices=sorted(VOCABULARY_PATHS),
        help="only accept conceitos from this assunto's vocabulary",
    )
    ingest_cmd = commands.add_parser("ingest")
    ingest_cmd.add_argument("assunto", choices=sorted(ANCHORS))
    ingest_cmd.add_argument(
        "--enrich",
        action="store_true",
        help="also send the chunks the rules left to the LLM; re-running resumes the pending ones",
    )
    commands.add_parser("ingest-jurisprudencia")
    draft_cmd = commands.add_parser("draft-concepts")
    draft_cmd.add_argument("assunto", choices=sorted(VOCABULARY_PATHS))
    commands.add_parser("refresh-prompts")
    commands.add_parser("ask").add_argument("query")
    for name in ("export-seed", "seed"):
        commands.add_parser(name).add_argument("path", nargs="?", type=Path, default=DEFAULT_SEED)
    args = parser.parse_args(argv)
    load_env()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    if args.command == "refresh-prompts":
        from legal_radar.prompts import LOCK_PATH, langsmith_fetch, refresh_lock

        lock = refresh_lock(langsmith_fetch)
        print(f"wrote {LOCK_PATH} ({len(lock.prompts)} prompts, {lock.snapshot_hash})")
        return

    store = Neo4jGraphStore.connect(
        os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
        os.environ.get("NEO4J_USER", "neo4j"),
        os.environ.get("NEO4J_PASSWORD", "legal-radar-dev"),
    )
    try:
        if args.command in ("export-seed", "seed"):
            from legal_radar.seed import export_seed, load_seed

            if args.command == "export-seed":
                args.path.parent.mkdir(parents=True, exist_ok=True)
                args.path.write_text(export_seed(store.driver), encoding="utf-8")
            else:
                load_seed(store.driver, args.path.read_text(encoding="utf-8"))
            return
        if args.command == "ask":
            from legal_radar.adapters.neo4j_reader import Neo4jGraphReader
            from legal_radar.answer import ask
            from legal_radar.assunto import AssuntoResolver
            from legal_radar.router_config import build_router, load_config

            router = build_router(load_config("router.yaml"))
            result = ask(
                args.query, AssuntoResolver(router).resolve, Neo4jGraphReader(store.driver), router
            )
            if result.assunto is None:
                print(f"no known assunto matches {args.query!r}")
            elif result.answer is None:
                print(f"assunto {result.assunto!r} resolved, but the graph has none of its leis")
            else:
                print(result.answer)
            for c in result.citations:
                path = " -> ".join(f"{h.type}({h.target})" for h in c.path) or "anchor"
                print(f"- {c.kind} {c.id}: {path}")
            return
        if args.command == "draft-concepts":
            from legal_radar.concepts import (
                corpus_ids,
                draft_candidates,
                graph_corpus,
                with_assunto,
            )
            from legal_radar.router_config import build_router, load_config

            router = build_router(load_config("router.yaml"))
            corpus = graph_corpus(store.driver)
            drafted = draft_candidates(args.assunto, corpus, router)
            draft, error = with_assunto(args.assunto, drafted, corpus_ids(corpus))
            target = VOCABULARY_PATHS[args.assunto].with_suffix(".draft.yml")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(draft, encoding="utf-8")
            if error:
                print(f"warning: the draft does not load yet: {error}")
            print(f"wrote {target}; curate it into {VOCABULARY_PATHS[args.assunto]}")
            return
        if args.command == "ingest":
            from legal_radar.adapters.pages import BrowserPageSource

            config = enrich_config(args.assunto) if args.enrich else None
            browser = BrowserPageSource()
            try:
                ingested = ingest(ANCHORS[args.assunto], browser, browser, store, enrichment=config)
                print(ingested.render())
            finally:
                browser.close()
                if config:
                    config.metadata.close()
            return
        if args.command == "ingest-jurisprudencia":
            from legal_radar.adapters.pages import BrowserPageSource
            from legal_radar.adapters.stf import StfFetcher
            from legal_radar.adapters.stj import StjFetcher
            from legal_radar.jurisprudencia import ingest_jurisprudencia

            browser = BrowserPageSource(
                channel="chrome"
            )  # STJ's Cloudflare rejects bundled Chromium
            try:
                fetchers = {"STF": StfFetcher(browser), "STJ": StjFetcher(browser)}
                report = ingest_jurisprudencia(fetchers, store)
                print(report.render())
                if report.failed:
                    raise SystemExit(1)
            finally:
                browser.close()
            return
        ids = None
        if args.assunto:
            from legal_radar.concepts import load_registered

            ids = [c.id for c in load_registered(args.assunto).conceitos]
        batch = run(
            args.fixture.read_text(encoding="utf-8"), FakeProvider(), store, conceito_ids=ids
        )
    finally:
        store.close()
    print(
        f"wrote {batch.lei.id}: {len(batch.dispositivos)} dispositivos, "
        f"{len(batch.conceitos)} conceitos"
    )


if __name__ == "__main__":
    main()
