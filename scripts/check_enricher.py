"""Live check of the LLM enricher: CC art. 50 and CDC art. 28 against the draft vocabulary.

Usage: check_enricher.py [gemini|groq|lmstudio] (default gemini); Gemini needs GEMINI_API_KEY
(read from the environment or `.env`). Uses the template shipped in `legal_radar.enricher`, not the
Hub, and prints per dispositivo whether the reply followed the schema, what was dropped and why,
the tokens spent and the edges produced. It does not measure quality: that is the gold set (#28).
"""

import sys
from pathlib import Path

from legal_radar.__main__ import load_env
from legal_radar.adapters.planalto import decode_html, parse_planalto
from legal_radar.adapters.router_config import (
    build_router,
    enrichment_max_input_tokens,
    load_config,
)
from legal_radar.concepts import load_vocabulary
from legal_radar.enricher import ENRICHMENT_PROMPT, ENRICHMENT_TEMPLATE, candidate_targets, enrich
from legal_radar.prompts import refresh
from legal_radar.relations import extract_relations

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "planalto"
SLICES = (
    ("l10406_excerpt.htm", "urn:lex:br:federal:lei:2002-01-10;10406", "art50"),
    ("l8078_excerpt.htm", "urn:lex:br:federal:lei:1990-09-11;8078", "art28"),
)


def main(provider: str) -> int:
    load_env()
    config = load_config(ROOT / "router.yaml")
    config["providers"] = [provider]
    router = build_router(config)
    max_input_tokens = enrichment_max_input_tokens(config)
    vocabulary = load_vocabulary(ROOT / "concepts" / "desconsideracao_personalidade.draft.yml")
    lock = refresh({ENRICHMENT_PROMPT: "local"}, lambda name, commit: (ENRICHMENT_TEMPLATE, None))

    totals = {"calls": 0, "failed": 0, "dropped": 0, "edges": 0, "tokens_in": 0, "tokens_out": 0}
    for filename, lei_id, root in SLICES:
        everything = parse_planalto(decode_html((FIXTURES / filename).read_bytes()), lei_id)
        by_id = {d.id: d for d in everything}
        candidates = candidate_targets(everything)
        for d in everything:
            if d.path != root and not d.path.startswith(root + "_"):
                continue
            ancestors, parent = [], by_id.get(d.parent_id or "")
            while parent:
                ancestors.insert(0, parent)
                parent = by_id.get(parent.parent_id or "")
            unresolved = [r for r in extract_relations(d).relations if r.unresolved]
            result = enrich(
                d, vocabulary, router, lock,
                ancestors=ancestors, unresolved=unresolved, candidates=candidates,
                max_input_tokens=max_input_tokens,
            )  # fmt: skip
            print(f"\n{d.id}  [{d.kind}]")
            if result.skipped:
                print(f"  skipped: {result.skipped}")
                continue
            totals["calls"] += 1
            totals["failed"] += bool(result.failed)
            totals["dropped"] += result.dropped
            totals["edges"] += len(result.relations)
            totals["tokens_in"] += result.tokens_in
            totals["tokens_out"] += result.tokens_out
            print(
                f"  schema: {'FAILED ' + result.failed if result.failed else 'ok'}; "
                f"dropped {result.dropped}; out-of-vocabulary {result.out_of_vocabulary}; "
                f"tokens {result.tokens_in}/{result.tokens_out}"
            )
            for r in result.relations:
                print(f"  {r.type.value:10} -> {r.target_id}  «{r.evidence}»")
    print(f"\ntotals: {totals}")
    return 1 if totals["failed"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "gemini"))
