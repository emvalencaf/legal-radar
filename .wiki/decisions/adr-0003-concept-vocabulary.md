---
type: Decision
title: 'ADR-0003: One concept vocabulary per subject'
description: Keep a flat, curated vocabulary per subject, shared by statutes and case law.
tags:
- decision
- adr
status: stable
generated:
  by: claude-code/sonnet-5.5
  at: '2026-10-16T06:00:00Z'
sources:
- id: adr-0003
  resource: docs/adr/0003-concept-vocabulary-per-assunto.md
  title: ADR-0003
---

# Decision

A per-statute vocabulary would fragment one concept into several nodes. **Decision:** one YAML file per subject, seven
categories, no hierarchy in the MVP, drafted by an LLM and curated by a person, with the vocabulary hash in the
idempotency key. Out-of-vocabulary terms are reported, not added.

**Consequence:** curation is manual work per subject and the main cost of growing the catalogue. The case-law relation
limit was lifted by [ADR-0008](/decisions/adr-0008-decisions-take-every-relation.md). See
[concept vocabulary](/domain/concept-vocabulary.md).

The full record, with context and alternatives, is `docs/adr/0003-concept-vocabulary-per-assunto.md`.
