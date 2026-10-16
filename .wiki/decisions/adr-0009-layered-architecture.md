---
type: Decision
title: 'ADR-0009: Layered architecture enforced by import-linter'
description: One bounded context in four layers, with inward-only dependencies checked in CI.
tags:
- decision
- adr
status: stable
generated:
  by: claude-code/sonnet-5.5
  at: '2026-10-16T06:00:00Z'
sources:
- id: adr-0009
  resource: docs/adr/0009-layered-architecture-enforced-by-import-linter.md
  title: ADR-0009
---

# Decision

One context over several because the vocabulary and graph are shared; light DDD (a pure domain and ports) over aggregates
and repositories a batch pipeline has no lifecycle for. **Rejected:** convention without lint (boundaries erode), several
contexts with a shared kernel (ceremony), and full tactical DDD with CQRS. See [layers](/architecture/layers.md).

The full record, with context and alternatives, is `docs/adr/0009-layered-architecture-enforced-by-import-linter.md`.
