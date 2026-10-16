import pytest

from legal_radar.adapters.fixture.parser import parse_lei


def test_parses_artigos_and_paragrafos_with_hierarchy():
    lei, ds = parse_lei("Lei 1 Teste\nArt. 1º Texto.\n§ 1º Sub.\nArt. 2º Outro.")

    assert lei.id == "lei:1"
    assert [(d.id, d.parent_id) for d in ds] == [
        ("lei:1#art1", None),
        ("lei:1#art1_par1", "lei:1#art1"),
        ("lei:1#art2", None),
    ]


def test_rejects_unrecognized_line():
    with pytest.raises(ValueError):
        parse_lei("Lei 1 Teste\nlixo")
