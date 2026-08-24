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


def test_detacher_pays_retire_le_pays_et_ses_adjacences():
    f = stockage_federation.creer_federation("cle-a", "F1")
    m1 = stockage_spatial.creer_monde("cle-a", _cellules(2), seed=1)
    m2 = stockage_spatial.creer_monde("cle-a", _cellules(2), seed=2)
    stockage_federation.rattacher_pays(f["id"], m1["id"], "cle-a", None)
    stockage_federation.rattacher_pays(f["id"], m2["id"], "cle-a", None)
    stockage_federation.declarer_adjacence(f["id"], m1["id"], m2["id"])

    assert stockage_federation.detacher_pays(f["id"], m1["id"], "cle-a") is True

    lu = stockage_federation.lire_federation(f["id"])
    assert [p["monde_id"] for p in lu["pays"]] == [m2["id"]]
    assert lu["adjacences"] == []  # l'adjacence impliquant m1 a disparu avec lui


def test_detacher_pays_mauvaise_cle_api_renvoie_false():
    f = stockage_federation.creer_federation("cle-a", "F1")
    m1 = stockage_spatial.creer_monde("cle-a", _cellules(2), seed=1)
    stockage_federation.rattacher_pays(f["id"], m1["id"], "cle-a", None)
    assert stockage_federation.detacher_pays(f["id"], m1["id"], "cle-autre") is False
    # toujours membre : la mauvaise cle_api n'a rien retiré
    assert [p["monde_id"] for p in stockage_federation.lire_federation(f["id"])["pays"]] == [m1["id"]]


def test_membre_vrai_si_cle_api_possede_un_pays():
    f = stockage_federation.creer_federation("cle-createur", "F1")
    m1 = stockage_spatial.creer_monde("cle-membre", _cellules(2), seed=1)
    stockage_federation.rattacher_pays(f["id"], m1["id"], "cle-membre", None)
    assert stockage_federation.membre(f["id"], "cle-membre") is True
    # le créateur seul (sans pays à lui) n'est PAS "membre" au sens de cette fonction
    assert stockage_federation.membre(f["id"], "cle-createur") is False


def test_declarer_adjacence_normalisee():
    f = stockage_federation.creer_federation("cle-a", "F1")
    m1 = stockage_spatial.creer_monde("cle-a", _cellules(2), seed=1)
    m2 = stockage_spatial.creer_monde("cle-a", _cellules(2), seed=2)
    stockage_federation.rattacher_pays(f["id"], m1["id"], "cle-a", None)
    stockage_federation.rattacher_pays(f["id"], m2["id"], "cle-a", None)

    a, b = sorted([m1["id"], m2["id"]])
    resultat = stockage_federation.declarer_adjacence(f["id"], m2["id"], m1["id"])  # ordre inversé
    assert (resultat["monde_id_a"], resultat["monde_id_b"]) == (a, b)

    lu = stockage_federation.lire_federation(f["id"])
    assert lu["adjacences"] == [{"monde_id_a": a, "monde_id_b": b}]


def test_declarer_adjacence_pays_non_membre_renvoie_none():
    f = stockage_federation.creer_federation("cle-a", "F1")
    m1 = stockage_spatial.creer_monde("cle-a", _cellules(2), seed=1)
    m2 = stockage_spatial.creer_monde("cle-a", _cellules(2), seed=2)
    stockage_federation.rattacher_pays(f["id"], m1["id"], "cle-a", None)
    # m2 n'a jamais été rattaché à f
    assert stockage_federation.declarer_adjacence(f["id"], m1["id"], m2["id"]) is None


def test_pays_adjacents_union_de_plusieurs_federations():
    f1 = stockage_federation.creer_federation("cle-a", "F1")
    f2 = stockage_federation.creer_federation("cle-a", "F2")
    m1 = stockage_spatial.creer_monde("cle-a", _cellules(2), seed=1)
    m2 = stockage_spatial.creer_monde("cle-a", _cellules(2), seed=2)
    m3 = stockage_spatial.creer_monde("cle-a", _cellules(2), seed=3)
    for f in (f1, f2):
        stockage_federation.rattacher_pays(f["id"], m1["id"], "cle-a", None)
    stockage_federation.rattacher_pays(f1["id"], m2["id"], "cle-a", None)
    stockage_federation.rattacher_pays(f2["id"], m3["id"], "cle-a", None)
    stockage_federation.declarer_adjacence(f1["id"], m1["id"], m2["id"])
    stockage_federation.declarer_adjacence(f2["id"], m1["id"], m3["id"])

    assert stockage_federation.pays_adjacents(m1["id"]) == sorted([m2["id"], m3["id"]])
    assert stockage_federation.pays_adjacents(m2["id"]) == [m1["id"]]


def test_pays_adjacents_aucune_federation_renvoie_liste_vide():
    m1 = stockage_spatial.creer_monde("cle-a", _cellules(2), seed=1)
    assert stockage_federation.pays_adjacents(m1["id"]) == []


def test_supprimer_federation_ne_touche_jamais_les_mondes():
    f = stockage_federation.creer_federation("cle-a", "F1")
    m1 = stockage_spatial.creer_monde("cle-a", _cellules(2), seed=1)
    stockage_federation.rattacher_pays(f["id"], m1["id"], "cle-a", None)

    assert stockage_federation.supprimer_federation("cle-a", f["id"]) is True
    assert stockage_federation.lire_federation(f["id"]) is None
    # le monde sous-jacent existe toujours
    assert stockage_spatial.monde_existe("cle-a", m1["id"]) is True


def test_supprimer_federation_mauvaise_cle_api_renvoie_false():
    f = stockage_federation.creer_federation("cle-a", "F1")
    assert stockage_federation.supprimer_federation("cle-autre", f["id"]) is False
    assert stockage_federation.lire_federation(f["id"]) is not None


def test_population_vivante_federation_agrege_par_pays():
    import stockage
    f = stockage_federation.creer_federation("cle-a", "F1")
    m1 = stockage_spatial.creer_monde("cle-a", _cellules(2), seed=1)
    m2 = stockage_spatial.creer_monde("cle-a", _cellules(2), seed=2)
    stockage_federation.rattacher_pays(f["id"], m1["id"], "cle-a", None)
    stockage_federation.rattacher_pays(f["id"], m2["id"], "cle-a", None)
    e1 = stockage.creer("cle-a", "A", "X", None, None, {}, "d", {}, False, sexe="F")
    e2 = stockage.creer("cle-a", "B", "X", None, None, {}, "d", {}, False, sexe="M")
    stockage_spatial.placer(m1["id"], e1, 0)
    stockage_spatial.placer(m2["id"], e2, 0)

    etat = stockage_federation.population_vivante_federation(f["id"])
    assert etat["population_totale"] == 2
    assert {p["monde_id"]: p["population_vivante"] for p in etat["pays"]} == {
        m1["id"]: 1, m2["id"]: 1}


def test_population_vivante_federation_introuvable_renvoie_none():
    assert stockage_federation.population_vivante_federation("id-inconnu") is None


def _cellules(n=2):
    return [{"cellule_id": i, "x": float(i) * 10, "y": 0.0, "biome": "plaine",
             "ressources": ["ble"], "voisins": [j for j in range(n) if j != i]}
            for i in range(n)]
