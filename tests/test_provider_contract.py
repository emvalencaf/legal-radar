"""Shared contract: every adapter, driven by canned HTTP responses, behaves the same under
the router (fallback on quota, wait on RPM, single retry on a transient error)."""

import pytest

from legal_radar.adapters.http_providers import GeminiProvider, GroqProvider, LMStudioProvider
from legal_radar.router import Router
from legal_radar.router_config import DEFAULT_PRIORITY, build_router, load_config
from legal_radar.wide_events import WideEventLog


def openai_ok(payload=None):
    return (
        200,
        {},
        {
            "choices": [{"message": {"content": "ok"}}],
            "usage": {
                "prompt_tokens": 7,
                "completion_tokens": 3,
                "completion_tokens_details": {"reasoning_tokens": 1},
            },
        },
    )


def gemini_ok():
    return (
        200,
        {},
        {
            "candidates": [{"content": {"parts": [{"text": "ok"}]}}],
            "usageMetadata": {
                "promptTokenCount": 7,
                "candidatesTokenCount": 3,
                "thoughtsTokenCount": 1,
            },
        },
    )


ADAPTERS = {
    "groq": (lambda transport: GroqProvider("m", "key", transport), openai_ok),
    "gemini": (lambda transport: GeminiProvider("m", "key", transport), gemini_ok),
    "lmstudio": (lambda transport: LMStudioProvider("m", transport=transport), openai_ok),
}


class ScriptedTransport:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, url, headers, body):
        self.requests.append((url, headers, body))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


@pytest.fixture(params=sorted(ADAPTERS))
def adapter(request):
    factory, ok = ADAPTERS[request.param]
    return factory, ok


def router_for(tmp_path, *providers):
    sleeps = []
    router = Router(list(providers), WideEventLog(tmp_path / "log.jsonl"), sleep=sleeps.append)
    return router, sleeps


def test_success_maps_text_and_token_breakdown(adapter, tmp_path):
    factory, ok = adapter
    router, _ = router_for(tmp_path, factory(ScriptedTransport(ok())))

    result = router.complete("hi")

    assert (result.text, result.tokens_in, result.tokens_out, result.tokens_thinking) == (
        "ok",
        7,
        3,
        1,
    )


def test_quota_exhaustion_falls_back(adapter, tmp_path):
    factory, _ = adapter
    quota = (429, {}, {"error": {"message": "Rate limit reached on requests per day (RPD)"}})
    backup = LMStudioProvider("b", transport=ScriptedTransport(openai_ok()))
    router, sleeps = router_for(tmp_path, factory(ScriptedTransport(quota)), backup)

    result = router.complete("hi")

    assert result.provider == "lmstudio"
    assert sleeps == []


def test_rpm_throttling_waits_then_retries_same_provider(adapter, tmp_path):
    factory, ok = adapter
    throttled = (429, {"Retry-After": "4"}, {"error": {"message": "requests per minute"}})
    transport = ScriptedTransport(throttled, ok())
    router, sleeps = router_for(tmp_path, factory(transport))

    assert router.complete("hi").text == "ok"
    assert sleeps == [4.0]
    assert len(transport.requests) == 2


def test_transient_error_is_retried_once(adapter, tmp_path):
    factory, _ = adapter
    transport = ScriptedTransport((503, {}, {}), TimeoutError("slow"))
    backup = LMStudioProvider("b", transport=ScriptedTransport(openai_ok()))
    router, _ = router_for(tmp_path, factory(transport), backup)

    result = router.complete("hi")

    assert len(transport.requests) == 2
    assert result.provider == "lmstudio"
    assert result.fallback_from == factory(None).name


def test_transient_error_then_success_counts_one_retry(adapter, tmp_path):
    factory, ok = adapter
    router, _ = router_for(tmp_path, factory(ScriptedTransport((500, {}, {}), ok())))

    assert router.complete("hi").retry_count == 1


def test_default_priority_and_models_when_config_omitted():
    router = build_router({}, env={"GROQ_API_KEY": "k"})

    assert [p.name for p in router.providers] == DEFAULT_PRIORITY
    models = {p.name: p.model for p in router.providers}
    assert models["groq"] == "openai/gpt-oss-120b"
    assert "flash-lite" in models["gemini"]


def test_router_yaml_in_repo_sets_priority_and_models():
    config = load_config("router.yaml")
    config["providers"] = ["gemini", "groq"]
    config["models"] = {"groq": "openai/gpt-oss-20b"}

    router = build_router(config, env={})

    assert [(p.name, p.model) for p in router.providers] == [
        ("gemini", "gemini-3.1-flash-lite"),
        ("groq", "openai/gpt-oss-20b"),
    ]
    assert router.daily_limits == {"gemini": 500}
