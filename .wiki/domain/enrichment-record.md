---
type: Domain Term
title: Enrichment record and pending
description: The persisted state of a provision that went through the LLM, and the rule that decides what runs again.
tags:
- domain
- pipeline
status: stable
generated:
  by: claude-code/sonnet-5.5
  at: '2026-10-16T06:00:00Z'
sources:
- id: context
  resource: CONTEXT.md
  title: Domain glossary
- id: adr-0002
  resource: docs/adr/0002-hybrid-relation-extraction-with-provenance-confidence.md
  title: Hybrid extraction
---

# Overview

An **enrichment record** (*registro de enriquecimento*) holds the source (a statute, or the court of a
decision), the idempotency key, a status (`ok` or `pending`) and the count of dropped items. It is kept in
`data/ingestion.sqlite` (`METADATA_DB` overrides the path), outside the graph, which only receives validated
edges.

A provision is **pending** when its record is missing, failed, or carries a key that no longer matches the
current text, vocabulary, prompt or extractor version. Only pending provisions are sent to the LLM again, and
their rule-derived edges are kept. A failed batch does not block loading a statute.
