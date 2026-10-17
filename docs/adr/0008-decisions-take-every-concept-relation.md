# Let a jurisprudência decision take every concept relation, and guard it in the prompt

ADR-0003 limited the jurisprudência→conceito edges to `APPLIES_TO`, `DEFINES` and `RELATES_TO`, on the reasoning that a decision does not create obligations, prohibitions or exceptions. In practice it does: the binding thesis of a repetitivo or of a repercussão geral requires, forbids and carves out (Tema 1210 fixes when the desconsideração does not apply). Dropping those relations would lose the effects that matter most to a query. The first run of the decision enricher against Groq also labelled every edge `DEFINES`, and kept a heading in capitals as evidence.

## Decision

- **A decision takes the same six concept relations as a dispositivo**: `DEFINES`, `APPLIES_TO`, `OBLIGES`, `PROHIBITS`, `EXCEPTS`, `RELATES_TO`. This supersedes the "allowing `APPLIES_TO`, `DEFINES` and `RELATES_TO`" bullet of ADR-0003. Origin stays `llm`, confidence `MEDIUM`, evidence a literal slice of the ementa or of the tese; the decisão is still never read, and citations are still not resolved.
- **The relations are defined for what a court does**, not for what a norm does: `OBLIGES` is a duty, burden or requirement the court's position imposes; `PROHIBITS` what it rules out; `EXCEPTS` the limit or carve-out it sets. `APPLIES_TO` is the default and `DEFINES` only holds when the court fixes the meaning of the concept.
- **False positives are fought in the prompt** (`jurisprudencia-enrichment`): an empty answer is the expected one when unsure; only the court's own position counts, never what a party argues or what the lower court held; a mere mention, a quoted rule or a doctrine citation is no relation; a negation changes the relation (a rule that does not apply is `EXCEPTS` or `PROHIBITS`, never `APPLIES_TO`); at most one relation per concept; the evidence is a full clause, preferably from the tese.
- **And in the code**: an item whose evidence is entirely in capitals (a heading) is dropped and counted.

## Consequences

- The quality of the six relations on decisions is only verifiable against a gold set of decisions, which does not exist yet; until then the prompt is judged by reading runs.
- The prompt text changed, so the decisions already enriched go back to `pending`.
