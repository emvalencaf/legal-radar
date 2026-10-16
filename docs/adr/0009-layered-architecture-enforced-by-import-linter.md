# Layered architecture, enforced by import-linter

`legal_radar` is one bounded context organised in four layers, `entrypoints > adapters > application > domain`, with dependencies pointing inward only. Ports (small `Protocol`s) live in `application/ports/`; adapters implement them; `bootstrap.py` is the only module that knows concrete adapters and reads the environment, and a `Settings` object holds every path and configuration value. An `import-linter` contract in CI fails the build when a layer imports outward, and the domain may not import `neo4j`, `bs4`, `sqlite3`, `langsmith` or similar.

We chose one context over several (knowledge building, answering, evaluation) because the vocabulary and the graph are shared and the code is small; capabilities are subpackages and can be promoted to contexts later. We chose light DDD (a pure domain model plus ports) over entities, aggregates and repositories, which a batch pipeline has no lifecycle for. The migration is structural only: behaviour does not change, and the lint contract starts permissive with a documented `ignore_imports` list that shrinks as modules move.

## Considered Options

- **Convention only, no lint.** Rejected: boundaries erode within weeks without an automated check.
- **Several bounded contexts with a shared kernel.** Rejected for now: ceremony outweighs the benefit at this size.
- **Full tactical DDD, CQRS and a unit of work.** Rejected: no write-side lifecycle to model.
