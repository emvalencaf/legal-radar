"""Parse a Planalto lei page into the legal-document AST (see ADR-0001).

Real Planalto pages have few usable anchors and carry struck-through superseded versions of
amended provisions, so structure is recognised from the text of each block, not from the markup.
"""

import re
from dataclasses import dataclass

from bs4 import BeautifulSoup, NavigableString, Tag

from legal_radar.domain import Dispositivo

_ROMAN = r"[IVXLCDM]+"
_HEADINGS: list[tuple[str, int, re.Pattern[str]]] = [
    ("parte", 0, re.compile(r"^PARTE\s+(GERAL|ESPECIAL)\b\s*(.*)$")),
    ("livro", 1, re.compile(rf"^LIVRO\s+({_ROMAN}|ÚNICO)\b\s*(.*)$")),
    ("titulo", 2, re.compile(rf"^TÍTULO\s+({_ROMAN}|ÚNICO)(-[A-Z])?\s*(.*)$")),
    ("subtitulo", 3, re.compile(rf"^SUBTÍTULO\s+({_ROMAN}|ÚNICO)(-[A-Z])?\s*(.*)$")),
    ("capitulo", 4, re.compile(rf"^CAPÍTULO\s+({_ROMAN}|ÚNICO)(-[A-Z])?\s*(.*)$")),
    ("secao", 5, re.compile(rf"^SEÇÃO\s+({_ROMAN}|ÚNICA)(-[A-Z])?\s*(.*)$", re.IGNORECASE)),
    ("subsecao", 6, re.compile(rf"^SUBSEÇÃO\s+({_ROMAN}|ÚNICA)(-[A-Z])?\s*(.*)$", re.IGNORECASE)),
]
_ARTIGO = re.compile(
    r"^Art\.\s*(\d+(?:\.\d{3})*)\s*(?:[º°]|o(?![a-zà-ú]))?\s*(?:-\s*([A-Z]{1,2}))?\s*[.\-\u2013]?\s*(.*)$"
)
_PARAGRAFO = re.compile(
    r"^(?:§\s*(\d+(?:\.\d{3})*)\s*(?:[º°]|o(?![a-zà-ú]))?\s*(?:-\s*([A-Z]))?|(Parágrafo\s+único))"
    r"\s*[.\-\u2013]?\s*(.*)$"
)
_INCISO = re.compile(rf"^({_ROMAN})\s*(?:-\s*([A-Z])\s*)?[-\u2013—]\s+(.*)$")
_ALINEA = re.compile(r"^([a-z])\)\s*(.*)$")
_END = re.compile(r"^(Brasília,|Este texto não substitui)")
_BLOCK_TAGS = ["p", "div", "br", "tr", "table", "li", "h1", "h2", "h3", "h4", "h5", "h6"]
_STRUCK_STYLE = re.compile(r"line-through")


def decode_html(raw: bytes) -> str:
    """Planalto serves cp1252 (declared inconsistently); fall back when it isn't valid UTF-8."""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")


@dataclass
class _Node:
    dispositivo: Dispositivo
    rank: int
    text: list[str]


def parse_planalto(html: str, lei_id: str) -> list[Dispositivo]:
    nodes: list[_Node] = []
    seen: set[str] = set()
    org: list[_Node] = []  # open organizational headings, outermost first
    artigo: _Node | None = None
    paragrafo: _Node | None = None
    inciso: _Node | None = None
    current: _Node | None = None  # receives continuation lines

    def add(kind: str, rank: int, path: str, parent: _Node | None, text: str) -> _Node | None:
        d = Dispositivo(
            f"{lei_id}#{path}", lei_id, path, "", parent.dispositivo.id if parent else None, kind
        )
        if d.id in seen:
            return None  # same provision repeated in the page: the first (current) one wins
        seen.add(d.id)
        node = _Node(d, rank, [text] if text else [])
        nodes.append(node)
        return node

    for line in _lines(html):
        if _END.match(line) and artigo is not None:
            break
        if heading := _match_heading(line):
            kind, rank, code, rest = heading
            while org and org[-1].rank >= rank:
                org.pop()
            path = "_".join(([org[-1].dispositivo.path] if org else []) + [f"{kind}{code}"])
            node = add(kind, rank, path, org[-1] if org else None, rest)
            current = node if node and not rest else None
            if node:
                org.append(node)
            artigo = paragrafo = inciso = None
        elif m := _ARTIGO.match(line):
            code = m[1].replace(".", "") + (m[2] or "")
            node = add("artigo", 10, f"art{code}", org[-1] if org else None, m[3])
            artigo, paragrafo, inciso, current = node, None, None, node
        elif artigo and (m := _PARAGRAFO.match(line)):
            code = "Unico" if m[3] else (m[1].replace(".", "") + (m[2] or ""))
            node = add("paragrafo", 11, f"{artigo.dispositivo.path}_par{code}", artigo, m[4])
            paragrafo, inciso, current = node, None, node
        elif artigo and (m := _INCISO.match(line)):
            parent = paragrafo or artigo
            code = m[1] + (m[2] or "")
            node = add("inciso", 12, f"{parent.dispositivo.path}_inc{code}", parent, m[3])
            inciso, current = node, node
        elif artigo and (m := _ALINEA.match(line)):
            parent = inciso or paragrafo or artigo
            node = add("alinea", 13, f"{parent.dispositivo.path}_ali{m[1]}", parent, m[2])
            current = node
        elif current is not None:
            current.text.append(line)
            if current.rank < 10:
                current = None  # a heading's name is one line; anything after it is stray

    return [_with_text(n.dispositivo, " ".join(n.text)) for n in nodes]


def _with_text(d: Dispositivo, text: str) -> Dispositivo:
    return Dispositivo(
        d.id, d.lei_id, d.path, re.sub(r"\s+", " ", text).strip(), d.parent_id, d.kind
    )


def _match_heading(line: str) -> tuple[str, int, str, str] | None:
    squeezed = line.replace(" ", "").upper()  # Planalto letter-spaces "P A R T E  G E R A L"
    if squeezed in ("PARTEGERAL", "PARTEESPECIAL"):
        line = f"PARTE {squeezed[5:]}"
    for kind, rank, pattern in _HEADINGS:
        if m := pattern.match(line):
            code, rest = m[1], m.groups()[-1]
            suffix = m[2] if len(m.groups()) == 3 and m[2] else ""
            if (
                rest
                and not rest.startswith(("-", "\u2013", "—"))
                and kind not in ("parte", "livro")
            ):
                continue  # prose that merely starts with the word, e.g. "Seção I deste capítulo"
            code = code.upper().replace("Ú", "U").replace("PARTE", "")
            if kind == "parte":
                code = code.title()
            return kind, rank, code + suffix.lstrip("-"), rest.lstrip("-\u2013— ").strip()
    return None


def _lines(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(["strike", "s", "del", "script", "style"]):
        tag.decompose()
    for tag in soup.find_all(style=_STRUCK_STYLE):
        tag.decompose()
    for text in soup.find_all(string=True):
        if isinstance(text, NavigableString):
            text.replace_with(re.sub(r"\s+", " ", str(text).replace("\xa0", " ")))
    for tag in soup.find_all(_BLOCK_TAGS):
        if isinstance(tag, Tag):
            tag.insert_before("\n")
            if tag.name != "br":
                tag.insert_after("\n")
    text = soup.get_text("")
    return [line for raw in text.split("\n") if (line := re.sub(r"\s+", " ", raw).strip())]
