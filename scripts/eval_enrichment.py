"""Score the enrichment (rules + LLM) of the anchor slice against a gold set and apply the gates.

Usage: eval_enrichment.py GOLD.yml [--provider gemini|groq|lmstudio] [--persist DIR]
                          [--thresholds evaluation.yml]

Runs the rules and the LLM over the Planalto excerpts under `tests/fixtures/planalto`, scores the
dispositivos listed in the gold set per edge (split by origin and relation type), prints the
indirect metrics and exits non-zero when a gate fails. `--persist` keeps every input and output as
JSONL for audit. The gold set itself is annotated by a human (#67).
"""

import argparse
import sys
from pathlib import Path

from legal_radar.__main__ import load_env
from legal_radar.concepts import load_vocabulary
from legal_radar.enricher import ENRICHMENT_PROMPT, ENRICHMENT_TEMPLATE
from legal_radar.evaluation import (
    check_gates,
    enrich_dispositivos,
    indirect_metrics,
    load_gold,
    load_thresholds,
    persist_run,
    score_edges,
)
from legal_radar.planalto import decode_html, parse_planalto
from legal_radar.prompts import refresh
from legal_radar.router_config import build_router, enrichment_max_input_tokens, load_config

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "planalto"
LEIS = (
    ("l10406_excerpt.htm", "urn:lex:br:federal:lei:2002-01-10;10406"),
    ("l8078_excerpt.htm", "urn:lex:br:federal:lei:1990-09-11;8078"),
)


def fmt(value: float | None) -> str:
    return "  n/a" if value is None else f"{value:5.2f}"


def main(args: argparse.Namespace) -> int:
    load_env()
    config = load_config(ROOT / "router.yaml")
    config["providers"] = [args.provider]
    router = build_router(config)
    vocabulary = load_vocabulary(ROOT / "concepts" / "desconsideracao_personalidade.draft.yml")
    lock = refresh({ENRICHMENT_PROMPT: "local"}, lambda name, commit: (ENRICHMENT_TEMPLATE, None))
    gold = load_gold(args.gold.read_text(encoding="utf-8"))

    dispositivos = [
        d
        for filename, lei_id in LEIS
        for d in parse_planalto(decode_html((FIXTURES / filename).read_bytes()), lei_id)
    ]
    missing = set(gold) - {d.id for d in dispositivos}
    if missing:
        print(f"gold dispositivos not in the slice: {sorted(missing)}", file=sys.stderr)
        return 2
    outcomes = enrich_dispositivos(
        dispositivos,
        vocabulary,
        router,
        lock,
        max_input_tokens=enrichment_max_input_tokens(config),
    )
    scored = [o for o in outcomes if o.dispositivo.id in gold]
    scores, indirect = score_edges(scored, gold), indirect_metrics(scored)
    failures = check_gates(scores, indirect, load_thresholds(args.thresholds))

    print(f"{'origin':6} {'type':11} {'tp':>3} {'fp':>3} {'fn':>3}  prec   rec    f1")
    for (origin, type_), s in sorted(scores.items(), key=lambda kv: tuple(map(str, kv[0]))):
        print(
            f"{origin:6} {type_:11} {s.tp:3} {s.fp:3} {s.fn:3}  "
            f"{fmt(s.precision)} {fmt(s.recall)} {fmt(s.f1)}"
        )
    print(
        f"\ntarget-resolved {fmt(indirect.target_resolved_rate)}  "
        f"valid-evidence {fmt(indirect.valid_evidence_rate)}  drop {fmt(indirect.drop_rate)}"
    )
    if args.persist:
        path = persist_run(
            args.persist, scored, {"provider": args.provider, "gold": str(args.gold)}
        )
        print(f"persisted {path}")
    for f in failures:
        print(f"GATE FAILED [{f.gate}]: {f.reason}")
    return 1 if failures else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("gold", type=Path)
    parser.add_argument("--provider", default="gemini", choices=["gemini", "groq", "lmstudio"])
    parser.add_argument("--persist", type=Path)
    parser.add_argument("--thresholds", type=Path, default=ROOT / "evaluation.yml")
    sys.exit(main(parser.parse_args()))
