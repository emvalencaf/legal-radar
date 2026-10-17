"""Write the static report and, when its inputs exist, the graph sample page next to it."""

from collections.abc import Callable
from pathlib import Path

from legal_radar.adapters.assets import cytoscape_js
from legal_radar.application.evaluation.comparison import latest_runs
from legal_radar.application.evaluation.graph_sample import render_graph_page
from legal_radar.application.evaluation.report import (
    build_report,
    latest_enrichment_run,
    load_enrichment_run,
)
from legal_radar.domain.prompts import PromptLock
from legal_radar.settings import Settings

GRAPH_PAGE = "graph.html"


def write_report(
    out: Path, settings: Settings, lock: PromptLock, warn: Callable[[str], None] = print
) -> list[Path]:
    """Write `out` and `graph.html` beside it; the graph page is skipped, with a warning, when the
    seed or the enrichment run is missing. An invalid input raises."""
    runs_dir = settings.runs_dir
    missing = []
    if not settings.seed_path.is_file():
        missing.append(f"the seed {settings.seed_path}")
    enrichment_path = latest_enrichment_run(runs_dir)
    if enrichment_path is None:
        missing.append(f"an enrichment run in {runs_dir}")

    out.parent.mkdir(parents=True, exist_ok=True)
    written = [out]
    graph_page = None
    if not missing:
        header, outcomes = load_enrichment_run(enrichment_path)
        relations = [r for o in outcomes for r in o.relations]
        graph_page = render_graph_page(
            settings.seed_path.read_text(encoding="utf-8"),
            (str(header.get("id", enrichment_path.stem)), relations),
            latest_runs(runs_dir),
            cytoscape_js(),
        )
    else:
        warn(f"warning: no graph page, missing {' and '.join(missing)}")
    report = build_report(runs_dir, lock, GRAPH_PAGE if graph_page else None)
    out.write_text(report, encoding="utf-8")
    if graph_page:
        graph_path = out.with_name(GRAPH_PAGE)
        graph_path.write_text(graph_page, encoding="utf-8")
        written.append(graph_path)
    return written
