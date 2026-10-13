"""Idempotency key of an LLM-processed chunk (ADR-0003, ADR-0004).

A chunk goes back to `pending` only when one ingredient of its key changes: its text, the
extractor, the vocabulary of its assunto or the prompt that enriches it (`dispositivo-enrichment`).
Rule-derived edges do not use it, so they are kept.
"""

from legal_radar.concepts import Vocabulary
from legal_radar.llm import content_hash
from legal_radar.prompts import PromptLock, default_lock

ENRICHMENT_PROMPT = "dispositivo-enrichment"
EXTRACTOR_VERSION = "1"  # bump when the extraction code changes in a way prompts do not capture


def enrichment_key(
    text: str,
    vocabulary: Vocabulary,
    lock: PromptLock | None = None,
    extractor_version: str = EXTRACTOR_VERSION,
) -> str:
    lock = lock or default_lock()
    return content_hash(
        {
            "text": content_hash(text),
            "vocabulary": vocabulary.hash,
            "prompt": lock.prompt_hash(ENRICHMENT_PROMPT),
            "extractor": extractor_version,
        }
    )
