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
    """La suppression se fait TOUJOURS dans l'ordre de `main.py` :
    `stockage_spatial.supprimer_monde` d'abord, puis cette cascade. L'ordre compte
    depuis le rattrapage paresseux de `lire_horloge` (correctif revue finale) : tant
    que la ligne `mondes` existe, relire l'horloge d'un monde vivant RECRÉE sa ligne
    par défaut — c'est précisément le comportement voulu pour un monde legacy."""
    monde = stockage_spatial.creer_monde("cle-h10", _cellules_factices(), seed=1)
    stockage_horloge.initialiser_horloge(monde["id"])
    stockage_horloge.former_couple(monde["id"], 0, "hab-a", "hab-b", tick=1)
    stockage_spatial.supprimer_monde("cle-h10", monde["id"])
    stockage_horloge.supprimer_pour_monde(monde["id"])
    assert stockage_horloge.lire_horloge(monde["id"]) is None
    assert stockage_horloge.couples_actifs_cellule(monde["id"], 0) == []


# --- Correctifs revue finale Sprint C ---

def test_couples_actifs_monde_groupe_par_cellule_et_ignore_les_dissous():
    """Correctif revue finale (Critical) : accesseur en lot remplaçant N appels à
    `couples_actifs_cellule` (un par cellule) dans `horloge_moteur.executer_tick`."""
    monde = stockage_spatial.creer_monde("cle-h11", _cellules_factices(), seed=1)
    c0 = stockage_horloge.former_couple(monde["id"], 0, "a", "b", tick=1)
    c2 = stockage_horloge.former_couple(monde["id"], 2, "c", "d", tick=1)
    mort = stockage_horloge.former_couple(monde["id"], 2, "e", "f", tick=1)
    stockage_horloge.dissoudre_couple(mort, tick=2)

    par_cellule = stockage_horloge.couples_actifs_monde(monde["id"])
    assert set(par_cellule) == {0, 2}
    assert [c["id"] for c in par_cellule[0]] == [c0]
    assert [c["id"] for c in par_cellule[2]] == [c2]


def test_former_couples_lot_et_dissoudre_couples_en_lot():
    monde = stockage_spatial.creer_monde("cle-h12", _cellules_factices(), seed=1)
    ids = stockage_horloge.former_couples_lot(
        monde["id"], [(0, "a", "b"), (1, "c", "d")], tick=3)
    assert len(ids) == 2
    assert [c["id"] for c in stockage_horloge.couples_actifs_cellule(monde["id"], 0)] == [ids[0]]
    assert [c["id"] for c in stockage_horloge.couples_actifs_cellule(monde["id"], 1)] == [ids[1]]

    stockage_horloge.dissoudre_couples(ids, tick=4)
    assert stockage_horloge.couples_actifs_monde(monde["id"]) == {}


def test_deplacer_couples_habitants_recale_la_cellule_du_couple():
    """Correctif revue finale (Important) : un couple indexé sur la cellule
    d'origine d'un migrant le rendait « célibataire » dans sa cellule d'arrivée,
    donc éligible à un SECOND couple actif simultané."""
    monde = stockage_spatial.creer_monde("cle-h13", _cellules_factices(), seed=1)
    cid = stockage_horloge.former_couple(monde["id"], 0, "hab-a", "hab-b", tick=1)
    stockage_horloge.deplacer_couples_habitants(monde["id"], [("hab-b", 2)])
    assert stockage_horloge.couples_actifs_cellule(monde["id"], 0) == []
    actifs_2 = stockage_horloge.couples_actifs_cellule(monde["id"], 2)
    assert [c["id"] for c in actifs_2] == [cid]


def test_deplacer_couples_habitants_ignore_les_couples_dissous():
    monde = stockage_spatial.creer_monde("cle-h14", _cellules_factices(), seed=1)
    cid = stockage_horloge.former_couple(monde["id"], 0, "hab-a", "hab-b", tick=1)
    stockage_horloge.dissoudre_couple(cid, tick=2)
    stockage_horloge.deplacer_couples_habitants(monde["id"], [("hab-a", 2)])
    assert stockage_horloge.couples_actifs_monde(monde["id"]) == {}


def test_lire_horloge_rattrape_un_monde_sans_ligne_horloges():
    """Correctif revue finale (Important) : un monde antérieur au Sprint C (ou dont
    `initialiser_horloge` a échoué après un `creer_monde` déjà commité) n'a aucune
    ligne `horloges`. `lire_horloge` renvoyait None ⇒ `GET /horloge/{id}` répondait
    `200 null` et `demarrer`/`arreter` faisaient un UPDATE sur zéro ligne."""
    monde = stockage_spatial.creer_monde("cle-h15", _cellules_factices(), seed=1)
    # PAS de initialiser_horloge : on simule le monde legacy.
    etat = stockage_horloge.lire_horloge(monde["id"])
    assert etat == {"monde_id": monde["id"], "tick_actuel": 0, "actif": False,
                     "intervalle_secondes": None, "derniere_execution": None}

    # La ligne est bien PERSISTÉE, pas juste fabriquée en mémoire.
    stockage_horloge.marquer_execution(monde["id"], 1)
    assert stockage_horloge.lire_horloge(monde["id"])["tick_actuel"] == 1


def test_demarrer_et_arreter_prennent_effet_sur_un_monde_sans_ligne_horloges():
    monde = stockage_spatial.creer_monde("cle-h16", _cellules_factices(), seed=1)
    stockage_horloge.demarrer(monde["id"], 60)  # aucune ligne `horloges` au départ
    etat = stockage_horloge.lire_horloge(monde["id"])
    assert etat["actif"] is True and etat["intervalle_secondes"] == 60
    stockage_horloge.arreter(monde["id"])
    assert stockage_horloge.lire_horloge(monde["id"])["actif"] is False


def test_lire_horloge_ne_rattrape_pas_un_monde_inexistant():
    """Le rattrapage est conditionné à l'existence du MONDE : un id inventé (ou un
    monde supprimé) ne doit jamais créer de ligne `horloges` fantôme."""
    assert stockage_horloge.lire_horloge("monde-jamais-cree") is None
