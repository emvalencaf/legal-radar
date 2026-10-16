---
type: Architecture
title: Subject resolution
description: Maps a query to a known subject by cosine similarity over embeddings, in memory.
tags:
- architecture
- rag
status: stable
generated:
  by: claude-code/sonnet-5.5
  at: '2026-10-16T06:00:00Z'
sources:
- id: adr-0005
  resource: docs/adr/0005-embedding-provider-and-assunto-resolution.md
  title: Embedding and resolution
---

# Overview

The anchor catalogue is embedded once per process and the query is matched by cosine similarity. Below
`DEFAULT_THRESHOLD` (0.5) nothing resolves, which is how an unrelated query is rejected. There is no vector store
because the catalogue is tiny. Vectors from different models are never compared: the resolver re-embeds the
catalogue when a fallback model serves the query.

Gemini `gemini-embedding-001` is the primary model and LM Studio `text-embedding-bge-m3` the local fallback; Groq
serves no embeddings. The 0.5 threshold was calibrated to the offline `FakeProvider`, and a real-model value needs
checking with live embeddings (`scripts/check_embeddings.py`).[^adr-0005]

[^adr-0005]: ADR-0005, consequences.
