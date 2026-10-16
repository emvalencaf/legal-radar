# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Entries are added
under `Unreleased` in the PR that makes the change, and moved under a dated
heading when `development` is released to `master`.

## [Unreleased]

### Removed

- Obsolete scripts: the `setup-langsmith-*` wizards (the prompts are published and pinned in
  `prompts/pins.yml`; `make refresh-prompts` maintains them), `skeleton.sh` (replaced by
  `docker compose up -d neo4j` and `legal-radar run`) and `check_enricher.py` (covered by
  `legal-radar eval` and `scripts/eval_enrichment.py`).

### Changed

- The last layer-boundary exceptions are gone (`ignore_imports` is empty): the use cases take
  the prompt lock instead of defaulting to the file-backed one, `ingest` depends on the
  `LeiLocator` and `LeiTextSource` ports (LexML and Planalto adapters), and `build_index` uses
  a `VectorStore` port (SQLite adapter). A new import-linter contract keeps infrastructure
  packages out of `application`. No behaviour change.
- Layered architecture (ADR-0009): `legal_radar` is organised as `entrypoints > adapters >
  application > domain`, enforced by `import-linter` in CI. `domain.py` moved to
  `legal_radar.domain.model`, and `legal_radar.settings.Settings` centralises paths and
  environment-derived values. No behaviour change. The CLI moved to
  `legal_radar.entrypoints.cli.app` behind the new composition root `legal_radar.bootstrap`
  (`python -m legal_radar` and the `legal-radar` script are unchanged), and the setup scripts
  import the new module paths.

### Added

