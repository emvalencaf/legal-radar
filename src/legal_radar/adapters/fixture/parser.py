"""Parse the skeleton's plain-text lei fixture into Lei and Dispositivos."""

import re

from legal_radar.domain.model import Provision, Statute

_STATUTE = re.compile(r"^Lei (?P<number>\S+) (?P<title>.+)$")
_ARTICLE = re.compile(r"^Art\. (?P<n>\d+)º? (?P<text>.+)$")
_PARAGRAPH = re.compile(r"^§ (?P<n>\d+)º? (?P<text>.+)$")


def parse_statute(raw: str) -> tuple[Statute, list[Provision]]:
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    header = _STATUTE.match(lines[0])
    if header is None:
        raise ValueError(f"first line is not a lei header: {lines[0]!r}")
    statute = Statute(id=f"lei:{header['number']}", title=header["title"])

    provisions: list[Provision] = []
    article: Provision | None = None
    for line in lines[1:]:
        if m := _ARTICLE.match(line):
            path = f"art{m['n']}"
            article = Provision(f"{statute.id}#{path}", statute.id, path, m["text"])
            provisions.append(article)
        elif (m := _PARAGRAPH.match(line)) and article is not None:
            path = f"{article.path}_par{m['n']}"
            provisions.append(
                Provision(f"{statute.id}#{path}", statute.id, path, m["text"], parent_id=article.id)
            )
        else:
            raise ValueError(f"unrecognized line: {line!r}")
    return statute, provisions
