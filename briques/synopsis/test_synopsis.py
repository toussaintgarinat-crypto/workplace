"""Tests offline — synopsis : santé, auth, /resumer, /reel (mocks YouTube + LLM + ffmpeg)."""
import importlib
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


@pytest.fixture(autouse=True)
def _uploads_en_tmp(monkeypatch, tmp_path):
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))

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
    assert r.status_code == 202


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
    assert r.status_code == 202
    monkeypatch.setenv("API_KEYS", "")
    importlib.reload(main)


# ── /resumer ─────────────────────────────────────────────────────────────────

def test_resumer_renvoie_202_avec_job_id(monkeypatch, tmp_path):
    import lib.jobs as _j
    monkeypatch.setattr(_j, "JOBS_DB", str(tmp_path / "jobs.db"))
    _j.init_db()
    with (
        patch("main.get_youtube_transcript", return_value=_TRANSCRIPT_FAKE),
        patch("main.chunk_transcript", return_value=_CHUNKS_FAKE),
        patch("main.llm_complete", return_value=_RESUME_FAKE),
    ):
        r = client.post("/resumer", json={"url": "https://youtube.com/watch?v=abc"})
    assert r.status_code == 202
    data = r.json()
    assert "job_id" in data
    assert data["statut"] == "en_cours"
    assert data["poll_url"].startswith("/jobs/")


def test_resumer_job_termine_apres_pipeline(monkeypatch, tmp_path):
    import lib.jobs as _j
    monkeypatch.setattr(_j, "JOBS_DB", str(tmp_path / "jobs.db"))
    _j.init_db()
    with (
        patch("main.get_youtube_transcript", return_value=_TRANSCRIPT_FAKE),
        patch("main.chunk_transcript", return_value=_CHUNKS_FAKE),
        patch("main.llm_complete", return_value=_RESUME_FAKE),
    ):
        r = client.post("/resumer", json={"url": "https://youtube.com/watch?v=abc"})
    jid = r.json()["job_id"]
    job = _j.lire_job(jid)
    assert job["statut"] == "termine"
    assert job["resultat"]["titre"] == "Introduction à Python"
    assert "resume" in job["resultat"]


def test_resumer_job_erreur_sur_value_error(monkeypatch, tmp_path):
    import lib.jobs as _j
    monkeypatch.setattr(_j, "JOBS_DB", str(tmp_path / "jobs.db"))
    _j.init_db()
    with patch("main.get_youtube_transcript", side_effect=ValueError("Vidéo inaccessible")):
        r = client.post("/resumer", json={"url": "https://youtube.com/watch?v=bad"})
    assert r.status_code == 202
    jid = r.json()["job_id"]
    job = _j.lire_job(jid)
    assert job["statut"] == "erreur"
    assert "Vidéo inaccessible" in (job["erreur"] or "")


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
    assert r.status_code == 202


# ── /reel ────────────────────────────────────────────────────────────────────

def test_reel_renvoie_202_avec_job_id(monkeypatch, tmp_path):
    import lib.jobs as _j
    monkeypatch.setattr(_j, "JOBS_DB", str(tmp_path / "jobs.db"))
    _j.init_db()
    reel_result = {"reel_path": "/clips/test.mp4", "clip_count": 3, "vertical_path": None}
    with (
        patch("main.get_youtube_transcript", return_value=_TRANSCRIPT_FAKE),
        patch("main.chunk_transcript", return_value=_CHUNKS_FAKE),
        patch("main.llm_complete", return_value=_RESUME_FAKE),
        patch("main._highlight_reel", return_value=reel_result),
    ):
        r = client.post("/reel", json={"url": "https://youtube.com/watch?v=abc"})
    assert r.status_code == 202
    data = r.json()
    assert "job_id" in data
    assert data["statut"] == "en_cours"


