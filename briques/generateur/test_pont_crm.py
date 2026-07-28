"""Pont consenti app→CRM (S24) — briques `donnees` et `forge` mockées, aucun réseau.

Écrit à l'origine comme script autonome (`def run()`), donc jamais exécuté par le filet.
Converti en tests pytest le 2026-07-28.

⚠ Les 6 scénarios d'origine s'ENCHAÎNAIENT sur un même registre SQLite : l'idempotence
(2) supposait que (1) ait poussé, et les révocations (4, 5) supposaient les mêmes leads
encore enregistrés. Un tel filet ne dit plus rien dès qu'un test est lancé seul ou que
l'ordre change (`-k`, `-p no:randomly`, exécution parallèle). Chaque test reçoit donc
maintenant un **registre neuf** et pose lui-même ce dont il a besoin.
"""
import importlib
import json
import os

import httpx
import pytest

# La VRAIE classe, figée à l'import. Indispensable : un test peut brancher deux backends
# successifs (pousser avec l'un, révoquer avec l'autre) ; si le second capturait
# `httpx.Client` au moment de sa création, il capturerait le FAUX client du premier et
# rejouerait ses appels sur l'ancien transport. Défaut vécu en écrivant ce fichier — la
# révocation rapportait bien 2 suppressions, mais le backend observé n'en voyait aucune.
_VRAI_CLIENT = httpx.Client

ENTITES = {
    "clients": [
        {"_id": "r1", "nom": "Jean Dupont", "email": "jean@exemple.fr", "telephone": "0102"},
        {"_id": "r2", "societe": "ACME", "mail": "contact@acme.fr"},
    ],
    "factures": [
        {"_id": "f1", "montant": 1200},
    ],
}

CONSENTI = {"actif": True, "entites": ["clients"]}


def _transport(etat):
    """MockTransport routant `donnees` (export) + `forge` (CRM), et journalisant les appels."""
    def handler(request: httpx.Request) -> httpx.Response:
        chemin, methode = request.url.path, request.method
        etat["calls"].append(f"{methode} {chemin}")

        if etat.get("forge_ko") and "/crm" in chemin:
            raise httpx.ConnectError("forge down")

        if methode == "GET" and chemin.endswith("/export"):
            return httpx.Response(200, json={"app_id": "app-1", "entites": etat["entites"]})

        if methode == "POST" and chemin.endswith("/crm"):
            corps = json.loads(request.content)
            lead_id = f"lead-{len(etat['leads']) + 1}"
            etat["leads"][lead_id] = corps
            return httpx.Response(200, json={"ok": True, "id": lead_id, **corps})

        if methode == "DELETE" and "/crm/" in chemin:
            lead_id = chemin.rsplit("/", 1)[-1]
            etat["leads"].pop(lead_id, None)
            etat["supprimes"].append(lead_id)
            return httpx.Response(200, json={"ok": True})

        return httpx.Response(404, json={"path": chemin})

    return httpx.MockTransport(handler)


@pytest.fixture
def pont(tmp_path, monkeypatch):
    """`pont_crm` rechargé sur un registre SQLite VIERGE, plus un brancheur de faux backend.

    Le rechargement est nécessaire : le module lit `DB_PATH` et crée sa table à l'import.
    Sans ça, tous les tests partageraient le registre — et la vraie `/data/apps.db`.
    """
    monkeypatch.setenv("DB_PATH", str(tmp_path / "apps_test.db"))
    import pont_crm as pc
    importlib.reload(pc)

    def brancher(**options):
        etat = {"entites": ENTITES, "leads": {}, "supprimes": [], "calls": [], **options}
        transport = _transport(etat)

        def faux_client(*a, **k):
            k.pop("timeout", None)
            return _VRAI_CLIENT(transport=transport)

        monkeypatch.setattr(pc.httpx, "Client", faux_client)
        return etat

    return pc, brancher


def test_consentement_oui_seules_les_entites_en_liste_blanche_remontent(pont):
    pc, brancher = pont
    etat = brancher()
    r = pc.pousser("app-1", CONSENTI)
    assert r["actif"] and r["pousses"] == 2 and r["erreurs"] == 0, r
    assert len(etat["leads"]) == 2, "les factures ne doivent PAS remonter"
    noms = {lead["nom"] for lead in etat["leads"].values()}
    assert "Jean Dupont" in noms and "ACME" in noms, noms  # repli du nom sur la société
    assert all("[pont:app-1/clients]" in lead["notes"] for lead in etat["leads"].values()), \
        etat["leads"]


def test_idempotence_une_seconde_remontee_ne_recree_rien(pont):
    pc, brancher = pont
    brancher()
    pc.pousser("app-1", CONSENTI)          # 1re remontée : peuple le registre
    etat = brancher()                      # backend neuf : tout POST serait visible
    r = pc.pousser("app-1", CONSENTI)
    assert r["pousses"] == 0 and r["ignores"] == 2, r
    assert etat["leads"] == {}, "aucun nouveau POST /crm attendu"


def test_consentement_non_rien_ne_sort_et_aucun_appel_reseau(pont):
    """Souveraineté : partage désactivé ⇒ on ne contacte même pas la brique `donnees`."""
    pc, brancher = pont
    etat = brancher()
    r = pc.pousser("app-2", {"actif": False, "entites": ["clients"]})
    assert not r["actif"] and r["pousses"] == 0, r
    assert etat["calls"] == [], "aucun appel réseau quand le partage est désactivé"


def test_revocation_sans_purge_arrete_le_pont_et_conserve_les_donnees(pont):
    pc, brancher = pont
    brancher()
    pc.pousser("app-1", CONSENTI)
    etat = brancher()
    r = pc.revoquer("app-1", purger=False)
    assert not r["purge"] and r["supprimes"] == 0 and r["restants"] == 2, r
    assert etat["supprimes"] == [], "aucun DELETE quand on ne purge pas"


def test_revocation_avec_purge_supprime_les_leads_remontes(pont):
    pc, brancher = pont
    brancher()
    pc.pousser("app-1", CONSENTI)
    etat = brancher()
    r = pc.revoquer("app-1", purger=True)
    assert r["purge"] and r["supprimes"] == 2 and r["restants"] == 0, r
    assert len(etat["supprimes"]) == 2, etat["supprimes"]


def test_forge_injoignable_best_effort_erreurs_comptees_sans_exception(pont):
    pc, brancher = pont
    brancher(forge_ko=True)
    r = pc.pousser("app-3", CONSENTI)
    assert r["actif"] and r["pousses"] == 0 and r["erreurs"] == 2, r
