---
type: Architecture
title: The end-to-end run
description: Ingest statutes and decisions, export the seed, answer, evaluate and report; enrichment is optional.
tags:
- architecture
- pipeline
status: stable
generated:
  by: claude-code/sonnet-5.5
  at: '2026-10-16T06:00:00Z'
sources:
- id: architecture
  resource: ARCHITECTURE.md
  title: Architecture
- id: readme
  resource: README.md
  title: README
- id: makefile
  resource: Makefile
  title: Makefile
---

# Overview

Diagram, The end-to-end run: `docs/diagrams/pipeline.svg` in the repository.

`make run-all` (`legal-radar run-all <subject>`) runs, in order: ingest the anchor statutes (LexML then Planalto),
ingest the seed decisions and top court hits (STF, STJ), export the graph to `seed/graph.jsonl`, answer the subject as
a cited query, score the question set into `eval-runs/`, and write `report/index.html`. It needs Neo4j, the
`browser` and `eval` extras, Google Chrome and the router's providers, and it overwrites `seed/graph.jsonl`.

`--enrich` adds the optional LLM [enrichment](/domain/enrichment.md) of statutes and decisions; its state goes to
the [enrichment records](/domain/enrichment-record.md). `make seed` rebuilds a fresh Neo4j from the versioned
seed with MERGE-based, idempotent loading.

Diagram, Outputs: `docs/diagrams/outputs.svg` in the repository.
