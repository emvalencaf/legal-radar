# Decisions

The architecture decision records, summarised.

* [ADR-0001: Planalto HTML as the full-text source](/decisions/adr-0001-planalto-full-text.md) - Use Planalto's HTML rendition, not LexML XML, as the statute's full text.
* [ADR-0002: Hybrid relation extraction](/decisions/adr-0002-hybrid-extraction.md) - Extract relations with rules plus an LLM and derive confidence from provenance, never from the LLM.
* [ADR-0003: One concept vocabulary per subject](/decisions/adr-0003-concept-vocabulary.md) - Keep a flat, curated vocabulary per subject, shared by statutes and case law.
* [ADR-0004: LangSmith prompts, tracing and the Pages report](/decisions/adr-0004-langsmith-prompts-and-pages.md) - Manage prompts in LangSmith by pinned commit, trace only query time and evaluation, publish the report on GitHub Pages.
* [ADR-0005: Embeddings on the provider port, resolution in memory](/decisions/adr-0005-embedding-and-resolution.md) - Put `embed()` on the provider port, Gemini first, and resolve the subject in memory by cosine similarity.
* [ADR-0006: Structured output and two-step vocabulary drafting](/decisions/adr-0006-two-step-vocabulary-drafting.md) - Draft the vocabulary with provider-level structured output in two steps, keeping provenance outside the hash.
* [ADR-0007: One enrichment prompt with grounded references](/decisions/adr-0007-single-enrichment-prompt.md) - Replace the one-concept tagger with one prompt per provision and ground references in a closed candidate list.
* [ADR-0008: Decisions take every concept relation](/decisions/adr-0008-decisions-take-every-relation.md) - Let a decision take all six concept relations and guard against false positives in the prompt and the code.
* [ADR-0009: Layered architecture enforced by import-linter](/decisions/adr-0009-layered-architecture.md) - One bounded context in four layers, with inward-only dependencies checked in CI.
