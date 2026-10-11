"""Deterministic provider for tests and the offline skeleton run."""


class FakeProvider:
    """Answers `abuso_da_personalidade` for texts mentioning abuso, else `decisao_judicial`."""

    def complete(self, prompt: str) -> str:
        return "abuso_da_personalidade" if "abuso" in prompt else "decisao_judicial"
