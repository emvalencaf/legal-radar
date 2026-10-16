---
type: Decision
title: 'ADR-0007: One enrichment prompt with grounded references'
description: Replace the one-concept tagger with one prompt per provision and ground references in a closed candidate list.
tags:
- decision
- adr
status: stable
generated:
  by: claude-code/sonnet-5.5
  at: '2026-10-16T06:00:00Z'
sources:
- id: adr-0007
  resource: docs/adr/0007-single-enrichment-prompt-with-grounded-references.md
  title: ADR-0007
---

# Decision

The tagger never read the curated labels and instructions and returned no relation or evidence. **Decision:** one call per
provision with a cache-friendly stable prefix, structured output of `{concept id, relation, evidence}` with literal
evidence, concepts for every provision, and references only from a closed list of candidates behind an unresolved citation.

**Rejected:** a second prompt for relations (doubles the calls), batching (evidence attribution gets ambiguous), and
free reference proposals (admits invented targets). See [enrichment](/domain/enrichment.md).

The full record, with context and alternatives, is `docs/adr/0007-single-enrichment-prompt-with-grounded-references.md`.
