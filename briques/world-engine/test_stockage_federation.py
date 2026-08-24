"""Tests du stockage SQLite des fédérations de pays (Sprint D) — même motif que
test_stockage_horloge.py/test_stockage_spatial.py (DB temporaire posée par
conftest.py)."""
import stockage_federation
import stockage_spatial


def test_creer_federation():
    f = stockage_federation.creer_federation("cle-a", "Le Vieux Continent")
    assert f["nom"] == "Le Vieux Continent"
    assert f["createur_cle_api"] == "cle-a"
    assert f["id"]
    assert f["cree_le"]


def test_creer_federation_sans_nom():
    f = stockage_federation.creer_federation("cle-a", None)
    assert f["nom"] is None


def test_rattacher_pays_puis_lire_federation():
    f = stockage_federation.creer_federation("cle-a", "F1")
    monde = stockage_spatial.creer_monde("cle-a", _cellules(2), seed=1)
    resultat = stockage_federation.rattacher_pays(f["id"], monde["id"], "cle-a", "France")
    assert resultat == {"federation_id": f["id"], "monde_id": monde["id"],
                         "nom": "France", "rattache_le": resultat["rattache_le"]}
    lu = stockage_federation.lire_federation(f["id"])
    assert lu["pays"] == [{"monde_id": monde["id"], "nom": "France",
                            "cle_api": "cle-a", "rattache_le": resultat["rattache_le"]}]
    assert lu["adjacences"] == []


def test_rattacher_pays_federation_introuvable_renvoie_none():
    monde = stockage_spatial.creer_monde("cle-a", _cellules(2), seed=1)
    assert stockage_federation.rattacher_pays("id-inconnu", monde["id"], "cle-a", None) is None


def test_lire_federation_introuvable_renvoie_none():
    assert stockage_federation.lire_federation("id-inconnu") is None


def test_lister_federations_createur_et_membre():
    f1 = stockage_federation.creer_federation("cle-createur", "F1")
    f2 = stockage_federation.creer_federation("cle-autre", "F2")
    monde = stockage_spatial.creer_monde("cle-membre", _cellules(2), seed=1)
    stockage_federation.rattacher_pays(f2["id"], monde["id"], "cle-membre", None)
    # cle-createur voit F1 (créatrice) mais pas F2 (ni créatrice ni membre)
    ids_createur = {f["id"] for f in stockage_federation.lister_federations("cle-createur")}
    assert ids_createur == {f1["id"]}
    # cle-membre voit F2 (membre) mais pas F1
    ids_membre = {f["id"] for f in stockage_federation.lister_federations("cle-membre")}
    assert ids_membre == {f2["id"]}


def _cellules(n=2):
    return [{"cellule_id": i, "x": float(i) * 10, "y": 0.0, "biome": "plaine",
             "ressources": ["ble"], "voisins": [j for j in range(n) if j != i]}
            for i in range(n)]
