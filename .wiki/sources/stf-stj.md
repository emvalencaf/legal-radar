---
type: Data Source
title: STF and STJ search
description: The court search surfaces used to ingest case law, preferred over LexML for this pillar.
tags:
- source
status: stable
generated:
  by: claude-code/sonnet-5.5
  at: '2026-10-16T06:00:00Z'
sources:
- id: jur-source
  resource: docs/research/jurisprudencia-source.md
  title: Jurisprudência source discovery
---

# Overview

The research recommends building case-law ingestion against **STF's `api/search/search` JSON endpoint** and
**STJ's `scon.stj.jus.br/SCON/` HTML search**, not LexML. STJ's search is session-based (the query is submitted
through the page form) and returns server-rendered HTML with full ementas; it surfaced Tema Repetitivo 1210
for the anchor subject. STJ's Cloudflare check rejects bundled Chromium, so ingestion needs Google Chrome.
