# Domain

The vocabulary of the system and the shape of the graph.

* [Case law (jurisprudência)](/domain/case-law.md) - Court decisions that interpret or apply a statute; the second pillar of the graph.
* [Concept vocabulary](/domain/concept-vocabulary.md) - One flat, curated YAML vocabulary per subject, shared by its statutes and case law.
* [Confidence](/domain/confidence.md) - How reliable an extracted relation is, derived from how it was extracted and never self-declared by the LLM.
* [Enrichment gold set](/domain/enrichment-gold-set.md) - The hand-validated relations each provision of the anchor slice should yield; scores agreement with one annotator.
* [Enrichment record and pending](/domain/enrichment-record.md) - The persisted state of a provision that went through the LLM, and the rule that decides what runs again.
* [Enrichment (enriquecimento)](/domain/enrichment.md) - The ingestion step that turns structural chunks into chunks carrying relations with evidence and confidence.
* [Knowledge graph](/domain/knowledge-graph.md) - The Neo4j graph of statutes, provisions, decisions and concepts; the core artifact every output derives from.
* [Legal concept (conceito jurídico)](/domain/legal-concept.md) - An entry of a subject's curated vocabulary that provisions and decisions are linked to.
* [Legal scholarship (doutrina)](/domain/legal-scholarship.md) - Academic writing and treatises on statutes and case law; the third pillar, with no source chosen yet.
* [Provision (dispositivo)](/domain/provision.md) - One structural unit of a statute: article, paragraph, item or sub-item; the granularity of graph nodes.
* [Pure-RAG baseline](/domain/pure-rag-baseline.md) - The comparison system that answers from embedding similarity alone, so the graph's value is measured.
* [Statute (lei)](/domain/statute.md) - A piece of legislation as published and structured by LexML; one of the three pillars of the graph.
* [Subject (assunto)](/domain/subject.md) - The legal topic a user searches for; the entry point that resolves to anchor statutes.
