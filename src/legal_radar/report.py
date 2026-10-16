"""The static HTML report published on GitHub Pages (ADR-0004): ingestion statistics, evaluation
results and example answers with their cited graph paths. It is built from files the pipeline
already leaves in `eval-runs/` and carries the `prompt_hash`, the run ids and the metrics, never a
link to a LangSmith trace (traces are private and expire)."""

import json
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime
from html import escape
from pathlib import Path

from legal_radar.domain.model import Dispositivo
from legal_radar.eval_comparison import METRICS, label, latest_runs
from legal_radar.evaluation import Indirect, Outcome, indirect_metrics, read_run
from legal_radar.prompts import PromptLock

EXAMPLES = 3

FONT_AWESOME = "https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css"

STYLE = """
:root{--bg:#f6f7fb;--card:#fff;--text:#1c2030;--muted:#5d6580;--line:#dfe3ef;--accent:#3b5bdb;
--accent-soft:#e7ecff;--ok:#2b8a3e;--warn:#e67700;--code:#eef0f7}
@media (prefers-color-scheme:dark){:root{--bg:#10131c;--card:#181c29;--text:#e8eaf3;
--muted:#9aa3bf;--line:#2b3148;--accent:#8ea2ff;--accent-soft:#232a4a;--ok:#63d17a;
--warn:#ffa94d;--code:#222840}}
*{box-sizing:border-box}
body{margin:0;font-family:system-ui,-apple-system,"Segoe UI",sans-serif;background:var(--bg);
color:var(--text);line-height:1.55}
main{max-width:64rem;margin:0 auto;padding:0 1rem 3rem}
header.hero{background:linear-gradient(135deg,#27346b,#3b5bdb);color:#fff;padding:2.5rem 1rem}
header.hero div{max-width:64rem;margin:0 auto}
header.hero h1{margin:0 0 .3rem;font-size:2rem}
header.hero p{margin:0;opacity:.85}
h2{margin:2.5rem 0 1rem;font-size:1.4rem;display:flex;gap:.6rem;align-items:center}
h2 i{color:var(--accent)}
h3{margin:1.5rem 0 .5rem;font-size:1.05rem}
.card{background:var(--card);border:1px solid var(--line);border-radius:.8rem;padding:1rem 1.2rem}
.grid{display:grid;gap:1rem;grid-template-columns:repeat(auto-fit,minmax(12rem,1fr))}
.stat{text-align:center}.stat i{font-size:1.4rem;color:var(--accent)}
.stat b{display:block;font-size:2rem;margin:.2rem 0}.stat span{color:var(--muted);font-size:.9rem}
.flow{display:flex;flex-wrap:wrap;gap:.6rem;align-items:stretch;margin:.5rem 0 1rem}
.step{flex:1 1 9rem;background:var(--card);border:1px solid var(--line);border-radius:.8rem;
padding:.8rem;text-align:center;position:relative}
.step i{font-size:1.5rem;color:var(--accent);margin-bottom:.3rem}
.step b{display:block}.step small{color:var(--muted)}
.step:not(:last-child)::after{content:"\\f054";font-family:"Font Awesome 6 Free";font-weight:900;
position:absolute;right:-.75rem;top:50%;transform:translateY(-50%);color:var(--muted);
font-size:.8rem;z-index:1}
.lane{font-size:.85rem;font-weight:600;color:var(--muted);text-transform:uppercase;
letter-spacing:.05em;margin-top:1rem}
table{width:100%;border-collapse:collapse;background:var(--card);border-radius:.8rem;
overflow:hidden;border:1px solid var(--line);margin:.5rem 0 1rem}
th,td{padding:.5rem .8rem;text-align:left;border-bottom:1px solid var(--line)}
th{background:var(--accent-soft)}tr:last-child td{border-bottom:0}
.scroll{overflow-x:auto}
code{background:var(--code);padding:.1rem .35rem;border-radius:.3rem;font-size:.85em;
word-break:break-all}
.bar{display:inline-block;width:5rem;height:.5rem;background:var(--line);border-radius:1rem;
margin-right:.5rem;vertical-align:middle;overflow:hidden}
.bar i{display:block;height:100%;background:var(--accent)}
blockquote{margin:.5rem 0;padding:.7rem 1rem;border-left:4px solid var(--accent);
background:var(--accent-soft);border-radius:0 .5rem .5rem 0}
ul.cites{list-style:none;padding:0;margin:.5rem 0}
ul.cites li{margin:.3rem 0}ul.cites i{color:var(--accent);margin-right:.4rem}
.pill{display:inline-block;background:var(--accent-soft);color:var(--accent);border-radius:1rem;
padding:.05rem .6rem;font-size:.8rem;margin:.1rem}
.muted{color:var(--muted)}
.stack{display:grid;gap:1rem}
dl{margin:0}dt{margin-top:.6rem}dd{margin:.15rem 0 0 1rem;color:var(--muted)}
"""

