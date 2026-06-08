"""Router voice. Portage de routes/voice.ts (S134). Monté /api/voice, protégé.

STT (``/transcribe``) et TTS (``/synthesize``) en proxy vers des providers externes :
- STT : Groq (défaut, whisper-large-v3-turbo), OpenAI (whisper-1), Deepgram (nova-3).
- TTS : OpenAI (tts-1), ElevenLabs (eleven_multilingual_v2).

Clé provider absente → 503 ; échec amont → 502 (parité Bun). La synthèse renvoie
de l'audio brut (``audio/mpeg``).
"""

from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.auth import get_current_user
from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter(dependencies=[Depends(get_current_user)])

VALID_OPENAI_VOICES = ["alloy", "echo", "fable", "onyx", "nova", "shimmer"]


# ── STT : POST /api/voice/transcribe ────────────────────────────────────
@router.post("/transcribe")
async def transcribe(
    audio: UploadFile | None = File(default=None),
    provider: str = Form(default="groq"),
):
    if audio is None:
        raise HTTPException(status_code=400, detail="Champ audio manquant")

    data = await audio.read()
    filename = audio.filename or "audio.webm"
    content_type = audio.content_type or "audio/webm"

    if provider == "openai":
        return await _stt_openai(data, filename)
    if provider == "deepgram":
        return await _stt_deepgram(data, content_type)
    return await _stt_groq(data, filename)


async def _stt_whisper(url: str, key: str | None, model: str, data: bytes, filename: str, tag: str):
    if not key:
        raise HTTPException(status_code=503, detail=f"{tag} non configuré")
    files = {"file": (filename, data, "application/octet-stream")}
    form = {"model": model, "response_format": "json"}
    async with httpx.AsyncClient(timeout=60.0) as client:
        res = await client.post(url, headers={"Authorization": f"Bearer {key}"}, data=form, files=files)
    if res.status_code >= 400:
        logger.error("[forge:stt] %s %s", url, res.text[:200])
        raise HTTPException(status_code=502, detail="Erreur transcription")
    return {"text": res.json().get("text", "")}


async def _stt_groq(data: bytes, filename: str):
    return await _stt_whisper(
        "https://api.groq.com/openai/v1/audio/transcriptions",
        settings.GROQ_API_KEY, "whisper-large-v3-turbo", data, filename, "GROQ_API_KEY",
    )


async def _stt_openai(data: bytes, filename: str):
    return await _stt_whisper(
        "https://api.openai.com/v1/audio/transcriptions",
        settings.OPENAI_API_KEY, "whisper-1", data, filename, "OPENAI_API_KEY",
    )


async def _stt_deepgram(data: bytes, content_type: str):
    key = settings.DEEPGRAM_API_KEY
    if not key:
        raise HTTPException(status_code=503, detail="DEEPGRAM_API_KEY non configuré")
    async with httpx.AsyncClient(timeout=60.0) as client:
        res = await client.post(
            "https://api.deepgram.com/v1/listen?model=nova-3&smart_format=true",
            headers={"Authorization": f"Token {key}", "Content-Type": content_type or "audio/webm"},
            content=data,
        )
    if res.status_code >= 400:
        logger.error("[forge:stt:deepgram] %s", res.text[:200])
        raise HTTPException(status_code=502, detail="Erreur transcription Deepgram")
    body = res.json()
    try:
        text = body["results"]["channels"][0]["alternatives"][0]["transcript"] or ""
    except (KeyError, IndexError, TypeError):
        text = ""
    return {"text": text}


# ── TTS : POST /api/voice/synthesize ────────────────────────────────────
class SynthBody(BaseModel):
    text: str = Field(min_length=1, max_length=4096)
    provider: str = "openai"
    voice: str = "nova"
    speed: float = Field(default=1, ge=0.25, le=4)


@router.post("/synthesize")
async def synthesize(body: SynthBody):
    if body.provider == "elevenlabs":
        return await _tts_elevenlabs(body.text, body.voice)
    return await _tts_openai(body.text, body.voice, body.speed)


async def _tts_openai(text: str, voice: str, speed: float):
    key = settings.OPENAI_API_KEY
    if not key:
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY non configuré")
    safe_voice = voice if voice in VALID_OPENAI_VOICES else "nova"
    async with httpx.AsyncClient(timeout=60.0) as client:
        res = await client.post(
            "https://api.openai.com/v1/audio/speech",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"model": "tts-1", "input": text, "voice": safe_voice, "speed": speed},
        )
    if res.status_code >= 400:
        logger.error("[forge:tts:openai] %s", res.text[:200])
        raise HTTPException(status_code=502, detail="Erreur synthèse OpenAI")
    return Response(content=res.content, media_type="audio/mpeg", headers={"Cache-Control": "no-cache"})


async def _tts_elevenlabs(text: str, voice_id: str):
    key = settings.ELEVENLABS_API_KEY
    if not key:
        raise HTTPException(status_code=503, detail="ELEVENLABS_API_KEY non configuré")
    vid = voice_id or "EXAVITQu4vr4xnSDxMaL"  # défaut : Sarah
    async with httpx.AsyncClient(timeout=60.0) as client:
        res = await client.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{vid}",
            headers={"xi-api-key": key, "Content-Type": "application/json"},
            json={
                "text": text,
                "model_id": "eleven_multilingual_v2",
                "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
            },
        )
    if res.status_code >= 400:
        logger.error("[forge:tts:elevenlabs] %s", res.text[:200])
        raise HTTPException(status_code=502, detail="Erreur synthèse ElevenLabs")
    return Response(content=res.content, media_type="audio/mpeg", headers={"Cache-Control": "no-cache"})
