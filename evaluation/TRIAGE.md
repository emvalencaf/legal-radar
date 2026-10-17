# Triage of the baseline false positives

The 42 LLM false positives (and 40 false negatives) of the baseline run in `BASELINE.md`, read one by
one against the gold set. The run is `eval-runs/enrichment-20261013T004615Z.jsonl`. The buckets are a
reading of the text by Claude Code, to be confirmed by the annotator; none was applied to the gold
automatically.

| Bucket | FP | Meaning |
|---|---:|---|
| A. Overlapping concepts | 20 | `personalidade_juridica` (15) and `pessoa_juridica` on negatives (5): the vocabulary offered two concepts for the same thing |
| B. Same target, other type | 10 | The model and the gold agree on the concept and differ on the relation type |
| C. Plausibly right, missing from the gold | 9 | The text supports the edge; the gold does not hold it |
| D. Likely model error | 3 | The text does not support the edge |

Counting B and C as hits would put precision near 0.70 (an estimate from this reading, not a
measurement); the real model errors are about 3 of 42.

## A. Overlapping concepts (20)

| Dispositivo | Model edge |
|---|---|
| `art40`, `art41`, `art41_incI`, `art41_incII`, `art41_incIV`, `art44_incII`, `art44_incIII`, `art44_incIV`, `art44_incVII`, `art45`, `art46_incVI`, `art51_par1` | `DEFINES personalidade_juridica` (the gold has `DEFINES pessoa_juridica`) |
| `art41_incIII` | `APPLIES_TO personalidade_juridica` |
| `art28` | `RELATES_TO personalidade_juridica` |
| `art28_par5` | `APPLIES_TO personalidade_juridica` |
| `art41_incIII`, `art46_incVI`, `art49`, `art51_par1`, `art51_par3` | `APPLIES_TO pessoa_juridica` (the gold holds nothing) |

14 false negatives are the mirror: `DEFINES pessoa_juridica` where the model answered
`personalidade_juridica`.

## B. Same target, other type (10)

| Dispositivo | Model | Gold |
|---|---|---|
| `art47` | `OBLIGES administrador`, `OBLIGES pessoa_juridica` | `RELATES_TO` (the model reads the text better) |
| `art50` | `RELATES_TO socio`, `administrador`, `beneficio_direto_ou_indireto` | `APPLIES_TO` |
| `art50_par2_incII` | `DEFINES confusao_patrimonial` | `APPLIES_TO` |
| `art50_par4` | `PROHIBITS grupo_economico` | `EXCEPTS` |
| `art28_par3` | `DEFINES responsabilidade_solidaria` | `APPLIES_TO` |
| `art29` | `DEFINES consumidor` (the article extends the definition) | `APPLIES_TO` |
| `art1` | `DEFINES direito_do_consumidor` | `APPLIES_TO` |

These need one rule for `DEFINES` against `APPLIES_TO` (and for `OBLIGES`/`PROHIBITS`/`EXCEPTS`
against `RELATES_TO`), not a case-by-case fix.

## C. Plausibly right, missing from the gold (9)

| Dispositivo | Model edge | Why it holds |
|---|---|---|
| `art43` | `APPLIES_TO culpa_ou_dolo` | the text says "culpa ou dolo" |
| `art46_incV` | `DEFINES responsabilidade_subsidiaria` | "respondem ... subsidiariamente" |
| `art50_par1` | `APPLIES_TO prejuizo_ao_credor` | "lesar credores" |
| `art50_par3` | `APPLIES_TO extensao_da_responsabilidade` | "extensão das obrigações de sócios" |
| `art1` | `APPLIES_TO consumidor` | "defesa do consumidor" |
| `art46_incII`, `art46_incIV` | `APPLIES_TO administrador` | directors, administration |
| `art46_incIII` | `DEFINES administrador` | how it is administered and represented |
| `art49` | `DEFINES administrador` | "administrador provisório" |

## D. Likely model error (3)

| Dispositivo | Model edge | Why not |
|---|---|---|
| `art44_par2` | `RELATES_TO extensao_da_responsabilidade` | the text is about applying the rules of associations |
| `art50_par2_incI` | `DEFINES extensao_da_responsabilidade` | the inciso gives a form of confusão patrimonial |
| `art28` | `APPLIES_TO administrador` | "má administração" is a trigger, not an actor |

## Decisions taken

- Merge `personalidade_juridica` into `pessoa_juridica` (the surviving id, category ATOR) and
  rewrite every concept's `instructions` with when to use it, when not to, and invented example
  wordings. No dispositivo is cited or quoted there: examples drawn from the evaluation slice would
  leak the answer into the prompt and bias the metrics. The gold was remapped and its `vocabulary_hash` re-pinned.
- Open: which of C to add to the gold, and the `DEFINES` against `APPLIES_TO` rule for B.
- A new run is needed to see the effect: the baseline predates the change.
