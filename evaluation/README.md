# Enrichment gold set

The hand-validated relations each normative dispositivo of the anchor slice (CC art. 50 and CDC
art. 28 excerpts under `tests/fixtures/planalto`) should yield, against the curated vocabulary
`concepts/desconsideracao_personalidade.yml`. See ADR-0002 and the *Gold set de enriquecimento*
term in `CONTEXT.md`.

## Limitation

There is a single annotator. The metrics computed against this gold set measure **agreement with
that one annotator, not absolute truth**. Claude Code proposed the relations before the review, so
anchoring bias is possible: every edge records `review: accepted | corrected | added`, and rejected
proposals are kept under `rejected`, so the share of accepted proposals can be audited.

## Files

| File | What |
|---|---|
| `enrichment_gold.proposed.yml` | Claude Code's proposal for the 60 normative dispositivos. Not the gold set. |
| `enrichment_gold.yml` | The reviewed gold set, written by the wizard once every dispositivo is reviewed. |

`vocabulary_hash` pins the vocabulary the file was annotated against; `load_gold` rejects the file
when the vocabulary changes.

## Seeing the whole graph

```bash
uv run python scripts/visualize_gold.py   # writes evaluation/gold.html (git-ignored)
```

A read-only page with dispositivos on the left and the curated concepts on the right, edges coloured
by relation type (dashed = added, dotted = corrected). Switch between the proposal, the review
progress and the gold; click a dispositivo or a concept to isolate its edges. Concepts with no edge
are greyed out, which is where vocabulary gaps and dead concepts show.

## Reviewing in the browser

```bash
uv run python scripts/gold_editor.py   # then open http://localhost:8765
```

The same graph, editable. For each dispositivo, accept, correct or reject what Claude Code
inferred, add what it missed, then confirm. A dispositivo only counts once confirmed (a proposal
with nothing is confirmed as a negative), so none can be skipped, and the gold file is written only
when all are confirmed. It shares `enrichment_gold.progress.yml` with the terminal wizard below, so
the two can be mixed.

## Reviewing in the terminal

```bash
uv run python scripts/annotate_gold.py
```

The wizard cannot skip a dispositivo (an empty answer confirms a negative) and saves progress after
each one, so it can be resumed. Then run `scripts/eval_enrichment.py evaluation/enrichment_gold.yml`
for the baseline.
