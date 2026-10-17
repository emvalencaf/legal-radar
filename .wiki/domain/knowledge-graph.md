---
type: Domain Term
title: Knowledge graph
description: The Neo4j graph of statutes, provisions, decisions and concepts; the core artifact every output derives from.
tags:
- domain
- graph
status: stable
generated:
  by: claude-code/sonnet-5.5
  at: '2026-10-16T06:00:00Z'
sources:
- id: architecture
  resource: ARCHITECTURE.md
  title: Architecture
- id: diagram
  resource: docs/diagrams/graph-model.svg
  title: Graph model diagram
---

# Overview

The graph is the core artifact; the answers, the seed and the report are derived from it.

Diagram, The knowledge graph: `docs/diagrams/graph-model.svg` in the repository.

| Node (label) | Python | Holds |
|---|---|---|
| `:Lei` | `Statute` | id (LexML URN), title, planalto_url |
| `:Dispositivo` | `Provision` | id, `lei_id`, path, kind, text, parent_id, revoked |
| `:Jurisprudencia` | `CaseLaw` | id (court:native), court, number, `ementa`, `tese`, `decisao` |
| `:Conceito` | `ConceptNode` | id |

Edges: `PARTS` (statute to provision, and provision to child), `REFERENCES`, `REVOKES`, and the six concept
relations. Every relation carries `type`, [confidence](/domain/confidence.md), `origin`, `evidence` and, when
unresolved, the citation as written.

Neo4j labels, property names and the seed (`seed/graph.jsonl`) keep the Portuguese terms; the Python names are
English ([layers](/architecture/layers.md)). Not to be confused with LangGraph, which only orchestrates the
[query-time pipeline](/architecture/query-time-answering.md).
