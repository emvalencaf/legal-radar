---
type: Playbook
title: Publish the report
description: Build the static report and push it to the gh-pages branch, then serve it with GitHub Pages.
tags:
- playbook
status: stable
generated:
  by: claude-code/sonnet-5.5
  at: '2026-10-16T06:00:00Z'
sources:
- id: script
  resource: scripts/publish-report.sh
  title: publish-report.sh
- id: adr-0004
  resource: docs/adr/0004-langsmith-prompts-tracing-and-pages-report.md
  title: Pages report
---

# Steps

1. Make sure `eval-runs/` holds a run (`make eval`); it is git-ignored.
2. `make publish-report` builds the report from the latest runs and pushes it as the only content of `gh-pages`. It does
   nothing when the report is unchanged, and adds `graph.html` only when the seed and an enrichment run exist.
3. First time only: in the repository settings enable Pages from branch `gh-pages`, folder `/`.

Publishing is manual by design, with no CI ([ADR-0004](/decisions/adr-0004-langsmith-prompts-and-pages.md)).
Once Pages is enabled the site may be publicly reachable, even for a private repository, so check the plan and the content first.
