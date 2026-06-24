"""Chat vocal temps réel (porté de Gungnir) : config, auth WS et repli honnête.

Le relais lui-même parle à une API tierce (réseau) → non testable hors-ligne. Mais tout
ce qui décide AVANT de composer en amont l'est : résolution des clés par env, auth du
WebSocket, catalogue, et le refus honnête quand aucune clé n'est configurée.
"""
import os

import pytest
from fastapi.testclient import TestClient

import main
import realtime


client = TestClient(main.app)


# ── Résolution des clés par env (alias dédié prioritaire) ─────────────────────

def test_cle_fournisseur_absente_par_defaut():
    assert realtime.cle_fournisseur("openai") is None
    assert realtime.cle_fournisseur("google") is None
    assert realtime.cle_fournisseur("grok") is None


def test_cle_fournisseur_alias_dedie_prioritaire(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "standard")
    monkeypatch.setenv("VOIX_OPENAI_API_KEY", "dedie")
    assert realtime.cle_fournisseur("openai") == "dedie"


def test_cle_fournisseur_repli_variable_standard(monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "xai-123")
    assert realtime.cle_fournisseur("grok") == "xai-123"


def test_nom_agent_par_defaut(monkeypatch):
    monkeypatch.delenv("VOIX_AGENT_NOM", raising=False)
    assert realtime.nom_agent() == "Assistant"


# ── Catalogue exposé à l'UI ───────────────────────────────────────────────────

def test_fournisseurs_configures_liste_les_trois(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    cfg = realtime.fournisseurs_configures()
    assert set(cfg) == {"openai", "google", "grok"}
    assert cfg["openai"]["configure"] is True
    assert cfg["google"]["configure"] is False


def test_endpoint_voix_realtime():
    r = client.get("/voix/realtime")
    assert r.status_code == 200
    data = r.json()
    assert set(data["fournisseurs"]) == {"openai", "google", "grok"}


def test_sante_expose_le_temps_reel(monkeypatch):
    r = client.get("/sante")
    assert r.status_code == 200
    assert "temps_reel" in r.json()      # liste (vide en test, aucune clé)
    assert r.json()["temps_reel"] == []


# ── Auth WebSocket (jeton brique) ─────────────────────────────────────────────

class _FauxWS:
    """Imite l'interface minimale lue par realtime.authentifier/extraire_jeton."""
    def __init__(self, headers=None, query=None):
        self.headers = headers or {}
        self.query_params = query or {}


def test_extraire_jeton_header_puis_sousprotocole_puis_query():
    assert realtime.extraire_jeton(_FauxWS(headers={"authorization": "Bearer abc"})) == "abc"
    assert realtime.extraire_jeton(_FauxWS(headers={"sec-websocket-protocol": "bearer.xyz"})) == "xyz"
    assert realtime.extraire_jeton(_FauxWS(query={"token": "qqq"})) == "qqq"


def test_authentifier_ouvert_si_pas_de_cle_brique(monkeypatch):
    monkeypatch.setenv("API_KEYS", "")
    assert realtime.authentifier(_FauxWS()) is True


def test_authentifier_exige_un_jeton_valide_si_cles_definies(monkeypatch):
    monkeypatch.setenv("API_KEYS", "secret1,secret2")
    assert realtime.authentifier(_FauxWS()) is False
    assert realtime.authentifier(_FauxWS(headers={"authorization": "Bearer secret2"})) is True


# ── Repli honnête côté WebSocket : pas de clé → erreur + fermeture ────────────

@pytest.mark.parametrize("chemin, attendu", [
    ("/realtime/openai", "openai"),
    ("/realtime/google", "google"),
    ("/realtime/grok", "grok"),
])
def test_ws_sans_cle_renvoie_une_erreur_honnete(chemin, attendu):
    with client.websocket_connect(chemin) as ws:
        msg = ws.receive_json()
    assert msg["type"] == "error"
    assert attendu in msg["error"]      # nomme le fournisseur manquant, n'invente rien
