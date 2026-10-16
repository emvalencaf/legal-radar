"""Side-by-side report of evaluation runs: the graph against the RAG baselines (#79), per metric
and per `nivel`. Reads the JSON that `Report.write` leaves in `eval-runs/`."""

import json
from pathlib import Path

from legal_radar.application.evaluation.answers import BASE_NIVEL, System

METRICS = (
    "citation_correctness",
    "citation_correctness_precision",
    "citation_correctness_recall",
    "fabricated_citations",
    "grounded_mentions",
    "abstention",
    "contradiction_surfaced",
    "graph_path",
)
ORDER = {"graph": 0, "rag-naive": 1, "rag-contextual": 2}


def system_of(run: dict) -> System:
    """The system of a run file; one from before the baselines is the graph."""
    return System(run.get("system", "graph"), run.get("k"))


def label(run: dict) -> str:
    return system_of(run).label


def latest_runs(directory: Path) -> list[dict]:
    """The most recent run of each system and k found in `directory`."""
    latest: dict[str, tuple[float, dict]] = {}
    for path in directory.glob("*.json"):
        run = json.loads(path.read_text(encoding="utf-8"))
        if "scores" not in run:
            continue
        mtime = path.stat().st_mtime
        if label(run) not in latest or mtime > latest[label(run)][0]:
            latest[label(run)] = (mtime, run)
    return [run for _, run in latest.values()]


def _sorted(runs: list[dict]) -> list[dict]:
    return sorted(runs, key=lambda r: (ORDER.get(system_of(r).name, 9), system_of(r).k or 0))


def _cell(value) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def _mean_tokens(run: dict, nivel: str | None = None) -> float | None:
    """Mean input tokens per question (the answer only, not the judges), of one nivel or all."""
    tokens = [
        q["input_tokens"]
        for q in run["questions"]
        if "input_tokens" in q and (nivel is None or (q.get("nivel") or BASE_NIVEL) == nivel)
    ]
    return sum(tokens) / len(tokens) if tokens else None


def _tokens_cell(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0f}"


def _table(header: str, columns: list[str], rows: list[tuple[str, list[str]]]) -> list[str]:
    lines = [f"| {header} | {' | '.join(columns)} |", "|---|" + "---|" * len(columns)]
    lines += [f"| {name} | {' | '.join(cells)} |" for name, cells in rows]
    return lines


def render_comparison(runs: list[dict]) -> str:
    """Markdown: one table of every metric per system, then one per metric split by `nivel`.
    A system that lacks a score (not applicable) shows `n/a`."""
    runs = _sorted(runs)
    columns = [label(r) for r in runs]
    out = ["## Overall", ""]
    rows = [(m, [_cell(r["scores"].get(m)) for r in runs]) for m in METRICS]
    rows.append(("questions", [str(len(r["questions"])) for r in runs]))
    rows.append(("tokens in / question", [_tokens_cell(_mean_tokens(r)) for r in runs]))
    rows.append(("tokens in (total)", [str(r["input_tokens"]) for r in runs]))
    rows.append(("tokens out (total)", [str(r["output_tokens"]) for r in runs]))
    out += _table("metric", columns, rows)
    niveis = sorted(
        {n for r in runs for n in r.get("by_nivel", {})}
        | {q.get("nivel") or BASE_NIVEL for r in runs for q in r["questions"]}
    )
    for metric in METRICS:  # every metric is also split by nivel
        out += ["", f"## {metric} per nivel", ""]
        rows = [
            (n, [_cell(r.get("by_nivel", {}).get(n, {}).get(metric)) for r in runs]) for n in niveis
        ]
        out += _table("nivel", columns, rows)
    out += ["", "## tokens in per question, per nivel", ""]
    rows = [(n, [_tokens_cell(_mean_tokens(r, n)) for r in runs]) for n in niveis]
    out += _table("nivel", columns, rows)
    return "\n".join(out)
