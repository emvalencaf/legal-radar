"""Neo4j adapter for the GraphStore port: hand-written parameterized Cypher."""

from neo4j import Driver, GraphDatabase

from legal_radar.domain.model import (
    CONCEPT_RELATIONS,
    CaseLaw,
    GraphBatch,
    Relation,
    RelationType,
)

CONSTRAINTS = [
    "CREATE CONSTRAINT lei_id IF NOT EXISTS FOR (n:Lei) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT dispositivo_id IF NOT EXISTS FOR (n:Dispositivo) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT jurisprudencia_id IF NOT EXISTS "
    "FOR (n:Jurisprudencia) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT conceito_id IF NOT EXISTS FOR (n:Conceito) REQUIRE n.id IS UNIQUE",
]


def ensure_constraints(session) -> None:
    for statement in CONSTRAINTS:
        session.run(statement)


MERGE_STATUTE = """
MERGE (l:Lei {id: $id}) SET l.title = $title, l.planalto_url = $planalto_url
REMOVE l.stub
"""
MERGE_PROVISION = """
MERGE (d:Dispositivo {id: $id})
SET d.path = $path, d.text = $text, d.kind = $kind, d.revoked = $revoked,
    d.revocations = $revocations
"""
# A statute only cited (or only revoking) is a stub keyed by its URN until it is ingested.
MERGE_STUB_STATUTE = "MERGE (l:Lei {id: $id}) ON CREATE SET l.stub = true"
COUNT_PROVISION = "MATCH (d:Dispositivo {id: $id}) RETURN count(d) AS n"
MERGE_REFERENCE = """
MATCH (s:Dispositivo|Jurisprudencia {id: $source}), (t:Dispositivo {id: $target})
MERGE (s)-[r:REFERENCES]->(t)
SET r.confidence = $confidence, r.origin = $origin, r.evidence = $evidence
"""
MERGE_REFERENCE_TO_STUB = """
MATCH (s:Dispositivo|Jurisprudencia {id: $source}), (t:Lei {id: $target})
MERGE (s)-[r:REFERENCES {locator: $locator}]->(t)
SET r.confidence = $confidence, r.origin = $origin, r.evidence = $evidence
"""
MERGE_REVOKES = """
MATCH (s:Lei {id: $source}), (t:Dispositivo {id: $target})
MERGE (s)-[r:REVOKES]->(t)
SET r.confidence = $confidence, r.origin = $origin, r.evidence = $evidence
"""
KEEP_UNRESOLVED_REFERENCE = """
MATCH (n:Dispositivo|Jurisprudencia {id: $id})
SET n.unresolved_references =
    [x IN coalesce(n.unresolved_references, []) WHERE x <> $citation] + [$citation]
"""
KEEP_UNRESOLVED_REVOKER = """
MATCH (n:Dispositivo {id: $id})
SET n.unresolved_revokers =
    [x IN coalesce(n.unresolved_revokers, []) WHERE x <> $citation] + [$citation]
"""
DELETE_LLM_RELATIONS = """
MATCH (:Dispositivo|Jurisprudencia {id: $id})-[r]->() WHERE r.origin = 'llm' DELETE r
"""
RESOLVE_CITATIONS = """
MATCH (n:Dispositivo|Jurisprudencia {id: $id})
SET n.unresolved_references = [x IN coalesce(n.unresolved_references, []) WHERE NOT x IN $citations]
"""
# Relationship types cannot be parameters; `type` is always a member of `RelationType`.
MERGE_CONCEPT_EDGE = """
MATCH (s:Dispositivo|Jurisprudencia {{id: $source}})
MERGE (c:Conceito {{id: $target}})
MERGE (s)-[r:{type}]->(c)
SET r.confidence = $confidence, r.origin = $origin, r.evidence = $evidence
"""
MERGE_STATUTE_PARTS = """
MATCH (l:Lei {id: $lei_id}), (d:Dispositivo {id: $id})
MERGE (l)-[:PARTS]->(d)
"""
MERGE_PARTS = """
MATCH (p:Dispositivo {id: $parent_id}), (d:Dispositivo {id: $id})
MERGE (p)-[:PARTS]->(d)
"""
MERGE_CASE_LAW = """
MERGE (j:Jurisprudencia {id: $id})
SET j.court = $court, j.number = $number, j.ementa = $ementa, j.tese = $tese, j.decisao = $decisao
"""
MERGE_CONCEPT = "MERGE (:Conceito {id: $id})"
MERGE_LINK = """
MATCH (d:Dispositivo {id: $dispositivo_id}), (c:Conceito {id: $conceito_id})
MERGE (d)-[:RELATES_TO]->(c)
"""


