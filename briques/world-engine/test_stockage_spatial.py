"""Tests du stockage SQLite du maillage spatial (mondes/cellules/placements) —
Sprint B. Même motif que test_stockage.py (DB temporaire posée par conftest.py)."""
import stockage
import stockage_spatial


def _cellules_factices(n=3):
    return [{"cellule_id": i, "x": float(i) * 10, "y": float(i) * 5, "biome": "plaine",
             "ressources": ["ble"], "voisins": [j for j in range(n) if j != i]}
            for i in range(n)]


def test_creer_monde_puis_lire():
    meta = stockage_spatial.creer_monde("cle-a", _cellules_factices(3), seed=42)
    assert isinstance(meta["id"], str) and meta["id"]
    assert meta["nb_cellules"] == 3
    assert meta["seed"] == 42
    assert meta["forked_from_id"] is None

    monde = stockage_spatial.lire_monde("cle-a", meta["id"])
    assert monde["id"] == meta["id"]
    assert len(monde["cellules"]) == 3
    assert monde["cellules"][0]["biome"] == "plaine"
    assert monde["cellules"][0]["ressources"] == ["ble"]
    assert monde["cellules"][0]["enfants"] == []


def test_lire_monde_introuvable_renvoie_none():
    assert stockage_spatial.lire_monde("cle-a", "id-inconnu") is None


def test_lire_monde_cloisonne_par_cle_api():
    meta = stockage_spatial.creer_monde("cle-b", _cellules_factices(3), seed=1)
    assert stockage_spatial.lire_monde("cle-b", meta["id"]) is not None
    assert stockage_spatial.lire_monde("autre-cle", meta["id"]) is None


def test_lister_mondes_cloisonne_et_ordonne():
    stockage_spatial.creer_monde("cle-c", _cellules_factices(3), seed=1)
    m2 = stockage_spatial.creer_monde("cle-c", _cellules_factices(3), seed=2)
    resultats = stockage_spatial.lister_mondes("cle-c")
    assert resultats[0]["id"] == m2["id"]  # plus récent d'abord
    assert "cellules" not in resultats[0]  # liste allégée
    assert stockage_spatial.lister_mondes("cle-vide") == []


def test_monde_existe():
    meta = stockage_spatial.creer_monde("cle-d", _cellules_factices(3), seed=1)
    assert stockage_spatial.monde_existe("cle-d", meta["id"]) is True
    assert stockage_spatial.monde_existe("autre-cle", meta["id"]) is False
    assert stockage_spatial.monde_existe("cle-d", "id-inconnu") is False


def test_lire_cellule():
    meta = stockage_spatial.creer_monde("cle-e", _cellules_factices(3), seed=1)
    cellule = stockage_spatial.lire_cellule("cle-e", meta["id"], 1)
    assert cellule["cellule_id"] == 1
    assert cellule["voisins"] == [0, 2]
    assert stockage_spatial.lire_cellule("cle-e", meta["id"], 99) is None
    assert stockage_spatial.lire_cellule("autre-cle", meta["id"], 1) is None


def test_voisins_cellule():
    meta = stockage_spatial.creer_monde("cle-f", _cellules_factices(3), seed=1)
    assert stockage_spatial.voisins_cellule(meta["id"], 0) == [1, 2]
    assert stockage_spatial.voisins_cellule(meta["id"], 99) is None


def test_nb_cellules_monde():
    meta = stockage_spatial.creer_monde("cle-g", _cellules_factices(5), seed=1)
    assert stockage_spatial.nb_cellules_monde(meta["id"]) == 5
    assert stockage_spatial.nb_cellules_monde("id-inconnu") is None


