"""CLI: `legal-radar run [fixture]` runs the skeleton pipeline with a fake provider;
`legal-radar ingest <assunto>` ingests the assunto's anchor leis from LexML/Planalto;
`legal-radar ingest-jurisprudencia` ingests the seed precedents and top STF/STJ hits."""

import argparse
import logging
import os
from pathlib import Path

from legal_radar.adapters.fake_provider import FakeProvider
from legal_radar.adapters.neo4j_store import Neo4jGraphStore
from legal_radar.anchors import ANCHORS
from legal_radar.ingest import ingest
from legal_radar.pipeline import run

DEFAULT_FIXTURE = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "mini_lei.txt"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="legal-radar")
    commands = parser.add_subparsers(dest="command", required=True)
    run_cmd = commands.add_parser("run")
    run_cmd.add_argument("fixture", nargs="?", type=Path, default=DEFAULT_FIXTURE)
    ingest_cmd = commands.add_parser("ingest")
    ingest_cmd.add_argument("assunto", choices=sorted(ANCHORS))
    commands.add_parser("ingest-jurisprudencia")
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
