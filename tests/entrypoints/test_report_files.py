import json
from dataclasses import replace

import pytest
from test_graph_sample import PAR1, seed
from test_report import LOCK, enrichment, run

from legal_radar.application.evaluation.enrichment_gold import append_outcome, start_run
from legal_radar.entrypoints.report_files import write_report
from legal_radar.settings import Settings


@pytest.fixture
def settings(tmp_path):
    runs = tmp_path / "eval-runs"
    runs.mkdir()
    cited = run()
    cited["questions"][0]["citations"] = [PAR1]
    (runs / "graph-1.json").write_text(json.dumps(cited), encoding="utf-8")
    path = start_run(runs, {"model": "m1"}, run_id="20261013T032054Z")
    append_outcome(path, enrichment()[1][0])
    return replace(Settings(), runs_dir=runs, seed_path=tmp_path / "graph.jsonl")


def test_the_graph_page_is_written_next_to_the_report_and_linked(settings, tmp_path):
    settings.seed_path.write_text(seed(), encoding="utf-8")

    written = write_report(tmp_path / "out" / "index.html", settings, LOCK)

    assert [p.name for p in written] == ["index.html", "graph.html"]
    assert 'href="graph.html"' in written[0].read_text(encoding="utf-8")
    graph = written[1].read_text(encoding="utf-8")
    assert "20261013T032054Z" in graph and "cytoscape" in graph.lower()


def test_without_the_seed_the_report_is_still_written_without_the_link(settings, tmp_path):
    warnings = []

    written = write_report(tmp_path / "index.html", settings, LOCK, warnings.append)

    assert [p.name for p in written] == ["index.html"]
    assert "graph.html" not in written[0].read_text(encoding="utf-8")
    assert not (tmp_path / "graph.html").exists()
    assert "the seed" in warnings[0]


def test_without_an_enrichment_run_it_warns_about_it(settings, tmp_path):
    settings.seed_path.write_text(seed(), encoding="utf-8")
    for run_file in settings.runs_dir.glob("enrichment-*.jsonl"):
        run_file.unlink()
    warnings = []

    written = write_report(tmp_path / "index.html", settings, LOCK, warnings.append)

    assert len(written) == 1 and "enrichment run" in warnings[0]


def test_an_invalid_seed_fails(settings, tmp_path):
    settings.seed_path.write_text("not json\n", encoding="utf-8")

    with pytest.raises(ValueError):
        write_report(tmp_path / "index.html", settings, LOCK)
