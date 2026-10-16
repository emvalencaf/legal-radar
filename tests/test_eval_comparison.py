import json
import os

import pytest

from legal_radar.eval_comparison import latest_runs, render_comparison


def run(system, k, f1, nivel_f1, paths=None):
    return {
        "experiment": f"{system}-{k}",
        "system": system,
        "k": k,
        "scores": {"citation_correctness": f1, "graph_path": paths},
        "by_nivel": {"facil": {"citation_correctness": nivel_f1}, "dificil": {"abstention": 1.0}},
        "questions": [
            {"nivel": "facil", "input_tokens": 100},
            {"nivel": None, "input_tokens": 300},
        ],
        "input_tokens": 100,
        "output_tokens": 10,
    }


RUNS = [
    run("rag-contextual", 15, 0.6, 0.7),
    run("graph", None, 0.8, 0.9, paths=0.5),
    run("rag-naive", 5, 0.4, 0.5),
]


def test_columns_follow_graph_then_naive_then_contextual():
    header = render_comparison(RUNS).splitlines()[2]

    assert header == "| metric | graph | rag-naive@5 | rag-contextual@15 |"


def test_each_metric_is_a_row_and_what_does_not_apply_is_na():
    rows = {line.split(" | ")[0].strip("| "): line for line in render_comparison(RUNS).splitlines()}

    assert rows["citation_correctness"].endswith("| 0.800 | 0.400 | 0.600 |")
    assert rows["graph_path"].endswith("| 0.500 | n/a | n/a |")
    assert rows["tokens in (total)"].endswith("| 100 | 100 | 100 |")


def test_nivel_tables_split_each_metric():
    text = render_comparison(RUNS)

    section = text.split("## citation_correctness per nivel")[1].split("##")[0]
    assert "| facil | 0.900 | 0.500 | 0.700 |" in section
    assert "| dificil | n/a | n/a | n/a |" in section  # no score for that metric in that nivel


def test_a_run_from_before_the_baselines_is_the_graph(tmp_path):
    old = {
        "experiment": "e",
        "scores": {"citation_correctness": 0.5},
        "questions": [],
        "input_tokens": 1,
        "output_tokens": 1,
    }

    assert "| metric | graph |" in render_comparison([old])


def test_latest_runs_keeps_the_newest_per_system_and_k(tmp_path):
    for name, f1, when in (("a", 0.1, 1), ("b", 0.2, 2)):
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(run("rag-naive", 5, f1, 0.0)))
        os.utime(path, (when, when))
    (tmp_path / "other.json").write_text(json.dumps(run("rag-naive", 15, 0.3, 0.0)))
    (tmp_path / "noise.json").write_text("{}")

    got = {
        (r["system"], r["k"]): r["scores"]["citation_correctness"] for r in latest_runs(tmp_path)
    }

    assert got == pytest.approx({("rag-naive", 5): 0.2, ("rag-naive", 15): 0.3})


def test_compare_evals_command_prints_the_table_of_the_given_runs(tmp_path, capsys):
    from legal_radar.__main__ import main

    path = tmp_path / "r.json"
    path.write_text(json.dumps(run("rag-naive", 5, 0.4, 0.5)))

    main(["compare-evals", str(path)])

    assert "| metric | rag-naive@5 |" in capsys.readouterr().out


def test_every_metric_is_split_by_nivel_and_tokens_are_averaged_per_question():
    text = render_comparison(RUNS)

    for metric in ("citation_correctness_precision", "fabricated_citations", "graph_path"):
        assert f"## {metric} per nivel" in text
    rows = {line.split(" | ")[0].strip("| "): line for line in text.splitlines()}
    assert rows["tokens in / question"].endswith("| 200 | 200 | 200 |")
    tokens = text.split("## tokens in per question, per nivel")[1]
    assert "| facil | 100 | 100 | 100 |" in tokens and "| base | 300 | 300 | 300 |" in tokens
