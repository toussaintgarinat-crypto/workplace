"""Tests offline — synopsis : santé, auth, /resumer, /reel (mocks YouTube + LLM + ffmpeg)."""
import importlib
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient

import main

client = TestClient(main.app)

_TRANSCRIPT_FAKE = {
    "transcript": "Bonjour tout le monde. Aujourd'hui on parle de Python.",
    "title": "Introduction à Python",
    "language": "fr",
}
_RESUME_FAKE = (
    "## Chapitres\n00:00 Introduction\n01:00 Les bases\n\n"
    "## Insights\n- Python est populaire"
)
_CHUNKS_FAKE = [{"text": "Bonjour tout le monde.", "tokens": 10}]


# ── Santé ────────────────────────────────────────────────────────────────────

def test_sante_ok():
    r = client.get("/sante")
    assert r.status_code == 200
    data = r.json()
    assert data["api"] == "ok"
    assert "gateway" in data


# ── Auth ─────────────────────────────────────────────────────────────────────

def test_auth_ouverte_sans_cles(monkeypatch):
    monkeypatch.setenv("API_KEYS", "")
    m = importlib.reload(main)
    c = TestClient(m.app)
    with patch.object(m, "_summarize", return_value={
        "titre": "T", "resume": "R", "chapitres": [], "insights": [], "langue_source": "fr"
    }):
        r = c.post("/resumer", json={"url": "https://youtube.com/watch?v=test"})
    assert r.status_code == 200


def test_auth_401_sans_cle_si_configuree(monkeypatch):
    monkeypatch.setenv("API_KEYS", "cle-test")
    m = importlib.reload(main)
    c = TestClient(m.app)
    r = c.post("/resumer", json={"url": "https://youtube.com/watch?v=test"})
    assert r.status_code == 401
    monkeypatch.setenv("API_KEYS", "")
    importlib.reload(main)


def test_auth_401_mauvaise_cle(monkeypatch):
    monkeypatch.setenv("API_KEYS", "cle-test")
    m = importlib.reload(main)
    c = TestClient(m.app)
    r = c.post("/resumer", json={"url": "https://youtube.com/watch?v=test"},
               headers={"X-API-Key": "mauvaise"})
    assert r.status_code == 401
    monkeypatch.setenv("API_KEYS", "")
    importlib.reload(main)


def test_auth_ok_bonne_cle(monkeypatch):
    monkeypatch.setenv("API_KEYS", "cle-test")
    m = importlib.reload(main)
    c = TestClient(m.app)
    with patch.object(m, "_summarize", return_value={
        "titre": "T", "resume": "R", "chapitres": [], "insights": [], "langue_source": "fr"
    }):
        r = c.post("/resumer", json={"url": "https://youtube.com/watch?v=test"},
                   headers={"X-API-Key": "cle-test"})
    assert r.status_code == 200
    monkeypatch.setenv("API_KEYS", "")
    importlib.reload(main)


# ── /resumer ─────────────────────────────────────────────────────────────────

def test_resumer_structure():
    with (
        patch("main.get_youtube_transcript", return_value=_TRANSCRIPT_FAKE),
        patch("main.chunk_transcript", return_value=_CHUNKS_FAKE),
        patch("main.llm_complete", return_value=_RESUME_FAKE),
    ):
        r = client.post("/resumer", json={"url": "https://youtube.com/watch?v=abc"})
    assert r.status_code == 200
    data = r.json()
    assert data["titre"] == "Introduction à Python"
    assert "resume" in data
    assert isinstance(data["chapitres"], list)
    assert isinstance(data["insights"], list)
    assert data["langue_source"] == "fr"


def test_resumer_langue():
    with (
        patch("main.get_youtube_transcript", return_value=_TRANSCRIPT_FAKE),
        patch("main.chunk_transcript", return_value=_CHUNKS_FAKE),
        patch("main.llm_complete", return_value=_RESUME_FAKE),
    ):
        r = client.post("/resumer", json={
            "url": "https://youtube.com/watch?v=abc",
            "langue": "English",
        })
    assert r.status_code == 200


def test_resumer_erreur_transcript_400():
    with patch("main.get_youtube_transcript", side_effect=ValueError("Vidéo inaccessible")):
        r = client.post("/resumer", json={"url": "https://youtube.com/watch?v=bad"})
    assert r.status_code == 400
    assert "Vidéo" in r.json()["detail"]


# ── /reel ────────────────────────────────────────────────────────────────────

def test_reel_structure():
    reel_result = {"reel_path": "/clips/test.mp4", "clip_count": 3, "vertical_path": None}
    with (
        patch("main.get_youtube_transcript", return_value=_TRANSCRIPT_FAKE),
        patch("main.chunk_transcript", return_value=_CHUNKS_FAKE),
        patch("main.llm_complete", return_value=_RESUME_FAKE),
        patch("main._highlight_reel", return_value=reel_result),
    ):
        r = client.post("/reel", json={"url": "https://youtube.com/watch?v=abc"})
    assert r.status_code == 200
    data = r.json()
    assert data["reel_path"] == "/clips/test.mp4"
    assert data["clip_count"] == 3
    assert data["titre"] == "Introduction à Python"


def test_reel_erreur_transcript_400():
    with patch("main.get_youtube_transcript", side_effect=ValueError("Privée")):
        r = client.post("/reel", json={"url": "https://youtube.com/watch?v=bad"})
    assert r.status_code == 400
