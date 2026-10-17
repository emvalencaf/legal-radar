"""Prompts pinned to LangSmith Hub commits, held as an offline snapshot (the lock).

`PromptLock` is the snapshot of each pinned prompt's template; reading and refreshing it live in
`legal_radar.adapters.prompt_lock`.
"""

import json
from dataclasses import dataclass

from legal_radar.domain.llm import content_hash


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
