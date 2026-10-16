---
type: Domain Term
title: Case law (jurisprudência)
description: Court decisions that interpret or apply a statute; the second pillar of the graph.
tags:
- domain
- glossary
status: stable
generated:
  by: claude-code/sonnet-5.5
  at: '2026-10-16T06:00:00Z'
sources:
- id: context
  resource: CONTEXT.md
  title: Domain glossary
- id: jur-source
  resource: docs/research/jurisprudencia-source.md
  title: Jurisprudência source discovery
---

# Overview

**Case law** (*jurisprudência*) is the body of decisions, including binding precedents (*precedentes*),
that interpret or apply a [statute](/domain/statute.md). A decision carries a court, a number, an
*ementa* (headnote), a *tese* (thesis) and a *decisão* (ruling).

Decisions are ingested from STF and STJ ([research](/research/jurisprudencia-source.md)) and linked
to concepts by [case-law enrichment](/domain/enrichment.md#case-law-enrichment). The anchor subject's
seeds are STJ Tema 1210 and STF Tema 1232.

In code: `CaseLaw`. In Neo4j: the `:Jurisprudencia` label.
