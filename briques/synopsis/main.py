"""Synopsis — Résumé de vidéos par IA. Gateway-aware, standalone-capable.

Accepte N'IMPORTE QUELLE vidéo :
  • URL YouTube           → transcript natif (rapide, sans téléchargement) ;
  • URL d'un média direct → délégué à la brique transcription (Whisper) ;
  • Fichier uploadé       → audio extrait (ffmpeg) puis transcription (Whisper).
Puis pipeline LLM commune : chunk → analyse → fusion → résumé + chapitres + insights.
"""

import logging
import os
import re
from pathlib import Path
from typing import Optional

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

from lib.extractor import get_youtube_transcript
from lib.chunker import chunk_transcript
from lib.fusion import _extract_chapters, _extract_insights
from lib.llm_client import llm_complete
from lib import transcribe_client, audio
from lib import jobs as _jobs

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("synopsis")

app = FastAPI(title="Synopsis API", version="1.1.0",
              description="Résumé de n'importe quelle vidéo (YouTube, URL, fichier) — Gateway-ready.")
_cors = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()] or ["*"]
app.add_middleware(CORSMiddleware, allow_origins=_cors, allow_methods=["*"], allow_headers=["*"])

try:
    _jobs.init_db()
    logger.info("Jobs DB prête (%s)", _jobs.JOBS_DB)
except Exception as _e:
    logger.warning("init_db jobs échoué : %s", _e)

API_KEYS = {k.strip() for k in os.getenv("API_KEYS", "").split(",") if k.strip()}


def cle_api(x_api_key: Optional[str] = Header(None),
            authorization: Optional[str] = Header(None)) -> str:
    presentee = x_api_key or (authorization or "").removeprefix("Bearer ").strip() or None
    if not API_KEYS:
        return presentee or "public"
    if presentee in API_KEYS:
        return presentee
    raise HTTPException(401, "Clé API manquante ou invalide (header X-API-Key).")


PROMPTS_DIR = Path(__file__).parent / "prompts"
FRONT_HTML = (Path(__file__).parent / "front.html").read_text(encoding="utf-8")
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE_TOKENS", "12000"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP_TOKENS", "1200"))
MODEL = os.getenv("LLM_MODEL", "deepseek/deepseek-v4-flash")


class ResumerRequest(BaseModel):
    url: str = Field(..., description="URL de la vidéo (YouTube ou média direct)")
    langue: str = Field("Français", description="Langue du résumé produit")
    modele: str = Field("", description="Modèle LLM (override)")


class ReelRequest(BaseModel):
    url: str = Field(..., description="YouTube video URL")
    duree_clip: float = Field(45, description="Clip duration per chapter (seconds)")
    sous_titres: bool = Field(True, description="Burn chapter subtitles")
    narration: bool = Field(False, description="Add TTS narration")
    langue_narration: str = Field("fr", description="Narration language")
    export_vertical: str = Field("", description="Vertical export mode: blur, crop, pad")


def _load_prompt(name: str) -> str:
    return (PROMPTS_DIR / name).read_text(encoding="utf-8")


def _run_pipeline(transcript: list[dict], title: str, output_language: str, model: str,
                  langue_source: str = "unknown") -> dict:
    """Pipeline LLM commune à toutes les sources : chunk → analyse → fusion → résumé."""
    model = model or MODEL
    chunks = chunk_transcript(transcript, max_tokens=CHUNK_SIZE, overlap_tokens=CHUNK_OVERLAP)
    if not chunks:
        raise ValueError("Transcript vide — rien à résumer.")

    prompt_tpl = _load_prompt("analyzer.xml")
    analyses = []
    for i, ch in enumerate(chunks):
        prompt = (prompt_tpl.replace("{video_title}", title)
                  .replace("{output_language}", output_language)
                  .replace("{transcript}", ch["text"]))
        logger.info("Analyse chunk %d/%d (%d tokens)", i + 1, len(chunks), ch["tokens"])
        try:
            analyses.append(llm_complete(prompt, model=model))
        except Exception as e:  # noqa: BLE001
            logger.error("Chunk %d failed: %s", i + 1, e)
            analyses.append(f"[Chunk {i+1} error: {e}]")

    if len(analyses) > 1:
        fusion_tpl = _load_prompt("fusion.xml")
        fusion_prompt = (fusion_tpl.replace("{video_title}", title)
                         .replace("{output_language}", output_language)
                         .replace("{analyses}", "\n\n---\n\n".join(analyses)))
        logger.info("Fusion des %d analyses", len(analyses))
        final = llm_complete(fusion_prompt, model=model)
    else:
        final = analyses[0] if analyses else "Aucune analyse produite."

    return {
        "titre": title,
        "resume": final,
        "chapitres": _extract_chapters(final),
        "insights": _extract_insights(final),
        "langue_source": langue_source,
    }


def _est_youtube(url: str) -> bool:
    return bool(re.search(r"(youtube\.com|youtu\.be)", url, re.I))


