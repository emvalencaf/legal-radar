---
type: Domain Term
title: Enrichment (enriquecimento)
description: The ingestion step that turns structural chunks into chunks carrying relations with evidence and confidence.
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
- id: adr-0007
  resource: docs/adr/0007-single-enrichment-prompt-with-grounded-references.md
  title: Single enrichment prompt
- id: adr-0008
  resource: docs/adr/0008-decisions-take-every-concept-relation.md
  title: Decisions take every relation
---

# Overview

Enrichment runs after parsing and before the graph load. It is **hybrid**
([ADR-0002](/decisions/adr-0002-hybrid-extraction.md)): deterministic rules produce `REFERENCES` and
`REVOKES`, and an LLM handles the ambiguous citations and every provision-to-concept relation.
`REVOKES` is never produced by the LLM. Parsing is structural and rule-only; enrichment is semantic.

Every edge carries its [confidence](/domain/confidence.md) and origin, and `evidence` must be a literal
substring of the text, otherwise the item is dropped and counted.

# Per-provision LLM call

One call per provision ([ADR-0007](/decisions/adr-0007-single-enrichment-prompt.md)): a stable prefix
shared by the subject (relation definitions and the rendered vocabulary, so providers can cache it) and a
variable part with the statute name, the path, the ancestors' text and the target provision. Unresolved
citations are resolved from a closed list of candidates, enforced by an enum.

# Case-law enrichment

The LLM reads a decision's *ementa* and *tese* (never the *decisão*) and links it to concepts with the same
six relations, always origin `llm` and `MEDIUM`. Evidence is a literal slice of the ementa or the tese; it
does not resolve citations ([ADR-0008](/decisions/adr-0008-decisions-take-every-relation.md)).

# Persistence

Per-chunk state lives in an enrichment record, outside the graph: [see the record](/domain/enrichment-record.md).