def test_placer_et_lire_avec_enfants():
    meta = stockage_spatial.creer_monde("cle-h", _cellules_factices(3), seed=1)
    eid = stockage.creer("cle-h", "Nova", "Test", None, None,
                          {"theme_complet": {}}, "d", {"resume": {}}, False)
    stockage_spatial.placer(meta["id"], eid, 1)
    assert stockage_spatial.placement_cellule(meta["id"], eid) == 1

    monde = stockage_spatial.lire_monde("cle-h", meta["id"])
    cellule_1 = next(c for c in monde["cellules"] if c["cellule_id"] == 1)
    assert cellule_1["enfants"] == [{"id": eid, "prenoms": "Nova", "nom": "Test"}]

    cellule = stockage_spatial.lire_cellule("cle-h", meta["id"], 1)
    assert cellule["enfants"] == [{"id": eid, "prenoms": "Nova", "nom": "Test"}]


def test_placement_cellule_absent_renvoie_none():
    meta = stockage_spatial.creer_monde("cle-i", _cellules_factices(3), seed=1)
    assert stockage_spatial.placement_cellule(meta["id"], "enfant-inconnu") is None


def test_placer_remplace_le_placement_precedent():
    meta = stockage_spatial.creer_monde("cle-j", _cellules_factices(3), seed=1)
    eid = stockage.creer("cle-j", "Nova", "", None, None,
                          {"theme_complet": {}}, "d", {"resume": {}}, False)
    stockage_spatial.placer(meta["id"], eid, 0)
    stockage_spatial.placer(meta["id"], eid, 2)
    assert stockage_spatial.placement_cellule(meta["id"], eid) == 2


def test_forker_monde_copie_cellules_et_placements():
    meta = stockage_spatial.creer_monde("cle-k", _cellules_factices(3), seed=1)
    eid = stockage.creer("cle-k", "Nova", "", None, None,
                          {"theme_complet": {}}, "d", {"resume": {}}, False)
    stockage_spatial.placer(meta["id"], eid, 1)

    fork = stockage_spatial.forker_monde("cle-k", meta["id"])
    assert fork["forked_from_id"] == meta["id"]
    assert fork["id"] != meta["id"]
    assert fork["nb_cellules"] == 3
    assert fork["seed"] == 1
    assert stockage_spatial.placement_cellule(fork["id"], eid) == 1

    monde_fork = stockage_spatial.lire_monde("cle-k", fork["id"])
    assert len(monde_fork["cellules"]) == 3


def test_forker_monde_independant_de_loriginal():
    meta = stockage_spatial.creer_monde("cle-l", _cellules_factices(3), seed=1)
    fork = stockage_spatial.forker_monde("cle-l", meta["id"])
    eid = stockage.creer("cle-l", "Nouveau", "", None, None,
                          {"theme_complet": {}}, "d", {"resume": {}}, False)
    stockage_spatial.placer(fork["id"], eid, 0)  # placement APRÈS le fork, sur le fork seul
    assert stockage_spatial.placement_cellule(fork["id"], eid) == 0
    assert stockage_spatial.placement_cellule(meta["id"], eid) is None  # jamais propagé à l'original


def test_forker_monde_introuvable_renvoie_none():
    assert stockage_spatial.forker_monde("cle-m", "id-inconnu") is None


def test_supprimer_monde_cascade():
    meta = stockage_spatial.creer_monde("cle-n", _cellules_factices(3), seed=1)
    eid = stockage.creer("cle-n", "Nova", "", None, None,
                          {"theme_complet": {}}, "d", {"resume": {}}, False)
    stockage_spatial.placer(meta["id"], eid, 0)

    assert stockage_spatial.supprimer_monde("cle-n", meta["id"]) is True
    assert stockage_spatial.lire_monde("cle-n", meta["id"]) is None
    assert stockage_spatial.voisins_cellule(meta["id"], 0) is None
    assert stockage_spatial.placement_cellule(meta["id"], eid) is None


def test_supprimer_monde_introuvable_renvoie_false():
    assert stockage_spatial.supprimer_monde("cle-n", "id-inconnu") is False


def test_supprimer_monde_cloisonne_par_cle_api():
    meta = stockage_spatial.creer_monde("cle-o", _cellules_factices(3), seed=1)
    assert stockage_spatial.supprimer_monde("autre-cle", meta["id"]) is False
    assert stockage_spatial.lire_monde("cle-o", meta["id"]) is not None
