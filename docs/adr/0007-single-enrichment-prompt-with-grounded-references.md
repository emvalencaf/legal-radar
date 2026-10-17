# Replace the one-concept tagger with a single enrichment prompt, and ground LLM references in a closed candidate list

The tagger shipped with issue #58 asks the LLM for one `conceito_id` per dispositivo, with only the text of that dispositivo. The vocabulary reaches the model as an enum of ids, so the `label`, `aliases` and `instructions` a person curated (ADR-0003) are never read, an inciso arrives without its caput, and the reply carries neither a relation type nor evidence. ADR-0002 needs all three, plus a way to resolve the citations the rules leave unresolved. Issue #27 builds that enricher.

## Decision

- **One prompt replaces `dispositivo-concept`**, one call per dispositivo, no batching (consistent with ADR-0004). It needs `refresh-prompts` and changes the idempotency key.
- **Context engineering.** A stable prefix shared by every call of an assunto (the assunto, the definition of each relation type, the rendered vocabulary with id, label, aliases and instructions) so providers can cache it. The variable part holds the lei name, the path, the text of the ancestors (the caput for an inciso or alínea, the artigo for a parágrafo) and the target dispositivo.
- **Structured output** is a list of `{conceito_id, relacao, evidence}`; `conceito_id` and `relacao` are enums, `evidence` must be a literal substring of the target dispositivo (whitespace-normalised on both sides; ancestors do not count). An empty list is a valid reply.
- **Every dispositivo goes to the LLM for concepts**, since rules never produce them. ADR-0002's "only chunks the rules did not fully resolve" applies to reference resolution only. A deterministic triage skips `revoked`, structural kinds without norm text, and empty text; a per-call input-token ceiling in configuration trims the farthest ancestors first and skips the dispositivo if the target alone exceeds it. The report counts what was skipped by reason.
- **References are grounded.** The LLM only sees `citações não resolvidas` (the rules' `LOW`/`unresolved` edges) and picks a target from a closed list of candidates (dispositivos of the same lei, and the curated codes), enforced by an enum. A grounded pick with literal evidence is `MEDIUM`/`llm`; anything else stays `LOW`/unresolved. The LLM never creates a `REFERENCES` without an unresolved citation behind it.

## Considered options

- **Keep the tagger and add a second prompt for relations.** Doubles the calls and the cost on a free tier (Gemini's daily cap) and splits one judgment (which concept, in what relation) across two prompts.
- **Batch several dispositivos per call.** Cheaper per dispositivo, but evidence attribution gets ambiguous and one failure drops several items. The anchor corpus is tens of dispositivos, so there is no cost pressure.
- **Let the LLM propose references freely.** Contradicts ADR-0002, which gives `REFERENCES` to the rules, and would admit invented targets.

## Consequences

- Each call carries a prefix of roughly 2-3k tokens (to be measured); it is the price of the LLM reading the curated instructions.
- A change to the vocabulary, a relation definition or the prompt returns the LLM-processed chunks to `pending` (ADR-0003, ADR-0004); rule-derived edges are kept.
- Quality of the relation types is only verifiable against the gold set of issue #28.
- Jurisprudência (ementa + tese) reuses this enricher through a follow-up issue; the input is text, id and source type.