def test_reel_job_termine_contient_reel_path_titre(monkeypatch, tmp_path):
    import lib.jobs as _j
    monkeypatch.setattr(_j, "JOBS_DB", str(tmp_path / "jobs.db"))
    _j.init_db()
    reel_result = {"reel_path": "/clips/test.mp4", "clip_count": 3, "vertical_path": None}
    with (
        patch("main.get_youtube_transcript", return_value=_TRANSCRIPT_FAKE),
        patch("main.chunk_transcript", return_value=_CHUNKS_FAKE),
        patch("main.llm_complete", return_value=_RESUME_FAKE),
        patch("main._highlight_reel", return_value=reel_result),
    ):
        r = client.post("/reel", json={"url": "https://youtube.com/watch?v=abc"})
    jid = r.json()["job_id"]
    job = _j.lire_job(jid)
    assert job["statut"] == "termine"
    assert job["resultat"]["reel_path"] == "/clips/test.mp4"
    assert job["resultat"]["titre"] == "Introduction à Python"


def test_reel_job_erreur_sur_value_error(monkeypatch, tmp_path):
    import lib.jobs as _j
    monkeypatch.setattr(_j, "JOBS_DB", str(tmp_path / "jobs.db"))
    _j.init_db()
    with patch("main.get_youtube_transcript", side_effect=ValueError("Privée")):
        r = client.post("/reel", json={"url": "https://youtube.com/watch?v=bad"})
    assert r.status_code == 202
    jid = r.json()["job_id"]
    job = _j.lire_job(jid)
    assert job["statut"] == "erreur"
    assert "Privée" in (job["erreur"] or "")


# ── Routage YouTube vs média quelconque ──────────────────────────────────────

def test_est_youtube():
    assert main._est_youtube("https://www.youtube.com/watch?v=abc")
    assert main._est_youtube("https://youtu.be/abc")
    assert not main._est_youtube("https://example.com/cours.mp4")
    assert not main._est_youtube("https://vimeo.com/123")


def test_resumer_url_media_delegue_transcription(monkeypatch, tmp_path):
    """Une URL NON-YouTube passe par la brique transcription, pas par YouTube."""
    import lib.jobs as _j
    monkeypatch.setattr(_j, "JOBS_DB", str(tmp_path / "jobs.db"))
    _j.init_db()
    fake = {"transcript": [{"start": 0.0, "text": "Bonjour", "duration": 0.0}],
            "titre": "cours.mp4", "langue": "fr"}
    with (
        patch("main.transcribe_client.transcrire_url", return_value=fake) as mock_tr,
        patch("main.get_youtube_transcript") as mock_yt,
        patch("main.chunk_transcript", return_value=_CHUNKS_FAKE),
        patch("main.llm_complete", return_value=_RESUME_FAKE),
    ):
        r = client.post("/resumer", json={"url": "https://example.com/cours.mp4"})
    assert r.status_code == 202
    jid = r.json()["job_id"]
    job = _j.lire_job(jid)
    assert job["statut"] == "termine"
    assert job["resultat"]["titre"] == "cours.mp4"
    mock_tr.assert_called_once()
    mock_yt.assert_not_called()


# ── /resumer-fichier (n'importe quelle vidéo uploadée) ───────────────────────

def test_resumer_fichier_renvoie_202_avec_job_id(monkeypatch, tmp_path):
    import lib.jobs as _j
    monkeypatch.setattr(_j, "JOBS_DB", str(tmp_path / "jobs.db"))
    _j.init_db()
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
    assert r.status_code == 202
    data = r.json()
    assert "job_id" in data
    assert data["statut"] == "en_cours"
    jid = data["job_id"]
    job = _j.lire_job(jid)
    assert job["statut"] == "termine"
    assert job["resultat"]["titre"] == "ma-video"
    mock_audio.assert_called_once()
    mock_tr.assert_called_once()


def test_resumer_fichier_vide_422():
    r = client.post("/resumer-fichier",
                    files={"fichier": ("vide.mp4", b"", "video/mp4")})
    assert r.status_code == 422


