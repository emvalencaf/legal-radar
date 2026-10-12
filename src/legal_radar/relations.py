"""Rule-based extraction of REFERENCES and REVOKES edges from one dispositivo (ADR-0002).

Every edge comes from a regex match, so it is HIGH and origin `rule`, unless its target is a stub
(a lei the graph does not hold, or a dispositivo missing from one it does) or unresolved: then LOW.
Whatever looks like a citation but no rule resolved is returned in `Extraction.needs_llm` for the
LLM enricher. `(Redação dada por …)` and other amendment marks are masked, never read as citations.
"""

import re
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass

from legal_radar.domain import Confidence, Dispositivo, Origin, Relation, RelationType
from legal_radar.lexml import LexmlError, search_urn
from legal_radar.ports import PageSource

UrnResolver = Callable[[str, str, int], str | None]  # (kind, numero, ano) -> URN, e.g. ("lei", ...)

_FEDERAL = "urn:lex:br:federal"
_CODES: dict[str, tuple[str, ...]] = {
    f"{_FEDERAL}:lei:2002-01-10;10406": ("Código Civil", "CC"),
    f"{_FEDERAL}:lei:1990-09-11;8078": ("Código de Defesa do Consumidor", "CDC"),
    f"{_FEDERAL}:lei:2015-03-16;13105": ("Código de Processo Civil", "CPC"),
    f"{_FEDERAL}:lei:1966-10-25;5172": ("Código Tributário Nacional", "CTN"),
    f"{_FEDERAL}:decreto.lei:1940-12-07;2848": ("Código Penal", "CP"),
    f"{_FEDERAL}:decreto.lei:1941-10-03;3689": ("Código de Processo Penal", "CPP"),
    f"{_FEDERAL}:decreto.lei:1943-05-01;5452": ("Consolidação das Leis do Trabalho", "CLT"),
    f"{_FEDERAL}:constituicao:1988-10-05;1988": ("Constituição Federal", "CF"),
}
_NAME_URN = {name: urn for urn, names in _CODES.items() for name in names}
_URN_KEY = re.compile(r"^urn:lex:br:federal:([\w.]+):(\d{4})-\d{2}-\d{2};(\d+)$")
_ACT_URN = {
    (m[1], m[3], int(m[2])): urn for urn in _CODES if (m := _URN_KEY.match(urn))
}  # (kind, numero, ano) -> URN
_KINDS = {
    "Lei Complementar": "lei.complementar",
    "Lei": "lei",
    "Decreto-Lei": "decreto.lei",
    "Decreto": "decreto",
    "Emenda Constitucional": "emenda.constitucional",
}

_ROMAN = r"\b[IVXLCDM]+\b"
_NUM = r"\d+(?:\.\d{3})*"
_KIND = "|".join(sorted(_KINDS, key=len, reverse=True))
_ACT = (
    rf"(?P<kind>{_KIND})\s*(?:n[ºo°.]*)?\s*(?P<numero>{_NUM})"
    r"(?:\s*/\s*(?P<ano>\d{4})|,?\s*de\s+(?:\d{1,2}\s*[º°]?\s+de\s+\w+\s+de\s+)?(?P<ano2>\d{4}))"
)
_PAR = r"(?:§\s*(?P<par>\d+)\s*[º°]?|(?P<unico>[Pp]arágrafo único))"
_INC = rf"incisos?\s+(?P<i1>{_ROMAN})(?:\s+(?:a|ao)\s+(?P<i2>{_ROMAN}))?"
_NAMES = "|".join(re.escape(n) for n in sorted(_NAME_URN, key=len, reverse=True))

