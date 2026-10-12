# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Entries are added
under `Unreleased` in the PR that makes the change, and moved under a dated
heading when `development` is released to `master`.

## [Unreleased]

### Added

- Concept vocabulary (#41): `legal_radar.concepts` loads and validates one flat YAML vocabulary per
  assunto (snake_case ASCII ids, Portuguese label/aliases/instructions, one of seven categories,
  no duplicate ids or shared terms) and exposes `Vocabulary.hash`, independent of order and
  formatting, for the enrichment idempotency key. `legal-radar draft-concepts <assunto>` has an LLM
  draft candidates from the graph's dispositivos and jurisprudência into a `.draft.yml`. A first
  draft of `concepts/desconsideracao_personalidade.yml` (33 concepts) is committed and still needs
  human curation. Provenance lives in the file, outside the hash: per-concept `origin`
  (`llm`/`human`) and `reviewed_by` + `reviewed_on`, and a file `status` (`draft` by default,
  `curated` only when every concept is reviewed). `load_registered` only warns on a draft and checks
  the file's `assunto` against `VOCABULARY_PATHS`. See ADR-0003.
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
