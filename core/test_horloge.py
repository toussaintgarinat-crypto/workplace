"""Validation de l'horloge — planificateur de tâches périodiques (Sprint S29).

Autonome : aucune dépendance pytest ni vrai réseau (httpx simulé), journal SQLite
isolé dans un dossier temporaire.
    $ cd core && python3 test_horloge.py
Sortie « ✅ TOUS LES TESTS PASSENT » = contrat manifest + cadence + idempotence OK.
"""

import asyncio
import os
import sys
import tempfile
from datetime import datetime, timedelta

# Journal isolé AVANT d'importer le module.
_tmp = tempfile.mkdtemp()
os.environ["HORLOGE_DB"] = os.path.join(_tmp, "horloge.db")
sys.path.insert(0, os.path.dirname(__file__))

import horloge  # noqa: E402


# ── Doublures ────────────────────────────────────────────────────────────────

class _Registre:
    """Registre minimal : un dict de manifests (avec port pour résoudre l'URL)."""
    def __init__(self, briques: dict):
        self.briques = briques


class _FakeResp:
    def __init__(self, status_code=200, text="{}"):
        self.status_code = status_code
        self.text = text


class _FakeClient:
    """AsyncClient httpx simulé : enregistre les appels, renvoie une réponse scriptée."""
    appels: list = []

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def request(self, methode, url, headers=None, timeout=None):
        _FakeClient.appels.append({"methode": methode, "url": url, "headers": headers or {}})
        return _FakeClient.reponse


def _registre_demo():
    return _Registre({
        "forge": {
            "nom": "forge", "port": 5700,
            "taches": [{
                "nom": "relances-impayes", "description": "relances",
                "methode": "POST", "chemin": "/relances/executer",
                "cadence_heures": 24, "idempotent": True,
            }],
        },
        "agenda": {
            "nom": "agenda", "port": 8400,
            "taches": [{
                "nom": "sync-google", "chemin": "/google/sync",
                "cadence_heures": 6, "tolere_echec": True,
                "entetes": {"X-User-Id": "perso"},
                "entete_token_env": "CALENDAR_SERVICE_TOKEN",
            }],
        },
        "memoire": {"nom": "memoire", "port": 5600},  # aucune tâche déclarée
    })


def _reset():
    """Vide le journal SQLite entre les tests (table recréée à vide)."""
    horloge.init_db()
    with horloge._conn() as c:
        c.execute("DELETE FROM horloge_journal")
    _FakeClient.appels = []
    _FakeClient.reponse = _FakeResp(200, '{"ok": true}')


# ── Cadence (pure) ───────────────────────────────────────────────────────────

def test_cadence_pure():
    maintenant = datetime(2026, 6, 10, 12, 0, 0)
    assert horloge.tache_due(None, 24, maintenant) is True          # jamais tournée
    recent = (maintenant - timedelta(hours=1)).isoformat()
    assert horloge.tache_due(recent, 24, maintenant) is False        # cadence pas écoulée
    vieux = (maintenant - timedelta(hours=25)).isoformat()
    assert horloge.tache_due(vieux, 24, maintenant) is True          # cadence écoulée
    pile = (maintenant - timedelta(hours=24)).isoformat()
    assert horloge.tache_due(pile, 24, maintenant) is True           # exactement à l'échéance
    assert horloge.tache_due("pas-une-date", 24, maintenant) is True  # journal illisible → on relance


# ── Contrat manifest ─────────────────────────────────────────────────────────

def test_collecte_normalise_et_ignore_incomplet():
    reg = _Registre({
        "forge": {"nom": "forge", "port": 5700, "taches": [
            {"nom": "ok", "chemin": "/x"},                 # méthode/cadence par défaut
            {"description": "sans nom ni chemin"},          # incomplète → ignorée
        ]},
    })
    taches = horloge.collecter_taches(reg)
    assert len(taches) == 1
    t = taches[0]
    assert t["brique"] == "forge" and t["nom"] == "ok"
    assert t["methode"] == "POST"                           # défaut
    assert t["cadence_heures"] == horloge.CADENCE_DEFAUT_H  # défaut


