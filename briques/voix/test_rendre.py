"""Régression /rendre — S146.

C0 : voix macOS inconnue (ex. "Thomas") → repli sur voix par défaut, pas de crash.
C1 : URL retournée construite depuis le host de la requête (bug localhost→IP LAN).
C2 : liste de segments vide → 422, pas 500.
"""
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import main
import moteur

client = TestClient(main.app)

_FAUX_WAV = b"RIFF\x00\x00\x00\x00WAVEfmt \x10\x00\x00\x00"


def _proc_ok(*_args, **_kwargs):
    """Mock subprocess.run : returncode=0, ffprobe renvoie 1.5 secondes."""
    m = MagicMock()
    m.returncode = 0
    m.stderr = b""
    m.stdout = "1.5\n"
    return m


# ── C2 ───────────────────────────────────────────────────────────────────────

def test_segments_vides_422():
    """Segments vides → 422 explicite, pas 500."""
    r = client.post("/rendre", json={"segments": []})
    assert r.status_code == 422


# ── C0 ───────────────────────────────────────────────────────────────────────

def test_voix_inconnue_repli_sur_defaut(monkeypatch, tmp_path):
    """Voix absente du moteur (ex. macOS "Thomas") → repli sans voix, pas de crash."""
    monkeypatch.setattr(main, "_EPISODES_DIR", tmp_path)

    appels_voix = []

    async def faux_synthetiser(texte, voix=None, langue=None, format=None,
                               fournisseur=None, usage=None):
        appels_voix.append(voix)
        if voix == "Thomas":
            return {"place_holder": True, "backend": "placeholder"}
        return {"audio": _FAUX_WAV, "format": "wav", "backend": "piper", "place_holder": False}

    monkeypatch.setattr(moteur, "synthetiser", faux_synthetiser)

    with patch("subprocess.run", side_effect=_proc_ok):
        r = client.post("/rendre", json={"segments": [{"texte": "Bonjour", "voix": "Thomas"}]})

    assert r.status_code == 200
    assert "Thomas" in appels_voix, "Le 1er appel doit transmettre 'Thomas'"
    assert None in appels_voix, "Le 2e appel (repli) doit passer voix=None"
    assert "url" in r.json()


def test_voix_absente_un_seul_appel_moteur(monkeypatch, tmp_path):
    """Segment sans champ voix : 1 seul appel moteur, aucun repli inutile."""
    monkeypatch.setattr(main, "_EPISODES_DIR", tmp_path)

    appels_voix = []

    async def faux_synthetiser(texte, voix=None, langue=None, format=None,
                               fournisseur=None, usage=None):
        appels_voix.append(voix)
        return {"audio": _FAUX_WAV, "format": "wav", "backend": "piper", "place_holder": False}

    monkeypatch.setattr(moteur, "synthetiser", faux_synthetiser)

    with patch("subprocess.run", side_effect=_proc_ok):
        r = client.post("/rendre", json={"segments": [{"texte": "Bonjour"}]})

    assert r.status_code == 200
    assert len(appels_voix) == 1
    assert appels_voix[0] is None


# ── C1 ───────────────────────────────────────────────────────────────────────

def test_url_episode_depuis_host_lan(monkeypatch, tmp_path):
    """L'URL retournée doit utiliser l'IP du header Host, pas localhost."""
    monkeypatch.setattr(main, "_EPISODES_DIR", tmp_path)
    monkeypatch.delenv("VOIX_PUBLIC_URL", raising=False)

    async def faux_synthetiser(texte, voix=None, langue=None, format=None,
                               fournisseur=None, usage=None):
        return {"audio": _FAUX_WAV, "format": "wav", "backend": "piper", "place_holder": False}

    monkeypatch.setattr(moteur, "synthetiser", faux_synthetiser)

    with patch("subprocess.run", side_effect=_proc_ok):
        r = client.post(
            "/rendre",
            json={"segments": [{"texte": "Test"}]},
            headers={"Host": "192.168.1.89:5985"},
        )

    assert r.status_code == 200
    url = r.json()["url"]
    assert "192.168.1.89" in url, f"URL n'expose pas l'IP LAN : {url}"


def test_voix_public_url_prioritaire(monkeypatch, tmp_path):
    """VOIX_PUBLIC_URL doit primer sur le host de la requête."""
    monkeypatch.setattr(main, "_EPISODES_DIR", tmp_path)
    monkeypatch.setenv("VOIX_PUBLIC_URL", "https://mon-tunnel.trycloudflare.com")

    async def faux_synthetiser(texte, voix=None, langue=None, format=None,
                               fournisseur=None, usage=None):
        return {"audio": _FAUX_WAV, "format": "wav", "backend": "piper", "place_holder": False}

    monkeypatch.setattr(moteur, "synthetiser", faux_synthetiser)

    with patch("subprocess.run", side_effect=_proc_ok):
        r = client.post("/rendre", json={"segments": [{"texte": "Test"}]})

    assert r.status_code == 200
    url = r.json()["url"]
    assert "mon-tunnel.trycloudflare.com" in url, f"VOIX_PUBLIC_URL ignorée : {url}"
