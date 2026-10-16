"""STF jurisprudência: the search page's own JSON API (an Elasticsearch proxy), called in-page."""

import json

from legal_radar.domain.model import Jurisprudencia
from legal_radar.ports import JsonApi

API_URL = "https://jurisprudencia.stf.jus.br/api/search/search"
_SOURCE_FIELDS = [
    "titulo",
    "ementa_texto",
    "documental_tese_texto",
    "acordao_ata",
]


class StfFetcher:
    def __init__(self, api: JsonApi):
        self._api = api

    def search(self, query: str, limit: int) -> list[Jurisprudencia]:
        body = {
            "query": {
                "bool": {
                    "must": [
                        {"term": {"base": "acordaos"}},
                        {"query_string": {"query": query, "default_operator": "AND"}},
                    ]
                }
            },
            "size": limit,
            "_source": _SOURCE_FIELDS,
        }
        hits = json.loads(self._api.post_json(API_URL, body))["result"]["hits"]["hits"]
        return [j for hit in hits if (j := _parse(hit)) is not None]


def _parse(hit: dict) -> Jurisprudencia | None:
    source = hit["_source"]
    ementa = _clean(source.get("ementa_texto"), strip_prefix="EMENTA")
    decisao = _clean(source.get("acordao_ata"))
    if not ementa or not decisao:
        return None
    return Jurisprudencia(
        id=f"STF:{hit['_id']}",
        court="STF",
        number=source["titulo"],
        ementa=ementa,
        decisao=decisao,
        tese=_clean(source.get("documental_tese_texto")),
    )


def _clean(text: str | None, strip_prefix: str = "") -> str | None:
    text = (text or "").strip().removeprefix(strip_prefix)
    return "\n".join(line.strip() for line in text.splitlines() if line.strip()) or None
