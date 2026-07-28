"""Balayage périodique « app vivante » (S33) — fonctions pures, aucun réseau.

Écrit à l'origine comme script autonome (`def run()` + `python3 test_balayage.py`), donc
JAMAIS exécuté par le filet : ni `make test-briques` ni `scripts/tests_briques.sh` ne
lancent autre chose que pytest. Converti en tests pytest le 2026-07-28 — les 4 scénarios
sont conservés à l'identique, un test chacun.
"""
import json
import pathlib

import revue


def test_souverainete_consentement_inactif_ou_absent():
    """Sans consentement actif, on ne révise jamais — quelle que soit la forme de l'absence."""
    for partage in ({"actif": False, "entites": ["x"]}, {}, None):
        eligible, raison = revue.doit_reviser(partage, None)
        assert not eligible and raison == "consentement inactif", (partage, eligible, raison)


def test_respect_humain_une_revue_validee_en_attente_n_est_pas_ecrasee():
    eligible, raison = revue.doit_reviser({"actif": True}, {"statut": "validee"})
    assert not eligible and "validée" in raison, (eligible, raison)


def test_revue_absente_appliquee_rejetee_ou_proposee_est_eligible():
    for rev in (None, {"statut": "appliquee"}, {"statut": "rejetee"}, {"statut": "propose"}):
        eligible, raison = revue.doit_reviser({"actif": True}, rev)
        assert eligible and raison == "", (rev, eligible, raison)


def test_contrat_manifest_la_tache_est_exploitable_par_l_horloge():
    """La tâche `revue-app-vivante` doit rester bien formée pour `core/horloge.py` (S29).

    Chemin ancré sur `__file__` et non relatif : le script d'origine lisait
    `manifest.json` depuis le cwd et n'aurait rien trouvé lancé depuis la racine."""
    manifest = json.loads(
        (pathlib.Path(__file__).parent / "manifest.json").read_text(encoding="utf-8"))
    t = next((x for x in (manifest.get("taches") or [])
              if x.get("nom") == "revue-app-vivante"), None)
    assert t, "tâche revue-app-vivante absente du manifest"
    assert t["methode"] == "POST" and t["chemin"] == "/revues/balayage", t
    assert isinstance(t["cadence_heures"], (int, float)) and t["cadence_heures"] > 0, t
    assert t.get("tolere_echec") is True and t.get("idempotent") is True, t
