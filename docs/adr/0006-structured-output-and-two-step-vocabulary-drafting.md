# Draft the concept vocabulary with structured output in two steps, and keep its provenance outside the hash

ADR-0003 says an LLM drafts vocabulary candidates and a human curates them, but not how the draft is asked for, nor how a reader of the committed YAML can tell what the LLM wrote, from which texts, and what a person has already reviewed. The first draft asked for YAML in the prompt text and parsed it back out of code fences; it also asked for the number of concepts and the concepts in one go.

## Decision

- **Structured output on the provider port.** `CompletionParams.response_schema` carries a JSON Schema. Gemini receives it as `responseMimeType: application/json` plus `responseJsonSchema`; Groq and LM Studio as a strict `json_schema` `response_format`. The router logs its hash as `response_schema_id`, next to `prompt_id`. The prompt describes the content of each field, never the output format; every schema field has a `description`.
- **The schema enforces what it can.** Categories are an `enum` of ADR-0003's seven; `sources` may only cite ids present in the corpus sent. What it cannot express across providers (id pattern, uniqueness, 25-40 concepts) stays in the loader (`parse_vocabulary`), which every draft is run through. A draft that does not load is still written, with a warning.
- **Two steps.** Step 1 (`concept_vocabulary_count`) asks only how many distinct legal concepts the corpus holds, synonyms counting once. Step 2 (`concept_vocabulary_draft`) receives that number in its prompt and extracts exactly that many. A different number extracted is reported as a warning, not enforced with `minItems`/`maxItems`, which strict mode does not accept everywhere.
- **Provenance lives in the vocabulary file and never in `Vocabulary.hash`.** Per concept: `origin` (`llm` | `human`), `model` (`provider/model` of the extraction step, required with `llm`, forbidden otherwise), `sources` (ids of the dispositivos and jurisprudência it came from), `reviewed_by` + `reviewed_on` (together or not at all), `created_at`, `updated_at`. Per file: `status` (`draft` default | `curated`); `curated` is only accepted when every concept is reviewed. The hash covers `assunto` and each concept's `id`, `label`, `aliases`, `instructions` and `category`, so reviewing or re-dating a concept does not send LLM-processed chunks back to `pending` (ADR-0003, Versioning).
- **A draft vocabulary warns, it does not block.** `load_registered` logs how many concepts are unreviewed and still returns it, so the pipeline can be exercised before curation ends.
- **Who and when is also in git.** The file records only what git history cannot show: which concepts an LLM drafted, with which model and from which texts, and which a person reviewed. `created_at` and `updated_at` are kept by hand (or stamped on a new draft by `draft-concepts`) and can drift from `git log`; git remains the authority.
- **The registry is checked.** `load_registered` fails when the file's `assunto` differs from the one it is registered under in `VOCABULARY_PATHS`, and a test keeps `ANCHORS` and `VOCABULARY_PATHS` in step.

## Consequences

- Another provider only needs to map `response_schema` to its own structured-output field; the vocabulary code does not change.
- Two calls instead of one per draft; the count is only as good as the model's counting, and a mismatch is a warning for the curator.
- Strict `json_schema` was exercised live only against Gemini; its acceptance by the Groq and LM Studio models is covered by request-body tests only.
- The corpus is the cited ids, not their text: if a source changes after the draft, the file cannot show what the LLM read. Storing a hash of each source text next to its id is a possible extension.
- `reviewed_by` holds a name; the file is public with the repo.
- Language-neutral fields (`origin`, `status`) are English; label, aliases and instructions stay Portuguese as ADR-0003 requires.
