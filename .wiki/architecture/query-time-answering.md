---
type: Architecture
title: How a question is answered
description: Resolve the subject, traverse the graph, generate a cited answer, and check every citation.
tags:
- architecture
- rag
status: stable
generated:
  by: claude-code/sonnet-5.5
  at: '2026-10-16T06:00:00Z'
sources:
- id: answer
  resource: src/legal_radar/application/answer.py
  title: Query-time pipeline
- id: adr-0005
  resource: docs/adr/0005-embedding-provider-and-assunto-resolution.md
  title: Embedding and resolution
- id: diagram
  resource: docs/diagrams/ask-flow.svg
  title: Ask flow diagram
---

# Overview

Diagram, How a question is answered: `docs/diagrams/ask-flow.svg` in the repository.

A small LangGraph (`application/answer.py`) orchestrates three steps; the graph is read through the `GraphReader` port.

1. **Resolve the subject** ([resolution](/architecture/subject-resolution.md)). A query that matches no known
   subject is not answered (an abstention).
2. **Traverse** the graph from the anchor statutes: `PARTS` first, then one hop of `REFERENCES`.
3. **Generate** with the pinned `cited-answer` prompt. The sources come first and the question last so a provider
   can cache the fixed block. The reply follows a JSON schema whose `citations` are an enum of the context's ids.

# Guards

The prompt tells the model to use only the sources, to cite the smallest set that supports the answer, to say so
when the sources do not suffice, and to point out divergences. After generation, citations are checked against the
retrieved nodes, and articles the answer names that were not retrieved are reported as unsupported.