_ARTIGO = re.compile(
    rf"(?:\b[Aa]rts?\.|\b[Aa]rtigos?)\s*(?P<n>{_NUM})[º°]?(?:\s*-\s*(?P<sfx>[A-Z])\b)?"
    rf"(?:\s+(?:a|ao)\s+(?P<n2>{_NUM})[º°]?)?"
)
_LOCATOR = re.compile(rf"(?:\s*,?\s*(?:(?P<caput>caput)|{_PAR}))?(?:\s*,?\s*{_INC})?")
_LAW = re.compile(
    r"\s*,?\s*(?:(?P<same>desta Lei|deste Código|desta Constituição|desta Consolidação)"
    rf"|d[oa]s?\s+(?:(?P<name>{_NAMES})|{_ACT}"
    r"|(?P<other>Código(?:\s+(?:d[aeo]s?\s+)?[A-ZÀ-Ú]\w*)+)))"
)
_UNKNOWN_LAW = re.compile(r"\s*,?\s*d[oa]s?\s+[A-ZÀ-Ú]")
_THIS_ARTIGO = re.compile(rf"(?:{_INC}\s*(?:d[oa]\s+)?)?(?:{_PAR}\s*)?(?:deste|neste)\s+artigo\b")
_PREVIOUS_ARTIGO = re.compile(r"\b[Aa]rt(?:\.|igo)\s+anterior\b")
_ACT_MENTION = re.compile(_ACT)
_REVOKED = re.compile(rf"\(Revogad[oa]s?\s+(?:pel[ao]s?\s+)?{_ACT}[^)]*\)")
_AMENDMENT = re.compile(
    r"\((?:Redação|Inclu[ií]d|Vide|Regulamento|Vig[eê]ncia|Renumerad|Revogad|Produ[cç][aã]o)[^)]*\)"
)
_CITATION_MARK = re.compile(
    rf"(?:\b[Aa]rts?\.|\b[Aa]rtigos?)\s*\d|§\s*\d|\b{_INC}|\b[Pp]arágrafo único\b"
)
_OWN_ARTIGO = re.compile(r"^art\d+[A-Z]?$")
_MAX_EXPANSION = 50
_SNIPPET = 80


@dataclass(frozen=True)
class Extraction:
    relations: list[Relation]
    needs_llm: list[str]  # literal snippets of the chunk the rules could not resolve


def lexml_resolver(pages: PageSource) -> UrnResolver:
    """Fall back to a LexML keyword search for federal leis missing from the curated table."""

    def resolve(kind: str, numero: str, ano: int) -> str | None:
        if kind != "lei":
            return None
        try:
            return search_urn(pages, f"lei {numero} {ano}", numero, ano, retries=0)
        except LexmlError:
            return None

    return resolve


def extract_relations(
    d: Dispositivo,
    resolver: UrnResolver | None = None,
    ingested: Mapping[str, Collection[str]] | None = None,
) -> Extraction:
    """Extract the REFERENCES and REVOKES edges of `d`.

    `ingested` maps each lei in the graph to its dispositivo ids: a target in a lei missing from it
    is a stub, and one missing from its lei's ids does not exist, both LOW. `None` skips the check.
    """
    text = d.text
    masked = _AMENDMENT.sub(lambda m: " " * len(m[0]), text)
    out: list[Relation] = []
    flags: list[str] = []
    covered: list[tuple[int, int]] = []

    def edge(type_, source, target, evidence, unresolved=None):
        node = source if type_ is RelationType.REVOKES else target
        known = unresolved is None and _exists(node, ingested)
        confidence = Confidence.HIGH if known else Confidence.LOW
        out.append(Relation(type_, source, target, confidence, Origin.RULE, evidence, unresolved))

    for m in _REVOKED.finditer(text):
        urn, label = _act(m, resolver)
        edge(RelationType.REVOKES, urn, d.id, m[0], label if urn is None else None)

    own = _own_artigo(d)

    for m in _ARTIGO.finditer(masked):
        loc = _LOCATOR.match(masked, m.end())
        end = loc.end() if loc else m.end()
        law = _LAW.match(masked, end)
        if law:
            end = law.end()
        elif _UNKNOWN_LAW.match(masked, end):
            flags.append(_snippet(text, m.start()))
            covered.append((m.start(), end))
            continue
        covered.append((m.start(), end))
        urn, label = (d.lei_id, None) if law is None else _law(law, d.lei_id, resolver)
        artigos = _artigo_range(m)
        paths = [p for a in artigos for p in _expand(a, loc)] if artigos else None
        if paths is None:
            flags.append(_snippet(text, m.start()))
            continue
        for path in paths:
            if urn is None:
                edge(RelationType.REFERENCES, d.id, None, text[m.start() : end], f"{label} {path}")
            else:
                edge(RelationType.REFERENCES, d.id, f"{urn}#{path}", text[m.start() : end])
        if urn is None:
            flags.append(_snippet(text, m.start()))

    for m in _THIS_ARTIGO.finditer(masked):
        covered.append((m.start(), m.end()))
        if own is None:
            flags.append(_snippet(text, m.start()))
            continue
        for path in _expand(own, m):
            edge(RelationType.REFERENCES, d.id, f"{d.lei_id}#{path}", m[0])

    for m in _PREVIOUS_ARTIGO.finditer(masked):
        covered.append((m.start(), m.end()))
        previous = _previous(own)
        if previous is None:
            flags.append(_snippet(text, m.start()))
        else:
            edge(RelationType.REFERENCES, d.id, f"{d.lei_id}#{previous}", m[0])

    for m in _ACT_MENTION.finditer(masked):
        if any(a <= m.start() < b for a, b in covered):
            continue
        urn, label = _act(m, resolver)
        if urn == d.lei_id:
            continue
        edge(RelationType.REFERENCES, d.id, urn, m[0], label if urn is None else None)

    for m in _CITATION_MARK.finditer(masked):
        if not any(a <= m.start() < b for a, b in covered):
            flags.append(_snippet(text, m.start()))

    seen: set[tuple] = set()
    relations = []
    for r in out:
        key = (r.type, r.source_id, r.target_id, r.unresolved)
        if key not in seen and r.evidence in text and r.source_id != r.target_id:
            seen.add(key)
            relations.append(r)
    return Extraction(relations, list(dict.fromkeys(flags)))


