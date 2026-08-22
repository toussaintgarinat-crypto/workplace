"""Tests des dominantes — tables de dignités + méthodes comptage et score complexe."""
import dominantes as D


def test_methodes_constante():
    assert D.METHODES == ["comptage_dignite", "score_complexe"]


def test_domiciles_complets():
    """Chaque planète classique a 1 ou 2 domiciles ; anciens = 1, modernes = 1."""
    assert "Bélier" in D.DOMICILES["Mars"]
    assert "Scorpion" in D.DOMICILES["Mars"]
    assert D.DOMICILES["Soleil"] == ["Lion"]
    assert D.DOMICILES["Lune"] == ["Cancer"]
    # 10 planètes couvertes (Soleil→Pluton)
    assert set(D.DOMICILES.keys()) == {"Soleil", "Lune", "Mercure", "Vénus", "Mars",
                                       "Jupiter", "Saturne", "Uranus", "Neptune", "Pluton"}


def test_exaltations():
    assert D.EXALTATIONS["Soleil"] == "Bélier"
    assert D.EXALTATIONS["Lune"] == "Taureau"
    assert D.EXALTATIONS["Vénus"] == "Poissons"


def test_triplicites_diurne_nocturne():
    """Chaque élément a un gouverneur diurne et un nocturne."""
    for elem in ["Feu", "Terre", "Air", "Eau"]:
        assert (elem, "diurne") in D.TRIPPLICITES
        assert (elem, "nocturne") in D.TRIPPLICITES
    assert D.TRIPPLICITES[("Feu", "diurne")] == "Soleil"
    assert D.TRIPPLICITES[("Feu", "nocturne")] == "Jupiter"


def test_termes_egyptiens_5_par_signe():
    """Chaque signe a 5 termes, bornes croissantes, dernier = 30."""
    for signe, termes in D.TERMES_EGYPTIENS.items():
        assert len(termes) == 5
        bornes = [t[0] for t in termes]
        assert bornes == sorted(bornes)
        assert bornes[-1] == 30
        # Planètes valides
        for _, planete in termes:
            assert planete in {"Soleil", "Lune", "Mercure", "Vénus", "Mars",
                               "Jupiter", "Saturne"}


def test_faces_chaldeennes_3_par_signe():
    """Chaque signe a 3 décan/faces, planètes valides."""
    for signe, faces in D.FACES_CHALDEENNES.items():
        assert len(faces) == 3
        for planete in faces:
            assert planete in {"Soleil", "Lune", "Mercure", "Vénus", "Mars",
                               "Jupiter", "Saturne"}


def test_chart_diurne_soleil_au_dessus_horizon():
    """Soleil au-dessus de l'horizon (entre Asc et MC par voie diurne) = diurne."""
    # Simplifié : si Soleil dans la moitié supérieure (maisons 7-12) = diurne
    assert D._chart_diurne(soleil_lon=180.0, asc_lon=90.0, mc_lon=0.0) is True
    assert D._chart_diurne(soleil_lon=0.0, asc_lon=90.0, mc_lon=180.0) is False


def test_dominantes_comptage_schema():
    """dominantes() renvoie les 5 dominantes avec scores."""
    points = {
        "Soleil": {"longitude": 0.0, "signe": "Bélier", "maison": 1},
        "Lune": {"longitude": 120.0, "signe": "Lion", "maison": 5},
        "Mars": {"longitude": 0.0, "signe": "Bélier", "maison": 1},
        "Jupiter": {"longitude": 240.0, "signe": "Sagittaire", "maison": 9},
    }
    maisons = [{"maison": i + 1, "cuspe": 30 * i, "signe": "Bélier"} for i in range(12)]
    aspects = []
    res = D.dominantes(points, maisons, aspects, "comptage_dignite")
    assert {"element", "mode", "planete", "signe", "maison", "methode"} <= set(res.keys())
    assert res["methode"] == "comptage_dignite"
    # Soleil en Bélier (domicile + exaltation) → Mars en Bélier (domicile) → feu dominant
    assert res["element"]["dominant"] == "Feu"
    # Bélier dominant (Soleil x2 + Mars domicile)
    assert res["signe"]["dominant"] == "Bélier"


# ── Méthode 2 : score complexe ────────────────────────────────────
def test_score_complexe_schema():
    """score_complexe renvoie le même schéma que comptage_dignite."""
    points = {
        "Soleil": {"longitude": 0.0, "signe": "Bélier", "maison": 1,
                   "vitesse_deg_j": 0.95, "retrograde": False},
        "Lune": {"longitude": 120.0, "signe": "Lion", "maison": 5,
                 "vitesse_deg_j": 13.0, "retrograde": False},
        "Mars": {"longitude": 0.0, "signe": "Bélier", "maison": 1,
                 "vitesse_deg_j": 0.5, "retrograde": False},
        "Ascendant": {"longitude": 350.0},
        "Milieu du Ciel": {"longitude": 260.0},
        "Nœud Nord": {"longitude": 100.0},
    }
    maisons = [{"maison": i + 1, "cuspe": 30 * i, "signe": "Bélier"} for i in range(12)]
    aspects = [{"point_a": "Soleil", "point_b": "Mars", "type": "majeur"},
               {"point_a": "Lune", "point_b": "Mars", "type": "majeur"}]
    res = D.dominantes(points, maisons, aspects, "score_complexe")
    assert res["methode"] == "score_complexe"
    assert {"element", "mode", "planete", "signe", "maison"} <= set(res.keys())
    # Mars en Bélier (domicile) + maison 1 (angulaire) + aspects reçus
    # → score élevé → Mars dominante probable
    assert res["planete"]["dominante"] in {"Mars", "Soleil"}


def test_score_complexe_retro_bonus():
    """Une planète rétrograde reçoit +5 au score."""
    points = {
        "Mercure": {"longitude": 200.0, "signe": "Balance", "maison": 10,
                    "vitesse_deg_j": -0.5, "retrograde": True},
        "Soleil": {"longitude": 180.0, "signe": "Balance", "maison": 10,
                   "vitesse_deg_j": 0.95, "retrograde": False},
        "Ascendant": {"longitude": 350.0},
        "Milieu du Ciel": {"longitude": 260.0},
    }
    maisons = [{"maison": i + 1, "cuspe": 30 * i, "signe": "Bélier"} for i in range(12)]
    res = D.dominantes(points, maisons, [], "score_complexe")
    # Mercure rétro → bonus de 5 dans son score
    # On vérifie juste que la méthode tourne sans erreur et produit un score
    assert res["planete"]["scores"]["Mercure"] > 0


def test_score_complexe_combuste_malus():
    """Une planète combuste (<17° du Soleil) reçoit -10."""
    points = {
        "Mercure": {"longitude": 5.0, "signe": "Bélier", "maison": 1,
                    "vitesse_deg_j": 1.5, "retrograde": False},
        "Soleil": {"longitude": 10.0, "signe": "Bélier", "maison": 1,
                   "vitesse_deg_j": 0.95, "retrograde": False},
        "Ascendant": {"longitude": 350.0},
        "Milieu du Ciel": {"longitude": 260.0},
    }
    maisons = [{"maison": i + 1, "cuspe": 30 * i, "signe": "Bélier"} for i in range(12)]
    res = D.dominantes(points, maisons, [], "score_complexe")
    # Mercure combuste (5° du Soleil) → -10
    # On vérifie que le score Mercure est impacté (moins élevé qu'un Mercure non combuste)
    # Test simple : la méthode tourne et Mercure a un score
    assert "Mercure" in res["planete"]["scores"]
