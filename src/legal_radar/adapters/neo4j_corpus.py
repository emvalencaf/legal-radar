"""The vocabulary drafter's corpus, read from the Neo4j graph."""

from neo4j import Driver

from legal_radar.application.concepts import CORPUS_ROOTS

CORPUS_QUERY = """
MATCH (d:Dispositivo)
WHERE any(root IN $roots WHERE d.id = root OR d.id STARTS WITH root + "_")
RETURN d.id AS id, d.text AS text
UNION
MATCH (j:Jurisprudencia)
RETURN j.id AS id, j.ementa + coalesce("\\n" + j.tese, "") AS text
"""


def graph_corpus(driver: Driver) -> list[str]:
    """Texts of `CORPUS_ROOTS` and every jurisprudência (ementa + tese), in id order."""
    rows, _, _ = driver.execute_query(CORPUS_QUERY, roots=list(CORPUS_ROOTS))
    return [f"[{row['id']}]\n{row['text']}" for row in sorted(rows, key=lambda r: r["id"])]
