import json
from datetime import UTC, datetime

import pytest

from legal_radar.adapters.fake_provider import FakeProvider
from legal_radar.domain.llm import (
    AllProvidersFailedError,
    Completion,
    CompletionParams,
    ProviderError,
    QuotaExhaustedError,
    RateLimitedError,
    TransientError,
    content_hash,
)
from legal_radar.router import Router
from legal_radar.wide_events import WideEventLog

NOW = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)


def make_router(tmp_path, providers, daily_limits=None, log_full_content=False):
    sleeps: list[float] = []
    log = WideEventLog(tmp_path / "calls.jsonl", log_full_content=log_full_content)
    router = Router(
        providers, log, daily_limits=daily_limits or {}, sleep=sleeps.append, clock=lambda: NOW
    )
    return router, log, sleeps


def events(log):
    return [json.loads(line) for line in log.path.read_text().splitlines()]


def test_falls_back_to_next_provider_on_quota_exhaustion(tmp_path):
    first = FakeProvider("groq", script=[QuotaExhaustedError()])
    second = FakeProvider("gemini")
    router, log, _ = make_router(tmp_path, [first, second])

    result = router.complete("abuso")

    assert result.provider == "gemini"
    assert result.fallback_from == "groq"
    (event,) = events(log)
    assert (event["provider"], event["fallback_from"], event["outcome"]) == (
        "gemini",
        "groq",
        "success",
    )


def test_waits_on_rate_limit_then_retries_same_provider(tmp_path):
    first = FakeProvider("groq", script=[RateLimitedError(7)])
    second = FakeProvider("gemini")
    router, _, sleeps = make_router(tmp_path, [first, second])

    result = router.complete("x")

    assert result.provider == "groq"
    assert sleeps == [7]
    assert len(second.calls) == 0


def test_retries_transient_error_once_then_succeeds(tmp_path):
    first = FakeProvider("groq", script=[TransientError()])
    router, log, sleeps = make_router(tmp_path, [first])

    result = router.complete("x")

    assert result.retry_count == 1
    assert len(sleeps) == 1
    assert events(log)[0]["retry_count"] == 1


def test_falls_back_after_second_transient_error(tmp_path):
    first = FakeProvider("groq", script=[TransientError(), TransientError()])
    second = FakeProvider("gemini")
    router, _, _ = make_router(tmp_path, [first, second])

    result = router.complete("x")

    assert (result.provider, result.fallback_from) == ("gemini", "groq")
    assert len(first.calls) == 2


def test_gives_up_on_rate_limit_after_bounded_waits(tmp_path):
    first = FakeProvider("groq", script=[RateLimitedError(1)] * 10)
    second = FakeProvider("gemini")
    router, _, sleeps = make_router(tmp_path, [first, second])

    assert router.complete("x").provider == "gemini"
    assert 0 < len(sleeps) < 10


def test_raises_and_logs_failure_when_all_providers_fail(tmp_path):
    only = FakeProvider("groq", script=[QuotaExhaustedError()])
    router, log, _ = make_router(tmp_path, [only])

    with pytest.raises(AllProvidersFailedError):
        router.complete("x")

    (event,) = events(log)
    assert event["outcome"] == "failed"


def test_the_failure_names_why_each_provider_gave_up(tmp_path):
    first = FakeProvider("groq", script=[QuotaExhaustedError("groq daily quota exhausted")])
    second = FakeProvider("gemini", script=[ProviderError("gemini returned 400: bad schema")])
    router, _, _ = make_router(tmp_path, [first, second])

    with pytest.raises(AllProvidersFailedError) as caught:
        router.complete("x")

    assert "groq: groq daily quota exhausted" in str(caught.value)
    assert "gemini: gemini returned 400: bad schema" in str(caught.value)


def test_wide_event_has_hashes_and_breakdown_but_no_text_by_default(tmp_path):
    provider = FakeProvider(
        "groq", script=[Completion("out", 10, 5, 2, provider="groq", model="m")]
    )
    router, log, _ = make_router(tmp_path, [provider])
    tool = {"name": "graph_traverse", "parameters": {}}

    router.complete("hello", CompletionParams(pipeline_step="enrich", tools=(tool,)))

    (event,) = events(log)
    assert event["event"] == "llm_call"
    assert event["prompt_id"] == content_hash("hello")
    assert event["tool_schema_ids"] == [content_hash(tool)]
    assert event["pipeline_step"] == "enrich"
    assert (event["tokens_in"], event["tokens_out"], event["tokens_thinking"]) == (10, 5, 2)
    assert event["latency_ms"] >= 0
    assert event["prompt_text"] is None and event["output_text"] is None