PIPELINE = (
    ("fa-file-lines", "Ingest", "Planalto and LexML pages, STF/STJ decisions"),
    ("fa-sitemap", "Parse", "Split each lei into dispositivos (artigo, parágrafo, inciso)"),
    ("fa-scale-balanced", "Rules", "Deterministic REFERENCES, REVOKES, PARTS edges"),
    (
        "fa-wand-magic-sparkles",
        "LLM enrich",
        "Link chunks to the assunto's concepts, with evidence",
    ),
    ("fa-diagram-project", "Knowledge graph", "Neo4j, seeded from a versioned file"),
)
QUERY = (
    ("fa-magnifying-glass", "Question", "Free-text legal question"),
    ("fa-tags", "Resolve assunto", "Match the question to a known topic"),
    ("fa-route", "Traverse", "Walk PARTS then REFERENCES from the anchor lei"),
    ("fa-quote-right", "Cited answer", "LLM answers only from the retrieved sources"),
    ("fa-chart-column", "Evaluate", "Citations, graph paths, grounding, abstention"),
)


def latest_enrichment_run(directory: Path) -> Path | None:
    """The newest `enrichment-*.jsonl` run file (the names sort by their UTC stamp)."""
    return max(directory.glob("enrichment-*.jsonl"), default=None)


def load_enrichment_run(path: Path) -> tuple[dict, list[Outcome]]:
    """The header and the outcomes of an enrichment run file, rebuilt from what it recorded."""
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    dispositivos = {}
    for line in lines[1:]:
        i = line["input"]
        dispositivos[i["id"]] = Dispositivo(
            i["id"],
            i["lei_id"],
            i["path"],
            i["text"],
            kind=i["kind"],
            revocations=tuple(i.get("revocations", ())),
        )
    return read_run(path, dispositivos)


def _rate(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1%}"


def _cell(value: float | None) -> str:
    """A score in 0..1 as its number and a bar; `n/a` when it does not apply."""
    if value is None:
        return '<span class="muted">n/a</span>'
    width = max(0.0, min(1.0, value)) * 100
    return f'<span class="bar"><i style="width:{width:.0f}%"></i></span>{value:.3f}'


def _table(header: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    head = "".join(f"<th>{escape(h)}</th>" for h in header)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows)
    return f'<div class="scroll"><table><tr>{head}</tr>{body}</table></div>'


def _section(icon: str, title: str, body: str) -> str:
    return f'<h2><i class="fa-solid {icon}"></i>{escape(title)}</h2>{body}'


def _flow(steps: Sequence[tuple[str, str, str]]) -> str:
    return (
        '<div class="flow">'
        + "".join(
            f'<div class="step"><i class="fa-solid {icon}"></i><b>{escape(name)}</b>'
            f"<small>{escape(note)}</small></div>"
            for icon, name, note in steps
        )
        + "</div>"
    )


def _how_it_works() -> str:
    return _section(
        "fa-circle-nodes",
        "How it works",
        '<p class="muted">Legal Radar turns a legal topic into a knowledge graph, then answers '
        "questions by walking the graph instead of searching loose text.</p>"
        f'<div class="lane">Build the graph (offline)</div>{_flow(PIPELINE)}'
        f'<div class="lane">Answer and evaluate (query time)</div>{_flow(QUERY)}',
    )


