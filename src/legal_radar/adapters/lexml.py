"""LexML as identity layer: keyword search to a lei's URN, and the URN page's full-text links."""

import logging
import re
import time
from collections.abc import Callable
from urllib.parse import quote_plus, urlparse

from bs4 import BeautifulSoup

from legal_radar.application.ports import PageSource
from legal_radar.domain.anchors import AnchorStatute
from legal_radar.domain.urn import FEDERAL_STATUTE, LexmlError, UrnPage

SEARCH_URL = "https://www.lexml.gov.br/busca/search?keyword={keyword}"
URN_URL = "https://www.lexml.gov.br/urn/{urn}"
logger = logging.getLogger(__name__)


def search_urn(
    pages: PageSource, keyword: str, numero: str, ano: int, retries: int = 3, backoff_s: float = 2.0
) -> str:
    """Resolve the federal lei `numero`/`ano` to its URN from the keyword search results.

    LexML's search is flaky (a good query sometimes comes back without the lei), so a miss is
    retried `retries` times with exponential backoff, logging each one.
    """
    url = SEARCH_URL.format(keyword=quote_plus(keyword))
    for attempt in range(retries + 1):
        if urn := _find_urn(pages.get(url), numero, ano):
            return urn
        message = f"no URN for lei {numero}/{ano} in the results of {keyword!r}"
        if attempt == retries:
            logger.error("giving up after %d attempts: %s", attempt + 1, message)
            raise LexmlError(message)
        delay = backoff_s * 2**attempt
        logger.warning(
            "attempt %d/%d: %s; retrying in %.1fs", attempt + 1, retries + 1, message, delay
        )
        time.sleep(delay)
    raise AssertionError("unreachable")


def _find_urn(html: str, numero: str, ano: int) -> str | None:
    for a in BeautifulSoup(html, "html.parser").find_all("a", href=True):
        href = str(a["href"])
        if not href.startswith("/urn/"):
            continue
        urn = href.removeprefix("/urn/")
        if (m := FEDERAL_STATUTE.match(urn)) and m[2] == numero and int(m[1]) == ano:
            return urn
    return None


def resolve_urn(pages: PageSource, urn: str) -> UrnPage:
    soup = BeautifulSoup(pages.get(URN_URL.format(urn=urn)), "html.parser")
    title = soup.title.get_text(strip=True) if soup.title else urn
    parts = [p.strip() for p in title.split("::")[0].split(" - ")]
    name = re.sub(r"\s*\(\d{4}\)$", "", parts[1]) if len(parts) > 1 else ""
    title = f"{parts[0]} - {name}" if name else parts[0]

    marker = soup.find("strong", string=lambda s: bool(s) and s.strip() == "Texto Atualizado")
    item = marker.find_parent(class_="list-group-item") if marker else None
    links = [str(a["href"]) for a in item.find_all("a", href=True)] if item else []
    links = [u for u in links if "linker.lexml.gov.br" not in u]
    hosts = [urlparse(u).hostname or u for u in links]
    planalto = next(
        (u for u, h in zip(links, hosts, strict=True) if h.endswith("planalto.gov.br")), None
    )
    return UrnPage(urn, title, planalto, hosts)


class LexmlLocator:
    """`LeiLocator` over LexML: keyword search to the URN, then the URN page."""

    def __init__(self, pages: PageSource):
        self.pages = pages

    def locate(self, anchor: AnchorStatute) -> UrnPage:
        urn = search_urn(self.pages, anchor.keyword, anchor.numero, anchor.ano)
        return resolve_urn(self.pages, urn)


def lexml_resolver(pages: PageSource) -> Callable[[str, str, int], str | None]:
    """Fall back to a LexML keyword search for federal leis missing from the curated table."""

    def resolve(kind: str, numero: str, ano: int) -> str | None:
        if kind != "lei":
            return None
        try:
            return search_urn(pages, f"lei {numero} {ano}", numero, ano, retries=0)
        except LexmlError:
            return None

    return resolve
