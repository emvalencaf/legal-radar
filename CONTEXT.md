# Legal Radar

A graph-RAG system over Brazilian legal sources (LexML) that, given a legal subject, associates the law, jurisprudência, and doutrina that bear on it.

## Language

**Assunto**:
The subject/topic a user searches for — the entry point into the system, e.g. "prescrição intercorrente." Resolves to one or more `lei` as the anchor for graph traversal. See `Resolução de assunto` for how that resolution happens.
_Avoid_: Topic, query, search term (in English contexts, prefer keeping "assunto" since it's the domain's own entry-point concept).

**Resolução de assunto**:
The step that maps a user's raw query text to a known `assunto` in the system's growing catalog, by semantic similarity, yielding the anchor node graph traversal starts from. A one-time step per query, distinct from the graph traversal that follows it.
_Avoid_: Conflating with traversal itself — resolution picks the starting point; it doesn't walk the graph.

**Lei**:
A piece of legislation as published and structured by LexML (constitution, statute, decree, etc.). One of the three pillars of the knowledge graph.
_Avoid_: Law text, statute (use "lei" consistently; "statute" only when writing in English about a non-Brazilian comparison).

**Jurisprudência**:
The body of court decisions (precedentes) that interpret or apply a `lei`. The second pillar of the knowledge graph.
_Avoid_: Case law, precedent (as a standalone synonym — "precedente" is a member of jurisprudência, not interchangeable with the pillar itself).

**Doutrina**:
Legal scholarship/commentary (academic writing, treatises) that analyzes a `lei` or `jurisprudência`. The third pillar of the knowledge graph. Its source is not yet decided — LexML is not a strong doctrine source, so a viable source is an open question.
_Avoid_: Commentary, literature.

**AST (legal document structure tree)**:
In this project, "AST" means the parsed hierarchical structure of a legal document — título → capítulo → artigo → parágrafo → inciso → alínea. It is the intermediate representation between a `lei`'s full text and graph nodes, anchoring nodes at the right granularity (e.g. one node per artigo, not one node per document). Parsed from the `lei`'s Planalto HTML rendition (see `Lei full text`), not from a LexML XML document — see ADR-0001.
_Avoid_: Using "AST" unqualified outside this context, since it collides with the programming-language sense (parsed source code). Always read as "legal document AST" in this project. Don't imply it's parsed from LexML's own XML schema — it isn't (ADR-0001).

**LexML**:
The Brazilian federal legislative/jurisprudential portal (lexml.gov.br) treated as this project's identity and discovery layer for `lei` and `jurisprudência`: assunto search and URN resolution. Not the source of a `lei`'s full text — see `Lei full text` and ADR-0001.
_Avoid_: "The portal" alone without naming it, once multiple sources exist. Don't treat it as the full-text source — that's Planalto (ADR-0001).

**Lei full text**:
The actual document body a `lei`'s legal-document AST is parsed from. Sourced from the Planalto portal's HTML rendition (`planalto.gov.br/ccivil_03/leis/{law_id}.htm`), reached via the URL published on the `lei`'s resolved LexML URN page — not from LexML directly. See ADR-0001.
_Avoid_: Assuming this comes from LexML's own XML schema.

**Enriquecimento**:
The ingestion step that turns bare structural `LegalChunk`s into `EnrichedLegalChunk`s carrying relations (`REFERENCES`, `REVOKES`, dispositivo→conceito) with evidence and `Confidence`. Hybrid: deterministic rules for explicit references and revocations, an LLM for ambiguous cases and concepts. Runs after parsing and before graph load. See ADR-0002.
_Avoid_: Conflating with parsing — parsing (`PlanaltoHtmlParser`) is structural and rule-only; enrichment is semantic.

**Confidence**:
The reliability level of an extracted relation, derived from how it was extracted, never self-declared by the LLM: HIGH = a rule matched an explicit pattern in the text; MEDIUM = the LLM inferred it from context; LOW = unresolved target or stub. The origin (`rule` / `llm`) is stored on the edge too. See ADR-0002.
_Avoid_: Treating an LLM's verbalized confidence as this value.

**Conceito jurídico**:
A recurring legal idea (an institute, actor, requirement, theory, effect, principle, procedure or right) that dispositivos and `jurisprudência` decisions of an `assunto` speak about, e.g. "abuso da personalidade". The central hub of the knowledge graph: it is what lets a `lei` provision and a decision be associated through what they are about. Always belongs to exactly one category and to one `Vocabulário de conceitos`.
_Avoid_: Tag, keyword, topic (a conceito is a curated, closed-set entry, not free text; "assunto" is the search entry point, a broader thing).

**Vocabulário de conceitos**:
The curated, versioned, closed list of `conceito jurídico` entries for one `assunto`, shared by every `lei` and `jurisprudência` of that assunto. Enrichment only ever links to entries in it; a term it proposes that is not in the list is recorded for curation but never enters the knowledge graph. See ADR-0003.
_Avoid_: Ontology, taxonomy (it is flat: no hierarchy between conceitos), "per-lei vocabulary" (scope is the assunto, not the lei).

**Knowledge graph**:
The graph store holding `lei`, `jurisprudência`, and `doutrina` nodes and the relationships between them (e.g. a `jurisprudência` node citing a `lei` node's `artigo`). This is distinct from LangGraph — see below.
_Avoid_: "The graph" when LangGraph is also in scope in the same sentence; be explicit about which graph is meant.

**LangGraph**:
The orchestration framework used to structure the retrieval/generation pipeline (e.g. parse query → traverse knowledge graph → retrieve → rank → generate → cite) as a sequence/graph of pipeline steps. Not the knowledge graph itself, and not a graph database.
_Avoid_: "The graph" as shorthand — always qualify as "LangGraph" or "the pipeline" to keep it distinct from the knowledge graph.

**Alteração legislativa**:
A legislative amendment to a `lei`. Triggers a cascade of potentially-affected entities: artigos afetados (articles changed), conceitos afetados (concepts touched), precedentes potencialmente afetados (jurisprudência that may no longer hold), and documentos dependentes (doutrina or other documents referencing the changed text). This cascade is a candidate relationship shape for the knowledge graph, not yet an implemented feature.
_Avoid_: "Update" or "change" alone — "alteração legislativa" is the specific domain event; a generic "update" doesn't carry the cascade semantics.
