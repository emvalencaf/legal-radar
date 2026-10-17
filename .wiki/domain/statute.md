---
type: Domain Term
title: Statute (lei)
description: A piece of legislation as published and structured by LexML; one of the three pillars of the graph.
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
- id: adr-0001
  resource: docs/adr/0001-planalto-html-as-lei-fulltext-source.md
  title: Planalto HTML as full text
---

# Overview

A **statute** (*lei*) is a constitution, code, statute or decree. It is the first pillar of the
[knowledge graph](/domain/knowledge-graph.md), next to [case law](/domain/case-law.md) and
[legal scholarship](/domain/legal-scholarship.md). Its structure is a tree of
[provisions](/domain/provision.md).

Identity and discovery come from [LexML](/sources/lexml.md); the full text comes from
[Planalto](/sources/planalto.md) ([ADR-0001](/decisions/adr-0001-planalto-full-text.md)). The graph's
canonical statute id is the LexML URN, not Planalto's `law_id`.[^adr-0001]

In code: `Statute`. In Neo4j: the `:Lei` label.

[^adr-0001]: ADR-0001, consequences.
