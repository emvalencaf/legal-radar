.PHONY: seed export-seed refresh-prompts eval report publish-report

# Rebuild a fresh Neo4j from the versioned seed (docker compose up -d neo4j first).
seed:
	uv run legal-radar seed

# Re-export the live graph to seed/graph.jsonl.
export-seed:
	uv run legal-radar export-seed

# Re-snapshot the pinned LangSmith Hub prompts into prompts/lock.json (needs LANGSMITH_API_KEY).
refresh-prompts:
	uv run --extra prompts legal-radar refresh-prompts

# Answer the question set over the anchor assunto and score it (needs Neo4j, the router's
# providers and `uv sync --extra eval`); results land in eval-runs/.
eval:
	uv run --extra eval legal-radar eval "desconsideração da personalidade jurídica"

# Write the static report from the latest runs in eval-runs/ to report/index.html.
report:
	uv run legal-radar report

# Publish the report to GitHub Pages (manual; pushes the gh-pages branch).
publish-report:
	scripts/publish-report.sh
