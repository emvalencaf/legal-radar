---
type: Decision
title: 'ADR-0005: Embeddings on the provider port, resolution in memory'
description: Put `embed()` on the provider port, Gemini first, and resolve the subject in memory by cosine similarity.
tags:
- decision
- adr
status: stable
generated:
  by: claude-code/sonnet-5.5
  at: '2026-10-16T06:00:00Z'
sources:
- id: adr-0005
  resource: docs/adr/0005-embedding-provider-and-assunto-resolution.md
  title: ADR-0005
---

# Decision

`embed` goes through the same router as `complete`. Gemini `gemini-embedding-001` is primary and LM Studio
`text-embedding-bge-m3` the fallback; Groq has no embeddings. Vectors from different models are never compared, and
resolution below the 0.5 threshold rejects the query.

**Consequences:** only anchor subjects resolve; the real-model threshold needs checking with live embeddings.
See [subject resolution](/architecture/subject-resolution.md) and [the router](/architecture/llm-router.md).

The full record, with context and alternatives, is `docs/adr/0005-embedding-provider-and-assunto-resolution.md`.
