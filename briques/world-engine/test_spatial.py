"""Tests de la génération procédurale du maillage spatial (spatial.py) — fonctions
pures et déterministes, aucune dépendance SQLite/FastAPI."""
import spatial


def test_determiner_biome_couvre_les_8_biomes():
    cas = [
        (-0.5, 0.0, "ocean"),
        (-0.1, 0.5, "marais"),
        (-0.1, 0.0, "plaine"),
        (0.2, -0.4, "desert"),
        (0.2, 0.0, "plaine"),
        (0.2, 0.5, "foret"),
        (0.5, -0.2, "toundra"),
        (0.5, 0.2, "colline"),
        (0.8, 0.0, "montagne"),
    ]
    for altitude, humidite, attendu in cas:
        assert spatial.determiner_biome(altitude, humidite) == attendu


def test_generer_monde_produit_le_bon_nombre_de_cellules():
    cellules = spatial.generer_monde(nb_cellules=20, seed=42)
    assert len(cellules) == 20
    assert {c["cellule_id"] for c in cellules} == set(range(20))


def test_generer_monde_cellules_dans_la_bounding_box():
    cellules = spatial.generer_monde(nb_cellules=30, seed=1)
    for c in cellules:
        assert 0.0 <= c["x"] <= spatial.TAILLE_MONDE
        assert 0.0 <= c["y"] <= spatial.TAILLE_MONDE


def test_generer_monde_voisinage_symetrique():
    cellules = spatial.generer_monde(nb_cellules=25, seed=7)
    par_id = {c["cellule_id"]: c for c in cellules}
    for c in cellules:
        for v in c["voisins"]:
            assert c["cellule_id"] in par_id[v]["voisins"], (
                f"{c['cellule_id']} voisin de {v} mais pas réciproque")


def test_generer_monde_pas_de_cellule_orpheline_sauf_cas_degenere():
    cellules = spatial.generer_monde(nb_cellules=25, seed=7)
    assert all(len(c["voisins"]) > 0 for c in cellules)
    # Sous le seuil Qhull (< 4 points), repli explicite sans voisin, sans exception.
    petit = spatial.generer_monde(nb_cellules=2, seed=7)
    assert all(c["voisins"] == [] for c in petit)


def test_generer_monde_deterministe_meme_seed():
    a = spatial.generer_monde(nb_cellules=15, seed=99)
    b = spatial.generer_monde(nb_cellules=15, seed=99)
    assert a == b


def test_generer_monde_seeds_differents_divergent():
    a = spatial.generer_monde(nb_cellules=15, seed=1)
    b = spatial.generer_monde(nb_cellules=15, seed=2)
    assert a != b


def test_ressources_toujours_valides_pour_leur_biome():
    cellules = spatial.generer_monde(nb_cellules=40, seed=3)
    for c in cellules:
        pool = spatial.RESSOURCES_PAR_BIOME[c["biome"]]
        assert all(r in pool for r in c["ressources"])
        assert len(c["ressources"]) <= 2
        assert len(c["ressources"]) == len(set(c["ressources"]))  # jamais de doublon