GLOSSARY = (
    (
        "Evaluation",
        (
            (
                "system",
                "What answered the questions: <code>graph</code> walks the knowledge graph; "
                "<code>rag-naive</code> and <code>rag-contextual</code> are pure-RAG baselines "
                "without a graph, and <code>@k</code> is how many chunks they retrieve.",
            ),
            (
                "citation_correctness",
                "How well the cited sources match the ones a correct answer "
                "cites (F1 of precision and recall, 0 to 1; higher is better).",
            ),
            (
                "citation_correctness_precision",
                "Of the sources the answer cited, the share that is right.",
            ),
            (
                "citation_correctness_recall",
                "Of the sources a correct answer cites, the share the answer actually cited.",
            ),
            (
                "fabricated_citations",
                "Citations of ids that were never retrieved: invented sources. Should be 0.",
            ),
            (
                "grounded_mentions",
                "Share of answers that name no article outside their sources "
                "(1 means every article mentioned was retrieved).",
            ),
            (
                "abstention",
                "On questions the graph cannot answer, the share of answers that admit "
                "the sources fall short instead of answering anyway.",
            ),
            (
                "contradiction_surfaced",
                "On questions whose sources disagree, the share of answers "
                "that cite both sides and point out the disagreement.",
            ),
            (
                "graph_path",
                "How closely the nodes the traversal crossed match the expected ones "
                "(F1). n/a for baselines, which have no graph.",
            ),
            ("n/a", "The metric does not apply to that system or to any of its questions."),
            (
                "nivel",
                "Difficulty of a question (facil, medio, dificil, armadilha); questions "
                "without one are <code>base</code>.",
            ),
            (
                "citation path",
                "The hops walked from the anchor lei to a cited source, as "
                "<code>TYPE(target)</code>. <code>anchor</code> means the source is the anchor "
                "itself.",
            ),
        ),
    ),
    (
        "Ingestion",
        (
            ("dispositivo", "A unit of a lei: artigo, parágrafo, inciso or alínea."),
            (
                "assunto",
                "The legal topic the graph is built around, such as desconsideração da "
                "personalidade jurídica.",
            ),
            (
                "concept",
                "A term of the assunto's curated vocabulary that dispositivos and decisions "
                "are linked to.",
            ),
            (
                "target-resolved rate",
                "Of the references between dispositivos, the share whose target was identified.",
            ),
            (
                "valid-evidence rate",
                "Of the edges, the share whose evidence is a literal slice of "
                "the source text. Should be near 100%.",
            ),
            ("drop rate", "Of the items proposed, the share discarded for failing validation."),
            (
                "out-of-vocabulary term",
                "A concept id the LLM proposed that is not in the "
                "vocabulary; it is dropped and listed for curation.",
            ),
        ),
    ),
    (
        "Reproducibility",
        (
            ("run id", "Identifies one execution; the files it wrote carry the same id."),
            (
                "prompt_hash",
                "Fingerprint of one pinned prompt (commit, template and schema). "
                "It changes when that prompt does.",
            ),
            ("snapshot hash", "Fingerprint of all pinned prompts together."),
        ),
    ),
)


def _glossary() -> str:
    groups = "".join(
        f'<div class="card"><h3>{escape(title)}</h3><dl>'
        + "".join(f"<dt><code>{escape(term)}</code></dt><dd>{text}</dd>" for term, text in terms)
        + "</dl></div>"
        for title, terms in GLOSSARY
    )
    return _section(
        "fa-book",
        "How to read this report",
        '<p class="muted">Scores go from 0 to 1 (higher is better) unless noted. The terms '
        f'below are used across the page.</p><div class="stack">{groups}</div>',
    )


def _stat(icon: str, value: str, name: str) -> str:
    return (
        f'<div class="card stat"><i class="fa-solid {icon}"></i><b>{value}</b>'
        f"<span>{escape(name)}</span></div>"
    )


def _ingestion(run: dict, outcomes: list[Outcome]) -> str:
    indirect: Indirect = indirect_metrics(outcomes)
    unknown = Counter(term for o in outcomes for term in o.out_of_vocabulary)
    meta = "".join(
        f'<span class="pill">{escape(str(k))}: <code>{escape(str(v))}</code></span>'
        for k, v in run.items()
    )
    cards = "".join(
        [
            _stat("fa-bullseye", _rate(indirect.target_resolved_rate), "target-resolved rate"),
            _stat("fa-quote-left", _rate(indirect.valid_evidence_rate), "valid-evidence rate"),
            _stat("fa-trash-can", _rate(indirect.drop_rate), "drop rate"),
            _stat("fa-file-lines", str(len(outcomes)), "dispositivos enriched"),
        ]
    )
    terms = (
        _table(
            ["out-of-vocabulary term", "times proposed"],
            [[escape(t), str(n)] for t, n in unknown.most_common()],
        )
        if unknown
        else '<p class="muted">No out-of-vocabulary term was proposed.</p>'
    )
    return _section(
        "fa-database",
        "Ingestion",
        f'<p>Enrichment run {meta}</p><div class="grid">{cards}</div>'
        f"<h3>Out-of-vocabulary terms</h3>{terms}",
    )


