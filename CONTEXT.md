# Legal Radar

A graph-RAG system over Brazilian legal sources (LexML) that, given a legal subject, associates the law, jurisprudência, and doutrina that bear on it.

## Language

**Assunto**:
The subject/topic a user searches for — the entry point into the system, e.g. "prescrição intercorrente." Resolves to one or more `lei` as the anchor for graph traversal.
_Avoid_: Topic, query, search term (in English contexts, prefer keeping "assunto" since it's the domain's own entry-point concept).

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
In this project, "AST" means the parsed hierarchical structure of a legal document — título → capítulo → artigo → parágrafo → inciso → alínea — derived from LexML's XML schema. It is the intermediate representation between raw LexML documents and graph nodes, anchoring nodes at the right granularity (e.g. one node per artigo, not one node per document).
_Avoid_: Using "AST" unqualified outside this context, since it collides with the programming-language sense (parsed source code). Always read as "legal document AST" in this project.

**LexML**:
The Brazilian federal legislative/jurisprudential portal (lexml.gov.br) treated as this project's source of truth for `lei` and `jurisprudência`. Publishes documents in a structured XML schema that the legal-document AST is parsed from.
_Avoid_: "The portal" alone without naming it, once multiple sources exist.

**Knowledge graph**:
The graph store holding `lei`, `jurisprudência`, and `doutrina` nodes and the relationships between them (e.g. a `jurisprudência` node citing a `lei` node's `artigo`). This is distinct from LangGraph — see below.
_Avoid_: "The graph" when LangGraph is also in scope in the same sentence; be explicit about which graph is meant.

**LangGraph**:
The orchestration framework used to structure the retrieval/generation pipeline (e.g. parse query → traverse knowledge graph → retrieve → rank → generate → cite) as a sequence/graph of pipeline steps. Not the knowledge graph itself, and not a graph database.
_Avoid_: "The graph" as shorthand — always qualify as "LangGraph" or "the pipeline" to keep it distinct from the knowledge graph.

**Alteração legislativa**:
A legislative amendment to a `lei`. Triggers a cascade of potentially-affected entities: artigos afetados (articles changed), conceitos afetados (concepts touched), precedentes potencialmente afetados (jurisprudência that may no longer hold), and documentos dependentes (doutrina or other documents referencing the changed text). This cascade is a candidate relationship shape for the knowledge graph, not yet an implemented feature.
_Avoid_: "Update" or "change" alone — "alteração legislativa" is the specific domain event; a generic "update" doesn't carry the cascade semantics.
