"""Deterministic provider for tests and the offline skeleton run."""

from legal_radar.llm import Completion, CompletionParams


class FakeProvider:
    """Answers `abuso_da_personalidade` for texts mentioning abuso, else `decisao_judicial`.

    `script` lets a test queue exceptions or `Completion`s to be returned in order before the
    deterministic answer; every prompt received is kept in `calls`.
    """

    def __init__(self, name: str = "fake", model: str = "fake-model", script=()):
        self.name = name
        self.model = model
        self.script = list(script)
        self.calls: list[str] = []

    def complete(self, prompt: str, params: CompletionParams | None = None) -> Completion:
        self.calls.append(prompt)
        if self.script:
            step = self.script.pop(0)
            if isinstance(step, Exception):
                raise step
            return step
        text = "abuso_da_personalidade" if "abuso" in prompt else "decisao_judicial"
        return Completion(
            text, tokens_in=len(prompt.split()), tokens_out=1, provider=self.name, model=self.model
        )
