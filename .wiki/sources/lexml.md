---
type: Data Source
title: LexML
description: The Brazilian legislative portal used for identity, discovery and URN resolution, not for full text.
tags:
- source
status: stable
generated:
  by: claude-code/sonnet-5.5
  at: '2026-10-16T06:00:00Z'
sources:
- id: adr-0001
  resource: docs/adr/0001-planalto-html-as-lei-fulltext-source.md
  title: Planalto HTML as full text
- id: spotcheck
  resource: docs/research/lexml-sru-spotcheck.md
  title: LexML SRU spot-check
---

# Overview

`lexml.gov.br` is the identity and discovery layer: subject search and URN resolution. It does not publicly
expose a raw XML document per statute, so it is not the full-text source ([ADR-0001](/decisions/adr-0001-planalto-full-text.md)).
The site sits behind a JS-challenge interstitial that a real browser passes in a few seconds and a plain HTTP
client does not, which is why ingestion needs `uv sync --extra browser` and Chromium.[^spotcheck]

[^spotcheck]: LexML SRU spot-check, TL;DR.
