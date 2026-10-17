---
type: Domain Term
title: Confidence
description: How reliable an extracted relation is, derived from how it was extracted and never self-declared by the LLM.
tags:
- domain
- pipeline
status: stable
generated:
  by: claude-code/sonnet-5.5
  at: '2026-10-16T06:00:00Z'
sources:
- id: adr-0002
  resource: docs/adr/0002-hybrid-relation-extraction-with-provenance-confidence.md
  title: Hybrid extraction
---

# Overview

| Level | Meaning |
|---|---|
| HIGH | a rule matched an explicit pattern in the text |
| MEDIUM | the LLM inferred the target or concept from context, or grounded an unresolved citation |
| LOW | the target is unresolved, or a stub |

The origin (`rule` or `llm`) is stored on the edge too, so retrieval can weight edges by both. LLM-inferred
edges are never HIGH, and the LLM's own verbalised confidence is never used.
