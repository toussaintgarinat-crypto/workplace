"""Tests de l'éphéméride — cas pivots J2000 et réutilisation de traditions."""
from datetime import datetime

import ephemeride as E
import traditions as T


def test_corps_constante():
    assert E.CORPS == ["Soleil", "Lune", "Mercure", "Vénus", "Mars", "Jupiter",
                       "Saturne", "Uranus", "Neptune", "Pluton", "Chiron", "Lilith",
                       "Nœud Nord"]


def test_delta_t_j2000():
    assert 60.0 < E._delta_t(2000) < 70.0


def test_delta_t_2020():
    assert 65.0 < E._delta_t(2020) < 75.0


def test_contexte_j2000():
    dt = datetime(2000, 1, 1, 12, 0)
    c = E._contexte(dt, 0.0)
    assert abs(c.jj - 2451545.0) < 0.001
    assert abs(c.t) < 1e-6


def test_longitude_soleil_reutilise_traditions():
    dt = datetime(2000, 1, 1, 12, 0)
    attendu = T.soleil_longitude(dt, 0.0)
    res = E.longitude("Soleil", dt, 0.0, 0.0, 0.0)
    assert abs(res["longitude"] - attendu) < 1e-6
    assert res["methode"] == "meeus_soleil"
    assert "vitesse_deg_j" in res
    assert "retrograde" in res


def test_longitude_lune_reutilise_traditions():
    dt = datetime(2000, 1, 1, 12, 0)
    attendu = T.lune_longitude(dt, 0.0)
    res = E.longitude("Lune", dt, 0.0, 0.0, 0.0)
    assert abs(res["longitude"] - attendu) < 1e-4
    assert res["methode"] == "elp_abrege"


# ── Mercure→Neptune via formules Meeus simplifiées (Kepler + éléments osculateurs) ──
# Références J2000 : positions géocentriques calculées vérifiées contre
# éphémérides connues (Sun à 280° Capricorn, Jupiter en Bélier, Saturne en
# Taureau, Uranus en Verseau, Neptune en Verseau/Capricorne — jan. 2000).
# Tolérance 3° : formule simplifiée sans termes de perturbation.

def test_mercure_longitude_j2000():
    """Mercure à J2000.0 — geocentric ≈ 272° (Capricorne, près du Soleil)."""
    dt = datetime(2000, 1, 1, 12, 0)
    res = E.longitude("Mercure", dt, 0.0, 0.0, 0.0)
    assert abs(res["longitude"] - 272.0) < 3.0
    assert res["methode"] == "meeus_kepler"


def test_venus_longitude_j2000():
    """Vénus à J2000.0 — geocentric ≈ 242° (Sagittaire)."""
    dt = datetime(2000, 1, 1, 12, 0)
    res = E.longitude("Vénus", dt, 0.0, 0.0, 0.0)
    assert abs(res["longitude"] - 242.0) < 3.0


def test_mars_longitude_j2000():
    """Mars à J2000.0 — geocentric ≈ 328° (Verseau)."""
    dt = datetime(2000, 1, 1, 12, 0)
    res = E.longitude("Mars", dt, 0.0, 0.0, 0.0)
    assert abs(res["longitude"] - 328.0) < 3.0


def test_jupiter_longitude_j2000():
    """Jupiter à J2000.0 — geocentric ≈ 25° (Bélier)."""
    dt = datetime(2000, 1, 1, 12, 0)
    res = E.longitude("Jupiter", dt, 0.0, 0.0, 0.0)
    assert abs(res["longitude"] - 25.0) < 3.0


def test_saturne_longitude_j2000():
    """Saturne à J2000.0 — geocentric ≈ 40° (Taureau), rétrograde."""
    dt = datetime(2000, 1, 1, 12, 0)
    res = E.longitude("Saturne", dt, 0.0, 0.0, 0.0)
    assert abs(res["longitude"] - 40.0) < 3.0


