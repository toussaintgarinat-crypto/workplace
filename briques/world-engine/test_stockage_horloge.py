"""Tests du stockage SQLite de l'horloge (tables horloges/couples) — Sprint C.
Même motif que test_stockage_spatial.py (DB temporaire posée par conftest.py)."""
import stockage_horloge
import stockage_spatial


def _cellules_factices(n=3):
    return [{"cellule_id": i, "x": float(i) * 10, "y": float(i) * 5, "biome": "plaine",
             "ressources": ["ble"], "voisins": [j for j in range(n) if j != i]}
            for i in range(n)]


def test_initialiser_puis_lire_horloge():
    monde = stockage_spatial.creer_monde("cle-h1", _cellules_factices(), seed=1)
    stockage_horloge.initialiser_horloge(monde["id"])
    etat = stockage_horloge.lire_horloge(monde["id"])
    assert etat == {"monde_id": monde["id"], "tick_actuel": 0, "actif": False,
                     "intervalle_secondes": None, "derniere_execution": None}


def test_lire_horloge_introuvable_renvoie_none():
    assert stockage_horloge.lire_horloge("id-inconnu") is None


def test_demarrer_puis_arreter():
    monde = stockage_spatial.creer_monde("cle-h2", _cellules_factices(), seed=1)
    stockage_horloge.initialiser_horloge(monde["id"])
    stockage_horloge.demarrer(monde["id"], 60)
    etat = stockage_horloge.lire_horloge(monde["id"])
    assert etat["actif"] is True
    assert etat["intervalle_secondes"] == 60
    stockage_horloge.arreter(monde["id"])
    assert stockage_horloge.lire_horloge(monde["id"])["actif"] is False


def test_marquer_execution_avance_tick_et_horodate():
    monde = stockage_spatial.creer_monde("cle-h3", _cellules_factices(), seed=1)
    stockage_horloge.initialiser_horloge(monde["id"])
    stockage_horloge.marquer_execution(monde["id"], 1)
    etat = stockage_horloge.lire_horloge(monde["id"])
    assert etat["tick_actuel"] == 1
    assert etat["derniere_execution"] is not None


def test_horloges_actives_a_declencher_jamais_executee_est_due():
    monde = stockage_spatial.creer_monde("cle-h4", _cellules_factices(), seed=1)
    stockage_horloge.initialiser_horloge(monde["id"])
    stockage_horloge.demarrer(monde["id"], 60)
    dues = stockage_horloge.horloges_actives_a_declencher("2026-01-01T00:00:00+00:00")
    assert any(d["monde_id"] == monde["id"] and d["cle_api"] == "cle-h4" for d in dues)


def test_horloges_actives_a_declencher_ignore_inactif():
    monde = stockage_spatial.creer_monde("cle-h5", _cellules_factices(), seed=1)
    stockage_horloge.initialiser_horloge(monde["id"])  # actif=0 par défaut
    dues = stockage_horloge.horloges_actives_a_declencher("2026-01-01T00:00:00+00:00")
    assert not any(d["monde_id"] == monde["id"] for d in dues)


def test_horloges_actives_a_declencher_respecte_intervalle():
    from datetime import datetime, timezone
    monde = stockage_spatial.creer_monde("cle-h6", _cellules_factices(), seed=1)
    stockage_horloge.initialiser_horloge(monde["id"])
    stockage_horloge.demarrer(monde["id"], 3600)
    stockage_horloge.marquer_execution(monde["id"], 1)  # derniere_execution = maintenant réel
    juste_apres = datetime.now(timezone.utc).isoformat()  # quelques ms plus tard, très < 3600s
    dues = stockage_horloge.horloges_actives_a_declencher(juste_apres)
    assert not any(d["monde_id"] == monde["id"] for d in dues)  # écart quasi nul < 3600s


def test_copier_pour_fork_reprend_tick_mais_force_inactif():
    monde = stockage_spatial.creer_monde("cle-h7", _cellules_factices(), seed=1)
    stockage_horloge.initialiser_horloge(monde["id"])
    stockage_horloge.demarrer(monde["id"], 60)
    stockage_horloge.marquer_execution(monde["id"], 5)
    fork = stockage_spatial.forker_monde("cle-h7", monde["id"])
    stockage_horloge.copier_pour_fork(monde["id"], fork["id"])
    etat_fork = stockage_horloge.lire_horloge(fork["id"])
    assert etat_fork["tick_actuel"] == 5
    assert etat_fork["actif"] is False


def test_couples_former_lister_dissoudre():
    monde = stockage_spatial.creer_monde("cle-h8", _cellules_factices(), seed=1)
    cid = stockage_horloge.former_couple(monde["id"], 0, "hab-a", "hab-b", tick=1)
    actifs = stockage_horloge.couples_actifs_cellule(monde["id"], 0)
    assert len(actifs) == 1 and actifs[0]["id"] == cid
    stockage_horloge.dissoudre_couple(cid, tick=2)
    assert stockage_horloge.couples_actifs_cellule(monde["id"], 0) == []


def test_copier_pour_fork_duplique_les_couples_actifs():
    monde = stockage_spatial.creer_monde("cle-h9", _cellules_factices(), seed=1)
    stockage_horloge.initialiser_horloge(monde["id"])
    stockage_horloge.former_couple(monde["id"], 0, "hab-a", "hab-b", tick=1)
    fork = stockage_spatial.forker_monde("cle-h9", monde["id"])
    stockage_horloge.copier_pour_fork(monde["id"], fork["id"])
    actifs_fork = stockage_horloge.couples_actifs_cellule(fork["id"], 0)
    assert len(actifs_fork) == 1
    assert actifs_fork[0]["habitant_a_id"] == "hab-a"


def test_supprimer_pour_monde_purge_horloge_et_couples():
    monde = stockage_spatial.creer_monde("cle-h10", _cellules_factices(), seed=1)
    stockage_horloge.initialiser_horloge(monde["id"])
    stockage_horloge.former_couple(monde["id"], 0, "hab-a", "hab-b", tick=1)
    stockage_horloge.supprimer_pour_monde(monde["id"])
    assert stockage_horloge.lire_horloge(monde["id"]) is None
    assert stockage_horloge.couples_actifs_cellule(monde["id"], 0) == []
