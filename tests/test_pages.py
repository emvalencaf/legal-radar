import logging

import pytest

from legal_radar.adapters import pages
from legal_radar.adapters.pages import BrowserPageSource

Error = pytest.importorskip("playwright.sync_api").Error


def source(outcomes: list, retries: int = 3) -> BrowserPageSource:
    """A BrowserPageSource whose browser fetches replay `outcomes` (exceptions are raised)."""
    page_source = object.__new__(BrowserPageSource)
    page_source._retries, page_source._backoff_s = retries, 0.0
    calls = iter(outcomes)

    def get_once(url: str) -> str:
        outcome = next(calls)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    page_source._get_once = get_once
    return page_source


def test_retries_failed_fetches_and_logs_each_error(caplog, monkeypatch):
    monkeypatch.setattr(pages.time, "sleep", lambda _: None)
    page_source = source([Error("boom 1"), Error("boom 2"), "<html>ok</html>"])

    with caplog.at_level(logging.WARNING, logger=pages.logger.name):
        assert page_source.get("http://x") == "<html>ok</html>"

    assert [r.levelname for r in caplog.records] == ["WARNING", "WARNING"]
    assert "boom 1" in caplog.text
    assert "boom 2" in caplog.text


def test_gives_up_after_three_retries_and_logs_the_failure(caplog, monkeypatch):
    monkeypatch.setattr(pages.time, "sleep", lambda _: None)
    page_source = source([Error(f"boom {n}") for n in range(4)])

    with caplog.at_level(logging.WARNING, logger=pages.logger.name), pytest.raises(Error):
        page_source.get("http://x")

    assert [r.levelname for r in caplog.records] == ["WARNING"] * 3 + ["ERROR"]
    assert "after 4 attempts" in caplog.records[-1].message
