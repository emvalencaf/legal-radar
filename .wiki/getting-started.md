---
type: Reference
title: 'Getting started: Legal Radar'
description: What Legal Radar is, how the pieces fit, and where to read next.
tags:
- getting-started
status: stable
generated:
  by: claude-code/sonnet-5.5
  at: '2026-10-16T06:00:00Z'
sources:
- id: readme
  resource: README.md
  title: README
- id: architecture
  resource: ARCHITECTURE.md
  title: Architecture
---

# Overview

Legal Radar is a graph-RAG system over Brazilian law. Given a legal [subject](/domain/subject.md), it links the
[statutes](/domain/statute.md), [case law](/domain/case-law.md) and [concepts](/domain/legal-concept.md) that bear on it
in a [knowledge graph](/domain/knowledge-graph.md), and answers questions with citations traceable to the graph.

The domain is Brazilian law, so the data keeps the Portuguese terms; the code is in English. Start with
[how a question is answered](/architecture/query-time-answering.md), then [the layers](/architecture/layers.md) and
[how quality is measured](/architecture/evaluation.md). Every non-obvious choice is a [decision](/decisions/index.md).
