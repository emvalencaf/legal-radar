.PHONY: seed export-seed

# Rebuild a fresh Neo4j from the versioned seed (docker compose up -d neo4j first).
seed:
	uv run legal-radar seed

# Re-export the live graph to seed/graph.jsonl.
export-seed:
	uv run legal-radar export-seed
