---
type: Domain Term
title: Concept vocabulary
description: One flat, curated YAML vocabulary per subject, shared by its statutes and case law.
tags:
- domain
- vocabulary
status: stable
generated:
  by: claude-code/sonnet-5.5
  at: '2026-10-16T06:00:00Z'
sources:
- id: adr-0003
  resource: docs/adr/0003-concept-vocabulary-per-assunto.md
  title: Concept vocabulary per assunto
- id: adr-0006
  resource: docs/adr/0006-structured-output-and-two-step-vocabulary-drafting.md
  title: Two-step drafting
---

# Overview

Each [subject](/domain/subject.md) has one file, for example `concepts/desconsideracao_personalidade.yml`.
It is flat (no hierarchy), with seven categories: DIREITO, ATOR, PROCESSO, REQUISITO, PRINCIPIO, TEORIA and
EFEITO, exactly one per concept. `id` is lowercase ASCII snake_case; `label`, `aliases` and `instructions`
are in Portuguese, to match the text the LLM reads. The target size is about 25 to 40 concepts.[^adr-0003]

# Authoring

An LLM drafts candidates from the seed corpus in two steps (count, then extract) and a person curates
them ([ADR-0006](/decisions/adr-0006-two-step-vocabulary-drafting.md)). Provenance (`origin`, `model`,
`sources`, `reviewed_by`) lives in the file but stays outside the vocabulary hash, so reviewing a concept
does not send chunks back to `pending`. A vocabulary change returns only LLM-processed chunks to pending.

[^adr-0003]: ADR-0003, decision.
