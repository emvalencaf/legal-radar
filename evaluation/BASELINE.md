# Enrichment baseline

First real run of `scripts/eval_enrichment.py` against the gold set (#67). It is a reference point to
compare later changes against, **not** a quality bar: the gates in `evaluation.yml` were guesses
before this run and have not been tuned to it yet.

## Run

| | |
|---|---|
| Date | 2026-10-13 |
| Code | `a8b154b` |
| Provider and model | Groq, `openai/gpt-oss-120b` (default sampling) |
| Gold set | `evaluation/enrichment_gold.yml`, 60 dispositivos, 73 edges, commit `843cd32` |
| Vocabulary | `concepts/desconsideracao_personalidade.yml`, 40 concepts, hash `sha256:5d697834…12fb` |
| Duration | 15 min 29 s, 60 LLM calls |
| Persisted run | `eval-runs/enrichment-20261013T004615Z.jsonl` (not versioned) |

```bash
uv run python scripts/eval_enrichment.py evaluation/enrichment_gold.yml \
  --provider groq --model openai/gpt-oss-120b --persist eval-runs
```

## Per-edge scores

Scored per edge `(type, source, target)`, split by origin. `tp`/`fp`/`fn` are counts.

| Origin | Type | tp | fp | fn | Precision | Recall | F1 |
|---|---|---:|---:|---:|---:|---:|---:|
| rule | `REFERENCES` | 4 | 2 | 2 | 0.67 | 0.67 | 0.67 |
| llm | concepts (all) | 27 | 42 | 40 | 0.39 | 0.40 | 0.40 |
| llm | `APPLIES_TO` | 17 | 14 | 16 | 0.55 | 0.52 | 0.53 |
| llm | `DEFINES` | 9 | 20 | 16 | 0.31 | 0.36 | 0.33 |
| llm | `EXCEPTS` | 1 | 0 | 1 | 1.00 | 0.50 | 0.67 |
| llm | `OBLIGES` | 0 | 2 | 0 | 0.00 | n/a | n/a |
| llm | `PROHIBITS` | 0 | 1 | 0 | 0.00 | n/a | n/a |
| llm | `RELATES_TO` | 0 | 5 | 7 | 0.00 | 0.00 | 0.00 |
| llm | `REFERENCES` | 0 | 0 | 6 | n/a | 0.00 | n/a |
| all | all | 31 | 44 | 42 | 0.41 | 0.42 | 0.42 |

The LLM is not asked to find references the rules already catch, so its `REFERENCES` recall is
expected to be 0; its job is the concept edges.

## Indirect metrics

| Metric | Value | Gate |
|---|---:|---:|
| Target-resolved rate | 1.00 | ≥ 0.70 |
| Valid-evidence rate | 1.00 | ≥ 0.99 |
| Drop rate | 0.06 | ≤ 0.20 |

## Gates

All four precision/recall gates fail, as expected for an untuned first run:

- rules: precision 0.67 < 0.90, recall 0.67 < 0.80
- llm: precision 0.39 < 0.70, recall 0.40 < 0.50

The indirect gates pass. Enabling the gate in CI is deferred until the thresholds are set from
evidence like this.

## How to read it

- These numbers measure agreement with a single annotator, not absolute truth.
- The gold set is half reviewed one by one (the first 30 dispositivos, `art40` to `art46_incVI`) and
  half Claude Code's proposal confirmed in bulk, so part of the agreement is with Claude Code itself.
  Every edge records `accepted`, `corrected` or `added` to audit that.
- The first 30 mark `DEFINES pessoa_juridica` on almost every listing dispositivo of the Código
  Civil. The LLM proposes more concepts than the gold holds, which is where most of the 42 false
  positives come from; some are model errors, some are gaps in the gold. They have not been
  triaged.
- `DEFINES` against `APPLIES_TO` is the largest disagreement and the main legal judgement call.
- One run of one model: run-to-run variance is not measured.
