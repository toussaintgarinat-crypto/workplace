"""Synopsis — YouTube Video Summarizer. Gateway-aware, standalone-capable."""

import logging
import os
from pathlib import Path
from typing import Optional
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from lib.extractor import get_youtube_transcript
from lib.chunker import chunk_transcript
from lib.fusion import _extract_chapters, _extract_insights
from lib.llm_client import llm_complete

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("synopsis")

app = FastAPI(title="Synopsis API", version="1.0.0", description="YouTube video summarizer — Gateway-ready.")
_cors = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()] or ["*"]
app.add_middleware(CORSMiddleware, allow_origins=_cors, allow_methods=["*"], allow_headers=["*"])

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
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE_TOKENS", "12000"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP_TOKENS", "1200"))
MODEL = os.getenv("LLM_MODEL", "deepseek/deepseek-v4-flash")


class ResumerRequest(BaseModel):
    url: str = Field(..., description="YouTube video URL")
    langue: str = Field("Français", description="Summary output language")
    modele: str = Field("", description="LLM model override")


class ReelRequest(BaseModel):
    url: str = Field(..., description="YouTube video URL")
    duree_clip: float = Field(45, description="Clip duration per chapter (seconds)")
    sous_titres: bool = Field(True, description="Burn chapter subtitles")
    narration: bool = Field(False, description="Add TTS narration")
    langue_narration: str = Field("fr", description="Narration language")
    export_vertical: str = Field("", description="Vertical export mode: blur, crop, pad")


def _load_prompt(name: str) -> str:
    return (PROMPTS_DIR / name).read_text(encoding="utf-8")


def _summarize(url: str, output_language: str = "Français", model: str = "") -> dict:
    logger.info("Resumer %s (lang=%s)", url, output_language)
    model = model or MODEL

    data = get_youtube_transcript(url)
    transcript = data["transcript"]
    title = data["title"]
    chunks = chunk_transcript(transcript, max_tokens=CHUNK_SIZE, overlap_tokens=CHUNK_OVERLAP)

    prompt_tpl = _load_prompt("analyzer.xml")
    analyses = []
    for i, ch in enumerate(chunks):
        prompt = prompt_tpl.replace("{video_title}", title).replace("{output_language}", output_language).replace("{transcript}", ch["text"])
        logger.info("Analyse chunk %d/%d (%d tokens)", i + 1, len(chunks), ch["tokens"])
        try:
            result = llm_complete(prompt, model=model)
            analyses.append(result)
        except Exception as e:
            logger.error("Chunk %d failed: %s", i + 1, e)
            analyses.append(f"[Chunk {i+1} error: {e}]")

    if len(analyses) > 1:
        fusion_tpl = _load_prompt("fusion.xml")
        fusion_prompt = fusion_tpl.replace("{video_title}", title).replace("{output_language}", output_language).replace("{analyses}", "\n\n---\n\n".join(analyses))
        logger.info("Fusion des %d analyses", len(analyses))
        final = llm_complete(fusion_prompt, model=model)
    else:
        final = analyses[0] if analyses else "Aucune analyse produite."

    chapters = _extract_chapters(final)
    insights = _extract_insights(final)

    return {
        "titre": title,
        "resume": final,
        "chapitres": chapters,
        "insights": insights,
        "langue_source": data.get("language", "unknown"),
    }


def _highlight_reel(url: str, resume: str, duree_clip: float, sous_titres: bool, narration: bool, langue_narration: str, export_vertical: str) -> dict:
    from lib.video_mounter import create_highlight_reel as _reel
    result = _reel(
        video_url=url,
        summary_text=resume,
        clip_duration=duree_clip,
        burn_subtitles=sous_titres,
        tts_narration=narration,
        tts_lang=langue_narration,
        export_vertical_mode=export_vertical,
    )
    return {"reel_path": result.get("reel_path"), "clip_count": result.get("clip_count"), "vertical_path": result.get("vertical_path")}


@app.get("/sante")
def sante():
    checks = {"api": "ok", "version": "1.0.0"}
    try:
        gateway = os.getenv("GATEWAY_URL", "")
        if gateway:
            import httpx
            r = httpx.get(f"{gateway}/health/liveliness", timeout=5)
            checks["gateway"] = "ok" if r.status_code == 200 else f"status {r.status_code}"
        else:
            checks["gateway"] = "non configuré"
    except Exception as e:
        checks["gateway"] = f"erreur: {e}"
    return checks


@app.post("/resumer")
def resumer(req: ResumerRequest, _cle: str = Depends(cle_api)):
    try:
        result = _summarize(req.url, req.langue, req.modele)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Erreur /resumer")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/reel")
def reel(req: ReelRequest, _cle: str = Depends(cle_api)):
    try:
        summary = _summarize(req.url, "Français")
        result = _highlight_reel(req.url, summary["resume"], req.duree_clip, req.sous_titres, req.narration, req.langue_narration, req.export_vertical)
        result["titre"] = summary["titre"]
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Erreur /reel")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "6090")))
