"""Every path and environment-derived value, resolved in one place.

Only the composition root reads the environment; everything else receives a `Settings`.
Defaults match the layout of a source checkout.
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TIMEOUT_SECONDS = 60.0  # local models can take minutes; LLM_TIMEOUT_SECONDS overrides


@dataclass(frozen=True)
class Settings:
    """Filesystem locations and service credentials, with checkout-relative defaults."""

    root: Path = ROOT
    env_file: Path = ROOT / ".env"
    seed_path: Path = ROOT / "seed" / "graph.jsonl"
    report_path: Path = ROOT / "report" / "index.html"
    metadata_db: Path = ROOT / "data" / "ingestion.sqlite"
    index_dir: Path = ROOT / "data"
    fixture_path: Path = ROOT / "tests" / "fixtures" / "mini_lei.txt"
    prompts_dir: Path = ROOT / "prompts"
    runs_dir: Path = ROOT / "eval-runs"
    questions_dir: Path = ROOT / "evals"
    concepts_dir: Path = ROOT / "concepts"
    log_path: Path = ROOT / "logs" / "llm_calls.jsonl"
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "legal-radar-dev"
    llm_timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS

    @property
    def pins_path(self) -> Path:
        return self.prompts_dir / "pins.yml"

    @property
    def lock_path(self) -> Path:
        return self.prompts_dir / "lock.json"

    @property
    def checkpoint_dir(self) -> Path:
        return self.runs_dir / "checkpoints"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        """Defaults overridden by `METADATA_DB`, `NEO4J_*` and `LLM_TIMEOUT_SECONDS`."""
        env = os.environ if env is None else env
        default = cls()
        return cls(
            metadata_db=Path(env.get("METADATA_DB", default.metadata_db)),
            neo4j_uri=env.get("NEO4J_URI", default.neo4j_uri),
            neo4j_user=env.get("NEO4J_USER", default.neo4j_user),
            neo4j_password=env.get("NEO4J_PASSWORD", default.neo4j_password),
            llm_timeout_seconds=float(env.get("LLM_TIMEOUT_SECONDS", default.llm_timeout_seconds)),
        )
