"""Rule-based complexity of a retrieved context: decides which tier of providers answers it."""

from legal_radar.domain.model import Context

SIMPLE = "simple"
COMPLEX = "complex"
CHARS_PER_TOKEN = 4  # rough estimate; no tokenizer is shipped
DEFAULT_MAX_CONTEXT_TOKENS = 6000


def classify(context: Context, max_tokens: int = DEFAULT_MAX_CONTEXT_TOKENS) -> str:
    """`COMPLEX` when the context spans more than one lei, holds any jurisprudência, walks a
    REVOKES or LOW-confidence edge, or exceeds `max_tokens`; `SIMPLE` otherwise."""
    if len({d.statute_id for d in context.provisions}) > 1 or context.case_law:
        return COMPLEX
    walked = [h for path in context.paths.values() for h in path]
    if context.revocations or any(h.confidence == "LOW" for h in [*walked, *context.revocations]):
        return COMPLEX
    chars = sum(len(d.text) for d in context.provisions)
    return COMPLEX if chars / CHARS_PER_TOKEN > max_tokens else SIMPLE
