---
type: Research Note
title: Case-law source discovery
description: STJ SCON and STF's search API are the strongest surfaces for case law, ahead of LexML.
tags:
- research
status: stable
generated:
  by: claude-code/sonnet-5.5
  at: '2026-10-16T06:00:00Z'
sources:
- id: note
  resource: docs/research/jurisprudencia-source.md
  title: Jurisprudência source discovery
---

# Findings

LexML's UI indexes case law (27,382 hits for the keyword query) but its top results are labour-court rulings, not STF or
STJ. STJ's SCON has no bot-wall, is session-based (submit the form) and returns server-rendered HTML with full ementas;
it surfaced Tema Repetitivo 1210 first. **Recommendation:** build against STF's JSON endpoint and STJ's SCON HTML search.
See [STF and STJ](/sources/stf-stj.md) and [case law](/domain/case-law.md).
