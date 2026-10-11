"""PageSource adapter: a real browser, since LexML's bot-wall and Planalto's redirect agent reject
plain HTTP clients."""

import logging
import time

logger = logging.getLogger(__name__)

# LexML shows a titled interstitial; Planalto's WAF serves a script-only page (/TSPD/) that
# redirects once its JS has run. Either way the real page has neither marker.
_CHALLENGE_DONE = """() => !document.title.includes('Verificação de segurança')
    && !document.documentElement.innerHTML.includes('/TSPD/')"""


class BrowserPageSource:
    """Headless Chromium via Playwright (optional `browser` extra); waits out the JS challenge."""

    def __init__(self, timeout_ms: int = 30_000, retries: int = 3, backoff_s: float = 2.0):
        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(
            args=["--disable-blink-features=AutomationControlled"]
        )
        # Planalto's WAF never releases a client that announces itself as HeadlessChrome.
        probe = self._browser.new_page()
        user_agent = probe.evaluate("navigator.userAgent").replace("HeadlessChrome", "Chrome")
        probe.close()
        self._page = self._browser.new_context(user_agent=user_agent).new_page()
        self._timeout_ms = timeout_ms
        self._retries = retries
        self._backoff_s = backoff_s

    def get(self, url: str) -> str:
        """Fetch `url`, retrying up to `retries` times (backing off) on browser errors."""
        from playwright.sync_api import Error

        for attempt in range(self._retries + 1):
            try:
                return self._get_once(url)
            except Error as error:
                if attempt == self._retries:
                    logger.error("giving up on %s after %d attempts: %s", url, attempt + 1, error)
                    raise
                delay = self._backoff_s * 2**attempt
                logger.warning(
                    "attempt %d/%d for %s failed: %s; retrying in %.1fs",
                    attempt + 1,
                    self._retries + 1,
                    url,
                    error,
                    delay,
                )
                time.sleep(delay)
        raise AssertionError("unreachable")

    def _get_once(self, url: str) -> str:
        self._page.goto(url, timeout=self._timeout_ms)
        self._page.wait_for_function(_CHALLENGE_DONE, timeout=self._timeout_ms)
        return self._page.content()

    def close(self) -> None:
        self._browser.close()
        self._playwright.stop()
