# Extract relations with a hybrid rule + LLM enricher, and derive Confidence from provenance

`PlanaltoHtmlParser` yields bare structural `LegalChunk`s. The graph schema (issue #7) also needs `REFERENCES`, `REVOKES` and dispositivo→conceito edges, none of which Planalto or LexML expose as structured data: citations are loose text ("art. 50 do CCB"). We decided an **enrichment** step turns `LegalChunk`s into `EnrichedLegalChunk`s (issue #24).

The sibling repo `ip_lawyer_consiglier` does this with an LLM only, has no regex for cross-references, lets the LLM self-declare `Confidence`, never checks that `evidence` is literal, and has no enrichment gold set. We reuse its entities and enums but not those choices.

## Decision

- **Hybrid extraction.** Deterministic rules handle explicit references (`art. 50 do Código Civil`, `Lei nº 8.078/1990`), relatives (`deste artigo`, `o artigo anterior`) and ranges (`incisos I a III`, expanded to one edge per target), plus `REVOKES` from Planalto's `(Revogado pela …)` marks. The LLM handles only what the rules leave ambiguous or unresolved, and all dispositivo→conceito extraction, since concepts have no regular textual pattern. `REVOKES` is never produced by the LLM. `(Redação dada por …)` is an amendment, not a revocation, and is out of scope for now.
- **Confidence comes from provenance, never from the LLM's own claim.** HIGH: a rule matched an explicit pattern. MEDIUM: the LLM inferred the target or concept. LOW: unresolved target or stub. The origin (`rule` / `llm`) is also stored on the edge.
- **Concepts use a controlled vocabulary** loaded from configuration (YAML), the same pattern as the sibling repo; its content comes from issue #18. The LLM returns structured output validated against that vocabulary, and anything outside it is discarded.
- **MVP relation types:** `REFERENCES`, `REVOKES`, and dispositivo→conceito `DEFINES`, `APPLIES_TO`, `OBLIGES`, `PROHIBITS`, `EXCEPTS`, plus a generic `RELATES_TO` for the rest. The other `RelationType` values from #7 are deferred; the enricher interface is extensible.
- **Target resolution.** A law name resolves to a URN via a curated table of the most-cited codes, falling back to LexML for law numbers. A cited lei that is not ingested becomes a stub Lei node keyed by URN; if no URN resolves, the citation is kept as an unresolved attribute. If the target lei is already in the graph, the target dispositivo must exist, otherwise the edge is downgraded to LOW/stub.
- **Validation.** `evidence` must be a literal substring of the chunk, otherwise the item is dropped. Dropped items are logged and counted (no human-review queue in the MVP).
- **Pipeline placement.** Runs at ingestion, after parsing and before graph load. Per-chunk results (text hash, extractor version, status `ok`/`pending`, dropped-item count) are persisted in an ingestion-metadata store separate from the graph; only validated edges are loaded into the graph. A failed batch does not block loading a lei: its chunks stay `pending` and an idempotent reprocessing run resumes them.
- **LLM access.** Through the `ProviderPort` from issue #8, with the model set by configuration and no complexity routing in the MVP. Only chunks the rules did not fully resolve are sent.
- **Evaluation.** Continuous indirect metrics (target-resolved rate, valid-evidence rate, drop rate) plus a small hand-annotated gold set (~50–100 dispositivos of the issue #9 slice), scored per edge and per concept + relation type, split by origin so we can tell whether the LLM adds value over the rules.

## Consequences

- The deterministic extractor is new code; nothing in the sibling repo can be reused for it.
- Extraction quality is measurable per origin, so rules or prompts can change with evidence.
- LLM-inferred edges are never HIGH; retrieval may weight edges by confidence and origin.
- LLM concept extraction is blocked by the vocabulary from issue #18.