def test_resumer_fichier_job_erreur_sur_value_error(monkeypatch, tmp_path):
    import lib.jobs as _j
    monkeypatch.setattr(_j, "JOBS_DB", str(tmp_path / "jobs.db"))
    _j.init_db()
    with patch("main.audio.extraire_audio", return_value=b"wav"), \
         patch("main.transcribe_client.transcrire_fichier",
               side_effect=ValueError("aucun moteur de transcription configuré")):
        r = client.post("/resumer-fichier",
                        files={"fichier": ("v.mp4", b"data", "video/mp4")})
    assert r.status_code == 202
    jid = r.json()["job_id"]
    job = _j.lire_job(jid)
    assert job["statut"] == "erreur"
    assert "moteur" in (job["erreur"] or "")


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


# ── GET /jobs/{id} — polling async (S179) ────────────────────────────────────

def test_jobs_endpoint_rend_un_job_en_cours(monkeypatch, tmp_path):
    import lib.jobs as _j
    monkeypatch.setattr(_j, "JOBS_DB", str(tmp_path / "jobs.db"))
    _j.init_db()
    jid = _j.creer_job("resumer", url="https://youtube.com/watch?v=abc")
    r = client.get(f"/jobs/{jid}")
    assert r.status_code == 200
    data = r.json()
    assert data["statut"] == "en_cours"
    assert data["progress_pct"] == 0
    assert "resultat" in data and data["resultat"] is None


def test_jobs_endpoint_rend_un_job_termine_avec_resultat(monkeypatch, tmp_path):
    import lib.jobs as _j
    monkeypatch.setattr(_j, "JOBS_DB", str(tmp_path / "jobs.db"))
    _j.init_db()
    jid = _j.creer_job("resumer")
    _j.maj_statut(jid, "termine", resultat={"titre": "T", "resume": "R"}, progress_pct=100)
    r = client.get(f"/jobs/{jid}")
    assert r.status_code == 200
    data = r.json()
    assert data["statut"] == "termine"
    assert data["progress_pct"] == 100
    assert data["resultat"]["titre"] == "T"


def test_jobs_endpoint_rend_une_erreur_en_200_pas_500(monkeypatch, tmp_path):
    import lib.jobs as _j
    monkeypatch.setattr(_j, "JOBS_DB", str(tmp_path / "jobs.db"))
    _j.init_db()
    jid = _j.creer_job("resumer")
    _j.maj_statut(jid, "erreur", erreur="Vidéo inaccessible")
    r = client.get(f"/jobs/{jid}")
    assert r.status_code == 200
    data = r.json()
    assert data["statut"] == "erreur"
    assert data["erreur"] == "Vidéo inaccessible"


def test_jobs_endpoint_404_si_inexistant():
    r = client.get("/jobs/nexiste-pas-uuid")
    assert r.status_code == 404


# ── Front servi ──────────────────────────────────────────────────────────────

def test_front_servi():
    r = client.get("/")
    assert r.status_code == 200
    assert "Synopsis" in r.text
    assert "text/html" in r.headers["content-type"]


# ── Extraction du sommaire (chapitrage) — robustesse (S181) ───────────────────
# Régression : le sommaire disparaissait dès que le LLM s'écartait un peu du
# gabarit (HH:MM:SS des vidéos longues, emoji omis, titre traduit).

from lib.fusion import _extract_chapters, _extract_insights, _ts_to_seconds

_SYNOPSIS_BASE = (
    "# 📺 ANALYSE VIDÉO : Test\n"
    "## 🚀 Résumé Exécutif (TL;DR)\n> Bla bla.\n"
    "## 📍 Chapitrage Temporel\n"
    "| Time | Sujet | Description |\n"
    "| :--- | :--- | :--- |\n"
    "| [00:12] | *Intro* | Présentation |\n"
    "| [03:45] | *Sujet* | Détail |\n"
    "## 💡 Top 3 Moments Forts (Insights)\n"
    "1. *Le pic* [01:10] : moment clé\n"
    "2. *La chute* [02:30] : autre moment\n"
)