def _exists(node_id: str | None, ingested: Mapping[str, Collection[str]] | None) -> bool:
    if ingested is None or node_id is None:
        return True
    lei = node_id.split("#", 1)[0]
    return lei in ingested and ("#" not in node_id or node_id in ingested[lei])


def _act(m: re.Match[str], resolver: UrnResolver | None) -> tuple[str | None, str]:
    key = (_KINDS[m["kind"]], m["numero"].replace(".", ""), int(m["ano"] or m["ano2"]))
    urn = _ACT_URN.get(key) or (resolver(*key) if resolver else None)
    return urn, f"{key[0]}:{key[1]}/{key[2]}"


def _law(m: re.Match[str], this_lei: str, resolver: UrnResolver | None) -> tuple[str | None, str]:
    if m["same"]:
        return this_lei, m["same"]
    if m["name"]:
        return _NAME_URN[m["name"]], m["name"]
    if m["kind"]:
        return _act(m, resolver)
    return None, m["other"]


def _own_artigo(d: Dispositivo) -> str | None:
    return next((s for s in d.path.split("_") if _OWN_ARTIGO.match(s)), None)


def _previous(artigo: str | None) -> str | None:
    if artigo and (m := re.fullmatch(r"art(\d+)", artigo)) and int(m[1]) > 1:
        return f"art{int(m[1]) - 1}"
    return None


def _artigo_range(m: re.Match[str]) -> list[str] | None:
    first = int(m["n"].replace(".", ""))
    if not m["n2"]:
        return [f"art{first}{m['sfx'] or ''}"]
    last = int(m["n2"].replace(".", ""))
    if m["sfx"] or not first < last <= first + _MAX_EXPANSION:
        return None
    return [f"art{n}" for n in range(first, last + 1)]


def _expand(artigo: str, loc: re.Match[str] | None) -> list[str]:
    """The paths a locator (`§ 2º`, `incisos I a III`) selects inside `artigo`, one per inciso."""
    base = artigo
    if loc and loc["par"]:
        base += f"_par{loc['par']}"
    elif loc and loc["unico"]:
        base += "_parUnico"
    if not (loc and loc["i1"]):
        return [base]
    first = _roman(loc["i1"])
    last = _roman(loc["i2"]) if loc["i2"] else first
    if not 0 < first <= last <= first + _MAX_EXPANSION:
        return [base]  # unreadable range: keep the dispositivo, drop the inciso
    return [f"{base}_inc{_to_roman(n)}" for n in range(first, last + 1)]


_NUMERALS = [
    (1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"),
    (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"),
]  # fmt: skip


def _to_roman(n: int) -> str:
    out = ""
    for value, symbol in _NUMERALS:
        while n >= value:
            out += symbol
            n -= value
    return out


def _roman(s: str) -> int:
    return next((n for n in range(1, 4000) if _to_roman(n) == s), 0)


def _snippet(text: str, start: int) -> str:
    return text[start : start + _SNIPPET].strip()
