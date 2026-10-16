---
type: Domain Term
title: Provision (dispositivo)
description: 'One structural unit of a statute: article, paragraph, item or sub-item; the granularity of graph nodes.'
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
- id: architecture
  resource: ARCHITECTURE.md
  title: Architecture
---

# Overview

A **provision** (*dispositivo*) is a node of a [statute](/domain/statute.md)'s structure: artigo
(article), parágrafo (paragraph), inciso (item) or alínea (sub-item). The hierarchy título, capítulo,
artigo, parágrafo, inciso, alínea is the *legal document AST* parsed from the Planalto HTML, and it
becomes the graph's `PARTS` edges.

Provisions are what the system cites in an answer, what [enrichment](/domain/enrichment.md) reads and
what [relations](/domain/knowledge-graph.md) connect.

In code: `Provision`. In Neo4j: the `:Dispositivo` label.