def test_chapitres_format_exact():
    ch = _extract_chapters(_SYNOPSIS_BASE)
    assert [c["subject"] for c in ch] == ["Intro", "Sujet"]
    assert ch[0]["timestamp"] == "00:12" and ch[0]["ts_seconds"] == 12


def test_chapitres_video_longue_hhmmss():
    md = _SYNOPSIS_BASE.replace("[00:12]", "[1:05:12]").replace("[03:45]", "[1:22:40]")
    ch = _extract_chapters(md)
    assert len(ch) == 2
    assert ch[0]["ts_seconds"] == 3912  # 1*3600 + 5*60 + 12


def test_chapitres_sans_emoji_dans_le_titre():
    md = _SYNOPSIS_BASE.replace("## 📍 Chapitrage Temporel", "## Chapitrage Temporel")
    assert len(_extract_chapters(md)) == 2


def test_chapitres_titre_de_section_traduit():
    md = (_SYNOPSIS_BASE
          .replace("## 📍 Chapitrage Temporel", "## 📍 Timeline Chapters")
          .replace("## 💡 Top 3 Moments Forts (Insights)", "## 💡 Key Moments"))
    assert len(_extract_chapters(md)) == 2
    assert len(_extract_insights(md)) == 2


def test_chapitres_plage_horaire_prend_le_debut():
    md = _SYNOPSIS_BASE.replace("[00:12]", "[00:12 – 03:45]")
    ch = _extract_chapters(md)
    assert ch[0]["ts_seconds"] == 12


def test_chapitres_ignore_ligne_separatrice():
    # La ligne | :--- | :--- | :--- | ne doit jamais devenir un chapitre.
    ch = _extract_chapters(_SYNOPSIS_BASE)
    assert all(c["subject"] not in (":---", "---") for c in ch)


def test_chapitres_vide_si_aucun_tableau():
    assert _extract_chapters("# Titre\n> juste du texte, aucun sommaire") == []
    assert _extract_chapters("") == []


def test_insights_hhmmss():
    md = _SYNOPSIS_BASE.replace("[01:10]", "[1:01:10]")
    ins = _extract_insights(md)
    assert ins[0]["timestamp"] == "1:01:10"


def test_ts_to_seconds():
    assert _ts_to_seconds("03:45") == 225
    assert _ts_to_seconds("1:05:12") == 3912


def test_extraction_multilingue_6_langues():
    # Le LLM traduit souvent les titres de section dans la langue de sortie ;
    # chapitres ET points clés doivent survivre pour les 6 langues de l'UI.
    def mk(chap_h, ins_h):
        return (f"# Titre\n## {chap_h}\n| T | S | D |\n| :--- | :--- | :--- |\n"
                f"| [00:12] | Intro | d |\n| [03:45] | Sujet | d |\n"
                f"## {ins_h}\n1. Le pic [01:10] : cle\n2. La chute [02:30] : autre\n")
    cas = {
        "FR": ("📍 Chapitrage Temporel", "💡 Moments Forts (Insights)"),
        "EN": ("📍 Timeline Chapters", "💡 Key Moments"),
        "ES": ("📍 Capítulos Temporales", "💡 Momentos Clave"),
        "DE": ("📍 Zeitliche Kapitel", "💡 Höhepunkte"),
        "PT": ("📍 Capítulos Temporais", "💡 Momentos-Chave"),
        "IT": ("📍 Capitoli Temporali", "💡 Momenti Salienti"),
    }
    for lg, (ch, ins) in cas.items():
        md = mk(ch, ins)
        assert len(_extract_chapters(md)) == 2, f"chapitres KO pour {lg}"
        assert len(_extract_insights(md)) == 2, f"insights KO pour {lg}"
