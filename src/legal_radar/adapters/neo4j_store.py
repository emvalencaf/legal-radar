"""Neo4j adapter for the GraphStore port: hand-written parameterized Cypher."""

from neo4j import Driver, GraphDatabase

from legal_radar.domain import GraphBatch

CONSTRAINTS = [
    "CREATE CONSTRAINT lei_id IF NOT EXISTS FOR (n:Lei) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT dispositivo_id IF NOT EXISTS FOR (n:Dispositivo) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT conceito_id IF NOT EXISTS FOR (n:Conceito) REQUIRE n.id IS UNIQUE",
]

MERGE_LEI = "MERGE (l:Lei {id: $id}) SET l.title = $title, l.planalto_url = $planalto_url"
MERGE_DISPOSITIVO = """
MERGE (d:Dispositivo {id: $id}) SET d.path = $path, d.text = $text, d.kind = $kind
"""
MERGE_LEI_PARTS = """
MATCH (l:Lei {id: $lei_id}), (d:Dispositivo {id: $id})
MERGE (l)-[:PARTS]->(d)
"""
MERGE_PARTS = """
MATCH (p:Dispositivo {id: $parent_id}), (d:Dispositivo {id: $id})
MERGE (p)-[:PARTS]->(d)
"""
MERGE_CONCEITO = "MERGE (:Conceito {id: $id})"
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

    def close(self) -> None:
        self._driver.close()

    def write(self, batch: GraphBatch) -> None:
        with self._driver.session() as session:
            for statement in CONSTRAINTS:
                session.run(statement)
            session.execute_write(self._write, batch)

    @staticmethod
    def _write(tx, batch: GraphBatch) -> None:
        tx.run(
            MERGE_LEI,
            id=batch.lei.id,
            title=batch.lei.title,
            planalto_url=batch.lei.planalto_url,
        )
        for d in batch.dispositivos:
            tx.run(MERGE_DISPOSITIVO, id=d.id, path=d.path, text=d.text, kind=d.kind)
        for d in batch.dispositivos:
            if d.parent_id:
                tx.run(MERGE_PARTS, id=d.id, parent_id=d.parent_id)
            else:
                tx.run(MERGE_LEI_PARTS, id=d.id, lei_id=d.lei_id)
        for c in batch.conceitos:
            tx.run(MERGE_CONCEITO, id=c.id)
        for link in batch.links:
            tx.run(MERGE_LINK, dispositivo_id=link.dispositivo_id, conceito_id=link.conceito_id)
