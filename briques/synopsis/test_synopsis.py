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


# ── Routage YouTube vs média quelconque ──────────────────────────────────────

def test_est_youtube():
    assert main._est_youtube("https://www.youtube.com/watch?v=abc")
    assert main._est_youtube("https://youtu.be/abc")
    assert not main._est_youtube("https://example.com/cours.mp4")
    assert not main._est_youtube("https://vimeo.com/123")


def test_resumer_url_media_delegue_transcription():
    """Une URL NON-YouTube passe par la brique transcription, pas par YouTube."""
    fake = {"transcript": [{"start": 0.0, "text": "Bonjour", "duration": 0.0}],
            "titre": "cours.mp4", "langue": "fr"}
    with (
        patch("main.transcribe_client.transcrire_url", return_value=fake) as mock_tr,
        patch("main.get_youtube_transcript") as mock_yt,
        patch("main.chunk_transcript", return_value=_CHUNKS_FAKE),
        patch("main.llm_complete", return_value=_RESUME_FAKE),
    ):
        r = client.post("/resumer", json={"url": "https://example.com/cours.mp4"})
    assert r.status_code == 200
    assert r.json()["titre"] == "cours.mp4"
    mock_tr.assert_called_once()
    mock_yt.assert_not_called()


# ── /resumer-fichier (n'importe quelle vidéo uploadée) ───────────────────────

def test_resumer_fichier_ok():
    fake = {"transcript": [{"start": 0.0, "text": "Salut", "duration": 0.0}],
            "titre": "ma-video", "langue": "fr"}
    with (
        patch("main.audio.extraire_audio", return_value=b"RIFFfakewav") as mock_audio,
        patch("main.transcribe_client.transcrire_fichier", return_value=fake) as mock_tr,
        patch("main.chunk_transcript", return_value=_CHUNKS_FAKE),
        patch("main.llm_complete", return_value=_RESUME_FAKE),
    ):
        r = client.post("/resumer-fichier",
                        files={"fichier": ("ma-video.mp4", b"\x00\x01videodata", "video/mp4")},
                        data={"langue": "Français"})
    assert r.status_code == 200
    data = r.json()
    assert data["titre"] == "ma-video"
    assert isinstance(data["chapitres"], list)
    mock_audio.assert_called_once()
    mock_tr.assert_called_once()


def test_resumer_fichier_vide_422():
    r = client.post("/resumer-fichier",
                    files={"fichier": ("vide.mp4", b"", "video/mp4")})
    assert r.status_code == 422


def test_resumer_fichier_sans_moteur_400():
    """Si la transcription n'a aucun moteur, on rend une erreur honnête (400)."""
    with patch("main.audio.extraire_audio", return_value=b"wav"), \
         patch("main.transcribe_client.transcrire_fichier",
               side_effect=ValueError("aucun moteur de transcription configuré")):
        r = client.post("/resumer-fichier",
                        files={"fichier": ("v.mp4", b"data", "video/mp4")})
    assert r.status_code == 400
    assert "moteur" in r.json()["detail"]


# ── Normalisation des réponses de la brique transcription ────────────────────

def test_normaliser_place_holder_leve():
    from lib import transcribe_client
    import pytest
    with pytest.raises(ValueError, match="moteur"):
        transcribe_client._normaliser({"place_holder": True, "texte": "", "note": "rien"}, "T")


def test_normaliser_segments_horodates():
    from lib import transcribe_client
    data = {"texte": "a b", "segments": [
        {"start": 0, "text": "a", "duration": 1},
        {"start": 1, "text": "b", "duration": 1}]}
    out = transcribe_client._normaliser(data, "Titre")
    assert len(out["transcript"]) == 2
    assert out["transcript"][0]["text"] == "a"
    assert out["titre"] == "Titre"


def test_normaliser_sans_segments_un_seul_bloc():
    from lib import transcribe_client
    out = transcribe_client._normaliser({"texte": "tout le texte", "segments": []}, "T")
    assert len(out["transcript"]) == 1
    assert out["transcript"][0]["text"] == "tout le texte"


# ── Extraction audio ─────────────────────────────────────────────────────────

def test_extraire_audio_vide_leve():
    from lib import audio
    import pytest
    with pytest.raises(ValueError, match="vide"):
        audio.extraire_audio(b"", "x.mp4")


# ── lib/jobs — persistance async (S179) ──────────────────────────────────────

import os as _os
import tempfile as _tempfile

def _avec_db_temp(monkeypatch, tmp_path):
    """Redirige JOBS_DB vers un fichier temporaire isolé du test."""
    db = tmp_path / "jobs.db"
    import lib.jobs as _j
    monkeypatch.setattr(_j, "JOBS_DB", str(db))
    _j.init_db()
    return _j


def test_jobs_creer_puis_lire(monkeypatch, tmp_path):
    j = _avec_db_temp(monkeypatch, tmp_path)
    jid = j.creer_job("resumer", url="https://youtube.com/watch?v=abc", langue="Français")
    job = j.lire_job(jid)
    assert job["type"] == "resumer"
    assert job["url"] == "https://youtube.com/watch?v=abc"
    assert job["langue"] == "Français"
    assert job["statut"] == "en_cours"
    assert job["progress_pct"] == 0
    assert job["resultat"] is None and job["erreur"] is None


def test_jobs_maj_statut_termine_monkeypatch(monkeypatch, tmp_path):
    j = _avec_db_temp(monkeypatch, tmp_path)
    jid = j.creer_job("resumer")
    j.maj_statut(jid, "termine", resultat={"titre": "T", "resume": "R"}, progress_pct=100)
    job = j.lire_job(jid)
    assert job["statut"] == "termine"
    assert job["progress_pct"] == 100
    assert job["resultat"] == {"titre": "T", "resume": "R"}


def test_jobs_maj_statut_erreur(monkeypatch, tmp_path):
    j = _avec_db_temp(monkeypatch, tmp_path)
    jid = j.creer_job("reel")
    j.maj_statut(jid, "erreur", erreur="Whisper down")
    job = j.lire_job(jid)
    assert job["statut"] == "erreur"
    assert job["erreur"] == "Whisper down"


def test_jobs_lire_job_inexistant_rend_none(monkeypatch, tmp_path):
    j = _avec_db_temp(monkeypatch, tmp_path)
    assert j.lire_job("nexiste-pas") is None


def test_jobs_init_db_idempotent(monkeypatch, tmp_path):
    j = _avec_db_temp(monkeypatch, tmp_path)
    j.init_db()  # ne lève pas
    jid = j.creer_job("resumer")
    assert j.lire_job(jid) is not None


# ── Front servi ──────────────────────────────────────────────────────────────

def test_front_servi():
    r = client.get("/")
    assert r.status_code == 200
    assert "Synopsis" in r.text
    assert "text/html" in r.headers["content-type"]