class Neo4jGraphStore:
    def __init__(self, driver: Driver):
        self._driver = driver

    @classmethod
    def connect(cls, uri: str, user: str, password: str) -> "Neo4jGraphStore":
        return cls(GraphDatabase.driver(uri, auth=(user, password)))

    @property
    def driver(self) -> Driver:
        return self._driver

    def close(self) -> None:
        self._driver.close()

    def write(self, batch: GraphBatch) -> None:
        with self._driver.session() as session:
            self._ensure_constraints(session)
            session.execute_write(self._write, batch)

    def write_case_law(self, items: list[CaseLaw], relations: list[Relation] = ()) -> None:
        with self._driver.session() as session:
            self._ensure_constraints(session)
            for j in items:
                session.run(
                    MERGE_CASE_LAW,
                    id=j.id,
                    court=j.court,
                    number=j.number,
                    ementa=j.headnote,
                    tese=j.thesis,
                    decisao=j.ruling,
                )
            session.execute_write(self._write_relations, relations)

    @staticmethod
    def _write_relations(tx, relations: list[Relation]) -> None:
        for r in relations:
            Neo4jGraphStore._write_relation(tx, r)

    def replace_llm_relations(self, chunk_id: str, relations: list[Relation]) -> None:
        with self._driver.session() as session:
            session.execute_write(self._replace_llm_relations, chunk_id, relations)

    def resolve_citations(self, chunk_id: str, citations: list[str]) -> None:
        with self._driver.session() as session:
            session.run(RESOLVE_CITATIONS, id=chunk_id, citations=citations)

    @staticmethod
    def _replace_llm_relations(tx, chunk_id: str, relations: list[Relation]) -> None:
        tx.run(DELETE_LLM_RELATIONS, id=chunk_id)
        for r in relations:
            Neo4jGraphStore._write_relation(tx, r)

    @staticmethod
    def _ensure_constraints(session) -> None:
        ensure_constraints(session)

    @staticmethod
    def _write(tx, batch: GraphBatch) -> None:
        tx.run(
            MERGE_STATUTE,
            id=batch.statute.id,
            title=batch.statute.title,
            planalto_url=batch.statute.planalto_url,
        )
        for d in batch.provisions:
            tx.run(
                MERGE_PROVISION,
                id=d.id,
                path=d.path,
                text=d.text,
                kind=d.kind,
                revoked=d.revoked,
                revocations=list(d.revocations),
            )
        for d in batch.provisions:
            if d.parent_id:
                tx.run(MERGE_PARTS, id=d.id, parent_id=d.parent_id)
            else:
                tx.run(MERGE_STATUTE_PARTS, id=d.id, lei_id=d.statute_id)
        for r in batch.relations:
            Neo4jGraphStore._write_relation(tx, r)
        for c in batch.concepts:
            tx.run(MERGE_CONCEPT, id=c.id)
        for link in batch.links:
            tx.run(MERGE_LINK, dispositivo_id=link.provision_id, conceito_id=link.concept_id)

    @staticmethod
    def _write_relation(tx, r: Relation) -> None:
        edge = {
            "confidence": r.confidence.value,
            "origin": r.origin.value,
            "evidence": r.evidence,
        }
        if r.type in CONCEPT_RELATIONS:
            tx.run(
                MERGE_CONCEPT_EDGE.format(type=r.type.value),
                source=r.source_id,
                target=r.target_id,
                **edge,
            )
        elif r.type is RelationType.REVOKES:
            if r.source_id is None:  # the revoking act did not resolve: keep the citation
                tx.run(KEEP_UNRESOLVED_REVOKER, id=r.target_id, citation=r.unresolved)
                return
            tx.run(MERGE_STUB_STATUTE, id=r.source_id)
            tx.run(MERGE_REVOKES, source=r.source_id, target=r.target_id, **edge)
        elif r.target_id is None:
            tx.run(KEEP_UNRESOLVED_REFERENCE, id=r.source_id, citation=r.unresolved)
        elif tx.run(COUNT_PROVISION, id=r.target_id).single()["n"]:
            tx.run(MERGE_REFERENCE, source=r.source_id, target=r.target_id, **edge)
        else:  # a provision of a statute the graph lacks: point at the stub, keep where in it
            statute, _, locator = r.target_id.partition("#")
            tx.run(MERGE_STUB_STATUTE, id=statute)
            tx.run(
                MERGE_REFERENCE_TO_STUB, source=r.source_id, target=statute, locator=locator, **edge
            )
