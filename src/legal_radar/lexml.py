"""LexML as identity layer: keyword search to a lei's URN, and the URN page's full-text links."""

import re
from dataclasses import dataclass
from urllib.parse import quote_plus, urlparse

from bs4 import BeautifulSoup

from legal_radar.ports import PageSource

SEARCH_URL = "https://www.lexml.gov.br/busca/search?keyword={keyword}"
URN_URL = "https://www.lexml.gov.br/urn/{urn}"
_FEDERAL_LEI = re.compile(r"^urn:lex:br:federal:lei:(\d{4})-\d{2}-\d{2};(\d+)$")


class LexmlError(Exception):
    pass


@dataclass(frozen=True)
class UrnPage:
    urn: str
    title: str
    planalto_url: str | None
    destinations: list[str]  # hosts the "Texto Atualizado" links point to, for the report


def search_urn(pages: PageSource, keyword: str, numero: str, ano: int) -> str:
    """Resolve the federal lei `numero`/`ano` to its URN from the keyword search results."""
    html = pages.get(SEARCH_URL.format(keyword=quote_plus(keyword)))
    for a in BeautifulSoup(html, "html.parser").find_all("a", href=True):
        href = str(a["href"])
        if not href.startswith("/urn/"):
            continue
        urn = href.removeprefix("/urn/")
        if (m := _FEDERAL_LEI.match(urn)) and m[2] == numero and int(m[1]) == ano:
            return urn
    raise LexmlError(f"no URN for lei {numero}/{ano} in the results of {keyword!r}")


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
