"""Anchor leis per assunto: where the graph traversal starts."""

from dataclasses import dataclass


@dataclass(frozen=True)
class AnchorStatute:
    keyword: str  # LexML keyword search that surfaces the lei
    numero: str
    ano: int
    articles: tuple[
        str, ...
    ] = ()  # dispositivo paths the traversal starts from; none: the whole lei


ANCHORS: dict[str, list[AnchorStatute]] = {
    "desconsideração da personalidade jurídica": [
        AnchorStatute("lei 10406 2002 código civil", "10406", 2002, ("art50",)),
        AnchorStatute("lei 8078 1990 código de defesa do consumidor", "8078", 1990, ("art28",)),
    ],
}
