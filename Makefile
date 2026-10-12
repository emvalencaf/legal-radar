.PHONY: seed export-seed refresh-prompts

# Rebuild a fresh Neo4j from the versioned seed (docker compose up -d neo4j first).
seed:
	uv run legal-radar seed

# Re-export the live graph to seed/graph.jsonl.
export-seed:
	uv run legal-radar export-seed

# Re-snapshot the pinned LangSmith Hub prompts into prompts/lock.json (needs LANGSMITH_API_KEY).
refresh-prompts:
	uv run --extra prompts legal-radar refresh-prompts
