"""CLI: `legal-radar run [fixture]` runs the skeleton pipeline with a fake provider;
`legal-radar ingest <assunto>` ingests the assunto's anchor leis from LexML/Planalto;
`legal-radar ingest-jurisprudencia <assunto> [--enrich]` ingests the assunto's seed precedents and
top STF/STJ hits and, with --enrich, links each to the assunto's concepts;
`legal-radar run-all <assunto> [--enrich]` does it all in one go: ingests the leis and decisions,
exports the seed, answers a cited query, scores the question set and writes the report;
`legal-radar draft-concepts <assunto>` has an LLM draft concept candidates from the graph's corpus;
`legal-radar ask "<query>"` resolves the assunto, traverses the graph and prints a cited answer;
`legal-radar eval <assunto>` answers the assunto's question set and scores grounding, citations,
contradictions and graph paths under assayer (needs `uv sync --extra eval`);
`legal-radar eval <assunto> --baseline rag-naive|rag-contextual [--k 5 15]` answers the same
questions with a pure-RAG baseline (no graph) instead; `legal-radar index-rag <naive|contextual>`
builds its vector index ahead of time; `legal-radar compare-evals [run.json ...]` tables the graph
and the baselines per metric and per nivel;
with `LANGSMITH_API_KEY` set, `ask` and `eval` trace the LangGraph run and the experiment there;
`legal-radar refresh-prompts` re-snapshots the pinned LangSmith Hub prompts into prompts/lock.json;
`legal-radar report [out]` writes the static HTML report (ingestion, evaluation, example answers)
from the latest runs in eval-runs/ (`make publish-report` publishes it to GitHub Pages);
`legal-radar export-seed [path]` / `legal-radar seed [path]` write / rebuild the versioned seed."""

import argparse
import logging
import os
from pathlib import Path

