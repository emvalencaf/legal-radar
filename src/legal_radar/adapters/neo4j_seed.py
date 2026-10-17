"""Versioned graph seed: the whole graph as sorted JSON lines, rebuilt with MERGE.

One line per node (`{"kind": "node", "label", "props"}`) then per edge
(`{"kind": "edge", "type", "from", "to"}`), both sorted, so exporting an unchanged graph yields
byte-identical text and the seed diffs cleanly in git.
"""

import json
from collections import defaultdict

from neo4j import Driver

from legal_radar.adapters.neo4j_store import ensure_constraints

LABELS = ("Conceito", "Dispositivo", "Jurisprudencia", "Lei")
EDGE_TYPES = ("PARTS", "RELATES_TO")

NODES_QUERY = "MATCH (n) RETURN labels(n)[0] AS label, properties(n) AS props"
EDGES_QUERY = """
MATCH (a)-[r]->(b)
RETURN type(r) AS type, labels(a)[0] AS from_label, a.id AS from_id,
       labels(b)[0] AS to_label, b.id AS to_id
"""


def export_seed(driver: Driver) -> str:
    nodes, _, _ = driver.execute_query(NODES_QUERY)
    edges, _, _ = driver.execute_query(EDGES_QUERY)
    lines = [
        {"kind": "node", "label": r["label"], "props": r["props"]}
        for r in sorted(nodes, key=lambda r: (r["label"], r["props"]["id"]))
    ] + [
        {
            "kind": "edge",
            "type": r["type"],
            "from": [r["from_label"], r["from_id"]],
            "to": [r["to_label"], r["to_id"]],
        }
        for r in sorted(
            edges,
            key=lambda r: (r["type"], r["from_label"], r["from_id"], r["to_label"], r["to_id"]),
        )
    ]
    return "".join(json.dumps(line, sort_keys=True, ensure_ascii=False) + "\n" for line in lines)


def load_seed(driver: Driver, seed: str) -> None:
    """Rebuild the graph from a seed; MERGE on constrained ids makes re-loading a no-op."""
    nodes: dict[str, list[dict]] = defaultdict(list)
    edges: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for line in seed.splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if record["kind"] == "node":
            _check(record["label"], LABELS)
            nodes[record["label"]].append(record["props"])
        else:
            _check(record["type"], EDGE_TYPES)
            (from_label, from_id), (to_label, to_id) = record["from"], record["to"]
            _check(from_label, LABELS)
            _check(to_label, LABELS)
            edges[(record["type"], from_label, to_label)].append({"a": from_id, "b": to_id})

    with driver.session() as session:
        ensure_constraints(session)
        # Labels and types cannot be parameters; they are checked against the allow-lists above.
        for label, rows in nodes.items():
            session.run(
                f"UNWIND $rows AS row MERGE (n:{label} {{id: row.id}}) SET n += row", rows=rows
            )
        for (type_, from_label, to_label), rows in edges.items():
            session.run(
                f"UNWIND $rows AS row MATCH (a:{from_label} {{id: row.a}}), "
                f"(b:{to_label} {{id: row.b}}) MERGE (a)-[:{type_}]->(b)",
                rows=rows,
            )


def _check(value: str, allowed: tuple[str, ...]) -> None:
    if value not in allowed:
        raise ValueError(f"unexpected {value!r} in seed; expected one of {allowed}")
