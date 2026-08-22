"""Tests des systèmes de maisons — fonctions pures, cas pivots."""
import maisons as M
import traditions as T


def test_systemes_constante():
    assert M.SYSTEMES == ["whole_sign", "placidus", "equal_house"]


def test_whole_sign_asc_0_egal_a_equal_house():
    """Whole Sign == Equal House quand l'Asc est exactement à 0° d'un signe."""
    asc = 0.0
    ws = M.maisons(asc, 90.0, 45.0, "whole_sign")
    eh = M.maisons(asc, 90.0, 45.0, "equal_house")
    assert len(ws) == 12 and len(eh) == 12
    for i in range(12):
        assert abs(ws[i]["cuspe"] - eh[i]["cuspe"]) < 1e-6


def test_whole_sign_cuspes_multiples_de_30():
    """Whole Sign : cuspes = multiples de 30° à partir du début du signe asc."""
    asc = 12.5  # Asc à 12.5° Bélier
    ws = M.maisons(asc, 90.0, 45.0, "whole_sign")
    assert ws[0]["cuspe"] == 0.0       # début Bélier
    assert ws[1]["cuspe"] == 30.0      # début Taureau
    assert ws[11]["cuspe"] == 330.0


def test_equal_house_cuspes_a_partir_de_asc():
    """Equal House : cuspes = asc + 30*i (exact, pas arrondi au signe)."""
    asc = 12.5
    eh = M.maisons(asc, 90.0, 45.0, "equal_house")
    for i in range(12):
        assert abs(eh[i]["cuspe"] - (asc + 30 * i) % 360) < 1e-6


def test_placidus_cuspes_non_egaux():
    """Placidus : cuspes inégaux (sauf 1=Asc, 4=IC, 7=Desc, 10=MC)."""
    asc = 100.0
    mc = 220.0
    pl = M.maisons(asc, mc, 45.0, "placidus")
    assert len(pl) == 12
    assert abs(pl[0]["cuspe"] - 100.0) < 1e-6   # Asc
    assert abs(pl[6]["cuspe"] - 280.0) < 1e-6   # Desc = Asc + 180
    assert abs(pl[9]["cuspe"] - 220.0) < 1e-6   # MC
    assert abs(pl[3]["cuspe"] - 40.0) < 1e-6    # IC = MC + 180
    # Maison 2 ≠ Asc + 30 (Placidus inégal)
    assert abs(pl[1]["cuspe"] - (100.0 + 30.0)) > 0.1


def test_placidus_repli_au_dessus_de_66_deg():
    """Placidus indéfini au cercle polaire → repli Equal House + raison."""
    asc = 100.0
    mc = 220.0
    pl = M.maisons(asc, mc, 70.0, "placidus")  # 70° > 66°
    eh = M.maisons(asc, mc, 70.0, "equal_house")
    for i in range(12):
        assert abs(pl[i]["cuspe"] - eh[i]["cuspe"]) < 1e-6
    # Chaque maison porte la raison du repli
    assert "raison" in pl[0]
    assert "Equal" in pl[0]["raison"] or "equal" in pl[0]["raison"].lower()


def test_maisons_schema_de_sortie():
    asc = 100.0
    ws = M.maisons(asc, 220.0, 45.0, "whole_sign")
    m = ws[0]
    assert {"maison", "cuspe", "signe", "symbole", "longitude_cuspe", "systeme"} <= set(m.keys())
    assert m["maison"] == 1
    assert m["signe"] in [s[0] for s in T.SIGNES]
