---
type: Decision
title: 'ADR-0008: Decisions take every concept relation'
description: Let a decision take all six concept relations and guard against false positives in the prompt and the code.
tags:
- decision
- adr
status: stable
generated:
  by: claude-code/sonnet-5.5
  at: '2026-10-16T06:00:00Z'
sources:
- id: adr-0008
  resource: docs/adr/0008-decisions-take-every-concept-relation.md
  title: ADR-0008
---

# Decision

A binding thesis requires, forbids and carves out, so limiting decisions to three relations lost the effects that matter
most. The relations are defined for what a court does, the prompt prefers an empty answer when unsure and counts only the
court's own position, and an item whose evidence is entirely in capitals is dropped. Their quality is unverified until a
gold set of decisions exists. This supersedes part of [ADR-0003](/decisions/adr-0003-concept-vocabulary.md).

The full record, with context and alternatives, is `docs/adr/0008-decisions-take-every-concept-relation.md`.