def _snapshot(run: dict) -> str:
    return f"<code>{escape(str(run.get('prompt_snapshot') or 'n/a'))}</code>"


def _evaluation(runs: list[dict]) -> str:
    if not runs:
        return _section("fa-chart-column", "Evaluation", "<p>No evaluation run recorded.</p>")
    names = [label(r) for r in runs]
    rows = [[escape(m), *[_cell(r["scores"].get(m)) for r in runs]] for m in METRICS]
    ids = _table(
        ["system", "run id", "prompt snapshot"],
        [[escape(label(r)), f"<code>{escape(r['experiment'])}</code>", _snapshot(r)] for r in runs],
    )
    return _section(
        "fa-chart-column",
        "Evaluation",
        f"<h3>Metrics per system</h3>{_table(['metric', *names], rows)}<h3>Runs</h3>{ids}",
    )


def _examples(runs: list[dict]) -> str:
    graph = next((r for r in runs if r.get("system", "graph") == "graph"), None)
    if graph is None:
        return ""
    answered = [q for q in graph["questions"] if q["citations"]][:EXAMPLES]
    out = []
    for q in answered:
        out.append(f'<div class="card"><h3>{escape(q["id"])}</h3>')
        out.append(f'<blockquote>{escape(q["answer"])}</blockquote><ul class="cites">')
        for cited in q["citations"]:
            hops = q.get("citation_paths", {}).get(cited)
            if hops is None:
                path = "path not recorded"
            else:
                path = " → ".join(f"{escape(t)}({escape(tgt)})" for t, _, tgt in hops) or "anchor"
            out.append(
                f'<li><i class="fa-solid fa-link"></i><code>{escape(cited)}</code>: {path}</li>'
            )
        out.append("</ul></div>")
    return _section("fa-comments", "Example answers", "".join(out))


def _prompts(lock: PromptLock) -> str:
    rows = [
        [escape(n), f"<code>{escape(lock.prompt_hash(n))}</code>"] for n in sorted(lock.prompts)
    ]
    return _section(
        "fa-fingerprint",
        "Prompts",
        f"<p>Snapshot hash: <code>{escape(lock.snapshot_hash)}</code></p>"
        f"{_table(['prompt', 'prompt_hash'], rows)}",
    )


def render_report(
    enrichment: tuple[dict, list[Outcome]] | None,
    runs: list[dict],
    lock: PromptLock,
    generated_at: datetime | None = None,
) -> str:
    """The whole page. `enrichment` is a `load_enrichment_run` result, `runs` the evaluation run
    files (`eval_comparison.latest_runs`)."""
    stamp = (generated_at or datetime.now(UTC)).strftime("%Y-%m-%d %H:%M UTC")
    ingestion = (
        _ingestion(*enrichment)
        if enrichment
        else _section("fa-database", "Ingestion", "<p>No enrichment run.</p>")
    )
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>Legal Radar report</title>"
        f'<link rel="stylesheet" href="{FONT_AWESOME}"><style>{STYLE}</style></head><body>'
        '<header class="hero"><div><h1><i class="fa-solid fa-scale-balanced"></i> Legal Radar</h1>'
        f"<p>Pipeline report · generated {stamp}</p></div></header><main>"
        f"{_evaluation(runs)}{_examples(runs)}{_how_it_works()}{ingestion}"
        f"{_glossary()}{_prompts(lock)}"
        "</main></body></html>"
    )


def build_report(directory: Path, lock: PromptLock) -> str:
    """The report of the latest runs found in `directory` (usually `eval-runs/`)."""
    path = latest_enrichment_run(directory)
    return render_report(load_enrichment_run(path) if path else None, latest_runs(directory), lock)
