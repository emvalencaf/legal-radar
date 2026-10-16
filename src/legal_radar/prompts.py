"""Prompts pinned to LangSmith Hub commits and read offline from a versioned lockfile.

`prompts/pins.yml` maps each prompt name to the Hub commit it follows; `prompts/lock.json` holds a
snapshot of each pinned prompt's template. Everything at run time and in tests reads the lockfile:
LangSmith is only reached by `refresh`, so the pipeline needs no account or network.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import yaml

from legal_radar.domain.llm import content_hash

ROOT = Path(__file__).resolve().parents[2] / "prompts"
PINS_PATH = ROOT / "pins.yml"
LOCK_PATH = ROOT / "lock.json"

Fetch = Callable[[str, str], tuple[str, dict | None]]  # (name, commit) -> (template, schema)


class PromptError(Exception):
    """The pins or the lockfile are missing, malformed or out of step."""


@dataclass(frozen=True)
class PromptLock:
    prompts: dict[str, dict]  # name -> {"commit": str, "template": str, "schema": dict | None}

    @property
    def snapshot_hash(self) -> str:
        """Changes when any pinned prompt's commit or template does."""
        return content_hash(self.prompts)

    def prompt_hash(self, name: str) -> str:
        """Changes when this prompt's commit, template or schema does, and no other's."""
        self.template(name)
        return content_hash(self.prompts[name])

    def template(self, name: str) -> str:
        try:
            return self.prompts[name]["template"]
        except KeyError:
            raise PromptError(f"prompt {name!r} is not in the lockfile") from None

    def schema(self, name: str) -> dict | None:
        """The pinned JSON Schema of the prompt's structured output, if it has one."""
        self.template(name)
        return self.prompts[name].get("schema")

    def render(self, name: str, **values: object) -> str:
        return self.template(name).format(**values)

    def to_json(self) -> str:
        document = {"snapshot_hash": self.snapshot_hash, "prompts": self.prompts}
        return json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def parse_lock(text: str) -> PromptLock:
    try:
        document = json.loads(text)
        lock = PromptLock({n: dict(p) for n, p in document["prompts"].items()})
        recorded = document["snapshot_hash"]
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        raise PromptError(f"the prompt lockfile is malformed: {error}") from error
    if recorded != lock.snapshot_hash:
        raise PromptError("the prompt lockfile was edited by hand: run `refresh-prompts`")
    return lock


def load_lock(path: Path = LOCK_PATH) -> PromptLock:
    if not path.exists():
        raise PromptError(f"{path} is missing: run `legal-radar refresh-prompts`")
    return parse_lock(path.read_text(encoding="utf-8"))


def load_pins(path: Path = PINS_PATH) -> dict[str, str]:
    pins = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(pins, dict) or not all(
        isinstance(n, str) and isinstance(c, str) and c for n, c in pins.items()
    ):
        raise PromptError(f"{path} must map each prompt name to a commit hash")
    return pins


def refresh(pins: dict[str, str], fetch: Fetch) -> PromptLock:
    """Snapshot every pinned prompt at its pinned commit."""
    prompts = {}
    for name, commit in sorted(pins.items()):
        template, schema = fetch(name, commit)
        prompts[name] = {"commit": commit, "template": template, "schema": schema}
    return PromptLock(prompts)


def refresh_lock(
    fetch: Fetch, pins_path: Path = PINS_PATH, lock_path: Path = LOCK_PATH
) -> PromptLock:
    """Rewrites the lockfile from the Hub at the commits pinned in `pins_path`."""
    lock = refresh(load_pins(pins_path), fetch)
    lock_path.write_text(lock.to_json(), encoding="utf-8")
    return lock


def langsmith_fetch(name: str, commit: str) -> tuple[str, dict | None]:
    """Pulls a prompt's template and structured-output schema from the LangSmith Hub (needs
    `LANGSMITH_API_KEY`, the `prompts` extra and network)."""
    try:
        from langsmith import Client
    except ImportError as error:
        raise PromptError("install the `prompts` extra: uv sync --extra prompts") from error
    return parse_manifest(Client().pull_prompt_commit(f"{name}:{commit}").manifest)


def parse_manifest(manifest: dict) -> tuple[str, dict | None]:
    """A Hub manifest (a serialized LangChain prompt): the template of its first message and the
    `StructuredPrompt` schema, if any."""
    try:
        kwargs = manifest["kwargs"]
        template = kwargs["messages"][0]["kwargs"]["prompt"]["kwargs"]["template"]
    except (KeyError, IndexError, TypeError) as error:
        raise PromptError(f"unexpected Hub manifest shape: {error!r}") from error
    return template, kwargs.get("schema_")


_lock: PromptLock | None = None


def default_lock() -> PromptLock:
    global _lock
    if _lock is None:
        _lock = load_lock()
    return _lock
