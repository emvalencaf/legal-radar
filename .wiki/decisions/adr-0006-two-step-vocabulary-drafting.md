---
type: Decision
title: 'ADR-0006: Structured output and two-step vocabulary drafting'
description: Draft the vocabulary with provider-level structured output in two steps, keeping provenance outside the hash.
tags:
- decision
- adr
status: stable
generated:
  by: claude-code/sonnet-5.5
  at: '2026-10-16T06:00:00Z'
sources:
- id: adr-0006
  resource: docs/adr/0006-structured-output-and-two-step-vocabulary-drafting.md
  title: ADR-0006
---

# Decision

`CompletionParams.response_schema` carries a JSON Schema to every provider. Step 1 counts the distinct concepts, step 2
extracts exactly that many; a mismatch is a warning. Provenance (`origin`, `model`, `sources`, `reviewed_by`) lives in
the file but not in `Vocabulary.hash`. A draft vocabulary warns instead of blocking.

See [concept vocabulary](/domain/concept-vocabulary.md) and [the router](/architecture/llm-router.md).

The full record, with context and alternatives, is `docs/adr/0006-structured-output-and-two-step-vocabulary-drafting.md`.
