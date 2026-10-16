# Architecture

How the code is organised and how a question is answered and evaluated.

* [How quality is measured](/architecture/evaluation.md) - Answer evaluation against RAG baselines, and enrichment evaluation against a gold set with quality gates.
* [Layers and the dependency rule](/architecture/layers.md) - Four layers with inward-only dependencies, enforced by import-linter in CI.
* [LLM router and providers](/architecture/llm-router.md) - One provider port for completions and embeddings, with fallback, waits, retries and wide events.
* [The end-to-end run](/architecture/pipeline.md) - Ingest statutes and decisions, export the seed, answer, evaluate and report; enrichment is optional.
* [Prompts and tracing](/architecture/prompts-and-tracing.md) - Prompts are pinned to LangSmith Hub commits and read offline from a lockfile; tracing is optional.
* [How a question is answered](/architecture/query-time-answering.md) - Resolve the subject, traverse the graph, generate a cited answer, and check every citation.
* [Subject resolution](/architecture/subject-resolution.md) - Maps a query to a known subject by cosine similarity over embeddings, in memory.
