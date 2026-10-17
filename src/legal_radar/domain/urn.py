"""LexML identity values: the federal-lei URN pattern, the lookup error and the URN page."""

import re
from dataclasses import dataclass

FEDERAL_STATUTE = re.compile(r"^urn:lex:br:federal:lei:(\d{4})-\d{2}-\d{2};(\d+)$")


class LexmlError(Exception):
    pass


@dataclass(frozen=True)
class UrnPage:
    urn: str
    title: str
    planalto_url: str | None
    destinations: list[str]  # hosts the "Texto Atualizado" links point to, for the report
