"""Idempotency key of an LLM-processed chunk (ADR-0003, ADR-0004).

A chunk goes back to `pending` only when one ingredient of its key changes: its text, the
extractor, the vocabulary of its assunto or the prompt that enriches it (`dispositivo-enrichment`).
Rule-derived edges do not use it, so they are kept.
"""

from legal_radar.application.concepts import Vocabulary
from legal_radar.domain.llm import content_hash
from legal_radar.domain.prompts import PromptLock
from legal_radar.domain.relations import EXTRACTOR_VERSION

ENRICHMENT_PROMPT = "dispositivo-enrichment"
DECISION_PROMPT = "jurisprudencia-enrichment"


def enrichment_key(
    text: str,
    vocabulary: Vocabulary,
    lock: PromptLock,
    extractor_version: str = EXTRACTOR_VERSION,
    prompt: str = ENRICHMENT_PROMPT,
) -> str:
    return content_hash(
        {
            "text": content_hash(text),
            "vocabulary": vocabulary.hash,
            "prompt": lock.prompt_hash(prompt),
            "extractor": extractor_version,
        }
    )
