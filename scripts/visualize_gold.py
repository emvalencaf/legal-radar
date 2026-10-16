"""Render the enrichment gold set (or its proposal) as one self-contained, read-only HTML graph.

Usage: visualize_gold.py [--out evaluation/gold.html] [FILE ...]

Provisions sit in the left column, grouped by statute; the curated concepts in the right column,
grouped by category; an edge joins them, coloured by relation type. `REFERENCES` arcs stay on the
left. Several files can be loaded and switched in the page (default: the proposal, the gold and
the review progress, whichever exist). Click a provision or a concept to isolate its edges; the
side panel shows the text and how each edge was reviewed. Concepts without any edge are greyed
out, which is where vocabulary gaps and dead concepts show.
"""

import argparse
import json
import sys
from pathlib import Path

import yaml

from legal_radar.adapters.planalto import decode_html, parse_planalto
from legal_radar.application.concepts import load_vocabulary

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "planalto"
STATUTES = (
    ("l10406_excerpt.htm", "urn:lex:br:federal:lei:2002-01-10;10406", "Código Civil"),
    ("l8078_excerpt.htm", "urn:lex:br:federal:lei:1990-09-11;8078", "CDC"),
)
DEFAULTS = ("enrichment_gold.proposed.yml", "enrichment_gold.progress.yml", "enrichment_gold.yml")


def load_set(path: Path) -> list[dict]:
    document = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    return document["dispositivos"] if isinstance(document, dict) else document


def build_data(files: list[Path]) -> dict:
    vocabulary = load_vocabulary(ROOT / "concepts" / "desconsideracao_personalidade.yml")
    provisions = [
        {"id": d.id, "path": d.id.split("#")[1], "kind": d.kind, "text": d.text, "lei": name}
        for filename, statute_id, name in STATUTES
        for d in parse_planalto(decode_html((FIXTURES / filename).read_bytes()), statute_id)
        if d.kind in ("artigo", "paragrafo", "inciso", "alinea")
    ]
    return {
        "concepts": [
            {"id": c.id, "label": c.label, "category": c.category, "hint": c.instructions}
            for c in vocabulary.concepts
        ],
        "dispositivos": provisions,
        "sets": {f.name: load_set(f) for f in files},
    }


TEMPLATE = Path(__file__).with_suffix(".template.html")


def main(args: argparse.Namespace) -> int:
    files = args.files or [
        ROOT / "evaluation" / n for n in DEFAULTS if (ROOT / "evaluation" / n).exists()
    ]
    if not files:
        print("no gold file to show", file=sys.stderr)
        return 2
    page = TEMPLATE.read_text(encoding="utf-8").replace(
        "__DATA__", json.dumps(build_data(files), ensure_ascii=False).replace("</", "<\\/")
    )
    args.out.write_text(page, encoding="utf-8")
    print(f"{args.out} ({', '.join(f.name for f in files)})")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("files", nargs="*", type=Path)
    parser.add_argument("--out", type=Path, default=ROOT / "evaluation" / "gold.html")
    sys.exit(main(parser.parse_args()))
