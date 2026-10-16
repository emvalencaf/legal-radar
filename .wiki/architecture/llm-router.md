---
type: Architecture
title: LLM router and providers
description: One provider port for completions and embeddings, with fallback, waits, retries and wide events.
tags:
- architecture
- llm
status: stable
generated:
  by: claude-code/sonnet-5.5
  at: '2026-10-16T06:00:00Z'
sources:
- id: adr-0005
  resource: docs/adr/0005-embedding-provider-and-assunto-resolution.md
  title: Embedding and resolution
- id: adr-0006
  resource: docs/adr/0006-structured-output-and-two-step-vocabulary-drafting.md
  title: Structured output
- id: router
  resource: router.yaml
  title: Router configuration
---

# Overview

`embed(texts)` lives on the same `Provider` port as `complete()` and goes through the same router: fallback on
quota, RPM wait, one transient retry, daily limits, and one wide event per call. `router.yaml` lists the providers
in priority order, which is also the fallback order (`groq`, `gemini`, `lmstudio` by default); keys come from
`GROQ_API_KEY`, `GEMINI_API_KEY` and `LMSTUDIO_BASE_URL`.

Structured output is a `CompletionParams.response_schema`: Gemini receives `responseJsonSchema`, Groq and LM Studio
a strict `json_schema` `response_format`; the router logs its hash as `response_schema_id`.[^adr-0006] The deterministic
`FakeProvider` keeps tests offline.

[^adr-0006]: ADR-0006, decision.
