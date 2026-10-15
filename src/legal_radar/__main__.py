"""CLI: `legal-radar run [fixture]` runs the skeleton pipeline with a fake provider;
`legal-radar ingest <assunto>` ingests the assunto's anchor leis from LexML/Planalto;
`legal-radar ingest-jurisprudencia [--enrich]` ingests the seed precedents and top STF/STJ hits and,
with --enrich, links each to the assunto's concepts;
`legal-radar draft-concepts <assunto>` has an LLM draft concept candidates from the graph's corpus;
`legal-radar ask "<query>"` resolves the assunto, traverses the graph and prints a cited answer;
`legal-radar eval <assunto>` answers the assunto's question set and scores grounding, citations,
contradictions and graph paths under assayer (needs `uv sync --extra eval`);
`legal-radar eval <assunto> --baseline rag-naive|rag-contextual [--k 5 15]` answers the same
questions with a pure-RAG baseline (no graph) instead; `legal-radar index-rag <naive|contextual>`
builds its vector index ahead of time; `legal-radar compare-evals [run.json ...]` tables the graph
and the baselines per metric and per nivel;
`legal-radar refresh-prompts` re-snapshots the pinned LangSmith Hub prompts into prompts/lock.json;
`legal-radar export-seed [path]` / `legal-radar seed [path]` write / rebuild the versioned seed."""

import argparse
import logging
import os
from datetime import UTC, datetime
from pathlib import Path

from legal_radar.adapters.fake_provider import FakeProvider
from legal_radar.adapters.neo4j_store import Neo4jGraphStore
from legal_radar.anchors import ANCHORS
from legal_radar.answer_evaluation import QUESTION_PATHS
from legal_radar.concepts import VOCABULARY_PATHS
from legal_radar.enrichment import DECISION_PROMPT, ENRICHMENT_PROMPT
from legal_radar.ingest import ingest
from legal_radar.pipeline import run
from legal_radar.rag import BASELINES, CHUNKINGS

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


def enrich_config(assunto: str, prompt: str = ENRICHMENT_PROMPT):
    """The LLM phase of `ingest --enrich` and `ingest-jurisprudencia --enrich`, with the pinned
    `prompt` the phase needs; a missing vocabulary or provider is an error."""
    from legal_radar.adapters.sqlite_metadata import SqliteMetadataStore
    from legal_radar.concepts import VocabularyError, load_registered
    from legal_radar.ingest import EnrichConfig
    from legal_radar.prompts import PromptError, default_lock
    from legal_radar.router_config import (
        API_KEYS,
        DEFAULT_PRIORITY,
        build_router,
        enrichment_max_input_tokens,
        load_config,
        providers_without_credentials,
    )

    try:
        default_lock().prompt_hash(prompt)
        vocabulary = load_registered(assunto)
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
        SqliteMetadataStore(os.environ.get("METADATA_DB", DEFAULT_METADATA)),
        max_input_tokens=limit,
    )


