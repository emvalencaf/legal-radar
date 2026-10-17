---
type: Decision
title: 'ADR-0002: Hybrid relation extraction'
description: Extract relations with rules plus an LLM and derive confidence from provenance, never from the LLM.
tags:
- decision
- adr
status: stable
generated:
  by: claude-code/sonnet-5.5
  at: '2026-10-16T06:00:00Z'
sources:
- id: adr-0002
  resource: docs/adr/0002-hybrid-relation-extraction-with-provenance-confidence.md
  title: ADR-0002
---

# Decision

Rules handle explicit references, relatives and ranges plus `REVOKES` from Planalto marks; the LLM handles ambiguous
or unresolved citations and every provision-to-concept relation. Confidence is HIGH (rule), MEDIUM (LLM) or LOW
(unresolved or stub). Evidence must be a literal substring, otherwise the item is dropped and counted. Enrichment
runs after parsing and before the graph load, with per-chunk state kept outside the graph.

See [enrichment](/domain/enrichment.md), [confidence](/domain/confidence.md) and
[enrichment records](/domain/enrichment-record.md). Refined by [ADR-0007](/decisions/adr-0007-single-enrichment-prompt.md).

The full record, with context and alternatives, is `docs/adr/0002-hybrid-relation-extraction-with-provenance-confidence.md`.
