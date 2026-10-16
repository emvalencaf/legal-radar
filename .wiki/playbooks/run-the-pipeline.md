---
type: Playbook
title: Run the pipeline
description: The commands that ingest, seed, answer, evaluate and report.
tags:
- playbook
status: stable
generated:
  by: claude-code/sonnet-5.5
  at: '2026-10-16T06:00:00Z'
sources:
- id: readme
  resource: README.md
  title: README
- id: makefile
  resource: Makefile
  title: Makefile
---

# Steps

1. `docker compose up -d neo4j`, then `uv run legal-radar run` for the fixture statute.
2. For the anchor subject: `legal-radar ingest "<subject>"`, `legal-radar ingest-jurisprudencia "<subject>"`
   (add `--enrich` for the LLM step).
3. `make export-seed` and `make seed` to write and rebuild from the versioned seed.
4. `legal-radar ask "<question>"` for a cited answer; the `cited-answer` prompt must be pinned first.
5. `make eval`, `legal-radar compare-evals`, then `make report`.
6. Or all of it: `make run-all`.

Tests need Docker for the Neo4j container (`uv run pytest`); `uv run pytest -m live` is an opt-in smoke test against the
real courts. Details in [the pipeline](/architecture/pipeline.md).
