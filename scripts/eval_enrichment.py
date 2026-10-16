"""Score the enrichment (rules + LLM) of the anchor slice against a gold set and apply the gates.

Usage: eval_enrichment.py GOLD.yml [--provider groq|gemini|lmstudio] [--model NAME]
                          [--timeout SECONDS] [--persist DIR] [--resume RUNFILE]
                          [--thresholds evaluation.yml]

Runs the rules and the LLM over the Planalto excerpts under `tests/fixtures/planalto`, scores the
dispositivos listed in the gold set per edge (split by origin and relation type), prints the
indirect metrics and exits non-zero when a gate fails. Every input and output is written to a JSONL
run file under `--persist` (default `eval-runs/`) as each dispositivo finishes, so a rate limit or a
crash loses nothing: `--resume RUNFILE` continues it (same provider, model and vocabulary). The
gold set itself is annotated by a human (#67).
"""

import argparse
import os
import sys
import time
from pathlib import Path

from legal_radar.__main__ import load_env
from legal_radar.adapters.planalto import decode_html, parse_planalto
from legal_radar.adapters.prompt_lock import refresh
from legal_radar.adapters.router_config import (
    build_router,
    enrichment_max_input_tokens,
    load_config,
)
from legal_radar.application.concepts import load_vocabulary
from legal_radar.application.enricher import ENRICHMENT_PROMPT, ENRICHMENT_TEMPLATE
from legal_radar.domain.llm import AllProvidersFailedError
from legal_radar.evaluation import (
    append_outcome,
    check_gates,
    enrich_dispositivos,
    indirect_metrics,
    load_gold,
    load_thresholds,
    read_run,
    score_edges,
    start_run,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "planalto"
LEIS = (
    ("l10406_excerpt.htm", "urn:lex:br:federal:lei:2002-01-10;10406"),
    ("l8078_excerpt.htm", "urn:lex:br:federal:lei:1990-09-11;8078"),
)


def fmt(value: float | None) -> str:
    return "  n/a" if value is None else f"{value:5.2f}"


def clock(seconds: float) -> str:
    return f"{int(seconds) // 60}:{int(seconds) % 60:02d}"


def start_printer(already: int, grand_total: int):
    def show(position: int, total: int, d) -> None:
        """Announce a dispositivo before it is sent: a slow model shows nothing for minutes."""
        width = len(str(grand_total))
        print(
            f"[{already + position:>{width}}/{grand_total}] {d.id.split('#')[1]:<20} sending...",
            file=sys.stderr,
            flush=True,
        )

    return show


def progress_printer(started: float, already: int, grand_total: int, path: Path):
    """One line per dispositivo: position, what it yielded and the time left at this pace.

    Each finished dispositivo is also appended to the run file, so a failure loses nothing.
    """

    def show(done: int, total: int, outcome) -> None:
        append_outcome(path, outcome)
        elapsed = time.monotonic() - started
        eta = elapsed / done * (total - done)
        note = outcome.skipped or outcome.failed
        tokens = outcome.tokens_in + outcome.tokens_out
        print(
            f"[{already + done:>{len(str(grand_total))}}/{grand_total}] "
            f"{outcome.dispositivo.id.split('#')[1]:<20} "
            f"{len(outcome.relations):>2} relations  {tokens:>6} tok"
            f"  elapsed {clock(elapsed)}  eta {clock(eta)}" + (f"  [{note}]" if note else ""),
            file=sys.stderr,
            flush=True,
        )

    return show


def main(args: argparse.Namespace) -> int:
    load_env()
    os.environ.setdefault("LLM_TIMEOUT_SECONDS", str(args.timeout))
    config = load_config(ROOT / "router.yaml")
    config["providers"] = [args.provider]
    if args.model:
        config["models"] = {**(config.get("models") or {}), args.provider: args.model}
    model = (config.get("models") or {}).get(args.provider, "default")
    print(f"provider {args.provider}, model {model}", file=sys.stderr)
    router = build_router(config)
    vocabulary = load_vocabulary(ROOT / "concepts" / "desconsideracao_personalidade.yml")
    lock = refresh({ENRICHMENT_PROMPT: "local"}, lambda name, commit: (ENRICHMENT_TEMPLATE, None))
    gold = load_gold(args.gold.read_text(encoding="utf-8"), vocabulary)

    dispositivos = [
        d
        for filename, lei_id in LEIS
        for d in parse_planalto(decode_html((FIXTURES / filename).read_bytes()), lei_id)
    ]
    missing = set(gold) - {d.id for d in dispositivos}
    if missing:
        print(f"gold dispositivos not in the slice: {sorted(missing)}", file=sys.stderr)
        return 2
    header = {
        "provider": args.provider,
        "model": model,
        "gold": str(args.gold),
        "vocabulary": vocabulary.hash,
    }
    done: list = []
    if args.resume:
        previous, done = read_run(args.resume, {d.id: d for d in dispositivos})
        stale = [k for k in ("provider", "model", "vocabulary") if previous.get(k) != header[k]]
        if stale:
            print(f"cannot resume: {', '.join(stale)} changed since that run", file=sys.stderr)
            return 2
        path = args.resume
        print(f"resuming {path}: {len(done)} of {len(gold)} already done", file=sys.stderr)
    else:
        path = start_run(args.persist, header)
        print(f"writing {path}", file=sys.stderr)
    todo = set(gold) - {o.dispositivo.id for o in done}
    started = time.monotonic()
    try:
        outcomes = done + enrich_dispositivos(
            dispositivos,
            vocabulary,
            router,
            lock,
            max_input_tokens=enrichment_max_input_tokens(config),
            only=todo,
            on_start=start_printer(len(done), len(gold)),
            on_progress=progress_printer(started, len(done), len(gold), path),
        )
    except (AllProvidersFailedError, KeyboardInterrupt) as error:
        reason = str(error) or type(error).__name__
        print(f"\nstopped: {reason}\nwhat was done is saved. Resume with:", file=sys.stderr)
        print(
            f"  {sys.argv[0]} {args.gold} --provider {args.provider} --model {model} "
            f"--resume {path}",
            file=sys.stderr,
        )
        return 3
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
    print(f"run file {path}")
    for f in failures:
        print(f"GATE FAILED [{f.gate}]: {f.reason}")
    return 1 if failures else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("gold", type=Path)
    parser.add_argument("--provider", default="groq", choices=["groq", "gemini", "lmstudio"])
    parser.add_argument("--model", help="model name; defaults to `models` in router.yaml")
    parser.add_argument(
        "--timeout", type=int, default=600, help="seconds per LLM call (local models are slow)"
    )
    parser.add_argument(
        "--persist", type=Path, default=ROOT / "eval-runs", help="directory of the run file"
    )
    parser.add_argument("--resume", type=Path, help="run file to continue after a failure")
    parser.add_argument("--thresholds", type=Path, default=ROOT / "evaluation.yml")
    sys.exit(main(parser.parse_args()))
