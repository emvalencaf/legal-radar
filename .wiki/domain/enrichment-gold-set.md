---
type: Domain Term
title: Enrichment gold set
description: The hand-validated relations each provision of the anchor slice should yield; scores agreement with one annotator.
tags:
- domain
- evaluation
status: stable
generated:
  by: claude-code/sonnet-5.5
  at: '2026-10-16T06:00:00Z'
sources:
- id: gold
  resource: evaluation/README.md
  title: Enrichment gold set
- id: context
  resource: CONTEXT.md
  title: Domain glossary
---

# Overview

An LLM proposed the relations and one person corrected them, so the metrics measure **agreement with that one
annotator, not absolute truth**, and part of the agreement is with the proposing model. Every edge records
`review: accepted | corrected | added`; rejected proposals are kept. `vocabulary_hash` pins the vocabulary,
and `load_gold` rejects the file when it changes. See [evaluation](/architecture/evaluation.md).
