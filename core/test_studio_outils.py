"""Outils Studio de l'assistant + helper d'appel authentifié (`_studio_appel`).

S134 : les outils studio_* sont déclarés dans briques/studio/manifest.json (plus dans
OUTILS statique). Les tests vérifient le manifest directement.

`_studio_appel` envoie l'en-tête X-API-Key quand STUDIO_KEY est posé, en dégradant
proprement (401 / brique hors ligne) sans stacktrace.

Async via asyncio.run (motif du reste de la suite core/, pas de marqueur pytest).
"""

import asyncio
import json
import os
import pathlib

import httpx

os.environ.setdefault("STUDIO_URL", "http://studio.test")  # override → pas besoin du registre

import outils  # noqa: E402

_MANIFEST = json.loads(
    (pathlib.Path(__file__).parent.parent / "briques" / "studio" / "manifest.json").read_text()
)
_CAPS = {c["nom"]: c for c in _MANIFEST["capacites"]}


# ── Déclaration des outils (manifest, pas OUTILS statique depuis S134) ───────

def test_outils_studio_declares():
    attendus = {
        "studio_series_lister", "studio_serie_lire", "studio_personnages_lister",
        "studio_serie_creer", "studio_episode_produire", "studio_express",
        "studio_voix_lister", "studio_bible_proposer", "studio_distribution_proposer",
        "studio_bible_decider", "studio_perso_creer", "studio_audio_produire",
    }
    assert attendus <= set(_CAPS)


def test_actions_studio_gardees():
    gardees = {
        "studio_serie_creer", "studio_episode_produire", "studio_express",
        "studio_bible_decider", "studio_perso_creer", "studio_audio_produire",
    }
    for nom in gardees:
        assert _CAPS[nom].get("action") is True, f"{nom} devrait être action=True"
    # Les lectures et les PROPOSITIONS (non destructives) ne sont PAS des actions.
    for libre in ("studio_series_lister", "studio_voix_lister",
                  "studio_bible_proposer", "studio_distribution_proposer"):
        assert not _CAPS[libre].get("action"), f"{libre} ne devrait pas être une action"


# ── Helper _studio_appel ─────────────────────────────────────────────────────
class _Resp:
    def __init__(self, status=200, payload=None, content=b"{}"):
        self.status_code = status
        self._payload = payload if payload is not None else {}
        self.content = content
        self.text = ""

    def json(self):
        return self._payload


class _Client:
    """Stub httpx : enregistre le dernier appel (dont les en-têtes)."""
    def __init__(self, resp=None, boom=False):
        self.resp = resp or _Resp()
        self.boom = boom
        self.dernier = {}

    async def request(self, methode, url, json=None, params=None, headers=None, timeout=None):
        self.dernier = {"methode": methode, "url": url, "json": json,
                        "params": params, "headers": headers}
        if self.boom:
            raise httpx.ConnectError("injoignable")
        return self.resp


def test_studio_appel_envoie_la_cle(monkeypatch):
    # monkeypatch.setenv (pas os.environ direct) : restaure la valeur PRÉCÉDENTE de
    # STUDIO_KEY après le test, plutôt que de la détruire inconditionnellement — sinon ce
    # test pollue l'ordre pour test_studio_proxy.py, qui pose STUDIO_KEY à l'import (S187).
    monkeypatch.setenv("STUDIO_KEY", "secret-de-service")
    cli = _Client(_Resp(200, {"ok": True}))
    out = asyncio.run(outils._studio_appel(cli, None, "GET", "/series"))
    assert cli.dernier["headers"]["X-API-Key"] == "secret-de-service"
    assert cli.dernier["url"] == "http://studio.test/series"
    assert json.loads(out) == {"ok": True}


def test_studio_appel_sans_cle_pas_de_cle_api(monkeypatch):
    monkeypatch.delenv("STUDIO_KEY", raising=False)
    cli = _Client(_Resp(200, {"ok": True}))
    asyncio.run(outils._studio_appel(cli, None, "GET", "/series"))
    assert "X-API-Key" not in (cli.dernier["headers"] or {})


def test_studio_appel_forwarde_lidentite_par_personne(monkeypatch):
    import contexte_tenant as ct
    monkeypatch.setenv("STUDIO_KEY", "secret-de-service")
    try:
        ct.definir_contexte(utilisateur="claire")
        cli = _Client(_Resp(200, {"ok": True}))
        asyncio.run(outils._studio_appel(cli, None, "GET", "/series"))
        assert cli.dernier["headers"]["X-User-Id"] == "claire"
    finally:
        ct.definir_contexte(utilisateur=ct.UTILISATEUR_DEFAUT)
        ct._utilisateur.set(ct.UTILISATEUR_DEFAUT)


def test_studio_appel_401_message_clair():
    cli = _Client(_Resp(401, {"detail": "Clé invalide"}))
    out = json.loads(asyncio.run(outils._studio_appel(cli, None, "GET", "/series")))
    assert out["ok"] is False and "refusé" in out["message"].lower()


def test_studio_appel_hors_ligne_degrade():
    cli = _Client(boom=True)
    out = json.loads(asyncio.run(outils._studio_appel(cli, None, "GET", "/series")))
    assert out["ok"] is False and "injoignable" in out["message"].lower()
