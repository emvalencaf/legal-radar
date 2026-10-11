"""Parse the skeleton's plain-text lei fixture into Lei and Dispositivos."""

import re

from legal_radar.domain import Dispositivo, Lei

_LEI = re.compile(r"^Lei (?P<number>\S+) (?P<title>.+)$")
_ARTIGO = re.compile(r"^Art\. (?P<n>\d+)º? (?P<text>.+)$")
_PARAGRAFO = re.compile(r"^§ (?P<n>\d+)º? (?P<text>.+)$")


def parse_lei(raw: str) -> tuple[Lei, list[Dispositivo]]:
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    header = _LEI.match(lines[0])
    if header is None:
        raise ValueError(f"first line is not a lei header: {lines[0]!r}")
    lei = Lei(id=f"lei:{header['number']}", title=header["title"])

    dispositivos: list[Dispositivo] = []
    artigo: Dispositivo | None = None
    for line in lines[1:]:
        if m := _ARTIGO.match(line):
            path = f"art{m['n']}"
            artigo = Dispositivo(f"{lei.id}#{path}", lei.id, path, m["text"])
            dispositivos.append(artigo)
        elif (m := _PARAGRAFO.match(line)) and artigo is not None:
            path = f"{artigo.path}_par{m['n']}"
            dispositivos.append(
                Dispositivo(f"{lei.id}#{path}", lei.id, path, m["text"], parent_id=artigo.id)
            )
        else:
            raise ValueError(f"unrecognized line: {line!r}")
    return lei, dispositivos
