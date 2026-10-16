---
type: Data Source
title: Planalto
description: The portal whose HTML rendition of a statute is the full-text source for the document tree.
tags:
- source
status: stable
generated:
  by: claude-code/sonnet-5.5
  at: '2026-10-16T06:00:00Z'
sources:
- id: adr-0001
  resource: docs/adr/0001-planalto-html-as-lei-fulltext-source.md
  title: Planalto HTML as full text
---

# Overview

`planalto.gov.br/ccivil_03/leis/{law_id}.htm` is the source of the legal-document tree. It is reached by
following the "Texto Atualizado" link off the resolved LexML URN page, never by guessing the filename from the
statute number. Only statutes whose link resolves to Planalto are in scope.