def rag_index(chunking: str, reader, provider):
    """The vector index of the whole graph for one chunking, built once and kept under `data/`."""
    from legal_radar.rag import build_chunks, build_index, index_path

    dispositivos, jurisprudencias = reader.corpus()
    chunks = build_chunks(dispositivos, jurisprudencias, contextual=chunking == "contextual")
    return build_index(chunks, provider, index_path(chunking))


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
    jurisprudencia_cmd = commands.add_parser("ingest-jurisprudencia")
    jurisprudencia_cmd.add_argument(
        "--enrich",
        action="store_true",
        help="also link each decision to the assunto's concepts; re-running resumes the pending",
    )
    draft_cmd = commands.add_parser("draft-concepts")
    draft_cmd.add_argument("assunto", choices=sorted(VOCABULARY_PATHS))
    commands.add_parser("refresh-prompts")
    commands.add_parser("ask").add_argument("query")
    eval_cmd = commands.add_parser("eval")
    eval_cmd.add_argument("assunto", choices=sorted(QUESTION_PATHS))
    eval_cmd.add_argument("--price-in", type=float, default=0.0, help="USD per million tokens in")
    eval_cmd.add_argument("--price-out", type=float, default=0.0, help="USD per million tokens out")
    eval_cmd.add_argument(
        "--baseline",
        choices=BASELINES,
        help="answer with a pure-RAG baseline over the whole corpus instead of the graph",
    )
    eval_cmd.add_argument(
        "--k", type=int, nargs="+", default=[5], help="top-k of the baseline (one run per value)"
    )
    eval_cmd.add_argument(
        "--fresh",
        action="store_true",
        help="discard the answers a run that died left behind (default: resume them)",
    )
    eval_cmd.add_argument(
        "--grounding", action="store_true", help="also score RAGAS faithfulness (RAGAS_* env vars)"
    )
    commands.add_parser("index-rag").add_argument("chunking", choices=CHUNKINGS)
    compare_cmd = commands.add_parser("compare-evals")
    compare_cmd.add_argument(
        "runs",
        nargs="*",
        type=Path,
        help="run files (default: the latest of each system in eval-runs/)",
    )
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

    if args.command == "compare-evals":
        import json

        from legal_radar.assayer_harness import RUNS_DIR
        from legal_radar.eval_comparison import latest_runs, render_comparison

        runs = (
            [json.loads(path.read_text(encoding="utf-8")) for path in args.runs]
            if args.runs
            else latest_runs(RUNS_DIR)
        )
        if not runs:
            raise SystemExit(f"no evaluation run to compare in {RUNS_DIR}")
        print(render_comparison(runs))
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
        if args.command == "index-rag":
            from legal_radar.adapters.neo4j_reader import Neo4jGraphReader
            from legal_radar.router_config import build_router, load_config

            index = rag_index(
                args.chunking,
                Neo4jGraphReader(store.driver),
                build_router(load_config("router.yaml")),
            )
            print(f"{args.chunking}: {len(index.chunks)} chunks embedded with {index.model}")
            return
        if args.command == "eval":
            from legal_radar.adapters.neo4j_reader import Neo4jGraphReader
            from legal_radar.answer import ask
            from legal_radar.answer_evaluation import (
                UsageMeter,
                llm_flags_contradiction,
                llm_states_insufficiency,
                load_questions,
            )
            from legal_radar.assayer_harness import (
                Pricing,
                ragas_llm_from_env,
                run_evaluation,
            )
            from legal_radar.assunto import AssuntoResolver
            from legal_radar.prompts import default_lock
            from legal_radar.router_config import build_router, load_config

            meter = UsageMeter(build_router(load_config("router.yaml")))
            reader, lock = Neo4jGraphReader(store.driver), default_lock()
            questions = load_questions(QUESTION_PATHS[args.assunto])
            if args.baseline:
                from legal_radar.rag import RagBaseline

                index = rag_index(args.baseline.removeprefix("rag-"), reader, meter)
                systems = [
                    (RagBaseline(args.baseline, index, meter, k, lock).ask, args.baseline, k)
                    for k in args.k
                ]
            else:
                graph = lambda query: ask(  # noqa: E731
                    query, AssuntoResolver(meter).resolve, reader, meter, lock
                )
                systems = [(graph, "graph", None)]
            for answer, system, k in systems:
                from legal_radar.assayer_harness import checkpoint_for

                checkpoint = checkpoint_for(system, k, questions, lock.snapshot_hash)
                if args.fresh:
                    checkpoint.discard()
                    checkpoint = checkpoint_for(system, k, questions, lock.snapshot_hash)
                if checkpoint.done:
                    print(f"{system}: resuming with {len(checkpoint.done)} answers already saved")
                stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
                report = run_evaluation(
                    questions,
                    answer,
                    meter,
                    llm_flags_contradiction(meter),
                    llm_states_insufficiency(meter),
                    pricing=Pricing(args.price_in, args.price_out),
                    grounding_llm=ragas_llm_from_env() if args.grounding else None,
                    prompt_snapshot=lock.snapshot_hash,
                    experiment=f"{system}{'' if k is None else f'-k{k}'}-{stamp}",
                    system=system,
                    k=k,
                    graph_paths=k is None,
                    checkpoint=checkpoint,
                )
                print(report.render())
                print(f"wrote {report.write()}")
                checkpoint.discard()
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
            from legal_radar.jurisprudencia import ASSUNTO, ingest_jurisprudencia

            config = enrich_config(ASSUNTO, DECISION_PROMPT) if args.enrich else None

            browser = BrowserPageSource(
                channel="chrome"
            )  # STJ's Cloudflare rejects bundled Chromium
            try:
                fetchers = {"STF": StfFetcher(browser), "STJ": StjFetcher(browser)}
                report = ingest_jurisprudencia(fetchers, store, enrichment=config)
                print(report.render())
                if report.failed:
                    raise SystemExit(1)
            finally:
                browser.close()
                if config:
                    config.metadata.close()
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
