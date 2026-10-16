"""Shared contract: every adapter, driven by canned HTTP responses, behaves the same under
the router (fallback on quota, wait on RPM, single retry on a transient error)."""

import pytest

from legal_radar.adapters.http_providers import GeminiProvider, GroqProvider, LMStudioProvider
from legal_radar.adapters.router import Router
from legal_radar.adapters.router_config import DEFAULT_PRIORITY, build_router, load_config
from legal_radar.adapters.wide_events import WideEventLog
from legal_radar.domain.llm import AllProvidersFailedError


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
    assert router.daily_limits == {"gemini": 2000}


EMBEDDING_ADAPTERS = {
    "gemini": (
        lambda transport: GeminiProvider("m", "key", transport, "emb"),
        (200, {}, {"embeddings": [{"values": [1, 0]}, {"values": [0, 1]}]}),
    ),
    "lmstudio": (
        lambda transport: LMStudioProvider("m", transport=transport, embedding_model="emb"),
        (
            200,
            {},
            {
                "data": [
                    {"index": 1, "embedding": [0, 1]},
                    {"index": 0, "embedding": [1, 0]},
                ],
                "usage": {"prompt_tokens": 4},
            },
        ),
    ),
}


@pytest.mark.parametrize("name", sorted(EMBEDDING_ADAPTERS))
def test_embed_maps_vectors_in_input_order(name, tmp_path):
    factory, response = EMBEDDING_ADAPTERS[name]
    transport = ScriptedTransport(response)
    router, _ = router_for(tmp_path, factory(transport))

    result = router.embed(["a", "b"])

    assert result.vectors == [[1, 0], [0, 1]]
    assert (result.provider, result.model) == (name, "emb")
    assert "emb" in str(transport.requests[0])


def test_groq_has_no_embeddings_so_the_next_provider_serves_them(tmp_path):
    groq_transport = ScriptedTransport()
    groq = GroqProvider("m", "key", groq_transport)
    factory, response = EMBEDDING_ADAPTERS["lmstudio"]
    router, _ = router_for(tmp_path, groq, factory(ScriptedTransport(response)))

    result = router.embed(["a", "b"])

    assert (result.provider, result.fallback_from) == ("lmstudio", "groq")
    assert groq_transport.requests == []


def test_embed_with_a_wrong_vector_count_is_a_transient_failure(tmp_path):
    transport = ScriptedTransport(
        (200, {}, {"embeddings": [{"values": [1]}]}), (200, {}, {"embeddings": [{"values": [1]}]})
    )
    router, _ = router_for(tmp_path, GeminiProvider("m", "key", transport, "emb"))

    with pytest.raises(AllProvidersFailedError):
        router.embed(["a", "b"])


def test_build_router_wires_default_embedding_models():
    router = build_router({}, env={})

    assert {p.name: p.embedding_model for p in router.providers} == {
        "groq": "",
        "gemini": "gemini-embedding-001",
        "lmstudio": "text-embedding-bge-m3",
    }


SCHEMA = {"type": "object", "properties": {"a": {"type": "string"}}}


def test_strict_schemas_close_every_nested_object():
    from legal_radar.adapters.http_providers import _closed

    nested = {
        "type": "object",
        "properties": {"items": {"type": "array", "items": {"type": "object", "properties": {}}}},
    }

    closed = _closed(nested)

    assert closed["additionalProperties"] is False
    assert closed["properties"]["items"]["items"]["additionalProperties"] is False
    assert "additionalProperties" not in nested  # the caller's schema is not mutated


def test_openai_compatible_adapters_request_a_strict_json_schema():
    from legal_radar.domain.llm import CompletionParams

    for make in (ADAPTERS["groq"][0], ADAPTERS["lmstudio"][0]):
        transport = ScriptedTransport(openai_ok())
        make(transport).complete("p", CompletionParams(response_schema=SCHEMA))
        body = transport.requests[0][2]
        assert body["response_format"] == {
            "type": "json_schema",
            "json_schema": {
                "name": "response",
                "strict": True,
                "schema": {**SCHEMA, "additionalProperties": False},
            },
        }


def test_gemini_requests_json_output_with_the_schema():
    from legal_radar.domain.llm import CompletionParams

    transport = ScriptedTransport(gemini_ok())
    ADAPTERS["gemini"][0](transport).complete("p", CompletionParams(response_schema=SCHEMA))

    config = transport.requests[0][2]["generationConfig"]
    assert config["responseMimeType"] == "application/json"
    assert config["responseJsonSchema"] == SCHEMA


def test_no_schema_means_no_structured_output_fields():
    for make in (ADAPTERS["groq"][0], ADAPTERS["gemini"][0]):
        transport = ScriptedTransport(openai_ok() if make is ADAPTERS["groq"][0] else gemini_ok())
        make(transport).complete("p")
        body = transport.requests[0][2]
        assert "response_format" not in body and "generationConfig" not in body


def test_strict_schemas_drop_unique_items_which_groq_does_not_support():
    from legal_radar.adapters.http_providers import _closed

    schema = {"type": "array", "items": {"type": "string"}, "uniqueItems": True}

    assert "uniqueItems" not in _closed(schema)
    assert schema["uniqueItems"] is True  # the caller's schema keeps it for local validation