def test_full_text_is_logged_when_opted_in(tmp_path):
    router, log, _ = make_router(tmp_path, [FakeProvider("groq")], log_full_content=True)

    router.complete("abuso")

    (event,) = events(log)
    assert event["prompt_text"] == "abuso"
    assert event["output_text"] == "abuso_da_personalidade"


def test_quota_is_computed_from_log_lines_and_skips_exhausted_provider(tmp_path):
    first = FakeProvider("gemini")
    second = FakeProvider("lmstudio")
    router, log, _ = make_router(tmp_path, [first, second], daily_limits={"gemini": 2})

    providers = [router.complete("x").provider for _ in range(3)]

    assert providers == ["gemini", "gemini", "lmstudio"]
    assert log.usage_today("gemini", "fake-model", NOW) == 2
    assert log.usage_today("lmstudio", "fake-model", NOW) == 1


def test_usage_ignores_other_days_and_failures(tmp_path):
    log = WideEventLog(tmp_path / "calls.jsonl")
    base = {"event": "llm_call", "provider": "gemini", "model": "m"}
    lines = [
        {**base, "timestamp": "2026-10-10T23:59:00Z", "outcome": "success"},
        {**base, "timestamp": "2026-10-11T01:00:00Z", "outcome": "success"},
        {**base, "timestamp": "2026-10-11T02:00:00Z", "outcome": "failed"},
    ]
    log.path.write_text("\n".join(json.dumps(line) for line in lines) + "\n")

    assert log.usage_today("gemini", "m", NOW) == 1


def test_rejected_request_falls_back_instead_of_aborting(tmp_path):
    from legal_radar.domain.llm import ProviderError

    router, _, _ = make_router(
        tmp_path, [FakeProvider("groq", script=[ProviderError("401")]), FakeProvider("gemini")]
    )

    assert router.complete("x").provider == "gemini"


def test_usage_skips_a_torn_log_line(tmp_path):
    log = WideEventLog(tmp_path / "calls.jsonl")
    log.path.write_text('{"event": "llm_ca\n')

    assert log.usage_today("gemini", "m", NOW) == 0


def test_embed_is_routed_logged_and_falls_back_past_a_provider_without_embeddings(tmp_path):
    from legal_radar.domain.llm import ProviderError

    first = FakeProvider("groq", script=[ProviderError("no embedding model")])
    second = FakeProvider("gemini", embedding_model="emb-1")
    router, log, _ = make_router(tmp_path, [first, second])

    result = router.embed(["abuso", "fraude"], CompletionParams(pipeline_step="resolve"))

    assert (result.provider, result.model, result.fallback_from) == ("gemini", "emb-1", "groq")
    assert len(result.vectors) == 2
    (event,) = events(log)
    assert event["event"] == "embed_call"
    assert (event["provider"], event["model"], event["outcome"]) == ("gemini", "emb-1", "success")
    assert (event["pipeline_step"], event["input_count"]) == ("resolve", 2)
    assert event["prompt_text"] is None
    assert event["prompt_id"] == content_hash(["abuso", "fraude"])


def test_embed_failure_is_logged_and_raised(tmp_path):
    router, log, _ = make_router(tmp_path, [FakeProvider(script=[QuotaExhaustedError()])])

    with pytest.raises(AllProvidersFailedError):
        router.embed(["x"])

    assert events(log)[0]["outcome"] == "failed"


def test_embed_daily_limit_counts_the_embedding_model(tmp_path):
    first = FakeProvider("gemini", embedding_model="emb-1")
    second = FakeProvider("lmstudio")
    router, _, _ = make_router(tmp_path, [first, second], daily_limits={"gemini": 1})

    assert router.embed(["a"]).provider == "gemini"
    assert router.embed(["b"]).provider == "lmstudio"


def test_event_carries_the_prompt_snapshot(tmp_path):
    log = WideEventLog(tmp_path / "calls.jsonl")
    router = Router([FakeProvider()], log)
    router.complete("hi", CompletionParams(prompt_snapshot="sha256:abc"))
    assert events(log)[0]["prompt_snapshot"] == "sha256:abc"


def test_providers_without_credentials_lists_the_keyless_ones():
    from legal_radar.router_config import providers_without_credentials

    config = {"providers": ["groq", "gemini", "lmstudio"]}

    assert providers_without_credentials(config, {"GROQ_API_KEY": "k"}) == ["gemini"]
    assert providers_without_credentials(config, {}) == ["groq", "gemini"]