def test_entetes_token_depuis_env():
    tache = {"entetes": {"X-User-Id": "perso"}, "entete_token_env": "CALENDAR_SERVICE_TOKEN"}
    os.environ.pop("CALENDAR_SERVICE_TOKEN", None)
    assert "Authorization" not in horloge._entetes(tache)   # env absent → pas de Bearer
    os.environ["CALENDAR_SERVICE_TOKEN"] = "secret-123"
    try:
        ent = horloge._entetes(tache)
        assert ent["X-User-Id"] == "perso"
        assert ent["Authorization"] == "Bearer secret-123"
    finally:
        os.environ.pop("CALENDAR_SERVICE_TOKEN", None)


# ── Exécution + idempotence de cadence ───────────────────────────────────────

def test_run_due_execute_puis_respecte_la_cadence():
    _reset()
    horloge.httpx.AsyncClient = _FakeClient
    reg = _registre_demo()

    # 1er passage : les 2 tâches déclarées sont dues (jamais tournées).
    r1 = asyncio.run(horloge.run_due(reg))
    assert r1["nb_taches_declarees"] == 2
    assert r1["nb_executees"] == 2
    urls = {a["url"] for a in _FakeClient.appels}
    assert "http://host.docker.internal:5700/relances/executer" in urls
    assert "http://host.docker.internal:8400/google/sync" in urls
    assert all(e["statut"] == "ok" for e in r1["executees"])

    # 2e passage immédiat : cadence pas écoulée → rien n'est rejoué.
    _FakeClient.appels = []
    r2 = asyncio.run(horloge.run_due(reg))
    assert r2["nb_executees"] == 0
    assert len(r2["sautees"]) == 2
    assert _FakeClient.appels == []


def test_forcer_rejoue_malgre_la_cadence():
    _reset()
    horloge.httpx.AsyncClient = _FakeClient
    reg = _registre_demo()
    asyncio.run(horloge.run_due(reg))                       # amorce les journaux
    _FakeClient.appels = []
    r = asyncio.run(horloge.run_due(reg, forcer=True, filtre_brique="forge"))
    assert r["nb_executees"] == 1                            # filtré sur forge
    assert _FakeClient.appels[0]["url"].endswith("/relances/executer")


def test_tolere_echec_avance_quand_meme_lhorloge():
    _reset()
    horloge.httpx.AsyncClient = _FakeClient
    _FakeClient.reponse = _FakeResp(400, "Google non connecté")
    reg = _Registre({"agenda": _registre_demo().briques["agenda"]})

    r = asyncio.run(horloge.run_due(reg))
    assert r["executees"][0]["statut"] == "ignore"          # toléré, pas une alarme
    # L'horloge a été avancée : un 2e passage saute la tâche (pas de matraquage).
    r2 = asyncio.run(horloge.run_due(reg))
    assert r2["nb_executees"] == 0


def test_lister_etat_calcule_prochaine_echeance():
    _reset()
    horloge.httpx.AsyncClient = _FakeClient
    reg = _registre_demo()
    asyncio.run(horloge.run_due(reg))
    etat = {e["nom"]: e for e in horloge.lister_etat(reg)}
    assert etat["relances-impayes"]["dernier_statut"] == "ok"
    assert etat["relances-impayes"]["nb_executions"] == 1
    assert etat["relances-impayes"]["prochaine_echeance"] is not None
    # 24 h après la dernière exécution.
    derniere = datetime.fromisoformat(etat["relances-impayes"]["derniere_execution"])
    prochaine = datetime.fromisoformat(etat["relances-impayes"]["prochaine_echeance"])
    assert prochaine - derniere == timedelta(hours=24)


if __name__ == "__main__":
    for nom, fn in list(globals().items()):
        if nom.startswith("test_") and callable(fn):
            fn()
            print(f"  ✓ {nom}")
    print("\n✅ TOUS LES TESTS PASSENT")
