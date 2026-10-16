---
type: Domain Term
title: Pure-RAG baseline
description: The comparison system that answers from embedding similarity alone, so the graph's value is measured.
tags:
- domain
- evaluation
status: stable
generated:
  by: claude-code/sonnet-5.5
  at: '2026-10-16T06:00:00Z'
sources:
- id: context
  resource: CONTEXT.md
  title: Domain glossary
- id: readme
  resource: README.md
  title: README
---

# Overview

The baseline takes the top-k texts closest to the question by embedding similarity over the whole corpus
and answers with the same prompt, schema and evaluation as the graph. Two chunkings are reported apart:
**naive** (each provision's own text) and **contextual** (prepends the caput and parent article, so an item
is readable alone; only the provision itself is citable).

Built with `legal-radar index-rag <chunking>`, compared with `legal-radar compare-evals`; see
[evaluation](/architecture/evaluation.md).