- `legal-radar report` also writes `report/graph.html` (#87): an offline, phone-friendly sample of
  the knowledge graph (Cytoscape.js, shipped as package data) around the example answers'
  citations, with their `PARTS` ancestors and 1-hop typed neighbours, capped at 150 nodes. Node
  colour shows the kind; edge style the type, edge colour the confidence and the source-end marker
  the origin; hovering or tapping an edge shows its evidence. It is built from `seed/graph.jsonl`
  and the latest enrichment run, and skipped with a warning when either is missing.
  `scripts/publish-report.sh` publishes it with the report.
- `ARCHITECTURE.md` and four diagrams in `docs/diagrams/` (layers, the end-to-end run, the graph
  model and the outputs per command), and `import-linter` in CI (ADR-0009).
- One-command end-to-end run (#48): `legal-radar run-all <assunto> [--enrich]` (`make run-all`)
  ingests the leis and decisions, exports the seed, answers the assunto as a cited query, scores
  the question set and writes the report (`legal_radar.end_to_end.run_end_to_end`). Its top-seam
  test runs the same entrypoint over pinned fixtures with the fake provider (which now also answers
  the evaluation judges) and a Neo4j test container.
- Jurisprudência per assunto (#74): `JURISPRUDENCIA` catalogues each assunto's seeds, per-court
  searches and top hits (`JurisprudenciaSource`, 0 ingests only the seeds), in the style of
  `ANCHORS`. `legal-radar ingest-jurisprudencia <assunto>` now requires the assunto, limited to the
  catalogue; `ingest_jurisprudencia` takes the source instead of reading module constants. The
  anchor assunto behaves as before.
- Optional complexity tiers (#47), off by default: `legal_radar.complexity.classify` is a pure
  rule over the retrieved context (more than one lei, any jurisprudência, a REVOKES or LOW-confidence
  edge, or more than `tiers.max_context_tokens`). With `tiers.enabled: true` in `router.yaml`, a
  complex answer tries the `tiers.complex` providers first; an exhausted list downgrades the call
  to `providers` and the wide event records `complexity` and `downgraded_from`. `Hop` now carries
  the edge's `confidence`.
- Static report and GitHub Pages publish (#46): `legal-radar report` (`make report`) writes
  `report/index.html` from the latest runs in `eval-runs/`: ingestion statistics (target-resolved,
  valid-evidence and drop rates, out-of-vocabulary terms), evaluation metrics per system, example
  answers with the graph path of each citation, and the `prompt_hash` of every pinned prompt and
  the run ids; it links to no LangSmith trace (ADR-0004). `make publish-report` pushes it to the
  `gh-pages` branch by hand, with no CI. Enrichment run files now record each chunk's
  out-of-vocabulary ids and revocation marks, and evaluation reports record each citation's path.
- Optional LangSmith tracing (#45): with `LANGSMITH_API_KEY` set, `ask` traces each LangGraph node
  and `eval` publishes the experiment (a run per question, evaluations as feedback); without it, nothing changes and nothing fails.
  Ingestion and enrichment emit no traces (ADR-0004). `LANGSMITH_TRACING=false` opts out.
- Pure-RAG baselines (#79): `legal_radar.rag` embeds every live dispositivo and decision of the
  graph (revoked, empty and structural ones and the amendment marks left out) and keeps the vectors
  in SQLite per chunking: `naive` (the dispositivo's text) and `contextual` (after its ancestors').
  It answers with the same `cited-answer` prompt over the top-k by cosine. Building an index waits
  out a throttled provider and resumes from the batches already saved.
- `legal-radar eval --baseline rag-naive|rag-contextual --k 5 15` scores a baseline with the same
  harness (`graph_path` is n/a), `index-rag` builds an index ahead and `compare-evals` tables the
  graph and the baselines per metric and per `nivel`. `GraphReader.corpus()` reads the whole graph.
- Reports carry `system`, `k` and per-`nivel` scores, and `Question` reads `nivel` (the questions
  without one are grouped as `base`). `compare-evals` splits every metric by `nivel` and shows the
  mean input tokens per question, overall and per `nivel`.
- An interrupted `eval` resumes by default from the answers saved in `eval-runs/checkpoints/`,
  valid while the questions and pinned prompts are the same; `--fresh` discards them.

- Answer guards and evaluation (#44): `unsupported_mentions` flags the articles an answer names that
  were not retrieved, scored as `grounded_mentions`; a query with no letter resolves to no assunto;
  court texts are read unwrapped and in the case the rules expect; the context shown to the model
  drops the `(Incluído pela Lei …)` marks. The `cited-answer` prompt asks for the fewest sources,
  forbids outside knowledge, lets `citations` be empty and puts the question after the sources
  (new Hub commit, pinned). A question may list `also_ok` sources: neither required nor counted
  against precision.
- Eval set grown to 50 questions (#44): informal, broken and implicit-concept questions from easy
  to hard, plus edge cases the graph cannot answer (`nivel` marks the difficulty).
- Decision → dispositivo links (#76): `extract_decision_relations` reads the ementa and tese of a
  decision with the same rules as a dispositivo and yields `REFERENCES` edges (HIGH, origin `rule`);
  a citation that names no lei stays unresolved (LOW) for the LLM. `ingest-jurisprudencia` writes
  them through `write_jurisprudencia(items, relations)`, so the traversal reaches decisions and the
  `tema-1210` eval question is active again. LLM resolution of unresolved decision citations is not
  built yet.
- Jurisprudência enrichment (#65): `legal_radar.enricher.enrich_decision` runs the concept
  enricher over a decision's ementa and tese (never the decisão) with its own prompt,
  `jurisprudencia-enrichment`, and a schema that carries only `conceitos`. It returns concept
  edges of all six relations (ADR-0008: a thesis can require, forbid and carve out), MEDIUM, origin
  `llm`; a decision without ementa is skipped, and evidence in capitals (a heading) is dropped; `evidence` is a literal slice of
  the ementa or of the tese; out-of-vocabulary and non-literal items are dropped and counted.
  `legal-radar ingest-jurisprudencia --enrich` runs it over the ingested decisions, resumable like
  `ingest --enrich` (records grouped by court), and the Neo4j store accepts `Jurisprudencia` as the
  source of `llm` concept edges. The prompt is published to the Hub and pinned
  (`scripts/setup-langsmith-decision-prompt.sh`). `EnrichmentRecord.lei_id` became `source_id`
  (a lei, or a court for decisions); an existing metadata database is migrated on open.
- `ingest <assunto> --enrich` sends the chunks the rules left to the LLM enricher and records each
  one (key, `ok`/`pending`, dropped count) in a SQLite metadata store apart from the graph (#29).
  Re-running resumes only `pending` chunks; a changed text, vocabulary, enrichment prompt or
  extractor version returns just those to `pending`. A chunk's `llm` edges are replaced atomically
  (`GraphStore.replace_llm_relations`); `rule` edges are never touched. The Neo4j store now writes
  dispositivo → conceito edges. A citation the LLM grounds is dropped from the node's unresolved
  list on every run, a `too_long` chunk is recorded `ok` but reported apart, and `--enrich` fails
  at once when no configured provider has its API key.

### Fixed

- Groq rejected the cited-answer schema (`uniqueItems` is unsupported in strict mode): the OpenAI-
  compatible adapters no longer send it; replies are still validated against the full schema.
- `enrichment_key` mixes the hash of `dispositivo-enrichment`, the prompt `enrich()` runs, instead
  of `dispositivo-concept`.
- `AllProvidersFailedError` now says why each provider gave up (quota, rate limit, rejected
  request), instead of a bare "exhausted or failed" that hid the cause.
- OpenAI-compatible providers close every object of the response schema with
  `additionalProperties: false`, which strict mode needs: Groq answered 400 to the enricher's schema.
- HTTP providers send their own `User-Agent`: Groq (Cloudflare) answered 403 / error 1010 to the
  default `Python-urllib` one, so the Groq provider could never be used. A non-JSON error body is now
  kept in the provider error instead of being dropped.
- The enricher's structured-output schema no longer sends an empty `enum` for `referencias` when a
  dispositivo has no unresolved citation: LM Studio rejected it (`enum must be a non-empty array`),
  so no dispositivo could be enriched locally. `LLM_TIMEOUT_SECONDS` raises the per-call timeout
  for slow local models; `eval_enrichment.py --timeout` sets it (default 600).

### Changed

- The cited-answer generation is shared (`answer_from`, `render_sources`, `strip_amendments`,
  `jurisprudencia_text` in `legal_radar.answer`) so the graph and the baselines answer alike.
- `router.yaml`: the local daily cap for Gemini goes from 500 to 2000 requests; embedding a
  whole-corpus index needs hundreds of calls a day, and the Google quota is the real limit.
- Vocabulary `desconsideracao_personalidade`: `personalidade_juridica` merged into `pessoa_juridica`
  (39 concepts) and every `instructions` rewritten with when to use it, when not to and invented
  example wordings, citing no dispositivo so the evaluation slice does not leak into the prompt.
  The vocabulary hash changes (LLM-processed chunks return to pending, ADR-0003); the gold set was
  remapped and re-pinned (#67).

### Added

- `eval_enrichment.py` writes each dispositivo to its run file as it finishes and `--resume RUNFILE`
  continues an interrupted run (refused when provider, model or vocabulary changed); on a provider
  failure it stops and prints the resume command. The default provider is now `groq` (#67).
- `evaluation/TRIAGE.md`: the baseline's 42 false positives classified (overlapping concepts, type
  disagreement, gold gaps, model errors) with the decisions that followed (#67).
- `evaluation/BASELINE.md`: the baseline of the first real enrichment run against the gold set (Groq,
  `openai/gpt-oss-120b`), with the run's configuration and how to read it (#67).
- `scripts/setup-groq.sh`: wizard that creates the Groq API key, stores `GROQ_API_KEY` in `.env`,
  validates it against api.groq.com and checks the `router.yaml` model is available.
- `eval_enrichment.py`: `--model` next to `--provider`, `lmstudio` as the default provider, only the
  gold dispositivos are sent to the LLM, and a progress line per dispositivo (position, relations,
  tokens, elapsed, ETA) (#67).
- `scripts/gold_editor.py`: edit the enrichment gold set in the browser (graph plus review panel,
  no skipping, accepted/corrected/added marks), sharing progress with the terminal wizard (#67).
- `scripts/visualize_gold.py`: a read-only, self-contained HTML graph of the enrichment gold set
  (proposal, review progress or gold) to see every edge and the unused concepts at once (#67).
- Vocabulary `desconsideracao_personalidade` grows from 33 to 40 concepts, found missing while
  proposing the gold set (#67): `sociedade_controlada`, `sociedade_consorciada`,
  `sociedade_coligada`, `culpa_ou_dolo`, `excesso_de_poder_ou_infracao`,
  `responsabilidade_subsidiaria` and `responsabilidade_solidaria`. The vocabulary hash changes, so
  LLM-processed chunks return to pending (ADR-0003).
- Enrichment gold set tooling (#67, in progress): Claude Code's proposal for the 60 normative
  dispositivos of the anchor slice (`evaluation/`), `scripts/annotate_gold.py` for the maintainer's
  review (no skipping; records accepted/corrected/added), and a `vocabulary_hash` check in
  `load_gold`. `eval_enrichment.py` now scores against the curated vocabulary. The reviewed gold,
  baseline and CI gate wait on the maintainer's annotation.
- Enrichment evaluation harness (#28): `legal_radar.evaluation` scores enrichment edges against a
  gold set (per-edge precision/recall/F1 split by origin and relation type), computes the indirect
  metrics (target-resolved, valid-evidence and drop rates), applies a rules gate and an LLM gate
  from `evaluation.yml`, and can persist every input and output as JSONL. Run it with
  `scripts/eval_enrichment.py`. The real gold set is annotated in #67.
- LLM concept enricher (#27): `legal_radar.enricher.enrich` is a pure function that turns one
  dispositivo into `DEFINES`/`APPLIES_TO`/`OBLIGES`/`PROHIBITS`/`EXCEPTS`/`RELATES_TO` edges to
  vocabulary concepts and grounds the rules' unresolved citations in a closed candidate list
  (MEDIUM, origin `llm`), per ADR-0002/0003/0007. Evidence must be a literal substring of the
  dispositivo; out-of-vocabulary, non-literal and ungrounded items are dropped and counted. Triage
  skips revoked, structural and empty dispositivos, and a per-call input-token ceiling trims the
  farthest ancestors first. The `dispositivo-enrichment` prompt template ships in the module and
  is published to the Hub and pinned; the per-call ceiling is `enrichment.max_input_tokens` in
  `router.yaml`.
- Revocations in the parser and graph (#26): `Dispositivo` gains `revoked` and `revocations`; a
  fully revoked dispositivo (struck text plus `(Revogado …)` marks) is kept instead of vanishing,
  with the marks moved out of its text. `GraphBatch.relations` writes `REFERENCES` and `REVOKES`
  edges (confidence, origin, evidence) to Neo4j, with stub `Lei` nodes for leis not ingested and
  unresolved citations kept as node attributes. `ingest()` runs the extractor over every lei of the
  run and reports relations, chunks for the LLM and dropped items.
- Deterministic relation extractor (#26): `legal_radar.relations.extract_relations` turns a
  dispositivo into `REFERENCES` and `REVOKES` edges (`Relation`, `Confidence`, `Origin` in
  `legal_radar.domain`) with literal evidence, per ADR-0002. It covers explicit citations
  (`art. 50 do Código Civil`, `Lei nº 8.078/1990`), relatives (`deste artigo`, `artigo anterior`),
  inciso and artigo ranges, and Planalto `(Revogado pela …)` marks. Law names resolve through a
  curated code table with an optional LexML fallback; unresolved targets are LOW, and what the
  rules cannot read is returned in `needs_llm`. `Extraction` also carries the extractor version, the
  dropped-item count and `needs_enrichment` (unread text or an unresolved citation), so the two
  LLM-bound sets are never counted twice.
- Evaluation harness (#44): `legal-radar eval <assunto>` (`make eval`) answers the question set in
  `evals/` and scores it under `assayer` (`legal_radar.assayer_harness`, the `eval` extra):
  custom, table-tested citation correctness, contradiction surfacing and graph-path metrics
  (`legal_radar.answer_evaluation`), RAGAS faithfulness for flat grounding (`--grounding`, judge
  model from `RAGAS_BASE_URL`/`RAGAS_MODEL`), and tokens and cost per run (`--price-in` and
  `--price-out`, USD per million; zero by default). Results are written to `eval-runs/`.
  `CitedAnswer` now carries the retrieved ids and each `Citation` its source text.
  The question set has 23 questions with gabaritos read from the graph: 14 answerable and 9 the
  graph cannot answer (off the assunto, leis and decisions never ingested). The latter are marked
  `abstain: true` and scored by a custom abstention metric (an empty answer, or one that admits
  the sources fall short) instead of citations and paths.

- Retrieval and cited answer (#43): `legal-radar ask "<query>"` runs a LangGraph pipeline
  (`legal_radar.answer`: resolve assunto, traverse, generate) over the knowledge graph. The
  `GraphReader` port (`Neo4jGraphReader`) walks `PARTS` down from the anchor dispositivos (`AnchorLei.artigos`: CC art. 50, CDC art. 28; a lei with none starts from the whole lei, which was ~4,700 dispositivos and broke the model call), then 1 hop of
  `REFERENCES` (a dispositivo's outgoing ones, a jurisprudência's citations), sorted by id, with
  no scoring or cap. The reply must validate against the `cited-answer` schema, whose enum is the
  retrieved ids; each `Citation` carries its node kind and its graph path. The `cited-answer`
  prompt still has to be published to the Hub and pinned; until then `default_lock()` raises
  `PromptError`. Adds the `langgraph` dependency.
  `scripts/setup-langsmith-answer-prompt.sh` publishes `cited-answer` (`ANSWER_TEMPLATE` and
  `ANSWER_SCHEMA`) to the Hub, pins its commit and refreshes the lockfile. The CLI now loads `.env`
  (without overriding variables already set).

- Structured output for the tagging prompt (#58): `pipeline.run` sends the `dispositivo-concept`
  schema (`pipeline.TAG_SCHEMA`: `{conceito_id}`, enum filled from the vocabulary ids when
  `legal-radar run --assunto` or `conceito_ids` gives them) as `response_schema` and validates the
  reply with `jsonschema`; an answer outside it raises `TaggingError` instead of writing a bad
  conceito id. `scripts/setup-langsmith-tag-schema.sh` publishes the schema to the Hub, pins its
  commit and refreshes `prompts/lock.json`; until it runs, the lockfile has no schema and the
  pipeline raises `PromptError`.

- Prompts pinned to LangSmith Hub commits and read offline from `prompts/lock.json` (template,
  structured-output schema, commit); `legal-radar refresh-prompts` / `make refresh-prompts`
  re-snapshots them. The wide event carries `prompt_snapshot`, a hash of the prompt used (commit, template, schema).
  The drafting steps now read prompts and schemas from it, and the tagging call in `pipeline.run`
  now sends `pipeline_step="tag"` instead of the default.

- Concept vocabulary (#41): `legal_radar.concepts` loads and validates one flat YAML vocabulary per
  assunto (snake_case ASCII ids, Portuguese label/aliases/instructions, one of seven categories,
  no duplicate ids or shared terms) and exposes `Vocabulary.hash`, independent of order and
  formatting, for the enrichment idempotency key. `legal-radar draft-concepts <assunto>` has an LLM
  draft candidates from the graph's dispositivos and jurisprudência into a `.draft.yml`, in two structured-output steps (count the concepts, then extract exactly that many). The
  vocabulary `concepts/desconsideracao_personalidade.yml` (33 concepts, LLM-drafted) is committed
  and marked reviewed concept by concept by the maintainer. Provenance lives in the file, outside the hash: per-concept `origin` (with the `model` when `llm`)
  (`llm`/`human`) and `reviewed_by` + `reviewed_on`, and a file `status` (`draft` by default,
  `curated` only when every concept is reviewed), plus per-concept `created_at` and `updated_at` dates. Lineage: per-concept `sources` lists the dispositivo
  and jurisprudência ids it came from; the draft asks the LLM to cite them and flags any not in the
  corpus. `load_registered` only warns on a draft and checks
  the file's `assunto` against `VOCABULARY_PATHS`. See ADR-0003 and ADR-0006.
- Embeddings and assunto resolution (#40): `embed()` on the provider port, routed like `complete()`
  (fallback, retry, daily limits, an `embed_call` wide event) with Gemini `gemini-embedding-001`
  first and LM Studio `text-embedding-bge-m3` as fallback (Groq has none), configured under
  `embedding_models` in `router.yaml`. `AssuntoResolver` maps a raw query to an anchor assunto and
  its leis by in-memory cosine similarity, re-embedding the catalog if a fallback changes the model.
  See ADR-0005.
- Versioned graph seed (#39): `legal-radar export-seed` writes the whole graph as sorted JSON lines
  (`seed/graph.jsonl`, byte-stable for an unchanged graph) and `make seed` / `legal-radar seed`
  rebuilds a fresh Neo4j from it with uniqueness constraints and MERGE, so loading twice changes
  nothing. Run `make export-seed` after an ingestion to refresh and commit the seed.
- Jurisprudência ingestion (#38): `legal-radar ingest-jurisprudencia` loads a pinned manifest of
  seed precedents (STJ Tema Repetitivo 1210 core, STF Tema 1232 tangential) plus the top 5 hits
  per court as `Jurisprudencia` nodes (ementa, tese, decisão; no PDFs) keyed `{court}:{native id}`.
  STF is read through its in-page JSON API and STJ through its search form + HTML, both behind one
  `JurisprudenciaFetcher` port. Tested offline from saved responses; `pytest -m live` runs an
  opt-in smoke test against the real sources.
- Lei ingestion (#37): `legal-radar ingest <assunto>` resolves each anchor lei's LexML URN by
  keyword search, follows the "Texto Atualizado" Planalto link on the URN page, parses the page
  into the título → capítulo → artigo → parágrafo → inciso → alínea AST (text-based, dropping
  struck-through superseded versions) and loads `Lei`/`Dispositivo` nodes with `PARTS` edges
  (`{urn}#{path}` ids, idempotent). Non-Planalto leis are skipped and listed in the report.
  The sibling repo's anchor-based `PlanaltoHtmlParser` was not reused: real compiled pages carry
  almost no usable anchors. LexML and Planalto's redirect agent need a browser
  (`uv sync --extra browser`); the browser source retries failed fetches 3 times with backoff and
  logs every failure.
- Provider port: stateless `complete()` behind a hexagonal `Provider` port with Groq, Gemini
  and LM Studio adapters, a `Router` configured by `router.yaml` (default priority
  `[groq, gemini, lmstudio]`, secrets from env) that falls back on quota exhaustion, waits on
  RPM throttling and retries transient errors once, one wide-event JSONL line per call
  (content-hashed prompt/tool ids, token and latency breakdown, full text opt-in), daily quota
  computed from those lines, and a scriptable `FakeProvider` (issue #36).
- Walking skeleton: `legal-radar run` parses a fixture lei, tags dispositivos through a
  fake provider and writes them via a `GraphStore` port to Neo4j (`MERGE` + uniqueness
  constraints, idempotent); `scripts/skeleton.sh` starts Neo4j with docker compose and
  runs it; a test container test asserts the graph (issue #35).
- ADR-0002 and `CONTEXT.md` terms (`Enriquecimento`, `Confidence`): hybrid
  rule + LLM relation extraction with provenance-derived confidence (issue #24).
- ADR-0003 and `CONTEXT.md` terms (`Conceito jurídico`, `Vocabulário de conceitos`):
  one flat, curated concept vocabulary per assunto, shared by lei and
  jurisprudência (issue #18).
- ADR-0004: prompts and query-time tracing in LangSmith (pinned, with a local
  lockfile), static report published on GitHub Pages (issue #1).

## [0.1.0] - 2026-09-20

First release of the project template.

### Added

- Template scaffolding: `README.md` with step-by-step instructions for using the
  template, `.gitignore`, `.editorconfig`, `pyproject.toml` (ruff), `.wiki/` OKF
  knowledge bundle, PR template and commit template.
- `CONTRIBUTING.md` (branch strategy and commit convention), `CODE_STANDARDS.md`
  and this changelog.
- Git hooks in `.githooks/`: `commit-msg` enforces the commit format;
  `pre-commit` checks Unicode, runs ruff, and updates `.wiki/` automatically
  (via `claude -p`, with one validator-guided retry) with strict validation.
  Skip the wiki update with `SKIP_WIKI_UPDATE=1`.
- Scripts: `scripts/setup.sh`, `scripts/protect-master.sh`,
  `scripts/check_unicode.py`, `scripts/set-budget.sh`,
  `scripts/usage-tracking.sh` and `scripts/usage_log.sh`.
- GitHub Actions CI (`.github/workflows/ci.yml`): PR target rule (only
  `development` may target `master`), Unicode, ruff, `.wiki/` validation and
  commit message format checks.
- Project-level status line (`.claude/settings.json` and `scripts/statusline.sh`)
  showing project, model, branch (dirty and ahead/behind markers, red on
  `master`/`main`/`development`), context, cost or budget, rate limits,
  duration and session id. `scripts/set-budget.sh` sets, shows or clears the USD
  budget used for pay-per-token accounts (project or `--global`).
- Per-session usage log: the status line writes `.claude/usage/<session>.json`
  (git-ignored) when enabled with `scripts/usage-tracking.sh on|off|status`.
- `query` skill: natural-language search over OKF bundles, with `--limit` and
  metadata filters (`--type`, `--tag`, `--status`, `--path`, `--generated-by`,
  `--verified-by`, `--resource`, `--source`, `--stale`/`--fresh`,
  `--verified`/`--unverified`, `--include-deprecated`).
- `usage-report` skill: local HTML dashboard with tabs (Overview, Work, By type,
  Sessions). Tokens in and out per day, session and skill, duration, model,
  effort, context peak, top skills, heuristic intents and tool usage (names,
  calls, errors, time). The Work tab groups sessions by spec, ticket, feature
  directory or branch across the grill, spec, tickets, implement and review
  flow, resolves local `.scratch/` files and GitHub issues, and links commits
  through the `Session-Id` trailer (`--tracker`, `--offline`). Subagents appear
  as separate rows linked to their session and are never added to its totals. The
  By type tab classifies work as feature, bug fix, refactor, etc. from commit
  tags, branch prefix, GitHub labels or the opening skill. The logged cost is
  always labelled an estimate.

### Changed

- Renamed `ask-matt` to `ask-harness` and extended it to route the OKF skills
  (`query`, `okf`, `validate`, `visualize`, `backfill`), `usage-report` and the
  repo workflow. Dropped the `/prototype` and `/teach` references, which are not
  in this repo.
- Renamed `setup-matt-pocock-skills` to `setup-project-harness`; it now also sets
  the project name and description, configures `CODE_STANDARDS.md` with the
  matching `pyproject.toml` settings, and asks whether to keep usage tracking on
  and, for pay-per-token users, the status line budget.
- Moved the knowledge bundle from `.okf/` to `.wiki/`.
