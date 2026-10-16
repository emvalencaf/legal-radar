---
type: Decision
title: 'ADR-0001: Planalto HTML as the full-text source'
description: Use Planalto's HTML rendition, not LexML XML, as the statute's full text.
tags:
- decision
- adr
status: stable
generated:
  by: claude-code/sonnet-5.5
  at: '2026-10-16T06:00:00Z'
sources:
- id: adr-0001
  resource: docs/adr/0001-planalto-html-as-lei-fulltext-source.md
  title: ADR-0001
---

# Decision

LexML exposes no raw XML per statute (only an OAI-PMH toolkit for data providers), and a resolved URN page is
metadata plus outbound links, mostly to Planalto. **Decision:** ingestion treats Planalto as the full-text source,
reached through the "Texto Atualizado" link on the URN page; LexML narrows to subject search and URN identity.

**Consequences:** only statutes whose link resolves to Planalto are in scope; the LexML URN is the canonical statute id.
Related: [Planalto](/sources/planalto.md), [LexML](/sources/lexml.md), [statute](/domain/statute.md).

The full record, with context and alternatives, is `docs/adr/0001-planalto-html-as-lei-fulltext-source.md`.
