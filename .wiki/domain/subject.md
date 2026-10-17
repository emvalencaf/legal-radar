---
type: Domain Term
title: Subject (assunto)
description: The legal topic a user searches for; the entry point that resolves to anchor statutes.
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
---

# Overview

The **subject** (Portuguese *assunto*) is the topic a user asks about, for example
*desconsideração da personalidade jurídica*. It is the entry point into the system: a raw query is
mapped to a known subject by [subject resolution](/architecture/subject-resolution.md), and the
subject names the anchor [statutes](/domain/statute.md) from which the graph traversal starts.

Each subject has its own [concept vocabulary](/domain/concept-vocabulary.md).[^context]

The code calls it `Subject`; the data and the CLI keep `assunto`.

[^context]: Domain glossary, `CONTEXT.md`.
