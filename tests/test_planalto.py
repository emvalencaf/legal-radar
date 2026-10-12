from pathlib import Path

from legal_radar.planalto import decode_html, parse_planalto

FIXTURES = Path(__file__).parent / "fixtures" / "planalto"
URN = "urn:lex:br:federal:lei:2002-01-10;10406"


def parse(name: str, urn: str = URN):
    return {d.id: d for d in parse_planalto(decode_html((FIXTURES / name).read_bytes()), urn)}


def test_cc_art_50_follows_the_ast_hierarchy():
    ds = parse("l10406_excerpt.htm")

    assert ds[f"{URN}#art50"].parent_id == f"{URN}#parteGeral_livroI_tituloII_capituloI"
    assert ds[f"{URN}#art50_par2"].parent_id == f"{URN}#art50"
    assert ds[f"{URN}#art50_par2_incIII"].parent_id == f"{URN}#art50_par2"
    assert ds[f"{URN}#art50"].text.startswith("Em caso de abuso da personalidade jurídica")
    assert [d.kind for d in ds.values() if d.path.startswith("art50")][:2] == [
        "artigo",
        "paragrafo",
    ]


def test_organizational_levels_nest_and_are_named():
    ds = parse("l10406_excerpt.htm")

    capitulo = ds[f"{URN}#parteGeral_livroI_tituloII_capituloI"]
    assert capitulo.kind == "capitulo"
    assert capitulo.text == "Disposições Gerais"
    assert capitulo.parent_id == f"{URN}#parteGeral_livroI_tituloII"


def test_struck_through_superseded_text_is_dropped():
    ds = parse("l10406_excerpt.htm")

    art50 = ds[f"{URN}#art50"].text
    assert "desconsiderá-la" in art50
    assert "pode o juiz decidir" not in art50


def test_letter_suffixed_artigo_and_paragrafo_unico():
    ds = parse("l10406_excerpt.htm")

    assert f"{URN}#art48A" in ds
    assert ds[f"{URN}#art49A_parUnico"].parent_id == f"{URN}#art49A"


def test_cdc_art_28_under_its_secao():
    urn = "urn:lex:br:federal:lei:1990-09-11;8078"
    ds = parse("l8078_excerpt.htm", urn)

    assert ds[f"{urn}#art28"].parent_id == f"{urn}#tituloI_capituloIV_secaoV"
    assert ds[f"{urn}#art28_par2"].parent_id == f"{urn}#art28"
    assert ds[f"{urn}#art1"].text.startswith("O presente código")


def test_ids_are_deterministic_and_unique():
    first = parse_planalto(decode_html((FIXTURES / "l10406_excerpt.htm").read_bytes()), URN)
    second = parse_planalto(decode_html((FIXTURES / "l10406_excerpt.htm").read_bytes()), URN)

    assert first == second
    assert len({d.id for d in first}) == len(first)


def test_incisos_and_alineas_nest_under_the_closest_parent():
    html = "<p>Art. 1º Caput:</p><p>I - um:</p><p>a) alfa;</p><p>b) beta.</p><p>II - dois.</p>"
    ds = {d.path: d for d in parse_planalto(html, "u")}

    assert ds["art1_incI_aliA".replace("A", "a")].parent_id == "u#art1_incI"
    assert ds["art1_incII"].parent_id == "u#art1"
    assert ds["art1_incI_alib"].text == "beta."


def test_fully_revoked_inciso_is_kept_with_its_marks_moved_out_of_the_text():
    ds = parse("l10406_excerpt.htm")

    inciso = ds[f"{URN}#art44_incVI"]
    assert inciso.revoked
    assert inciso.text.startswith("as empresas individuais de responsabilidade limitada.")
    assert "Revogado" not in inciso.text
    assert inciso.revocations == (
        "(Revogado pela Lei nº 14.382, de 2022)",
        "(Revogado Pela Medida Provisória nº 1.085, de 2021)",
    )


def test_marks_belong_to_the_dispositivo_that_carries_them_and_others_stay_live():
    ds = parse("l10406_excerpt.htm")

    assert ds[f"{URN}#art44_incV"].revocations == () and not ds[f"{URN}#art44_incV"].revoked
    assert not ds[f"{URN}#art44_incVII"].revoked
    assert ds[f"{URN}#art44_incVII"].text.startswith("os empreendimentos")


def test_unstruck_revogado_mark_marks_the_dispositivo():
    html = "<p>Art. 5º Texto antigo.</p><p>Art. 6º (Revogado pela Lei nº 1.234, de 2010)</p>"

    ds = {d.path: d for d in parse_planalto(html, URN)}

    assert ds["art6"].revoked and ds["art6"].text == ""
    assert ds["art6"].revocations == ("(Revogado pela Lei nº 1.234, de 2010)",)
    assert not ds["art5"].revoked
