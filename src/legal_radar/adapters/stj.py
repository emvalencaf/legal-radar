"""STJ jurisprudência: the SCON search is session-bound, so the form is submitted and the
server-rendered result page parsed."""

import re

from bs4 import BeautifulSoup, Tag

from legal_radar.application.ports import FormPages
from legal_radar.domain.model import CaseLaw

SEARCH_URL = "https://scon.stj.jus.br/SCON/"
FORM = "frmPesquisaJurHeader"
_REGISTRO = re.compile(r"num_registro=(\d+)")


class StjFetcher:
    def __init__(self, pages: FormPages):
        self._pages = pages

    def search(self, query: str, limit: int) -> list[CaseLaw]:
        html = self._pages.submit_form(SEARCH_URL, FORM, {"livre": query, "b": "ACOR"})
        found: dict[str, CaseLaw] = {}
        for doc in BeautifulSoup(html, "html.parser").select(".documento"):
            # Afetação (PAF…) records repeat a decision's registro; the first one wins.
            if (j := _parse(doc)) and j.id not in found:
                found[j.id] = j
        return list(found.values())[:limit]


def _parse(doc: Tag) -> CaseLaw | None:
    registro = _REGISTRO.search(str(doc))
    fields = {
        _label(label): text.get_text("\n", strip=True)
        for block in doc.select(".paragrafoBRS")
        if (label := block.select_one(".docTitulo")) and (text := block.select_one(".docTexto"))
    }
    headnote, ruling = fields.get("ementa"), fields.get("acórdão")
    if not (registro and headnote and ruling):
        return None
    return CaseLaw(
        id=f"STJ:{registro[1]}",
        court="STJ",
        number=fields.get("processo", "").split("\n")[0],
        headnote=headnote,
        ruling=ruling,
        thesis=fields.get("tese jurídica"),
    )


def _label(tag: Tag) -> str:
    """The field name only: the real page appends a tooltip with the field's description."""
    return " ".join(next(tag.stripped_strings, "").split()).casefold()
