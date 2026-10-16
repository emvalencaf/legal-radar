import json
from datetime import UTC, datetime

import pytest

from legal_radar.adapters.fake_provider import FakeProvider
from legal_radar.domain.complexity import COMPLEX, DEFAULT_MAX_CONTEXT_TOKENS, SIMPLE, classify
from legal_radar.domain.llm import CompletionParams, QuotaExhaustedError
from legal_radar.domain.model import Context, Dispositivo, Hop, Jurisprudencia
from legal_radar.router import Router
from legal_radar.router_config import build_router, tier_max_context_tokens
from legal_radar.wide_events import WideEventLog

LEI_A = "urn:lex:br:federal:lei:2002-01-10;10406"
LEI_B = "urn:lex:br:federal:lei:1990-09-11;8078"


def disp(lei: str, path: str, text: str = "texto") -> Dispositivo:
    return Dispositivo(f"{lei}#{path}", lei, path, text)


def decision() -> Jurisprudencia:
    return Jurisprudencia("STJ:1", "STJ", "1", "ementa", "decisao", "tese")


CASES = [
    ("one lei, no decision", Context([disp(LEI_A, "art1")], [], {}), 1000, SIMPLE),
    ("empty context", Context([], [], {}), 1000, SIMPLE),
    (
        "two leis",
        Context([disp(LEI_A, "art1"), disp(LEI_B, "art2")], [], {}),
        1000,
        COMPLEX,
    ),
    ("any jurisprudencia", Context([disp(LEI_A, "art1")], [decision()], {}), 1000, COMPLEX),
    (
        "a revocation of a reached dispositivo",
        Context([disp(LEI_A, "art1")], [], {}, [Hop("REVOKES", LEI_B, f"{LEI_A}#art1", "HIGH")]),
        1000,
        COMPLEX,
    ),
    (
        "a LOW-confidence hop",
        Context(
            [disp(LEI_A, "art1")],
            [],
            {"x": [Hop("REFERENCES", f"{LEI_A}#art1", f"{LEI_A}#art2", "LOW")]},
        ),
        1000,
        COMPLEX,
    ),
    (
        "a HIGH-confidence reference",
        Context(
            [disp(LEI_A, "art1")],
            [],
            {"x": [Hop("REFERENCES", f"{LEI_A}#art1", f"{LEI_A}#art2", "HIGH")]},
        ),
        1000,
        SIMPLE,
    ),
    ("over the token threshold", Context([disp(LEI_A, "art1", "x" * 4001)], [], {}), 1000, COMPLEX),
    ("at the token threshold", Context([disp(LEI_A, "art1", "x" * 4000)], [], {}), 1000, SIMPLE),
]


@pytest.mark.parametrize(("name", "context", "max_tokens", "expected"), CASES)
def test_classify(name, context, max_tokens, expected):
    assert classify(context, max_tokens) == expected, name


NOW = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)


def make_router(tmp_path, simple, complex_=None):
    log = WideEventLog(tmp_path / "calls.jsonl")
    router = Router(
        simple, log, sleep=lambda _: None, clock=lambda: NOW, complex_providers=complex_
    )
    return router, log


def events(log):
    return [json.loads(line) for line in log.path.read_text().splitlines()]


def test_tiers_disabled_ignore_the_complexity(tmp_path):
    simple = FakeProvider("groq")
    router, log = make_router(tmp_path, [simple])

    result = router.complete("x", CompletionParams(complexity=COMPLEX))

    assert result.provider == "groq"
    assert events(log)[0]["complexity"] is None


def test_a_complex_call_uses_the_complex_list(tmp_path):
    router, log = make_router(tmp_path, [FakeProvider("groq")], [FakeProvider("gemini")])

    result = router.complete("x", CompletionParams(complexity=COMPLEX))

    assert result.provider == "gemini"
    assert events(log)[0]["complexity"] == COMPLEX


def test_a_simple_call_uses_the_simple_list(tmp_path):
    router, _ = make_router(tmp_path, [FakeProvider("groq")], [FakeProvider("gemini")])

    assert router.complete("x", CompletionParams(complexity=SIMPLE)).provider == "groq"
    assert router.complete("x").provider == "groq"


def test_an_exhausted_complex_list_downgrades_to_simple_and_logs_it(tmp_path):
    complex_ = FakeProvider("gemini", script=[QuotaExhaustedError()])
    router, log = make_router(tmp_path, [FakeProvider("groq")], [complex_])

    result = router.complete("x", CompletionParams(complexity=COMPLEX))

    assert result.provider == "groq"
    (event,) = events(log)
    assert (event["complexity"], event["downgraded_from"]) == (SIMPLE, COMPLEX)
    assert event["outcome"] == "success"


def test_a_complex_call_that_succeeds_is_not_marked_downgraded(tmp_path):
    router, log = make_router(tmp_path, [FakeProvider("groq")], [FakeProvider("gemini")])

    router.complete("x", CompletionParams(complexity=COMPLEX))

    assert events(log)[0]["downgraded_from"] is None


def test_config_leaves_tiers_off_by_default():
    router = build_router({"providers": ["groq"]}, env={})
    assert router.complex_providers == []

    enabled = {"providers": ["groq"], "tiers": {"complex": ["gemini", "groq"]}}
    assert build_router(enabled, env={}).complex_providers == []  # listed, but not enabled

    enabled["tiers"]["enabled"] = True
    assert [p.name for p in build_router(enabled, env={}).complex_providers] == ["gemini", "groq"]


def test_tier_max_context_tokens_defaults_and_rejects_bad_values():
    assert tier_max_context_tokens({}) == DEFAULT_MAX_CONTEXT_TOKENS
    assert tier_max_context_tokens({"tiers": {"max_context_tokens": 100}}) == 100
    for bad in (0, -1, "10", True):
        with pytest.raises(ValueError, match="max_context_tokens"):
            tier_max_context_tokens({"tiers": {"max_context_tokens": bad}})
