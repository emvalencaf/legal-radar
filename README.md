<a id="readme-top"></a>

<!-- Structure adapted from https://github.com/othneildrew/Best-README-Template -->

<br />
<div align="center">
  <h3 align="center">Legal Radar</h3>

  <p align="center">
    A RAG-based project that ingests a given legal topic (pointing to a law)
    and finds jurisprudence precedents, doctrine, and law amendments via the
    LexML Brasil portal.
    <br />
    <a href="CONTRIBUTING.md"><strong>Explore the docs »</strong></a>
    <br />
    <br />
    <a href="https://github.com/emvalencaf/legal-radar/issues/new">Report Bug</a>
    &middot;
    <a href="https://github.com/emvalencaf/legal-radar/issues/new">Request Feature</a>
  </p>
</div>

<details>
  <summary>Table of Contents</summary>
  <ol>
    <li>
      <a href="#about-the-project">About The Project</a>
      <ul>
        <li><a href="#built-with">Built With</a></li>
      </ul>
    </li>
    <li>
      <a href="#getting-started">Getting Started</a>
      <ul>
        <li><a href="#prerequisites">Prerequisites</a></li>
        <li><a href="#installation">Installation</a></li>
      </ul>
    </li>
    <li><a href="#usage">Usage</a></li>
    <li><a href="#roadmap">Roadmap</a></li>
    <li><a href="#contributing">Contributing</a></li>
    <li><a href="#license">License</a></li>
    <li><a href="#contact">Contact</a></li>
    <li><a href="#acknowledgments">Acknowledgments</a></li>
  </ol>
</details>

## About The Project

