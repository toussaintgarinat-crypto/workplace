"""Exposition Prometheus du Cœur (S225)."""

import outils
import validation_args
from shared.metriques import Registre


class FauxRegistre:
    def __init__(self, briques=None):
        self.briques = briques or {}


# ── Le format ────────────────────────────────────────────────────────────────

def test_entete_unique_par_nom_meme_avec_plusieurs_etiquettes():
    """Prometheus rejette un bloc HELP/TYPE dupliqué : le piège n°1 du format à la main."""
    r = Registre()
    r.jauge("truc", 1, {"a": "x"}, aide="Un truc.")
    r.jauge("truc", 2, {"a": "y"})
    sortie = r.rendu()
    assert sortie.count("# HELP truc") == 1
    assert sortie.count("# TYPE truc gauge") == 1
    assert 'truc{a="x"} 1' in sortie and 'truc{a="y"} 2' in sortie


def test_valeurs_d_etiquette_echappees():
    """Un nom de tâche vient d'un manifeste écrit à la main : un guillemet dedans
    casserait le parsing de tout le scrape."""
    r = Registre()
    r.jauge("truc", 1, {"tache": 'sync "pro"\\perso'})
    ligne = [l for l in r.rendu().splitlines() if l.startswith("truc")][0]
    assert ligne == 'truc{tache="sync \\"pro\\"\\\\perso"} 1'


def test_etiquette_nulle_omise():
    r = Registre()
    r.jauge("truc", 1, {"a": "x", "b": None})
    assert 'truc{a="x"} 1' in r.rendu()


def test_entiers_rendus_sans_decimale():
    r = Registre()
    r.jauge("truc", 3.0, {})
    r.jauge("machin", 0.25, {})
    sortie = r.rendu()
    assert "truc 3\n" in sortie and "machin 0.25" in sortie


def test_types_declares_correctement():
    r = Registre()
    r.compteur("bidule_total", 5)
    assert "# TYPE bidule_total counter" in r.rendu()


# ── La collecte ──────────────────────────────────────────────────────────────

def test_rendu_complet_sans_registre_utilisable():
    """Une sonde qui plante en scrutant est pire qu'une sonde absente : le rendu doit
    survivre à un registre vide comme à un registre cassé."""
    import metriques

    for reg in (FauxRegistre(), None, object()):
        sortie = metriques.rendu(reg)
        assert "workplace_demarrage_timestamp_secondes" in sortie
        assert sortie.endswith("\n")


def test_une_tache_jamais_executee_n_invente_pas_un_age(monkeypatch):
    """Un âge de 0 se lirait « toute fraîche » — exactement le contraire de la vérité."""
    import metriques

    r = Registre()
    monkeypatch.setattr(metriques.horloge, "lister_etat", lambda _r: [
        {"brique": "veille", "nom": "sync", "cadence_heures": 1,
         "derniere_execution": None, "nb_executions": 0}])
    metriques._taches(FauxRegistre(), r)
    sortie = r.rendu()
    assert "workplace_tache_age_secondes" not in sortie
    assert 'workplace_tache_jamais_executee{brique="veille",tache="sync"} 1' in sortie


def test_l_age_d_une_tache_est_expose(monkeypatch):
    import metriques
    from datetime import datetime, timedelta, timezone

    quand = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    r = Registre()
    monkeypatch.setattr(metriques.horloge, "lister_etat", lambda _r: [
        {"brique": "veille", "nom": "sync", "cadence_heures": 1,
         "derniere_execution": quand, "dernier_statut": "ok", "nb_executions": 12}])
    metriques._taches(FauxRegistre(), r)
    sortie = r.rendu()
    ligne = [l for l in sortie.splitlines() if l.startswith("workplace_tache_age_secondes")][0]
    assert 6000 < float(ligne.rsplit(" ", 1)[1]) < 8000
    assert 'workplace_tache_dernier_succes{brique="veille",tache="sync"} 1' in sortie


def test_horodatage_illisible_ne_leve_pas():
    import metriques

    assert metriques._age_secondes("pas une date") is None
    assert metriques._age_secondes(None) is None


def test_le_budget_illimite_n_expose_pas_de_ratio(monkeypatch):
    """0/illimité se lirait « on ne dépense rien », ce qui est faux."""
    import metriques

    monkeypatch.setattr(metriques.journal_usage, "resume", lambda: {
        "jour": {"cout_usd": 1.5, "appels": 3, "cache_hits": 1},
        "mois": {"cout_usd": 9.0, "appels": 30, "cache_hits": 4},
        "budget": {"jour": {"budget_usd": 0, "depense_usd": 1.5},
                   "mois": {"budget_usd": 20, "depense_usd": 9.0}},
    })
    r = Registre()
    metriques._llm(r)
    sortie = r.rendu()
    assert 'workplace_llm_budget_ratio{periode="jour"}' not in sortie
    assert 'workplace_llm_budget_ratio{periode="mois"} 0.45' in sortie
    assert 'workplace_llm_cout_usd{periode="jour"} 1.5' in sortie


# ── Le comptage d'appels d'outils ────────────────────────────────────────────

def test_les_appels_et_echecs_sont_comptes():
    import asyncio

    outils._APPELS.clear()
    outils._ECHECS.clear()
    asyncio.run(outils.executer("outil_qui_n_existe_pas", {}, FauxRegistre()))
    appels, echecs = outils.compteurs_appels()
    assert appels["outil_qui_n_existe_pas"] == 1
    assert echecs["outil_qui_n_existe_pas"] == 1, "« Outil inconnu » est bien un échec"


def test_l_heuristique_d_erreur_a_une_seule_source():
    """Elle vivait en double (assistant + outils) ; deux listes à garder synchrones
    finissent toujours par diverger."""
    import assistant

    assert assistant._PREFIXES_ERREUR_OUTIL is outils.PREFIXES_ERREUR
    assert outils.est_erreur('{"erreur": "[GATE] refusé"}')
    assert outils.est_erreur("Brique injoignable (mail) : timeout")
    assert not outils.est_erreur('{"ok": true, "souvenirs": []}')
    assert not outils.est_erreur("")


def test_les_capacites_jamais_appelees_sont_comptees():
    import metriques

    outils._APPELS.clear()
    outils._ECHECS.clear()
    reg = FauxRegistre({"mail": {"nom": "mail", "port": 6030, "capacites": [
        {"nom": "mail_lister", "chemin": "/mail", "description": "d"},
        {"nom": "mail_lire", "chemin": "/mail/{id}", "description": "d"}]}})
    outils._APPELS["mail_lister"] = 3
    r = Registre()
    metriques._outils(reg, r)
    sortie = r.rendu()
    assert "workplace_capacites_declarees 2" in sortie
    assert "workplace_capacites_jamais_appelees 1" in sortie
    assert 'workplace_outil_appels_total{brique="mail",outil="mail_lister"} 3' in sortie


def test_les_ecarts_de_validation_sont_exposes():
    import metriques

    validation_args.reinitialiser_compteurs()
    validation_args.valider("outil_inexistant", {}, FauxRegistre())
    r = Registre()
    metriques._validation(r)
    assert ('workplace_validation_ecarts_total{categorie="outil_inconnu"} 1'
            in r.rendu())
    validation_args.reinitialiser_compteurs()
