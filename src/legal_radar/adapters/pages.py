"""PageSource adapter: a real browser, since LexML's bot-wall and Planalto's redirect agent reject
plain HTTP clients."""


class BrowserPageSource:
    """Headless Chromium via Playwright (optional `browser` extra); waits out the JS challenge."""

    def __init__(self, challenge_title: str = "Verificação de segurança", timeout_ms: int = 30_000):
        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch()
        self._page = self._browser.new_page()
        self._challenge_title = challenge_title
        self._timeout_ms = timeout_ms

    def get(self, url: str) -> str:
        self._page.goto(url, timeout=self._timeout_ms)
        self._page.wait_for_function(
            "t => !document.title.includes(t)", arg=self._challenge_title, timeout=self._timeout_ms
        )
        return self._page.content()

    def close(self) -> None:
        self._browser.close()
        self._playwright.stop()
