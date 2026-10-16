---
type: Playbook
title: 'Contribute: branches and commits'
description: Work branches go through development to master, with an English commit format and two trailers.
tags:
- playbook
status: stable
generated:
  by: claude-code/sonnet-5.5
  at: '2026-10-16T06:00:00Z'
sources:
- id: contributing
  resource: CONTRIBUTING.md
  title: Contributing
---

# Steps

1. Cut `<tag>/<short-description>` from an up-to-date `development`; `master` is protected.
2. Commit as `tag(subject/subsubject): summary`, in English, imperative and lowercase, with a body explaining why and
   what, ending with `Session-Id` and `Co-Authored-By` trailers.
3. Open a pull request into `development`, with an entry under `Unreleased` in `CHANGELOG.md`.
4. Releases are a pull request from `development` into `master`.

Run `scripts/setup.sh` once to enable the hooks: Unicode check, ruff, and a `.wiki/` update when code changes
(`SKIP_WIKI_UPDATE=1` skips it).
