"""CLI: `legal-radar run [fixture]` runs the skeleton pipeline with a fake provider;
`legal-radar ingest <assunto>` ingests the assunto's anchor leis from LexML/Planalto;
`legal-radar ingest-jurisprudencia` ingests the seed precedents and top STF/STJ hits;
`legal-radar draft-concepts <assunto>` has an LLM draft concept candidates from the graph's corpus;
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

DEFAULT_SEED = Path(__file__).resolve().parents[2] / "seed" / "graph.jsonl"
DEFAULT_FIXTURE = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "mini_lei.txt"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="legal-radar")
    commands = parser.add_subparsers(dest="command", required=True)
    run_cmd = commands.add_parser("run")
    run_cmd.add_argument("fixture", nargs="?", type=Path, default=DEFAULT_FIXTURE)
    ingest_cmd = commands.add_parser("ingest")
    ingest_cmd.add_argument("assunto", choices=sorted(ANCHORS))
    commands.add_parser("ingest-jurisprudencia")
    draft_cmd = commands.add_parser("draft-concepts")
    draft_cmd.add_argument("assunto", choices=sorted(VOCABULARY_PATHS))
    for name in ("export-seed", "seed"):
        commands.add_parser(name).add_argument("path", nargs="?", type=Path, default=DEFAULT_SEED)
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

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
        if args.command == "draft-concepts":
            from legal_radar.concepts import draft_candidates, graph_corpus
            from legal_radar.router_config import build_router, load_config

            router = build_router(load_config("router.yaml"))
            draft = draft_candidates(args.assunto, graph_corpus(store.driver), router)
            target = VOCABULARY_PATHS[args.assunto].with_suffix(".draft.yml")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(draft, encoding="utf-8")
            print(f"wrote {target}; curate it into {VOCABULARY_PATHS[args.assunto]}")
            return
        if args.command == "ingest":
            from legal_radar.adapters.pages import BrowserPageSource

            browser = BrowserPageSource()
            try:
                print(ingest(ANCHORS[args.assunto], browser, browser, store).render())
            finally:
                browser.close()
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
        batch = run(args.fixture.read_text(encoding="utf-8"), FakeProvider(), store)
    finally:
        store.close()
    print(
        f"wrote {batch.lei.id}: {len(batch.dispositivos)} dispositivos, "
        f"{len(batch.conceitos)} conceitos"
    )


if __name__ == "__main__":
    main()
