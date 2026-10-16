import io
import urllib.error

from legal_radar.adapters import http_providers


def test_the_request_carries_its_own_user_agent(monkeypatch):
    # Cloudflare (Groq) answers 403 / error 1010 to the default `Python-urllib` agent.
    seen = []

    class Reply(io.BytesIO):
        status = 200
        headers = ()

    def urlopen(request, timeout):
        seen.append(request)
        return Reply(b"{}")

    monkeypatch.setattr(http_providers.urllib.request, "urlopen", urlopen)

    http_providers.urllib_transport("https://example.test", {}, {})

    assert seen[0].get_header("User-agent").startswith("legal-radar/")


def test_a_non_json_error_body_is_kept_so_the_reason_is_not_lost(monkeypatch):
    def urlopen(request, timeout):
        raise urllib.error.HTTPError(
            request.full_url, 403, "Forbidden", {}, io.BytesIO(b"error code: 1010\n")
        )

    monkeypatch.setattr(http_providers.urllib.request, "urlopen", urlopen)

    status, _, payload = http_providers.urllib_transport("https://example.test", {}, {})

    assert status == 403
    assert "error code: 1010" in str(payload)
