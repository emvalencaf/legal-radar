"""Deterministic provider for tests and the offline skeleton run."""

import hashlib
import json
import math
import re
import unicodedata

from legal_radar.domain.llm import Completion, CompletionParams, Embedding

EMBEDDING_DIMENSIONS = 256
STEM_LENGTH = 5
STOPWORDS = frozenset("a o as os de da do das dos e em um uma para por com que na no".split())


def _tokens(text: str) -> list[str]:
    plain = unicodedata.normalize("NFD", text.lower())
    plain = "".join(char for char in plain if not unicodedata.combining(char))
    return [word[:STEM_LENGTH] for word in re.findall(r"[a-z0-9]+", plain) if word not in STOPWORDS]


def fake_vector(text: str) -> list[float]:
    """Unit-length hashed bag of word stems: texts sharing words are similar, others are not."""
    vector = [0.0] * EMBEDDING_DIMENSIONS
    for token in _tokens(text):
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        vector[int.from_bytes(digest[:4], "big") % EMBEDDING_DIMENSIONS] += 1.0
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]


class FakeProvider:
    """Answers `abuso_da_personalidade` for texts mentioning abuso, else `decisao_judicial` (as
    `{"conceito_id": ...}` when the call asks for the tagging schema).

    `script` lets a test queue exceptions or `Completion`s to be returned in order before the
    deterministic answer; every prompt received is kept in `calls`.
    """

    def __init__(
        self,
        name: str = "fake",
        model: str = "fake-model",
        script=(),
        embedding_model: str = "fake-embedding",
    ):
        self.name = name
        self.model = model
        self.embedding_model = embedding_model
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
        properties = (params.response_schema or {}).get("properties", {}) if params else {}
        if "conceito_id" in properties:
            text = json.dumps({"conceito_id": text})
        elif "flags" in properties or "insufficient" in properties:  # the evaluation judges
            text = json.dumps({key: False for key in properties})
        elif "citations" in properties:  # cites every source it was allowed to
            sources = properties["citations"]["items"]["enum"]
            text = json.dumps(
                {"answer": f"Resposta com base em {len(sources)} fontes.", "citations": sources}
            )
        return Completion(
            text, tokens_in=len(prompt.split()), tokens_out=1, provider=self.name, model=self.model
        )

    def embed(self, texts: list[str], params: CompletionParams | None = None) -> Embedding:
        self.calls.extend(texts)
        if self.script:
            step = self.script.pop(0)
            if isinstance(step, Exception):
                raise step
            return step
        return Embedding(
            [fake_vector(text) for text in texts],
            tokens_in=sum(len(text.split()) for text in texts),
            provider=self.name,
            model=self.embedding_model,
        )