def _summarize(url: str, output_language: str = "Français", model: str = "") -> dict:
    """Résume une URL — YouTube (transcript natif) ou média direct (brique transcription)."""
    if _est_youtube(url):
        logger.info("Resumer YouTube %s (lang=%s)", url, output_language)
        data = get_youtube_transcript(url)
        return _run_pipeline(data["transcript"], data["title"], output_language, model,
                             langue_source=data.get("language", "unknown"))
    logger.info("Resumer URL média %s (lang=%s)", url, output_language)
    t = transcribe_client.transcrire_url(url)
    return _run_pipeline(t["transcript"], t["titre"], output_language, model,
                         langue_source=t.get("langue", "unknown"))


def _summarize_fichier(contenu: bytes, nom: str, output_language: str, model: str) -> dict:
    """Résume un fichier vidéo/audio quelconque : ffmpeg → transcription → pipeline."""
    audio_wav = audio.extraire_audio(contenu, nom)
    t = transcribe_client.transcrire_fichier(audio_wav, f"{Path(nom).stem or 'media'}.wav")
    titre = Path(nom).stem or "Vidéo"
    return _run_pipeline(t["transcript"], titre, output_language, model,
                         langue_source=t.get("langue", "unknown"))


def _highlight_reel(url, resume, duree_clip, sous_titres, narration, langue_narration, export_vertical) -> dict:
    from lib.video_mounter import create_highlight_reel as _reel
    result = _reel(video_url=url, summary_text=resume, clip_duration=duree_clip,
                   burn_subtitles=sous_titres, tts_narration=narration,
                   tts_lang=langue_narration, export_vertical_mode=export_vertical)
    return {"reel_path": result.get("reel_path"), "clip_count": result.get("clip_count"),
            "vertical_path": result.get("vertical_path")}


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def accueil():
    return HTMLResponse(FRONT_HTML)


# Design system partagé (S123) : tokens visuels du monorepo.
# Source unique = shared/static/workplace.css, copié ici par outils/sync_socle.sh.
@app.get("/workplace.css", include_in_schema=False)
def design_system():
    return FileResponse(Path(__file__).parent / "workplace.css", media_type="text/css")


@app.get("/sante")
def sante():
    checks = {"api": "ok", "version": "1.1.0"}
    try:
        gateway = os.getenv("GATEWAY_URL", "")
        if gateway:
            import httpx
            r = httpx.get(f"{gateway}/health/liveliness", timeout=5)
            checks["gateway"] = "ok" if r.status_code == 200 else f"status {r.status_code}"
        else:
            checks["gateway"] = "non configuré"
    except Exception as e:  # noqa: BLE001
        checks["gateway"] = f"erreur: {e}"
    return checks


def _pipeline_resumer(job_id: str, url: str, langue: str, modele: str):
    try:
        _jobs.maj_statut(job_id, "en_cours", progress_pct=10)
        data = _summarize(url, langue, modele)
        _jobs.maj_statut(job_id, "termine", progress_pct=100, resultat=data)
    except Exception as e:  # noqa: BLE001
        logger.exception("pipeline_resumer job=%s", job_id)
        _jobs.maj_statut(job_id, "erreur", erreur=str(e))


@app.post("/resumer", status_code=202)
def resumer(req: ResumerRequest, background_tasks: BackgroundTasks,
            _cle: str = Depends(cle_api)):
    job_id = _jobs.creer_job("resumer", url=req.url, langue=req.langue)
    background_tasks.add_task(_pipeline_resumer, job_id, req.url, req.langue, req.modele)
    return {"job_id": job_id, "statut": "en_cours", "poll_url": f"/jobs/{job_id}"}


@app.post("/resumer-fichier")
async def resumer_fichier(fichier: UploadFile = File(...),
                          langue: str = Form("Français"),
                          modele: str = Form(""),
                          _cle: str = Depends(cle_api)):
    """Résume N'IMPORTE QUEL fichier vidéo/audio uploadé (ffmpeg → transcription → LLM)."""
    contenu = await fichier.read()
    if not contenu:
        raise HTTPException(status_code=422, detail="Fichier vide.")
    try:
        return _summarize_fichier(contenu, fichier.filename or "media", langue, modele)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:  # noqa: BLE001
        logger.exception("Erreur /resumer-fichier")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/reel")
def reel(req: ReelRequest, _cle: str = Depends(cle_api)):
    try:
        summary = _summarize(req.url, "Français")
        result = _highlight_reel(req.url, summary["resume"], req.duree_clip, req.sous_titres,
                                 req.narration, req.langue_narration, req.export_vertical)
        result["titre"] = summary["titre"]
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:  # noqa: BLE001
        logger.exception("Erreur /reel")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/jobs/{job_id}")
def job_etat(job_id: str):
    job = _jobs.lire_job(job_id)
    if not job:
        raise HTTPException(404, f"Job {job_id} introuvable")
    return {
        "statut": job["statut"],
        "progress_pct": job.get("progress_pct") or 0,
        "resultat": job.get("resultat"),
        "erreur": job.get("erreur"),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "6090")))
