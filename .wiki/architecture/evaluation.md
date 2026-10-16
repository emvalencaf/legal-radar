---
type: Architecture
title: How quality is measured
description: Answer evaluation against RAG baselines, and enrichment evaluation against a gold set with quality gates.
tags:
- architecture
- evaluation
status: stable
generated:
  by: claude-code/sonnet-5.5
  at: '2026-10-16T06:00:00Z'
sources:
- id: readme
  resource: README.md
  title: README
- id: baseline
  resource: evaluation/BASELINE.md
  title: Enrichment baseline
- id: gates
  resource: evaluation.yml
  title: Quality gates
---

# Overview

Diagram, How quality is measured: `docs/diagrams/evaluation-loop.svg` in the repository.

**Answers** (`legal-radar eval`). The question set in `evals/` is run through the graph and the
[pure-RAG baselines](/domain/pure-rag-baseline.md) and scored: citation correctness, contradiction surfacing, graph
paths and abstention, plus RAGAS faithfulness with `--grounding`, with tokens and cost tracked. Results go to
`eval-runs/`; an interrupted run resumes from checkpoints; `compare-evals` tables the systems per metric and level.

**Enrichment** (`scripts/eval_enrichment.py`). Edges are scored against the
[gold set](/domain/enrichment-gold-set.md), per edge and split by origin, plus indirect metrics (target-resolved,
valid-evidence and drop rates), and the quality gates in `evaluation.yml` make the run exit non-zero.

# Results

On the 50-question set over one subject, citation correctness was 0.84 for the graph against 0.59 (RAG at 5) and
0.71 (RAG at 15), with no fabricated citations; the graph used about 1.8 times the input tokens of RAG at 15 and
surfaced contradictions poorly (0.33 at best for any system).

The first enrichment baseline (2026-10-13, Groq `openai/gpt-oss-120b`, 60 provisions, 73 edges) gave rule
`REFERENCES` precision and recall of 0.67 and LLM concept edges precision 0.39 and recall 0.40; all four
precision/recall gates failed, as expected for an untuned first run, and the indirect gates passed.[^baseline]

[^baseline]: `evaluation/BASELINE.md`, per-edge scores and gates.
