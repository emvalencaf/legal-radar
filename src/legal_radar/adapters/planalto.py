"""Parse a Planalto lei page into the legal-document AST (see ADR-0001).

Real Planalto pages have few usable anchors and carry struck-through superseded versions of
amended provisions, so structure is recognised from the text of each block, not from the markup.
"""

import re
from dataclasses import dataclass, field, replace

from bs4 import BeautifulSoup, NavigableString, Tag

from legal_radar.application.ports import PageSource
from legal_radar.domain.model import Dispositivo
from legal_radar.domain.urn import UrnPage

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
_REVOCATION = re.compile(r"\(Revogad[oa]s?\b[^)]*\)", re.IGNORECASE)
_STRUCK_OPEN, _STRUCK_CLOSE = "\ue000", "\ue001"  # bracket struck-through text through get_text


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
    revocations: list[str] = field(default_factory=list)


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

    for live, struck in _lines(html):
        line, marks = _split_revocations(live, struck)
        touched: _Node | None = None  # the dispositivo this line belongs to
        if not line:
            touched = current  # a bare mark continues the dispositivo above it
        elif _END.match(line) and artigo is not None:
            break
        elif heading := _match_heading(line):
            kind, rank, code, rest = heading
            while org and org[-1].rank >= rank:
                org.pop()
            path = "_".join(([org[-1].dispositivo.path] if org else []) + [f"{kind}{code}"])
            node = add(kind, rank, path, org[-1] if org else None, rest)
            current = node if node and not rest else None
            touched = node
            if node:
                org.append(node)
            artigo = paragrafo = inciso = None
        elif m := _ARTIGO.match(line):
            code = m[1].replace(".", "") + (m[2] or "")
            node = add("artigo", 10, f"art{code}", org[-1] if org else None, m[3])
            artigo, paragrafo, inciso, current = node, None, None, node
            touched = node
        elif artigo and (m := _PARAGRAFO.match(line)):
            code = "Unico" if m[3] else (m[1].replace(".", "") + (m[2] or ""))
            node = add("paragrafo", 11, f"{artigo.dispositivo.path}_par{code}", artigo, m[4])
            paragrafo, inciso, current = node, None, node
            touched = node
        elif artigo and (m := _INCISO.match(line)):
            parent = paragrafo or artigo
            code = m[1] + (m[2] or "")
            node = add("inciso", 12, f"{parent.dispositivo.path}_inc{code}", parent, m[3])
            inciso, current = node, node
            touched = node
        elif artigo and (m := _ALINEA.match(line)):
            parent = inciso or paragrafo or artigo
            node = add("alinea", 13, f"{parent.dispositivo.path}_ali{m[1]}", parent, m[2])
            current = touched = node
        elif current is not None:
            current.text.append(line)
            touched = current
            if current.rank < 10:
                current = None  # a heading's name is one line; anything after it is stray
        if touched:
            touched.revocations.extend(marks)

    return [_finish(n) for n in nodes]


def _finish(n: _Node) -> Dispositivo:
    marks = tuple(dict.fromkeys(n.revocations))
    text = re.sub(r"\s+", " ", " ".join(n.text)).strip()
    return replace(n.dispositivo, text=text, revoked=bool(marks), revocations=marks)


def _split_revocations(live: str, struck: str) -> tuple[str, list[str]]:
    """The line to parse and the `(Revogado …)` marks on it, struck or not.

    A line whose only live content is marks, over struck text that opens a dispositivo, is a fully
    revoked one: its struck text is kept. Any other struck text is a superseded version, dropped.
    """
    marks = [re.sub(r"\s+", " ", m[0]) for m in _REVOCATION.finditer(f"{live} {struck}")]
    live = _clean(_REVOCATION.sub("", live))
    struck = _clean(_REVOCATION.sub("", struck))
    if not live and marks and _opens_dispositivo(struck):
        return struck, marks
    return live, marks


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _opens_dispositivo(line: str) -> bool:
    return bool(
        _match_heading(line)
        or _ARTIGO.match(line)
        or _PARAGRAFO.match(line)
        or _INCISO.match(line)
        or _ALINEA.match(line)
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


def _lines(html: str) -> list[tuple[str, str]]:
    """Each block of the page as `(live text, struck-through text)`, blanks skipped."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(["script", "style"]):
        tag.decompose()
    struck_tags = soup.find_all(["strike", "s", "del"]) + soup.find_all(style=_STRUCK_STYLE)
    for tag in struck_tags:
        tag.insert_before(_STRUCK_OPEN)
        tag.insert_after(_STRUCK_CLOSE)
    for text in soup.find_all(string=True):
        if isinstance(text, NavigableString):
            text.replace_with(re.sub(r"\s+", " ", str(text).replace("\xa0", " ")))
    for tag in soup.find_all(_BLOCK_TAGS):
        if isinstance(tag, Tag):
            tag.insert_before("\n")
            if tag.name != "br":
                tag.insert_after("\n")
    depth = 0
    lines: list[tuple[str, str]] = []
    for raw in soup.get_text("").split("\n"):
        live: list[str] = []
        struck: list[str] = []
        for char in raw:
            if char == _STRUCK_OPEN:
                depth += 1
            elif char == _STRUCK_CLOSE:
                depth = max(0, depth - 1)
            else:
                (struck if depth else live).append(char)
        if (pair := (_clean("".join(live)), _clean("".join(struck)))) != ("", ""):
            lines.append(pair)
    return lines


class PlanaltoTextSource:
    """`LeiTextSource` over the lei's Planalto page."""

    def __init__(self, pages: PageSource):
        self.pages = pages

    def dispositivos(self, page: UrnPage) -> list[Dispositivo]:
        assert page.planalto_url is not None
        return parse_planalto(self.pages.get(page.planalto_url), page.urn)
