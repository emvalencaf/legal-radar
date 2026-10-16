---
type: Decision
title: 'ADR-0004: LangSmith prompts, tracing and the Pages report'
description: Manage prompts in LangSmith by pinned commit, trace only query time and evaluation, publish the report on GitHub Pages.
tags:
- decision
- adr
status: stable
generated:
  by: claude-code/sonnet-5.5
  at: '2026-10-16T06:00:00Z'
sources:
- id: adr-0004
  resource: docs/adr/0004-langsmith-prompts-tracing-and-pages-report.md
  title: ADR-0004
---

# Decision

Prompts are pulled by pinned hash and snapshotted in a versioned lockfile that tests read offline. Tracing covers
query-time and evaluation; ingestion stays on wide events. The report is static HTML published by a manual command,
and it embeds the `prompt_hash` and run id instead of trace links, because traces are private and expire after 14 days.

See [prompts and tracing](/architecture/prompts-and-tracing.md) and
[publishing the report](/playbooks/publish-the-report.md).

The full record, with context and alternatives, is `docs/adr/0004-langsmith-prompts-tracing-and-pages-report.md`.
