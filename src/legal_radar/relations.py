"""Rule-based extraction of REFERENCES and REVOKES edges from one dispositivo (ADR-0002).

Every edge comes from a regex match, so it is HIGH and origin `rule`, unless its target is a stub
(a lei the graph does not hold, or a dispositivo missing from one it does) or unresolved: then LOW.
Whatever looks like a citation but no rule resolved is returned in `Extraction.needs_llm` for the
LLM enricher. `(Redação dada por …)` and other amendment marks are masked, never read as citations.
"""

import logging
import re
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, field

from legal_radar.domain import (
    Confidence,
    Dispositivo,
    Jurisprudencia,
    Origin,
    Relation,
    RelationType,
)
from legal_radar.enrichment import EXTRACTOR_VERSION
from legal_radar.lexml import LexmlError, search_urn
from legal_radar.ports import PageSource

logger = logging.getLogger(__name__)
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
CURATED_CODES = tuple(_CODES)  # URNs of the most-cited codes, valid targets of a citation
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
    "Medida Provisória": "medida.provisoria",
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
_PRE_LOCATOR = re.compile(  # `§ 1º do`, `incisos I a III do` right before `art. 50`
    rf"(?:{_PAR}\s*,?\s*)?(?:{_INC}\s*,?\s*)?d[oa]\s+$"
)
_LAW = re.compile(
    r"\s*,?\s*(?:(?P<same>desta Lei|deste Código|desta Constituição|desta Consolidação)"
    rf"|d[oa]s?\s+(?:(?P<name>{_NAMES})|{_ACT}"
    r"|(?P<other>Código(?:\s+(?:d[aeo]s?\s+)?[A-ZÀ-Ú]\w*)+)))"
)
_UNKNOWN_LAW = re.compile(r"\s*,?\s*d[oa]s?\s+[A-ZÀ-Ú]")
_THIS_ARTIGO = re.compile(rf"(?:{_INC}\s*(?:d[oa]\s+)?)?(?:{_PAR}\s*)?(?:deste|neste)\s+artigo\b")
_PREVIOUS_ARTIGO = re.compile(r"\b[Aa]rt(?:\.|igo)\s+anterior\b")
_ACT_MENTION = re.compile(_ACT)
_REVOKED = re.compile(rf"\((?i:Revogad[oa]s?\s+(?:pel[ao]s?\s+)?){_ACT}[^)]*\)")
_AMENDMENT = re.compile(
    r"\((?:Redação|Inclu[ií]d|Vide|Regulamento|Vig[eê]ncia|Renumerad|Revogad|Produ[cç][aã]o)[^)]*\)"
)
_CITATION_MARK = re.compile(
    rf"(?:\b[Aa]rts?\.|\b[Aa]rtigos?)\s*\d|§\s*\d|\b{_INC}|\b[Pp]arágrafo único\b"
)
_ART_DOT = re.compile(r"\b([Aa]rts?)\s+\.")  # `ART .` once the wraps are joined
_OWN_ARTIGO = re.compile(r"^art\d+[A-Z]?$")
_MAX_EXPANSION = 50
_PRE_WINDOW = 60  # how far back a locator before `art.` is looked for
_SNIPPET = 80


@dataclass(frozen=True)
class Extraction:
    """Per-chunk result (ADR-0002): the edges, what is left for the LLM, and the audit counters."""

    relations: list[Relation]
    needs_llm: list[
        str
    ]  # snippets with no edge at all; an unresolved citation is a LOW edge instead
    dropped: int  # items discarded for failing validation (evidence not literal)
    extractor_version: str

    @property
    def needs_enrichment(self) -> bool:
        """Whether the chunk goes to the LLM: something unread, or a citation left unresolved."""
        return bool(self.needs_llm) or any(r.unresolved for r in self.relations)


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
    scan = _Scan(d, resolver, ingested)
    for pattern in (
        _revocations,
        _artigo_citations,
        _this_artigo,
        _previous_artigo,
        _act_mentions,
        _leftover_marks,
    ):
        pattern(scan)
    return scan.result()


def extract_decision_relations(
    j: Jurisprudencia,
    resolver: UrnResolver | None = None,
    ingested: Mapping[str, Collection[str]] | None = None,
) -> Extraction:
    """Extract the REFERENCES edges of a decision from its ementa and tese (never the decisão).

    A decision has no home lei, so a citation that names none (`art. 50` alone) is unresolved, and
    `deste artigo` / `artigo anterior` mean nothing. Same confidence rules as `extract_relations`.
    """
    # court texts arrive wrapped mid-citation (`ART\n.\n50`): read each part on one line
    parts = (_unwrap(t) for t in (j.ementa, j.tese) if t and t.strip())
    text = "\n\n".join(parts)
    scan = _Scan(Dispositivo(j.id, "", "", text), resolver, ingested, leading=True)
    for pattern in (_artigo_citations, _act_mentions, _leftover_marks):
        pattern(scan)
    return scan.result()


