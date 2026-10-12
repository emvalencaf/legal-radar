"""Wizard: review the proposed enrichment gold set one dispositivo at a time (#67).

Usage: annotate_gold.py [--proposed evaluation/enrichment_gold.proposed.yml]
                        [--gold evaluation/enrichment_gold.yml]

Shows each dispositivo with the relations Claude Code proposed and asks you to accept, correct or
reject each one, then to add what it missed. There is no way to skip a dispositivo: an empty answer
confirms a negative. Progress is saved after every dispositivo (re-run to resume); the gold file is
written once all are reviewed, with how each edge came to be (accepted, corrected, added). The
metrics measure agreement with a single annotator, not absolute truth.
"""

import argparse
import sys
from pathlib import Path

import yaml

from legal_radar.concepts import load_vocabulary
from legal_radar.domain import RelationType
from legal_radar.enricher import CONCEPT_RELATIONS
from legal_radar.evaluation import load_gold
from legal_radar.gold_review import review_all
from legal_radar.planalto import decode_html, parse_planalto

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "planalto"
LEIS = (
    ("l10406_excerpt.htm", "urn:lex:br:federal:lei:2002-01-10;10406"),
    ("l8078_excerpt.htm", "urn:lex:br:federal:lei:1990-09-11;8078"),
)
TYPES = [t.value for t in RelationType]
CONCEPT_TYPES = {t.value for t in CONCEPT_RELATIONS}
BOLD, DIM, RESET = ("\033[1m", "\033[2m", "\033[0m") if sys.stdout.isatty() else ("", "", "")


def show(edge: dict) -> str:
    return f"{edge['type']} -> {edge.get('target') or edge.get('source')}"


def parse_edge(line: str, concepts: set[str]) -> dict | None:
    """`TYPE target` -> an edge, or `None` when it is not valid.

    A concept relation targets a curated concept id, a `REFERENCES` a dispositivo id, and for a
    `REVOKES` the `target` typed is the revoking act (the dispositivo itself is the target).
    """
    parts = line.split()
    if len(parts) != 2 or parts[0].upper() not in TYPES:
        return None
    type_, target = parts[0].upper(), parts[1]
    if type_ == "REVOKES":  # the dispositivo is the target; the revoking act is the source
        return {"type": type_, "source": target}
    valid = target in concepts if type_ in CONCEPT_TYPES else "#" in target
    return {"type": type_, "target": target} if valid else None


def main(args: argparse.Namespace) -> int:
    vocabulary = load_vocabulary(ROOT / "concepts" / "desconsideracao_personalidade.yml")
    concepts = {c.id for c in vocabulary.conceitos}
    dispositivos = {
        d.id: d
        for filename, lei_id in LEIS
        for d in parse_planalto(decode_html((FIXTURES / filename).read_bytes()), lei_id)
    }
    proposed = yaml.safe_load(args.proposed.read_text(encoding="utf-8"))
    if proposed.get("vocabulary_hash") != vocabulary.hash:
        print("the proposal was made against another vocabulary: regenerate it", file=sys.stderr)
        return 2
    progress = args.gold.with_suffix(".progress.yml")
    done = (yaml.safe_load(progress.read_text("utf-8")) or []) if progress.exists() else []
    total = len(proposed["dispositivos"])

    def save(reviewed: list[dict]) -> None:
        progress.write_text(yaml.safe_dump(reviewed, allow_unicode=True, sort_keys=False), "utf-8")

    def decide(entry: dict, edge: dict) -> dict | None:
        if edge:
            print(f"\n  {BOLD}proposed:{RESET} {show(edge)}")
            answer = ""
            while answer not in ("a", "c", "r"):
                answer = input("  [a]ccept  [c]orrect  [r]eject > ").strip().lower()
            if answer != "c":
                return edge if answer == "a" else None
        while True:
            line = input(
                "  correct to TYPE target > " if edge else "  add TYPE target (empty = done) > "
            )
            if not line.strip() and not edge:
                return None
            if new := parse_edge(line, concepts):
                return new
            print("  expected two fields: TYPE target, e.g. `DEFINES consumidor`")
            print(f"  types: {', '.join(TYPES)}")
            print("  target: a curated concept id (or a dispositivo id for REFERENCES)")

    for index, entry in enumerate(proposed["dispositivos"], 1):
        if entry["id"] in {e["id"] for e in done}:
            continue  # reviewed in an earlier run
        d = dispositivos[entry["id"]]
        print(f"\n{BOLD}[{index}/{total}] {d.id.split('#')[1]}{RESET}  ({d.kind})\n\n  {d.text}")
        if entry.get("note"):
            print(f"  {DIM}note: {entry['note']}{RESET}")
        if not entry["edges"]:
            print(f"  {DIM}proposed: nothing (a negative){RESET}")
        done = review_all([entry], done, decide, save)
    document = {"vocabulary_hash": vocabulary.hash, "dispositivos": done}
    args.gold.write_text(
        yaml.safe_dump(document, allow_unicode=True, sort_keys=False, width=100), "utf-8"
    )
    load_gold(args.gold.read_text("utf-8"), vocabulary)  # fail now, not at the first eval run
    print(f"\nreviewed {len(done)} dispositivos -> {args.gold}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--proposed", type=Path, default=ROOT / "evaluation/enrichment_gold.proposed.yml"
    )
    parser.add_argument("--gold", type=Path, default=ROOT / "evaluation/enrichment_gold.yml")
    sys.exit(main(parser.parse_args()))
