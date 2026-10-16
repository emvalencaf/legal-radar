---
type: Research Note
title: LexML SRU spot-check
description: LexML's bot-wall is passable by a real browser; the raw SRU endpoint could not be located.
tags:
- research
status: stable
generated:
  by: claude-code/sonnet-5.5
  at: '2026-10-16T06:00:00Z'
sources:
- id: note
  resource: docs/research/lexml-sru-spotcheck.md
  title: LexML SRU hands-on spot-check
---

# Findings

The security interstitial resolves in 2 to 5 seconds in a real browser. The HTML search (`/busca/search`) and the URN
resolver (`/urn/<urn>`) work end to end. No SRU URL tried returned SRU/XML, and the only API-adjacent document describes
OAI-PMH for data providers. This underlies [ADR-0001](/decisions/adr-0001-planalto-full-text.md) and [LexML](/sources/lexml.md).
