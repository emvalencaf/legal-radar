# Keep one flat, curated concept vocabulary per assunto, shared by lei and jurisprudência

The graph's Conceito node (issue #7) needs a concrete vocabulary. The sibling repo `ip_lawyer_consiglier` has a YAML controlled vocabulary keyed by *lei* with categories specific to industrial property. Desconsideração da personalidade jurídica (issue #9) crosses CC, CPC and CDC plus STF/STJ precedents, so a per-lei vocabulary would fragment one concept into several nodes (issue #18).

## Decision

- **Reuse the shape, not the content.** A flat YAML controlled vocabulary with `id`, `label`, `aliases`, `instructions`, `category`; the LLM returns `concept_id`s validated against it (ADR-0002). No hierarchy (`parent` / `IS_A`) in the MVP: no retrieval query in issue #11 walks it. Left as a stage-2 extension point.
- **One file per assunto**, shared by every lei and by jurisprudência of that assunto (e.g. `concepts/desconsideracao_personalidade.yml`). Generic concepts repeat across assuntos; accepted.
- **Categories:** DIREITO, ATOR, PROCESSO, REQUISITO, PRINCIPIO, TEORIA, EFEITO. Exactly one per concept. The sibling's RESTRICAO and REFERENCIA are dropped: the category says what a concept *is*, the edge (`PROHIBITS`, `EXCEPTS`, `REFERENCES`) says the relation a text has to it.
- **Content conventions:** `id` is lowercase ASCII snake_case; `label`, `aliases`, `instructions` are in Portuguese, to match the text the LLM reads. Target size ~25-40 concepts, so it fits the prompt and stays reviewable.
- **Authoring:** an LLM drafts candidates from the seed corpus (CC art. 50, CPC arts. 133-137, ementas of Tema 1210 and Tema 1232); a human curates. Versioned in the repo.
- **Jurisprudência→Conceito** amends ADR-0002's scope: the same enricher and vocabulary run over a decision's ementa + tese, allowing `APPLIES_TO`, `DEFINES` and `RELATES_TO`, always origin `llm` / MEDIUM.
- **Out-of-vocabulary terms** stay out of the graph but are recorded (proposed term + chunk) in the ingestion report next to the drop counts; the human reads it to curate the next vocabulary version. No review queue, no automatic promotion.
- **Versioning:** the vocabulary's hash is part of the idempotency key (with text hash and extractor version). A vocabulary change returns only LLM-processed chunks to `pending`; rule-derived edges are kept.

## Consequences

- Vocabulary curation is manual work per assunto and is the main cost of growing the assunto catalog.
- Concept edges are only as complete as the vocabulary; the out-of-vocabulary report is the feedback loop.
- The enricher (issue #27) and persistence (issue #29) scopes change accordingly.
