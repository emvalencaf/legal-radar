from pathlib import Path

from legal_radar.settings import ROOT, Settings


def test_defaults_resolve_inside_the_checkout():
    settings = Settings()

    assert settings.root == ROOT
    assert settings.metadata_db == ROOT / "data" / "ingestion.sqlite"
    assert settings.lock_path == ROOT / "prompts" / "lock.json"
    assert settings.checkpoint_dir == ROOT / "eval-runs" / "checkpoints"
    assert settings.neo4j_uri == "bolt://localhost:7687"


def test_from_env_overrides_only_what_is_set():
    settings = Settings.from_env(
        {"METADATA_DB": "/tmp/m.sqlite", "NEO4J_USER": "me", "LLM_TIMEOUT_SECONDS": "300"}
    )

    assert settings.metadata_db == Path("/tmp/m.sqlite")
    assert settings.neo4j_user == "me"
    assert settings.llm_timeout_seconds == 300.0
    assert settings.neo4j_password == "legal-radar-dev"
    assert settings.report_path == ROOT / "report" / "index.html"
