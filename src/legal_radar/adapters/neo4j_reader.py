"""Neo4j adapter for the GraphReader port: the retrieval traversal as parameterized Cypher."""

from neo4j import Driver

from legal_radar.domain import Context, Dispositivo, Hop, Jurisprudencia

LEI_IDS = "MATCH (l:Lei) RETURN l.id AS id ORDER BY id"
PARTS_DOWN = """
MATCH p = (a)-[:PARTS*0..]->(d:Dispositivo)
WHERE a.id IN $anchor_ids AND (a:Lei OR a:Dispositivo)
RETURN d AS node, [r IN relationships(p) | [startNode(r).id, endNode(r).id]] AS hops
ORDER BY d.id, length(p)
"""
REFERENCED = """
MATCH (s:Dispositivo)-[:REFERENCES]->(t:Dispositivo)
WHERE s.id IN $ids
RETURN t AS node, s.id AS source, t.id AS target
ORDER BY t.id, s.id
"""
CITING = """
MATCH (j:Jurisprudencia)-[:REFERENCES]->(d:Dispositivo)
WHERE d.id IN $ids
RETURN j AS node, j.id AS source, d.id AS target
ORDER BY j.id, d.id
"""


def _dispositivo(node) -> Dispositivo:
    # The Lei is the id's prefix: ids are `{lei_id}#{path}`.
    return Dispositivo(
        id=node["id"],
        lei_id=node["id"].split("#", 1)[0],
        path=node["path"],
        text=node["text"],
        kind=node["kind"],
    )


def _jurisprudencia(node) -> Jurisprudencia:
    return Jurisprudencia(
        id=node["id"],
        court=node["court"],
        number=node["number"],
        ementa=node["ementa"],
        decisao=node["decisao"],
        tese=node["tese"],
    )


class Neo4jGraphReader:
    def __init__(self, driver: Driver):
        self._driver = driver

    def _rows(self, query: str, **parameters):
        records, _, _ = self._driver.execute_query(query, **parameters)
        return records

    def lei_ids(self) -> list[str]:
        return [r["id"] for r in self._rows(LEI_IDS)]

    def traverse(self, anchor_ids: list[str]) -> Context:
        dispositivos: dict[str, Dispositivo] = {}
        paths: dict[str, list[Hop]] = {}
        for r in self._rows(PARTS_DOWN, anchor_ids=anchor_ids):
            node = r["node"]
            if node["id"] in dispositivos:  # reached from two anchors: the nearer one is kept
                continue
            dispositivos[node["id"]] = _dispositivo(node)
            paths[node["id"]] = [Hop("PARTS", a, b) for a, b in r["hops"]]
        parts = list(dispositivos)

        for r in self._rows(REFERENCED, ids=parts):
            node = r["node"]
            if node["id"] in dispositivos:  # already reached through PARTS
                continue
            dispositivos[node["id"]] = _dispositivo(node)
            paths[node["id"]] = [*paths[r["source"]], Hop("REFERENCES", r["source"], r["target"])]

        jurisprudencias: dict[str, Jurisprudencia] = {}
        # only dispositivos reached by PARTS: a decision citing a REFERENCES target would be hop 2
        for r in self._rows(CITING, ids=parts):
            node = r["node"]
            if node["id"] in jurisprudencias:
                continue
            jurisprudencias[node["id"]] = _jurisprudencia(node)
            paths[node["id"]] = [*paths[r["target"]], Hop("REFERENCES", r["source"], r["target"])]

        return Context(
            sorted(dispositivos.values(), key=lambda d: d.id),
            sorted(jurisprudencias.values(), key=lambda j: j.id),
            paths,
        )