A RAG-based project that ingests a given legal topic (pointing to a law) and
finds jurisprudence precedents, doctrine, and law amendments via the
[LexML Brasil](https://www.lexml.gov.br/) portal.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

### Built With

* [Python](https://www.python.org) managed with [uv](https://docs.astral.sh/uv/)
* [ruff](https://docs.astral.sh/ruff/)

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## Getting Started

### Prerequisites

<!-- Tools and versions needed before installing. -->

* [`uv`](https://docs.astral.sh/uv/)

### Installation

1. Clone the repository
   ```bash
   git clone https://github.com/emvalencaf/legal-radar.git
   cd legal-radar
   ```
2. Enable the git hooks
   ```bash
   scripts/setup.sh
   ```

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## Usage

Start Neo4j with docker compose and run the pipeline over the fixture lei:

```bash
scripts/skeleton.sh
```

Ingest the anchor leis of an assunto from LexML/Planalto (needs `uv sync --extra browser` and
`playwright install chromium`, since both sites reject plain HTTP clients):

```bash
uv run legal-radar ingest "desconsideração da personalidade jurídica"
```

Add `--enrich` to also send the chunks the rules left to the LLM (needs the assunto's vocabulary
and a provider in `router.yaml`). Each chunk it sends gets a record in `data/ingestion.sqlite`
(`METADATA_DB` overrides the path); re-running resumes only the chunks that are still `pending`, or
whose text, vocabulary, `dispositivo-enrichment` prompt or extractor version changed.

Ingest the seed precedents (STJ Tema 1210, STF Tema 1232) and the top hits of each court. STJ's
Cloudflare check rejects bundled Chromium, so this needs Google Chrome installed:

```bash
uv run legal-radar ingest-jurisprudencia
```

Add `--enrich` to also link each decision's ementa and tese to the concepts of the assunto (the
`jurisprudencia-enrichment` prompt, pinned in `prompts/`); re-running only sends the pending
decisions.

Export the graph to the versioned seed (`seed/graph.jsonl`, commit it), or rebuild a fresh
Neo4j from it; loading is MERGE-based, so repeating it changes nothing:

```bash
make export-seed
make seed
```

Prompts (and their structured-output schemas) are pinned to LangSmith Hub commits in
`prompts/pins.yml` and read offline from `prompts/lock.json`; the pipeline and tests need no
LangSmith account or network, only a source checkout. To follow new Hub commits, set
`LANGSMITH_API_KEY`, edit the pins and refresh the lockfile (needs the `prompts` extra):

```bash
make refresh-prompts
```

Score the enrichment (rules and LLM) against a hand-validated gold set: per-edge
precision/recall/F1 split by origin and relation type, the indirect metrics (target-resolved,
valid-evidence and drop rates) and the quality gates in `evaluation.yml`. It exits non-zero when a
gate fails; `--persist DIR` keeps each input and output as JSONL for audit. The gold set format is
documented in `legal_radar.evaluation.load_gold`.

```bash
uv run scripts/eval_enrichment.py gold.yml --provider gemini --persist eval-runs
```

Ask a question: resolve the assunto, traverse the graph (`PARTS`, then 1 hop of `REFERENCES`)
and print an answer citing the dispositivos and jurisprudência it used, with their graph paths.
The `cited-answer` prompt must be published to the Hub and pinned first.

```bash
uv run legal-radar ask "pedido de desconsideração da personalidade jurídica"
```

Evaluate the answer pipeline over the question set in `evals/` (needs the graph, the router's
providers and `uv sync --extra eval`). It scores citation correctness, contradiction surfacing and
graph paths, plus RAGAS faithfulness with `--grounding` (judge model from `RAGAS_BASE_URL` and
`RAGAS_MODEL`, `RAGAS_API_KEY`; the endpoint must accept `json_object` output, so not LM Studio),
tracks tokens and cost (`--price-in`/`--price-out`, USD per million) and writes the
result to `eval-runs/`. Questions marked `abstain: true` are ones the graph cannot answer; they are scored
on whether the answer admits it. The `tema-1210` question is parked (commented in `evals/`) until
a decision is linked to the dispositivos it cites: today no jurisprudência has an edge, so the
traversal cannot reach one. RAGAS 0.4 needs a stub for
the `ChatVertexAI` import that langchain-community 0.4 dropped; the harness applies it.

```bash
make eval
```

Measure what the graph adds with the pure-RAG baselines: they embed the whole corpus (every live
dispositivo and decision, not only the anchor subtrees), retrieve the top-k by cosine similarity
and answer with the same `cited-answer` prompt. `naive` indexes each dispositivo's own text;
`contextual` prepends its caput and parent artigo. The vector index of each chunking is built once
(`data/rag-<chunking>.sqlite`, resumable after a quota error) and reused. `graph_path` is n/a for
them.

```bash
uv run legal-radar index-rag contextual                       # optional: build the index ahead
uv run --extra eval legal-radar eval "desconsideração da personalidade jurídica" \
  --baseline rag-contextual --k 5 15                          # likewise rag-naive
uv run legal-radar compare-evals                              # the latest run of each system
```

An interrupted `eval` resumes by default: each answer is saved to `eval-runs/checkpoints/` and
reused on the next run (while the questions and pinned prompts are the same); `--fresh` discards
them. `compare-evals` tables the graph, naive RAG and contextual RAG per metric and, for the main ones,
per `nivel` (the questions without one are `base`); give it run files to compare specific runs.

Opt-in live smoke test against the real courts (not run by default): `uv run pytest -m live`.

Tests (need Docker for the Neo4j test container): `uv run pytest`.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## Roadmap

- [ ] First milestone

See the [open issues](https://github.com/emvalencaf/legal-radar/issues) for proposed features and known issues.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## Contributing

Contributions follow the branch strategy and commit convention in
[CONTRIBUTING.md](CONTRIBUTING.md): cut a branch from `development`, commit as
`tag(subject/subsubject): summary`, and open a pull request into `development`.
Coding and documentation rules are in [CODE_STANDARDS.md](CODE_STANDARDS.md).

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## License

No license has been chosen yet.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## Contact

Edson Mota Valença Filho - [@emvalencaf](https://github.com/emvalencaf)

Project Link: [https://github.com/emvalencaf/legal-radar](https://github.com/emvalencaf/legal-radar)

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## Acknowledgments

* [Best-README-Template](https://github.com/othneildrew/Best-README-Template)

<p align="right">(<a href="#readme-top">back to top</a>)</p>
