---
type: Domain Term
title: Legal concept (conceito jurídico)
description: An entry of a subject's curated vocabulary that provisions and decisions are linked to.
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
- id: adr-0003
  resource: docs/adr/0003-concept-vocabulary-per-assunto.md
  title: Concept vocabulary per assunto
---

# Overview

A **legal concept** is an entry of the [concept vocabulary](/domain/concept-vocabulary.md): an `id`,
a `label`, `aliases`, `instructions` and one `category`. Provisions and decisions are linked to concepts
by the six relations `DEFINES`, `APPLIES_TO`, `OBLIGES`, `PROHIBITS`, `EXCEPTS` and `RELATES_TO`.

In code: `Concept` (vocabulary entry) and `ConceptNode` (graph node). In Neo4j: `:Conceito`.
