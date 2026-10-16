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
and, beside it, `graph.html`, a sample of the knowledge graph around those answers (needs the seed
and an enrichment run), from the latest runs in eval-runs/ (`make publish-report` publishes both
to GitHub Pages);
`legal-radar export-seed [path]` / `legal-radar seed [path]` write / rebuild the versioned seed."""

import argparse
import logging
from pathlib import Path

from legal_radar.adapters.fake_provider import FakeProvider
from legal_radar.adapters.fixture.pipeline import run
from legal_radar.adapters.tracing import configure_tracing, publisher_if_enabled
from legal_radar.application.concepts import VOCABULARY_PATHS
from legal_radar.application.enrichment import DECISION_PROMPT
from legal_radar.application.evaluation.answers import QUESTION_PATHS
from legal_radar.application.ingest import ingest
from legal_radar.application.jurisprudencia import JURISPRUDENCIA
from legal_radar.application.rag import BASELINES, CHUNKINGS
from legal_radar.bootstrap import connect_store, enrich_config, load_settings, rag_index
from legal_radar.domain.anchors import ANCHORS
from legal_radar.settings import Settings


def build_parser(defaults: Settings) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="legal-radar")
    commands = parser.add_subparsers(dest="command", required=True)
    run_cmd = commands.add_parser("run")
    run_cmd.add_argument("fixture", nargs="?", type=Path, default=defaults.fixture_path)
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
    commands.add_parser("report").add_argument(
        "out", nargs="?", type=Path, default=defaults.report_path
    )
    for name in ("export-seed", "seed"):
        commands.add_parser(name).add_argument(
            "path", nargs="?", type=Path, default=defaults.seed_path
        )
    return parser


def print_citations(citations) -> None:
    for c in citations:
        path = " -> ".join(f"{h.type}({h.target})" for h in c.path) or "anchor"
        print(f"- {c.kind} {c.id}: {path}")


def refresh_prompts(args: argparse.Namespace, settings: Settings) -> None:
    from legal_radar.adapters.prompt_lock import LOCK_PATH, langsmith_fetch, refresh_lock

    lock = refresh_lock(langsmith_fetch)
    print(f"wrote {LOCK_PATH} ({len(lock.prompts)} prompts, {lock.snapshot_hash})")


def report(args: argparse.Namespace, settings: Settings) -> None:
    from legal_radar.adapters.prompt_lock import default_lock
    from legal_radar.entrypoints.report_files import write_report

    runs_dir = settings.runs_dir
    if not any(runs_dir.glob("*.json")):
        print(f"warning: no evaluation run in {runs_dir}; the report will be empty")
    for path in write_report(args.out, settings, default_lock()):
        print(f"wrote {path}")


def compare_evals(args: argparse.Namespace, settings: Settings) -> None:
    import json

    from legal_radar.application.evaluation.comparison import latest_runs, render_comparison

    runs = (
        [json.loads(path.read_text(encoding="utf-8")) for path in args.runs]
        if args.runs
        else latest_runs(settings.runs_dir)
    )
    if not runs:
        raise SystemExit(f"no evaluation run to compare in {settings.runs_dir}")
    print(render_comparison(runs))


def seed(args: argparse.Namespace, settings: Settings, store) -> None:
    from legal_radar.adapters.neo4j_seed import export_seed, load_seed

    if args.command == "export-seed":
        args.path.parent.mkdir(parents=True, exist_ok=True)
        args.path.write_text(export_seed(store.driver), encoding="utf-8")
    else:
        load_seed(store.driver, args.path.read_text(encoding="utf-8"))


def ask_command(args: argparse.Namespace, settings: Settings, store) -> None:
    from legal_radar.adapters.neo4j_reader import Neo4jGraphReader
    from legal_radar.adapters.prompt_lock import default_lock
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
        default_lock(),
        max_context_tokens=tier_max_context_tokens(config),
    )
    if result.assunto is None:
        print(f"no known assunto matches {args.query!r}")
    elif result.answer is None:
        print(f"assunto {result.assunto!r} resolved, but the graph has none of its leis")
    else:
        print(result.answer)
    print_citations(result.citations)


def index_rag(args: argparse.Namespace, settings: Settings, store) -> None:
    from legal_radar.adapters.neo4j_reader import Neo4jGraphReader
    from legal_radar.adapters.router_config import build_router, load_config

    index = rag_index(
        settings,
        args.chunking,
        Neo4jGraphReader(store.driver),
        build_router(load_config("router.yaml")),
    )
    print(f"{args.chunking}: {len(index.chunks)} chunks embedded with {index.model}")


def evaluate(args: argparse.Namespace, settings: Settings, store) -> None:
    from legal_radar.adapters.assayer.harness import Pricing, ragas_llm_from_env
    from legal_radar.adapters.assayer.runner import run_systems
    from legal_radar.adapters.neo4j_reader import Neo4jGraphReader
    from legal_radar.adapters.prompt_lock import default_lock
    from legal_radar.adapters.router_config import (
        build_router,
        load_config,
        tier_max_context_tokens,
    )
    from legal_radar.application.answer import ask
    from legal_radar.application.assunto import AssuntoResolver
    from legal_radar.application.evaluation.answers import System, UsageMeter, load_questions

    publisher = publisher_if_enabled()  # also switches the LangGraph tracing on or off
    config = load_config("router.yaml")
    meter = UsageMeter(build_router(config))
    reader, lock = Neo4jGraphReader(store.driver), default_lock()
    if args.baseline:
        from legal_radar.application.rag import RagBaseline

        index = rag_index(settings, args.baseline.removeprefix("rag-"), reader, meter)
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


def run_all(args: argparse.Namespace, settings: Settings, store) -> None:
    from legal_radar.adapters.lexml import LexmlLocator
    from legal_radar.adapters.pages import BrowserPageSource
    from legal_radar.adapters.planalto import PlanaltoTextSource
    from legal_radar.adapters.router_config import build_router, load_config
    from legal_radar.adapters.stf import StfFetcher
    from legal_radar.adapters.stj import StjFetcher
    from legal_radar.entrypoints.end_to_end import run_end_to_end

    configure_tracing()
    lei_config = enrich_config(settings, args.assunto) if args.enrich else None
    decision_config = (
        enrich_config(settings, args.assunto, DECISION_PROMPT) if args.enrich else None
    )
    browser = BrowserPageSource()
    chrome = BrowserPageSource(channel="chrome")  # STJ's Cloudflare rejects Chromium
    try:
        result = run_end_to_end(
            args.assunto,
            locator=LexmlLocator(browser),
            texts=PlanaltoTextSource(browser),
            fetchers={"STF": StfFetcher(chrome), "STJ": StjFetcher(chrome)},
            store=store,
            provider=build_router(load_config("router.yaml")),
            report_out=settings.report_path,
            seed_out=settings.seed_path,
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
    print_citations(result.answer.citations)
    for evaluation in result.evaluations:
        print(evaluation.render())
    print(f"wrote {result.seed_path} and {result.report_path}")


def draft_concepts(args: argparse.Namespace, settings: Settings, store) -> None:
    from legal_radar.adapters.neo4j_corpus import graph_corpus
    from legal_radar.adapters.prompt_lock import default_lock
    from legal_radar.adapters.router_config import build_router, load_config
    from legal_radar.application.concepts import corpus_ids, draft_candidates, with_assunto

    router = build_router(load_config("router.yaml"))
    corpus = graph_corpus(store.driver)
    drafted = draft_candidates(args.assunto, corpus, router, default_lock())
    draft, error = with_assunto(args.assunto, drafted, corpus_ids(corpus))
    target = VOCABULARY_PATHS[args.assunto].with_suffix(".draft.yml")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(draft, encoding="utf-8")
    if error:
        print(f"warning: the draft does not load yet: {error}")
    print(f"wrote {target}; curate it into {VOCABULARY_PATHS[args.assunto]}")


def ingest_leis(args: argparse.Namespace, settings: Settings, store) -> None:
    from legal_radar.adapters.lexml import LexmlLocator
    from legal_radar.adapters.pages import BrowserPageSource
    from legal_radar.adapters.planalto import PlanaltoTextSource

    config = enrich_config(settings, args.assunto) if args.enrich else None
    browser = BrowserPageSource()
    try:
        ingested = ingest(
            ANCHORS[args.assunto],
            LexmlLocator(browser),
            PlanaltoTextSource(browser),
            store,
            enrichment=config,
        )
        print(ingested.render())
    finally:
        browser.close()
        if config:
            config.metadata.close()


def ingest_decisions(args: argparse.Namespace, settings: Settings, store) -> None:
    from legal_radar.adapters.pages import BrowserPageSource
    from legal_radar.adapters.stf import StfFetcher
    from legal_radar.adapters.stj import StjFetcher
    from legal_radar.application.jurisprudencia import ingest_jurisprudencia

    config = enrich_config(settings, args.assunto, DECISION_PROMPT) if args.enrich else None

    browser = BrowserPageSource(channel="chrome")  # STJ's Cloudflare rejects bundled Chromium
    try:
        fetchers = {"STF": StfFetcher(browser), "STJ": StjFetcher(browser)}
        result = ingest_jurisprudencia(
            fetchers, store, JURISPRUDENCIA[args.assunto], enrichment=config
        )
        print(result.render())
        if result.failed:
            raise SystemExit(1)
    finally:
        browser.close()
        if config:
            config.metadata.close()


def run_skeleton(args: argparse.Namespace, settings: Settings, store):
    ids = None
    if args.assunto:
        from legal_radar.application.concepts import load_registered

        ids = [c.id for c in load_registered(args.assunto).conceitos]
    return run(args.fixture.read_text(encoding="utf-8"), FakeProvider(), store, conceito_ids=ids)


# Commands that need no graph store.
OFFLINE = {
    "refresh-prompts": refresh_prompts,
    "report": report,
    "compare-evals": compare_evals,
}
# Commands that run against the Neo4j store.
ONLINE = {
    "export-seed": seed,
    "seed": seed,
    "ask": ask_command,
    "index-rag": index_rag,
    "eval": evaluate,
    "run-all": run_all,
    "draft-concepts": draft_concepts,
    "ingest": ingest_leis,
    "ingest-jurisprudencia": ingest_decisions,
}


def main(argv: list[str] | None = None) -> None:
    args = build_parser(Settings()).parse_args(argv)
    settings = load_settings()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    if args.command in OFFLINE:
        OFFLINE[args.command](args, settings)
        return

    store = connect_store(settings)
    try:
        if args.command in ONLINE:
            ONLINE[args.command](args, settings, store)
            return
        batch = run_skeleton(args, settings, store)
    finally:
        store.close()
    print(
        f"wrote {batch.lei.id}: {len(batch.dispositivos)} dispositivos, "
        f"{len(batch.conceitos)} conceitos"
    )
