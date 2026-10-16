"""Anchor leis per assunto: where the graph traversal starts."""

from dataclasses import dataclass


@dataclass(frozen=True)
class AnchorLei:
    keyword: str  # LexML keyword search that surfaces the lei
    numero: str
    ano: int
    artigos: tuple[
        str, ...
    ] = ()  # dispositivo paths the traversal starts from; none: the whole lei


ANCHORS: dict[str, list[AnchorLei]] = {
    "desconsideração da personalidade jurídica": [
        AnchorLei("lei 10406 2002 código civil", "10406", 2002, ("art50",)),
        AnchorLei("lei 8078 1990 código de defesa do consumidor", "8078", 1990, ("art28",)),
    ],
}
