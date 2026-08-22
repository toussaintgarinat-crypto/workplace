"""Tests des aspects — fonctions pures, cas pivots."""
import aspects as A


def test_aspects_constante():
    assert "conjonction" in A.ASPECTS
    assert A.ASPECTS["trigone"]["angle"] == 120
    assert A.ASPECTS["trigone"]["type"] == "majeur"
    assert A.ASPECTS["quintile"]["type"] == "mineur"


def test_conjonction_dans_orbe():
    """Soleil à 10°, Jupiter à 11° → conjonction (écart 1° < orbe 10)."""
    points = {"Soleil": {"longitude": 10.0}, "Jupiter": {"longitude": 11.0}}
    res = A.aspects(points)
    assert any(a["aspect"] == "conjonction" and a["point_a"] == "Soleil"
               and a["point_b"] == "Jupiter" for a in res)


def test_pas_daspect_hors_orbe():
    """Soleil à 10°, Jupiter à 50° → écart 40°, aucun aspect (orbe max 10)."""
    points = {"Soleil": {"longitude": 10.0}, "Jupiter": {"longitude": 50.0}}
    res = A.aspects(points)
    assert res == []


def test_pas_de_doublon():
    """A-B présent, B-A absent."""
    points = {"Soleil": {"longitude": 10.0}, "Lune": {"longitude": 70.0}}
    res = A.aspects(points)
    paires = [(a["point_a"], a["point_b"]) for a in res]
    assert ("Soleil", "Lune") in paires or ("Lune", "Soleil") in paires
    # Pas les deux
    assert not (("Soleil", "Lune") in paires and ("Lune", "Soleil") in paires)


def test_pas_dauto_aspect():
    """A-A absent."""
    points = {"Soleil": {"longitude": 10.0}}
    res = A.aspects(points)
    assert res == []


def test_tri_par_exactitude():
    """Aspects triés par exactitude décroissante."""
    points = {"Soleil": {"longitude": 10.0}, "Lune": {"longitude": 70.5},
              "Mars": {"longitude": 130.0}}
    res = A.aspects(points)
    exactitudes = [a["exactitude"] for a in res]
    assert exactitudes == sorted(exactitudes, reverse=True)


def test_orbe_par_type_de_point():
    """Soleil-Lune (luminaires) → orbe 10° ; Asc-Mars (point-planète) → orbe 5°."""
    points = {"Soleil": {"longitude": 0.0}, "Lune": {"longitude": 8.5},
              "Ascendant": {"longitude": 0.0}, "Mars": {"longitude": 4.5}}
    res = A.aspects(points)
    # Soleil-Lune écart 8.5° → dans orbe 10 (conjonction)
    # Asc-Mars écart 4.5° → dans orbe 5 (conjonction, min(luminaire 5, planete 8) → point 5)
    aspects_soleil_lune = [a for a in res if {a["point_a"], a["point_b"]} == {"Soleil", "Lune"}]
    aspects_asc_mars = [a for a in res if {a["point_a"], a["point_b"]} == {"Ascendant", "Mars"}]
    assert len(aspects_soleil_lune) == 1
    assert len(aspects_asc_mars) == 1
    assert aspects_soleil_lune[0]["orbe_max"] == 10
    assert aspects_asc_mars[0]["orbe_max"] == 5


def test_filtrer_par_type():
    points = {"Soleil": {"longitude": 0.0}, "Lune": {"longitude": 120.0},
              "Mars": {"longitude": 30.0}}
    res = A.aspects(points)
    majeurs = A.filtrer_par_type(res, "majeur")
    mineurs = A.filtrer_par_type(res, "mineur")
    tous = A.filtrer_par_type(res, "tous")
    assert all(a["type"] == "majeur" for a in majeurs)
    assert all(a["type"] == "mineur" for a in mineurs)
    assert len(tous) == len(res)


def test_aspects_normalisation_360():
    """Soleil à 350°, Jupiter à 10° → écart 20° (pas 340°) → pas de conjonction."""
    points = {"Soleil": {"longitude": 350.0}, "Jupiter": {"longitude": 10.0}}
    res = A.aspects(points)
    # Écart réel = 20°, orbe conjonction = 10° → hors orbe
    conjonctions = [a for a in res if a["aspect"] == "conjonction"]
    assert conjonctions == []


def test_schema_de_sortie():
    points = {"Soleil": {"longitude": 0.0}, "Jupiter": {"longitude": 120.3}}
    res = A.aspects(points)
    a = res[0]
    assert {"aspect", "type", "point_a", "point_b", "angle_exact",
            "angle_reel", "orb", "orbe_max", "exactitude"} <= set(a.keys())
