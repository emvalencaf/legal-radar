import json
from pathlib import Path

import pytest

from legal_radar.prompts import (
    PromptError,
    default_lock,
    load_lock,
    load_pins,
    parse_lock,
    parse_manifest,
    refresh,
    refresh_lock,
)


def fetch(name, commit):
    return f"{name}@{commit} {{x}}", None


def test_refresh_snapshots_each_pin_at_its_commit():
    lock = refresh({"b": "c2", "a": "c1"}, fetch)
    assert lock.prompts == {
        "a": {"commit": "c1", "template": "a@c1 {x}", "schema": None},
        "b": {"commit": "c2", "template": "b@c2 {x}", "schema": None},
    }
    assert lock.render("a", x=1) == "a@c1 1"


def test_snapshot_hash_changes_with_a_commit_or_template():
    assert refresh({"a": "c1"}, fetch).snapshot_hash != refresh({"a": "c2"}, fetch).snapshot_hash


def test_lock_round_trips_and_rejects_hand_edits():
    lock = refresh({"a": "c1"}, fetch)
    assert parse_lock(lock.to_json()) == lock
    edited = json.loads(lock.to_json())
    edited["prompts"]["a"]["template"] = "changed"
    with pytest.raises(PromptError, match="edited by hand"):
        parse_lock(json.dumps(edited))


def test_missing_lockfile_names_the_command(tmp_path):
    with pytest.raises(PromptError, match="refresh-prompts"):
        load_lock(tmp_path / "lock.json")


def test_committed_lockfile_covers_every_pin_offline():
    lock = default_lock()
    assert set(lock.prompts) == set(load_pins())
    assert {n: p["commit"] for n, p in lock.prompts.items()} == load_pins()


def test_schema_change_changes_the_snapshot_hash():
    plain = refresh({"a": "c1"}, fetch)
    structured = refresh({"a": "c1"}, lambda n, c: ("t", {"type": "object"}))
    other = refresh({"a": "c1"}, lambda n, c: ("t", {"type": "array"}))
    assert len({plain.snapshot_hash, structured.snapshot_hash, other.snapshot_hash}) == 3


def test_manifest_yields_template_and_schema():
    message = {"kwargs": {"prompt": {"kwargs": {"template": "hi {x}"}}}}
    manifest = {"kwargs": {"messages": [message], "schema_": {"type": "object"}}}
    assert parse_manifest(manifest) == ("hi {x}", {"type": "object"})
    del manifest["kwargs"]["schema_"]
    assert parse_manifest(manifest) == ("hi {x}", None)
    with pytest.raises(PromptError, match="manifest shape"):
        parse_manifest({"kwargs": {}})


def test_committed_manifests_parse_into_the_committed_lock():
    lock = default_lock()
    for name in lock.prompts:
        path = Path(__file__).parents[1] / "prompts" / "manifests" / f"{name}.json"
        template, schema = parse_manifest(json.loads(path.read_text(encoding="utf-8")))
        assert (template, schema) == (lock.template(name), lock.prompts[name]["schema"])


def test_refresh_lock_writes_the_lockfile_at_the_pinned_commits(tmp_path):
    pins, target = tmp_path / "pins.yml", tmp_path / "lock.json"
    pins.write_text("a: c1\n", encoding="utf-8")
    lock = refresh_lock(fetch, pins, target)
    assert load_lock(target) == lock
    assert lock.prompts["a"]["commit"] == "c1"


def test_prompt_hash_moves_only_with_its_own_prompt():
    one = refresh({"a": "c1", "b": "c1"}, fetch)
    two = refresh({"a": "c1", "b": "c2"}, fetch)
    assert one.prompt_hash("a") == two.prompt_hash("a")
    assert one.prompt_hash("b") != two.prompt_hash("b")


def test_pipeline_and_drafting_stamp_each_call_with_its_prompt_hash(tmp_path):
    from legal_radar.adapters.fake_provider import FakeProvider
    from legal_radar.pipeline import run

    seen = []
    provider = FakeProvider()
    complete = provider.complete
    provider.complete = lambda prompt, params=None: seen.append(params) or complete(prompt, params)

    class Store:
        def write(self, batch):
            pass

    schema = {"properties": {"conceito_id": {"type": "string"}}}
    lock = refresh({"dispositivo-concept": "c1"}, lambda n, c: ("Tag:\n{text}", schema))
    run(
        (Path(__file__).parent / "fixtures" / "mini_lei.txt").read_text(encoding="utf-8"),
        provider,
        Store(),
        lock,
    )
    assert {p.prompt_snapshot for p in seen} == {lock.prompt_hash("dispositivo-concept")}