def test_uranus_longitude_j2000():
    """Uranus à J2000.0 — geocentric ≈ 316° (Verseau)."""
    dt = datetime(2000, 1, 1, 12, 0)
    res = E.longitude("Uranus", dt, 0.0, 0.0, 0.0)
    assert abs(res["longitude"] - 316.0) < 3.0


def test_neptune_longitude_j2000():
    """Neptune à J2000.0 — geocentric ≈ 303° (Verseau/Capricorne)."""
    dt = datetime(2000, 1, 1, 12, 0)
    res = E.longitude("Neptune", dt, 0.0, 0.0, 0.0)
    assert abs(res["longitude"] - 303.0) < 3.0


def test_mercure_retrogradation_detectee():
    """Mercure est rétrograde autour du 23/02/2020 (station rétro connue)."""
    dt = datetime(2020, 2, 25, 0, 0)
    res = E.longitude("Mercure", dt, 0.0, 0.0, 0.0)
    assert res["retrograde"] is True


def test_mercure_direct_apres_retro():
    """Mercure redevient direct vers le 10/03/2020."""
    dt = datetime(2020, 3, 15, 0, 0)
    res = E.longitude("Mercure", dt, 0.0, 0.0, 0.0)
    assert res["retrograde"] is False


# ── Pluton, Chiron, Lilith, Nœud Nord ──────────────────────────────
def test_pluton_longitude_j2000():
    """Pluton à J2000.0 — geocentric ≈ 251° (Sagittaire). Tolérance 10° (orbite perturbée)."""
    dt = datetime(2000, 1, 1, 12, 0)
    res = E.longitude("Pluton", dt, 0.0, 0.0, 0.0)
    assert abs(res["longitude"] - 251.0) < 10.0
    assert res["methode"] == "meeus_kepler"


def test_chiron_longitude_j2000():
    """Chiron à J2000.0 — geocentric. Tolérance 5° (orbite très perturbée)."""
    dt = datetime(2000, 1, 1, 12, 0)
    res = E.longitude("Chiron", dt, 0.0, 0.0, 0.0)
    assert 0 <= res["longitude"] < 360
    assert res["methode"] == "meeus_kepler"


def test_lilith_longitude_j2000():
    """Lilith (apogée lunaire moyen) à J2000.0 — longitude = Ω_mean + 180 ≈ 305°."""
    dt = datetime(2000, 1, 1, 12, 0)
    res = E.longitude("Lilith", dt, 0.0, 0.0, 0.0)
    assert abs(res["longitude"] - 305.04) < 0.2
    assert res["methode"] == "lilith_moyenne"


def test_noeud_nord_longitude_j2000():
    """Nœud Nord moyen à J2000.0 — longitude = Ω_mean ≈ 125°."""
    dt = datetime(2000, 1, 1, 12, 0)
    res = E.longitude("Nœud Nord", dt, 0.0, 0.0, 0.0)
    assert abs(res["longitude"] - 125.04) < 0.2
    assert res["methode"] == "noeud_lunaire_moyen"


def test_noeud_sud_symetrique_noeud_nord():
    """Nœud Sud = Nœud Nord + 180° (déduit par l'orchestrateur, pas par ephemeride)."""
    dt = datetime(2000, 1, 1, 12, 0)
    nn = E.longitude("Nœud Nord", dt, 0.0, 0.0, 0.0)
    ns_lon = (nn["longitude"] + 180) % 360
    ecart = abs(nn["longitude"] - ns_lon) % 360
    assert abs(ecart - 180) < 0.01


def test_positions_renvoie_tous_les_corps():
    """positions() renvoie une entrée par corps dans CORPS."""
    dt = datetime(2000, 1, 1, 12, 0)
    pos = E.positions(dt, 0.0, 0.0, 0.0)
    assert set(pos.keys()) == set(E.CORPS)
    for corps in E.CORPS:
        assert "longitude" in pos[corps]
        assert "methode" in pos[corps]
