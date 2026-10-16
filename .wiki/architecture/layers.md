---
type: Architecture
title: Layers and the dependency rule
description: Four layers with inward-only dependencies, enforced by import-linter in CI.
tags:
- architecture
status: stable
generated:
  by: claude-code/sonnet-5.5
  at: '2026-10-16T06:00:00Z'
sources:
- id: architecture
  resource: ARCHITECTURE.md
  title: Architecture
- id: adr-0009
  resource: docs/adr/0009-layered-architecture-enforced-by-import-linter.md
  title: Layered architecture
---

# Overview

Diagram, Layers: `docs/diagrams/layers.svg` in the repository.

`legal_radar` is one bounded context in four layers, `entrypoints > adapters > application > domain`.

| Layer | Holds | May import |
|---|---|---|
| `domain/` | the model, rule-based extraction, URN and prompt-lock values, LLM value types | itself |
| `application/` | use cases and the ports they need (`Protocol`s in `application/ports/`) | `domain` |
| `adapters/` | Neo4j, SQLite, LLM providers and router, LexML, Planalto, STF, STJ, LangSmith, assayer harness | `application`, `domain` |
| `entrypoints/` | the CLI and the end-to-end run | everything |

`bootstrap.py` is the composition root, the only module that reads the environment and builds concrete
adapters; `settings.py` holds every path and configuration value in one frozen `Settings`.

# Enforcement

`import-linter` runs in CI (`uv run lint-imports`) with three contracts: layers point inward; the domain imports
no infrastructure (`neo4j`, `bs4`, `sqlite3`, `langsmith`, `playwright`, `langgraph`, `yaml`, `jsonschema`); the
application imports none of `neo4j`, `bs4`, `sqlite3`, `langsmith`, `playwright`. See
[ADR-0009](/decisions/adr-0009-layered-architecture.md).

# Naming

Python identifiers are English (`Statute`, `Provision`, `CaseLaw`, `Subject`). What is persisted keeps the
Portuguese terms: Neo4j labels and properties, YAML and JSONL keys, prompts, and the `assunto` and `by_nivel`
keys of run files and checkpoints.