from legal_radar.adapters.fake_provider import FakeProvider
from legal_radar.adapters.fixture.pipeline import run
from legal_radar.adapters.neo4j_store import Neo4jGraphStore
from legal_radar.adapters.tracing import configure_tracing, publisher_if_enabled
from legal_radar.answer_evaluation import QUESTION_PATHS
from legal_radar.application.concepts import VOCABULARY_PATHS
from legal_radar.application.enrichment import DECISION_PROMPT, ENRICHMENT_PROMPT
from legal_radar.application.ingest import ingest
from legal_radar.application.jurisprudencia import JURISPRUDENCIA
from legal_radar.domain.anchors import ANCHORS
from legal_radar.rag import BASELINES, CHUNKINGS

ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
DEFAULT_SEED = Path(__file__).resolve().parents[2] / "seed" / "graph.jsonl"
DEFAULT_REPORT = Path(__file__).resolve().parents[2] / "report" / "index.html"
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
    jurisprudencia_cmd.add_argument("assunto", choices=sorted(JURISPRUDENCIA))
    jurisprudencia_cmd.add_argument(
        "--enrich",
        action="store_true",
        help="also link each decision to the assunto's concepts; re-running resumes the pending",
    )
    run_all_cmd = commands.add_parser("run-all")
    run_all_cmd.add_argument("assunto", choices=sorted(ANCHORS))
    run_all_cmd.add_argument(
        "--enrich", action="store_true", help="also link the leis and decisions to the concepts"
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
    commands.add_parser("report").add_argument("out", nargs="?", type=Path, default=DEFAULT_REPORT)
    for name in ("export-seed", "seed"):
        commands.add_parser(name).add_argument("path", nargs="?", type=Path, default=DEFAULT_SEED)
    args = parser.parse_args(argv)
    load_env()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    if args.command == "refresh-prompts":
        from legal_radar.adapters.prompt_lock import LOCK_PATH, langsmith_fetch, refresh_lock

        lock = refresh_lock(langsmith_fetch)
        print(f"wrote {LOCK_PATH} ({len(lock.prompts)} prompts, {lock.snapshot_hash})")
        return

    if args.command == "report":
        from legal_radar.adapters.prompt_lock import default_lock
        from legal_radar.assayer_harness import RUNS_DIR
        from legal_radar.report import build_report

        if not any(RUNS_DIR.glob("*.json")):
            print(f"warning: no evaluation run in {RUNS_DIR}; the report will be empty")
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(build_report(RUNS_DIR, default_lock()), encoding="utf-8")
        print(f"wrote {args.out}")
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
            from legal_radar.adapters.neo4j_seed import export_seed, load_seed

            if args.command == "export-seed":
                args.path.parent.mkdir(parents=True, exist_ok=True)
                args.path.write_text(export_seed(store.driver), encoding="utf-8")
            else:
                load_seed(store.driver, args.path.read_text(encoding="utf-8"))
            return
        if args.command == "ask":
            from legal_radar.adapters.neo4j_reader import Neo4jGraphReader
            from legal_radar.adapters.router_config import (
                build_router,
                load_config,
                tier_max_context_tokens,
            )
            from legal_radar.application.answer import ask
            from legal_radar.application.assunto import AssuntoResolver

            configure_tracing()
            config = load_config("router.yaml")
            router = build_router(config)
            result = ask(
                args.query,
                AssuntoResolver(router).resolve,
                Neo4jGraphReader(store.driver),
                router,
                max_context_tokens=tier_max_context_tokens(config),
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
            from legal_radar.adapters.router_config import build_router, load_config

            index = rag_index(
                args.chunking,
                Neo4jGraphReader(store.driver),
                build_router(load_config("router.yaml")),
            )
            print(f"{args.chunking}: {len(index.chunks)} chunks embedded with {index.model}")
            return
        if args.command == "eval":
            from legal_radar.adapters.neo4j_reader import Neo4jGraphReader
            from legal_radar.adapters.prompt_lock import default_lock
            from legal_radar.adapters.router_config import (
                build_router,
                load_config,
                tier_max_context_tokens,
            )
            from legal_radar.answer_evaluation import System, UsageMeter, load_questions
            from legal_radar.application.answer import ask
            from legal_radar.application.assunto import AssuntoResolver
            from legal_radar.assayer_harness import Pricing, ragas_llm_from_env
            from legal_radar.eval_runner import run_systems

            publisher = publisher_if_enabled()  # also switches the LangGraph tracing on or off
            config = load_config("router.yaml")
            meter = UsageMeter(build_router(config))
            reader, lock = Neo4jGraphReader(store.driver), default_lock()
            if args.baseline:
                from legal_radar.rag import RagBaseline

                index = rag_index(args.baseline.removeprefix("rag-"), reader, meter)
                systems = [
                    (
                        System(args.baseline, k),
                        RagBaseline(args.baseline, index, meter, k, lock).ask,
                    )
                    for k in args.k
                ]
            else:
                resolve = AssuntoResolver(meter).resolve
                systems = [
                    (
                        System(),
                        lambda query: ask(
                            query,
                            resolve,
                            reader,
                            meter,
                            lock,
                            tier_max_context_tokens(config),
                        ),
                    )
                ]
            run_systems(
                systems,
                load_questions(QUESTION_PATHS[args.assunto]),
                meter,
                lock,
                pricing=Pricing(args.price_in, args.price_out),
                grounding_llm=ragas_llm_from_env() if args.grounding else None,
                fresh=args.fresh,
                publisher=publisher,
                on_report=lambda report, path: print(f"{report.render()}\nwrote {path}"),
                on_resume=lambda system, answered: print(
                    f"{system.label}: resuming with {answered} answers already saved"
                ),
            )
            return
        if args.command == "run-all":
            from legal_radar.adapters.pages import BrowserPageSource
            from legal_radar.adapters.router_config import build_router, load_config
            from legal_radar.adapters.stf import StfFetcher
            from legal_radar.adapters.stj import StjFetcher
            from legal_radar.end_to_end import run_end_to_end

            configure_tracing()
            lei_config = enrich_config(args.assunto) if args.enrich else None
            decision_config = enrich_config(args.assunto, DECISION_PROMPT) if args.enrich else None
            browser = BrowserPageSource()
            chrome = BrowserPageSource(channel="chrome")  # STJ's Cloudflare rejects Chromium
            try:
                result = run_end_to_end(
                    args.assunto,
                    lexml=browser,
                    planalto=browser,
                    fetchers={"STF": StfFetcher(chrome), "STJ": StjFetcher(chrome)},
                    store=store,
                    provider=build_router(load_config("router.yaml")),
                    report_out=DEFAULT_REPORT,
                    seed_out=DEFAULT_SEED,
                    lei_enrichment=lei_config,
                    decision_enrichment=decision_config,
                )
            finally:
                browser.close()
                chrome.close()
                for config in (lei_config, decision_config):
                    if config:
                        config.metadata.close()
            print(result.ingestion.render())
            print(result.jurisprudencia.render())
            print(result.answer.answer or f"no answer for {args.assunto!r}")
            for c in result.answer.citations:
                path = " -> ".join(f"{h.type}({h.target})" for h in c.path) or "anchor"
                print(f"- {c.kind} {c.id}: {path}")
            for report in result.evaluations:
                print(report.render())
            print(f"wrote {result.seed_path} and {result.report_path}")
            return
        if args.command == "draft-concepts":
            from legal_radar.adapters.neo4j_corpus import graph_corpus
            from legal_radar.adapters.router_config import build_router, load_config
            from legal_radar.application.concepts import corpus_ids, draft_candidates, with_assunto

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
            from legal_radar.application.jurisprudencia import ingest_jurisprudencia

            config = enrich_config(args.assunto, DECISION_PROMPT) if args.enrich else None

            browser = BrowserPageSource(
                channel="chrome"
            )  # STJ's Cloudflare rejects bundled Chromium
            try:
                fetchers = {"STF": StfFetcher(browser), "STJ": StjFetcher(browser)}
                report = ingest_jurisprudencia(
                    fetchers, store, JURISPRUDENCIA[args.assunto], enrichment=config
                )
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
            from legal_radar.application.concepts import load_registered

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
