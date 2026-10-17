# Embed on the provider port, Gemini first, and resolve assunto in memory

Issue #40 needs `Resolução de assunto` by semantic similarity and the spec left the embedding model open. The completion providers are already routed (fallback, wait, retry, wide events), and the anchor catalog is tiny.

## Decision

- **`embed(texts)` lives on the same `Provider` port as `complete()`** and goes through the same `Router`: fallback on quota, RPM wait, one transient retry, daily limits, and one wide event per call (`event: "embed_call"`, with `input_count` and the hash of the inputs, text only when `log_full_content`). Each provider carries an `embedding_model` next to its `model`; `router.yaml` sets it under `embedding_models`.
- **Gemini `gemini-embedding-001` is the primary model**: a multilingual model that handles Portuguese, on the free tier already used for completions. **LM Studio `text-embedding-bge-m3`** (multilingual) is the local fallback. **Groq serves no embedding model**, so its `embed()` raises and the router moves on. Model names are config, not code, and were not benchmarked on Portuguese legal text; the threshold below is the thing to recalibrate if they change.
- **Vectors from different models are never compared.** The resolver remembers which model embedded the catalog and re-embeds it when a query is served by another model (a fallback), and declines to match if the model changes mid-resolution.
- **Resolution is in memory, no vector store**: the anchor catalog (`ANCHORS` keys) is embedded once per process, and the query is matched by cosine similarity against it. Below `DEFAULT_THRESHOLD` (0.5) nothing resolves, which is how an unrelated query is rejected. The catalog is small, so a linear scan is enough; a vector store is deferred until the catalog grows.
- **A deterministic `FakeProvider.embed()`** (hashed bag of accent-stripped word stems) keeps tests offline and exercises threshold behaviour. Its 0.5 threshold is calibrated to the fake, not to a real model.

## Consequences

- Embedding calls are checked against the provider's daily limit but counted per model, so they do not draw down the completion count; the cap is not shared between `complete()` and `embed()`.
- Only anchor assuntos resolve; there is no catalog growth yet.
- The Gemini request sets no `taskType` (`RETRIEVAL_QUERY`/`RETRIEVAL_DOCUMENT`); revisit if live similarity is poor.
- The real-model threshold needs checking with live embeddings before relying on it.
