#!/usr/bin/env bash
# Start Neo4j via docker compose and run the pipeline over the fixture.
set -euo pipefail
cd "$(dirname "$0")/.."

if docker compose version >/dev/null 2>&1; then
  compose=(docker compose)
else
  compose=(docker-compose)
fi

"${compose[@]}" up -d neo4j
echo "waiting for Neo4j..."
for _ in $(seq 60); do
  "${compose[@]}" exec -T neo4j cypher-shell -u neo4j \
  -p "${NEO4J_PASSWORD:-legal-radar-dev}" 'RETURN 1' >/dev/null 2>&1 && break
  sleep 2
done
"${compose[@]}" exec -T neo4j cypher-shell -u neo4j -p "${NEO4J_PASSWORD:-legal-radar-dev}" 'RETURN 1' >/dev/null || { echo "Neo4j did not become ready" >&2; exit 1; }
uv run legal-radar run "$@"
