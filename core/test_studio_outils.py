"""Outils Studio de l'assistant + helper d'appel authentifié (`_studio_appel`).

Vérifie que : les 6 outils studio_* sont déclarés, les 3 actions sont gardées par
confirmation, et `_studio_appel` envoie l'en-tête X-API-Key quand STUDIO_KEY est posé,
en dégradant proprement (401 / brique hors ligne) sans stacktrace.

Async via asyncio.run (motif du reste de la suite core/, pas de marqueur pytest).
"""

import asyncio
import json
import os

import httpx

os.environ.setdefault("STUDIO_URL", "http://studio.test")  # override → pas besoin du registre

import outils  # noqa: E402


# ── Déclaration des outils ───────────────────────────────────────────────────
NOMS = {o["function"]["name"] for o in outils.OUTILS}


def test_outils_studio_declares():
    attendus = {
        # incrément 1
        "studio_series_lister", "studio_serie_lire", "studio_personnages_lister",
        "studio_serie_creer", "studio_episode_produire", "studio_express",
        # incrément 2 : bible fine, distribution/voix, audio
        "studio_voix_lister", "studio_bible_proposer", "studio_distribution_proposer",
        "studio_bible_decider", "studio_perso_creer", "studio_audio_produire",
    }
    assert attendus <= NOMS


def test_actions_studio_gardees():
    gardees = {
        "studio_serie_creer", "studio_episode_produire", "studio_express",
        "studio_bible_decider", "studio_perso_creer", "studio_audio_produire",
    }
    assert gardees <= outils.OUTILS_ACTION
    # Les lectures et les PROPOSITIONS (non destructives) ne sont PAS gardées.
    for libre in ("studio_series_lister", "studio_voix_lister",
                  "studio_bible_proposer", "studio_distribution_proposer"):
        assert libre not in outils.OUTILS_ACTION


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


def test_studio_appel_envoie_la_cle():
    os.environ["STUDIO_KEY"] = "secret-de-service"
    try:
        cli = _Client(_Resp(200, {"ok": True}))
        out = asyncio.run(outils._studio_appel(cli, None, "GET", "/series"))
        assert cli.dernier["headers"] == {"X-API-Key": "secret-de-service"}
        assert cli.dernier["url"] == "http://studio.test/series"
        assert json.loads(out) == {"ok": True}
    finally:
        os.environ.pop("STUDIO_KEY", None)


def test_studio_appel_sans_cle_pas_dentete():
    os.environ.pop("STUDIO_KEY", None)
    cli = _Client(_Resp(200, {"ok": True}))
    asyncio.run(outils._studio_appel(cli, None, "GET", "/series"))
    assert cli.dernier["headers"] is None  # mode ouvert : aucun en-tête d'auth


def test_studio_appel_401_message_clair():
    cli = _Client(_Resp(401, {"detail": "Clé invalide"}))
    out = json.loads(asyncio.run(outils._studio_appel(cli, None, "GET", "/series")))
    assert out["ok"] is False and "refusé" in out["message"].lower()


def test_studio_appel_hors_ligne_degrade():
    cli = _Client(boom=True)
    out = json.loads(asyncio.run(outils._studio_appel(cli, None, "GET", "/series")))
    assert out["ok"] is False and "injoignable" in out["message"].lower()
