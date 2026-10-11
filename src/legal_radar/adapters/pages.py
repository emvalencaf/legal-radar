"""PageSource adapter: a real browser, since LexML's bot-wall and Planalto's redirect agent reject
plain HTTP clients."""

import logging
import time
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# LexML shows a titled interstitial; Planalto's WAF serves a script-only page (/TSPD/) that
# redirects once its JS has run. Either way the real page has neither marker.
_CHALLENGE_DONE = """() => !document.title.includes('Verificação de segurança')
    && !document.title.includes('Just a moment')
    && !document.documentElement.innerHTML.includes('/TSPD/')"""

_POST_JSON = """async ([url, body]) => {
    const r = await fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json'},
                                body: JSON.stringify(body)});
    return {status: r.status, text: await r.text()};
}"""
# The search form opens its results in a new tab; keep them in this one.
_SUBMIT_FORM = """([name, fields]) => {
    const form = document.forms[name];
    form.target = '_self';
    for (const [key, value] of Object.entries(fields)) form.elements[key].value = value;
    form.submit();
}"""


class BrowserPageSource:
    """Chromium via Playwright (optional `browser` extra); waits out the JS challenge. STJ's
    Cloudflare Turnstile rejects bundled headless Chromium; use `channel="chrome"` for it."""

    def __init__(
        self,
        timeout_ms: int = 30_000,
        retries: int = 3,
        backoff_s: float = 2.0,
        headless: bool = True,
        channel: str | None = None,
    ):
        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(
            headless=headless,
            channel=channel,
            args=["--disable-blink-features=AutomationControlled"],
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

    def post_json(self, url: str, body: dict) -> str:
        """POST `body` to `url` from inside a page of the same site, with the page's cookies."""
        parts = urlparse(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if not self._page.url.startswith(origin):
            self.get(origin + "/")
        for _ in range(self._retries + 1):
            reply = self._page.evaluate(_POST_JSON, [url, body])
            if reply["status"] == 200:
                return reply["text"]
            # The site's WAF answers 202 until its challenge script has run in the page.
            self._page.wait_for_timeout(2_000)
        raise RuntimeError(f"POST {url} answered {reply['status']}")

    def submit_form(self, url: str, form: str, fields: dict[str, str]) -> str:
        """Open `url`, fill the named form's fields and submit it in the same tab."""
        self.get(url)
        self._page.wait_for_selector(f"form[name='{form}']", state="attached")
        with self._page.expect_navigation(timeout=self._timeout_ms):
            self._page.evaluate(_SUBMIT_FORM, [form, fields])
        self._page.wait_for_load_state("networkidle", timeout=self._timeout_ms)
        return self._page.content()

    def close(self) -> None:
        self._browser.close()
        self._playwright.stop()
