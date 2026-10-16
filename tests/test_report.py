import json
from datetime import UTC, datetime

from legal_radar.domain.model import Confidence, Dispositivo, Origin, Relation, RelationType
from legal_radar.evaluation import Outcome, append_outcome, start_run
from legal_radar.prompts import refresh
from legal_radar.report import build_report, load_enrichment_run, render_report

LEI = "urn:lex:br:federal:lei:2002-01-10;10406"
ART = Dispositivo(f"{LEI}#art50", LEI, "art50", "Em caso de abuso da personalidade jurídica.")
LOCK = refresh({"cited-answer": "c1"}, lambda name, commit: ("Responda {query}", None))
WHEN = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)


def relation(type_, target, evidence):
    return Relation(type_, ART.id, target, Confidence.MEDIUM, Origin.LLM, evidence, None)


def enrichment():
    outcome = Outcome(
        ART,
        [
            relation(RelationType.APPLIES_TO, "abuso", "abuso da personalidade"),
            relation(RelationType.REFERENCES, None, "texto que não está no dispositivo"),
        ],
        dropped=2,
        out_of_vocabulary=["invented_concept"],
    )
    return {"id": "20261013T032054Z", "model": "m1"}, [outcome]


def run(system="graph", k=None):
    return {
        "experiment": f"{system}-20261015T230547Z",
        "system": system,
        "k": k,
        "scores": {"citation_correctness": 0.84, "graph_path": 0.86},
        "prompt_snapshot": "sha256:abc",
        "questions": [
            {
                "id": "requisitos-cc",
                "answer": "Exige abuso <b>da</b> personalidade.",
                "citations": [f"{LEI}#art50", "STJ:1"],
                "citation_paths": {
                    f"{LEI}#art50": [["PARTS", LEI, f"{LEI}#art50"]],
                    "STJ:1": [],
                },
            },
            {"id": "abstain", "answer": "As fontes não bastam.", "citations": []},
        ],
        "input_tokens": 1,
        "output_tokens": 1,
    }


def page(**overrides):
    args = {"enrichment": enrichment(), "runs": [run()], "lock": LOCK, "generated_at": WHEN}
    return render_report(**{**args, **overrides})


def test_it_shows_the_ingestion_statistics_and_the_out_of_vocabulary_terms():
    html = page()

    assert "<b>0.0%</b><span>target-resolved rate" in html
    assert "<b>50.0%</b><span>valid-evidence rate" in html
    assert "<b>50.0%</b><span>drop rate" in html
    assert "invented_concept" in html


def test_it_shows_the_evaluation_metrics_per_system():
    html = page(runs=[run(), run("rag-naive", 5)])

    assert "<th>graph</th><th>rag-naive@5</th>" in html
    assert html.count("</span>0.840") == 2


def test_example_answers_list_each_citation_with_its_graph_path_and_skip_abstentions():
    html = page()

    assert "requisitos-cc" in html and "abstain" not in html
    assert f"<code>{LEI}#art50</code>: PARTS({LEI}#art50)" in html
    assert "<code>STJ:1</code>: anchor" in html


def test_it_embeds_the_prompt_hash_and_the_run_ids():
    html = page()

    assert LOCK.prompt_hash("cited-answer") in html
    assert LOCK.snapshot_hash in html
    assert "20261013T032054Z" in html and "graph-20261015T230547Z" in html
    assert "sha256:abc" in html


def test_it_carries_no_trace_link():
    html = page()

    assert "langchain" not in html and "<a " not in html


def test_model_output_is_escaped():
    assert "<b>da</b>" not in page() and "&lt;b&gt;da&lt;/b&gt;" in page()


def test_a_report_without_runs_still_renders():
    html = page(enrichment=None, runs=[])

    assert "No enrichment run" in html and "No evaluation run recorded" in html


def test_the_report_is_built_from_the_latest_runs_in_a_directory(tmp_path):
    path = start_run(tmp_path, {"model": "m1"}, run_id="20261013T032054Z")
    append_outcome(path, enrichment()[1][0])
    (tmp_path / "graph-1.json").write_text(json.dumps(run()), encoding="utf-8")

    header, outcomes = load_enrichment_run(path)
    html = build_report(tmp_path, LOCK)

    assert header["id"] == "20261013T032054Z" and outcomes == enrichment()[1]
    assert "invented_concept" in html and "graph-20261015T230547Z" in html


def test_it_illustrates_the_pipeline_and_loads_font_awesome():
    html = page()

    assert "How it works" in html and "Knowledge graph" in html and "Cited answer" in html
    assert "font-awesome/6.5.1" in html and 'class="fa-solid' in html


def test_evaluation_comes_first_and_the_glossary_explains_how_to_read_it():
    html = page()

    order = ["Evaluation</h2>", "How it works</h2>", "Ingestion</h2>", "How to read this report"]
    positions = [html.index(marker) for marker in order]
    assert positions == sorted(positions)
    assert "<dt><code>graph_path</code></dt>" in html and "<dt><code>nivel</code></dt>" in html


def test_a_run_from_before_the_paths_were_recorded_says_so_instead_of_anchor():
    old = run()
    del old["questions"][0]["citation_paths"]

    html = page(runs=[old])

    assert "path not recorded" in html and "</code>: anchor" not in html
