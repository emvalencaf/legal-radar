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
until "${compose[@]}" exec -T neo4j cypher-shell -u neo4j \
  -p "${NEO4J_PASSWORD:-legal-radar-dev}" 'RETURN 1' >/dev/null 2>&1; do
  sleep 2
done
uv run legal-radar run "$@"