_CONNECTORS = {
    "do", "da", "dos", "das", "de", "deste", "desta", "neste", "nesta", "inciso", "incisos",
    "parágrafo", "único", "artigo", "artigos", "art", "arts", "caput", "anterior", "nº", "a", "ao",
}  # fmt: skip


def _unwrap(text: str) -> str:
    """A court text read by the citation rules: wraps joined, `ART .` closed up, and the words of
    an all-capitals ementa put back in the case the rules expect (`ART. 50 DO CÓDIGO CIVIL`).
    Roman numerals and the codes' acronyms stay as they are."""

    def word(m: re.Match[str]) -> str:
        token = m[0]
        if len(token) < 2 or not token.isupper() or token in _NAME_URN or _is_roman(token):
            return token
        return token.lower() if token.lower() in _CONNECTORS else token.capitalize()

    return _ART_DOT.sub(r"\1.", re.sub(r"[^\W\d_]+", word, " ".join(text.split())))


@dataclass
class _Scan:
    """The state one pass over a dispositivo shares between the pattern functions."""

    d: Dispositivo
    resolver: UrnResolver | None
    ingested: Mapping[str, Collection[str]] | None
    leading: bool = False  # read a locator before the artigo (`§ 1º do art. 50`): decisions only
    out: list[Relation] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    covered: list[tuple[int, int]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.text = self.d.text
        self.masked = _AMENDMENT.sub(lambda m: " " * len(m[0]), self.text)  # same offsets as text
        self.own = next((s for s in self.d.path.split("_") if _OWN_ARTIGO.match(s)), None)

    def edge(
        self,
        type_: RelationType,
        source: str | None,
        target: str | None,
        evidence: str,
        unresolved: str | None = None,
    ) -> None:
        node = source if type_ is RelationType.REVOKES else target
        known = unresolved is None and _exists(node, self.ingested)
        confidence = Confidence.HIGH if known else Confidence.LOW
        self.out.append(
            Relation(type_, source, target, confidence, Origin.RULE, evidence, unresolved)
        )

    def reference_in(self, urn: str, path: str, evidence: str) -> None:
        self.edge(RelationType.REFERENCES, self.d.id, f"{urn}#{path}", evidence)

    def reference(self, target: str, evidence: str) -> None:
        self.edge(RelationType.REFERENCES, self.d.id, f"{self.d.lei_id}#{target}", evidence)

    def cover(self, start: int, end: int) -> None:
        self.covered.append((start, end))

    def is_covered(self, position: int) -> bool:
        return any(a <= position < b for a, b in self.covered)

    def flag(self, start: int) -> None:
        self.flags.append(self.text[start : start + _SNIPPET].strip())

    def result(self) -> Extraction:
        seen: set[tuple] = set()
        relations: list[Relation] = []
        dropped = 0
        for r in self.out:
            if not any(r.evidence in source for source in (self.text, *self.d.revocations)):
                dropped += 1
                logger.warning("dropped %s edge of %s: evidence is not literal", r.type, self.d.id)
                continue
            key = (r.type, r.source_id, r.target_id, r.unresolved)
            if key not in seen and r.source_id != r.target_id:  # a self-reference is no edge
                seen.add(key)
                relations.append(r)
        return Extraction(relations, list(dict.fromkeys(self.flags)), dropped, EXTRACTOR_VERSION)


def _revocations(s: _Scan) -> None:
    """`(Revogado pela Lei nº …)`: the revoking act (a stub Lei if not ingested) revokes this."""
    for mark in (s.text, *s.d.revocations):  # the parser moves the marks out of the text
        for m in _REVOKED.finditer(mark):
            urn, label = _act(m, s.resolver)
            s.edge(RelationType.REVOKES, urn, s.d.id, m[0], label if urn is None else None)


def _artigo_citations(s: _Scan) -> None:
    """`art. 5º, § 2º, incisos I a III, do Código Civil`, including artigo ranges."""
    for m in _ARTIGO.finditer(s.masked):
        loc = _LOCATOR.match(s.masked, m.end())
        end = loc.end() if loc else m.end()
        start = m.start()
        if s.leading and not (loc and (loc["caput"] or loc["par"] or loc["unico"] or loc["i1"])):
            pre = _PRE_LOCATOR.search(s.masked, max(0, start - _PRE_WINDOW), start)
            if pre and (pre["par"] or pre["unico"] or pre["i1"]):
                loc, start = pre, pre.start()  # the locator comes first: `§ 1º do art. 50`
        law = _LAW.match(s.masked, end)
        if law:
            end = law.end()
        s.cover(start, end)
        if law is None and _UNKNOWN_LAW.match(s.masked, end):
            s.flag(start)  # a law the table does not know: not the same lei, not guessable
            continue
        home = s.d.lei_id or None  # a decision has none
        urn, label = (home, "lei não informada") if law is None else _law(law, home, s.resolver)
        paths = _paths(m, loc)
        if paths is None:
            s.flag(start)
            continue
        for path in paths:
            if urn is None:  # unresolved: the LOW edge carries the citation, no need to flag it too
                s.edge(
                    RelationType.REFERENCES,
                    s.d.id,
                    None,
                    s.text[start:end],
                    f"{label} {path}",
                )
            else:
                s.reference_in(urn, path, s.text[start:end])


def _this_artigo(s: _Scan) -> None:
    """`deste artigo`, optionally prefixed by `§ 2º` or `incisos I a III`."""
    for m in _THIS_ARTIGO.finditer(s.masked):
        s.cover(m.start(), m.end())
        paths = _expand(s.own, m) if s.own else None
        if paths is None:
            s.flag(m.start())
            continue
        for path in paths:
            s.reference(path, m[0])


def _previous_artigo(s: _Scan) -> None:
    """`o artigo anterior`: only for an artigo numbered above 1 and without a letter suffix."""
    for m in _PREVIOUS_ARTIGO.finditer(s.masked):
        s.cover(m.start(), m.end())
        previous = _previous(s.own)
        if previous is None:
            s.flag(m.start())
        else:
            s.reference(previous, m[0])


def _act_mentions(s: _Scan) -> None:
    """`Lei nº 8.078/1990` on its own: a reference to the lei, not to one of its dispositivos."""
    for m in _ACT_MENTION.finditer(s.masked):
        if s.is_covered(m.start()):
            continue
        urn, label = _act(m, s.resolver)
        if urn != s.d.lei_id:
            s.edge(RelationType.REFERENCES, s.d.id, urn, m[0], label if urn is None else None)


def _leftover_marks(s: _Scan) -> None:
    """Whatever still looks like a citation after the other patterns goes to the LLM."""
    for m in _CITATION_MARK.finditer(s.masked):
        if not s.is_covered(m.start()):
            s.flag(m.start())


def _exists(node_id: str | None, ingested: Mapping[str, Collection[str]] | None) -> bool:
    if ingested is None or node_id is None:
        return True
    lei = node_id.split("#", 1)[0]
    return lei in ingested and ("#" not in node_id or node_id in ingested[lei])


def _act(m: re.Match[str], resolver: UrnResolver | None) -> tuple[str | None, str]:
    key = (_KINDS[m["kind"]], m["numero"].replace(".", ""), int(m["ano"] or m["ano2"]))
    urn = _ACT_URN.get(key) or (resolver(*key) if resolver else None)
    return urn, f"{key[0]}:{key[1]}/{key[2]}"


def _law(
    m: re.Match[str], this_lei: str | None, resolver: UrnResolver | None
) -> tuple[str | None, str]:
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


def _paths(m: re.Match[str], loc: re.Match[str] | None) -> list[str] | None:
    artigos = _artigo_range(m)
    if artigos is None:
        return None
    expanded = [_expand(a, loc) for a in artigos]
    return None if None in expanded else [p for paths in expanded for p in paths or []]


def _expand(artigo: str, loc: re.Match[str] | None) -> list[str] | None:
    """The paths a locator (`§ 2º`, `incisos I a III`) selects inside `artigo`, one per inciso.

    `None` when the inciso range is unreadable (reversed or too wide).
    """
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
        return None
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


_VALUES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}


def _is_roman(s: str) -> bool:
    return bool(re.fullmatch(r"[IVXLCDM]+", s)) and _roman(s) > 0


def _roman(s: str) -> int:
    """The value of a roman numeral, or 0 when `s` is not a well-formed one."""
    total = 0
    for symbol, following in zip(s, [*s[1:], ""], strict=True):
        value = _VALUES[symbol]
        total += -value if following and _VALUES[following] > value else value
    return total if total > 0 and _to_roman(total) == s else 0


def _snippet(text: str, start: int) -> str:
    return text[start : start + _SNIPPET].strip()
