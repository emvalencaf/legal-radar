---
type: Research Note
title: Doutrina source research
description: No source gives broad, legally reusable doctrine; broad ingestion is unrealistic for the project's scope.
tags:
- research
status: stable
generated:
  by: claude-code/sonnet-5.5
  at: '2026-10-16T06:00:00Z'
sources:
- id: note
  resource: docs/research/doutrina-source.md
  title: 'Research: viable doutrina source'
---

# Findings

SciELO is clean (CC-BY, real REST APIs) but narrow: about four Brazilian law journals. Institutional repositories and
OASISBR/BDTD are broad in principle but have per-record licence heterogeneity, an aggregator API that needed a
verification spike (it was bot-walled), and no guarantee of full text. **Recommendation:** full doutrina ingestion is not
realistic for a 2 to 4 week portfolio build. See [legal scholarship](/domain/legal-scholarship.md).
