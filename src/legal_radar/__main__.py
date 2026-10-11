"""CLI: `legal-radar run [fixture]` runs the pipeline against Neo4j with a fake provider."""

import argparse
import os
from pathlib import Path

from legal_radar.adapters.fake_provider import FakeProvider
from legal_radar.adapters.neo4j_store import Neo4jGraphStore
from legal_radar.pipeline import run

DEFAULT_FIXTURE = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "mini_lei.txt"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="legal-radar")
    parser.add_argument("command", choices=["run"])
    parser.add_argument("fixture", nargs="?", type=Path, default=DEFAULT_FIXTURE)
    args = parser.parse_args(argv)

    store = Neo4jGraphStore.connect(
        os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
        os.environ.get("NEO4J_USER", "neo4j"),
        os.environ.get("NEO4J_PASSWORD", "legal-radar-dev"),
    )
    try:
        batch = run(args.fixture.read_text(encoding="utf-8"), FakeProvider(), store)
    finally:
        store.close()
    print(
        f"wrote {batch.lei.id}: {len(batch.dispositivos)} dispositivos, "
        f"{len(batch.conceitos)} conceitos"
    )


if __name__ == "__main__":
    main()
