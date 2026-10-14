# Jurisprudência enrichment: run over the seed decisions

Issue #65. A run of `enrich_decision` (prompt `jurisprudencia-enrichment`,
Hub commit `1cf987887839`) over the two pinned seeds, read from the captured
fixtures (`tests/fixtures/jurisprudencia/`), against the vocabulary of
_desconsideração da personalidade jurídica_ (39 concepts).

- Model: `gemini-3.1-flash-lite`, one run, 2026-10-13. A second run on
  2026-10-14 could not be made: Groq's daily quota was spent, Gemini answered
  503 and LM Studio was off.
- Every edge is origin `llm`, `MEDIUM`; the validator guarantees each evidence
  is a literal slice of the ementa or of the tese.
- This is one run of one model, not an evaluation: there is no gold set of
  decisions yet (#67 follow-up).

## Core seed: STJ Tema 1210 (`STJ:202001090402`, REsp 1873811)

Expected edges, written by hand from the tese for a human to review. The
evidence column is the clause I would point at.

| # | Relation | Concept | Evidence |
|---|---|---|---|
| 1 | `OBLIGES` | `abuso_da_personalidade` | requer a efetiva comprovação de abuso da personalidade jurídica |
| 2 | `DEFINES` | `abuso_da_personalidade` | abuso da personalidade jurídica, caracterizado por desvio de finalidade ou por confusão patrimonial |
| 3 | `APPLIES_TO` | `desvio_de_finalidade` | caracterizado por desvio de finalidade ou por confusão patrimonial |
| 4 | `APPLIES_TO` | `confusao_patrimonial` | caracterizado por desvio de finalidade ou por confusão patrimonial |
| 5 | `APPLIES_TO` | `teoria_maior` | nos termos exigidos pelo art. 50 do Código Civil (Teoria Maior) |
| 6 | `EXCEPTS` | `insolvencia` | sendo insuficiente a mera inexistência de bens penhoráveis e/ou de encerramento irregular das atividades da sociedade empresária |

Edges the model produced (5): rows 3, 4, 5 and 6 as above, plus
`APPLIES_TO abuso_da_personalidade` on "a desconsideração da personalidade
jurídica requer a efetiva comprovação de abuso da personalidade jurídica".

- Matches: 3, 4, 5, 6.
- Misses: 1 and 2. The same clause was labelled `APPLIES_TO` instead of
  `OBLIGES` (a requirement) and `DEFINES` (what counts as abuse).
- Extra: none beyond that relabelling; no edge came from the decisão, a
  heading or a party's argument.
- Row 6 is my reading and deserves a second look: whether `insolvencia` is the
  right concept for "inexistência de bens penhoráveis" is a vocabulary
  question.

## Tangential seed: STF Tema 1232 (`STF:sjur550030`, RE 1387795)

No hand-written expectation (the seed is tangential, about the employer-group
redirection of a labour execution). The model produced 7 edges, all
`APPLIES_TO`: `devido_processo_legal`, `incidente_de_desconsideracao`,
`fase_de_execucao`, `grupo_economico`, `abuso_da_personalidade`,
`teoria_maior` and `responsabilidade_solidaria`; one item was dropped for
non-literal evidence. Two evidences read as exceptions ("Admite-se,
excepcionalmente, o redirecionamento…", "Apenas situações excepcionais,
qualificadas pelo abuso da personalidade jurídica…") and may deserve
`EXCEPTS`.

## What this says

- The guards work: no heading as evidence, no relation from the decisão, and
  non-literal items are dropped and counted.
- The model leans on `APPLIES_TO`; `OBLIGES`, `DEFINES` and `EXCEPTS` are
  under-used. The prompt was left as is by decision; a gold set is needed
  before tuning it.
