---
type: Architecture
title: Prompts and tracing
description: Prompts are pinned to LangSmith Hub commits and read offline from a lockfile; tracing is optional.
tags:
- architecture
- llm
status: stable
generated:
  by: claude-code/sonnet-5.5
  at: '2026-10-16T06:00:00Z'
sources:
- id: adr-0004
  resource: docs/adr/0004-langsmith-prompts-tracing-and-pages-report.md
  title: LangSmith prompts and tracing
- id: readme
  resource: README.md
  title: README
---

# Overview

Prompts and their output schemas live in the LangSmith Hub, pinned by commit hash in `prompts/pins.yml`, and are
read offline from `prompts/lock.json`; the pipeline and tests need no account or network. `make refresh-prompts`
follows new Hub commits (needs `LANGSMITH_API_KEY` and the `prompts` extra). The snapshot hash enters the wide event
and the enrichment idempotency key, so changing a prompt returns only the affected chunks to pending.

Tracing covers the query-time LangGraph run and evaluation only; ingestion stays on wide events. With tracing off
the pipeline runs identically. Pinned prompts: `cited-answer`, `concepts-count`, `concepts-extract`,
`dispositivo-concept`, `dispositivo-enrichment` and `jurisprudencia-enrichment`.
