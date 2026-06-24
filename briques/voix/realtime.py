"""Chat vocal TEMPS RÉEL (speech-to-speech) — porté du plugin « voice » de Gungnir.

La brique `voix` faisait du TTS one-shot (texte→audio, Piper souverain). Ce module y
AJOUTE le second versant : une conversation vocale bidirectionnelle en relayant un
WebSocket navigateur ↔ l'API temps réel d'un fournisseur. Vrai audio bidirectionnel
(VAD côté fournisseur), PAS de STT/TTS séparé.

Trois fournisseurs (tous derrière une clé, donc INERTES sans clé) :
  • openai — OpenAI Realtime (GPT-4o), PCM16 24 kHz, relais transparent ;
  • google — Gemini Multimodal Live, PCM16 16 kHz→24 kHz, événements normalisés ;
  • grok   — xAI Grok Realtime, protocole OpenAI-compatible.

DÉCOUPLAGE vs Gungnir : l'original lisait des clés PAR-UTILISATEUR en base (UserSettings)
et authentifiait le WS contre une table User. Ici, comme toute brique Workplace, les clés
viennent de l'ENV (héritées du .env racine) et l'auth WS se fait contre `API_KEYS` (jeton
porté par le header Authorization, le sous-protocole `bearer.<jeton>` ou `?token=`). Sans
`API_KEYS`, l'accès est ouvert (cohérent avec le reste de la brique).

Souveraineté : ces relais sont OPT-IN et ne s'activent qu'avec une clé tierce explicite.
Le cœur souverain de `voix` reste Piper (TTS local) ; rien ici ne le remplace.
"""
import asyncio
import json
import logging
import os
from typing import Optional

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger("workplace.voix.realtime")

# Catalogue présenté à l'UI (mode=relay : c'est la brique qui relaie le WS).
PROVIDER_INFO = {
    "openai": {
        "display_name": "OpenAI Realtime",
        "icon": "💚",
        "description": "GPT-4o natif — voix + raisonnement intégrés",
        "mode": "relay",
        "sample_rate_in": 24000,
        "sample_rate_out": 24000,
        "chemin_ws": "/realtime/openai",
        "doc_url": "https://platform.openai.com/docs/guides/realtime",
    },
    "google": {
        "display_name": "Gemini Live",
        "icon": "🔷",
        "description": "Gemini Multimodal Live — conversation native",
        "mode": "relay",
        "sample_rate_in": 16000,
        "sample_rate_out": 24000,
        "chemin_ws": "/realtime/google",
        "doc_url": "https://ai.google.dev/gemini-api/docs/live-api",
    },
    "grok": {
        "display_name": "Grok Realtime",
        "icon": "⚡",
        "description": "xAI Grok — protocole OpenAI-compatible",
        "mode": "relay",
        "sample_rate_in": 24000,
        "sample_rate_out": 24000,
        "chemin_ws": "/realtime/grok",
        "doc_url": "https://docs.x.ai/docs",
    },
}


# ── Configuration (clés par ENV, héritées du .env racine) ─────────────────────

def _api_keys() -> set[str]:
    return {k.strip() for k in os.getenv("API_KEYS", "").split(",") if k.strip()}


def cle_fournisseur(nom: str) -> Optional[str]:
    """Clé du fournisseur temps réel, lue dans l'env. None si non configurée.

    Accepte un alias dédié `VOIX_<X>_API_KEY` (prioritaire) puis la variable
    standard du fournisseur (partagée avec le reste du stack)."""
    candidats = {
        "openai": ("VOIX_OPENAI_API_KEY", "OPENAI_API_KEY"),
        "google": ("VOIX_GOOGLE_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"),
        "grok":   ("VOIX_XAI_API_KEY", "XAI_API_KEY", "GROK_API_KEY"),
    }.get(nom, ())
    for v in candidats:
        val = os.getenv(v)
        if val:
            return val
    return None


def nom_agent() -> str:
    return os.getenv("VOIX_AGENT_NOM", "Assistant")


def fournisseurs_configures() -> dict:
    """Catalogue + état de configuration (pour /voix/realtime et l'UI)."""
    out = {}
    for nom, info in PROVIDER_INFO.items():
        out[nom] = {**info, "configure": bool(cle_fournisseur(nom))}
    return out


# ── Auth WebSocket (jeton brique, pas d'utilisateur en base) ──────────────────

def extraire_jeton(ws: WebSocket) -> str:
    """Jeton du WS : header Authorization > sous-protocole `bearer.<jeton>` > `?token=`.

    On préfère le header / sous-protocole au query param (qui fuit dans les logs proxy
    et l'historique navigateur), mais on accepte `?token=` en repli (compat client web)."""
    auth = ws.headers.get("authorization", "") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    sp = ws.headers.get("sec-websocket-protocol", "") or ""
    for proto in (p.strip() for p in sp.split(",") if p.strip()):
        if proto.startswith("bearer."):
            return proto[len("bearer."):]
    return ws.query_params.get("token", "") or ""


def authentifier(ws: WebSocket) -> bool:
    """Vrai si le WS peut continuer. Ouvert si `API_KEYS` est vide (comme la brique),
    sinon exige un jeton présent dans `API_KEYS`."""
    keys = _api_keys()
    if not keys:
        return True
    return extraire_jeton(ws) in keys


# ── Relais ────────────────────────────────────────────────────────────────────

_INSTRUCTIONS = ("Tu es {agent}, un assistant vocal IA. Parle en français naturellement. "
                 "Sois concis et utile. Ne lis jamais de code — décris ce qu'il fait.")


async def _refuser(ws: WebSocket, message: str, code: int = 1000):
    """Envoie une erreur JSON honnête au client puis ferme proprement."""
    try:
        await ws.send_json({"type": "error", "error": message})
    except Exception:  # noqa: BLE001
        pass
    try:
        await ws.close(code=code)
    except Exception:  # noqa: BLE001
        pass


async def _preambule(ws: WebSocket, fournisseur: str) -> Optional[str]:
    """Accepte le WS, vérifie l'auth + la clé. Retourne la clé, ou None si refusé
    (auquel cas le WS est déjà fermé). Mutualise le début des trois relais."""
    await ws.accept()
    if not authentifier(ws):
        await _refuser(ws, "Authentification requise", code=4001)
        return None
    cle = cle_fournisseur(fournisseur)
    if not cle:
        await _refuser(ws, f"Clé API {fournisseur} non configurée côté brique voix.")
        return None
    try:
        import websockets  # noqa: F401
    except ImportError:
        await _refuser(ws, "Dépendance 'websockets' absente (pip install websockets).")
        return None
    return cle


async def relai_openai(ws: WebSocket):
    """Relais transparent navigateur ↔ OpenAI Realtime (PCM16 24 kHz, VAD serveur)."""
    cle = await _preambule(ws, "openai")
    if not cle:
        return
    import websockets
    try:
        async with websockets.connect(
            "wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview",
            additional_headers={"Authorization": f"Bearer {cle}",
                                "OpenAI-Beta": "realtime=v1"},
        ) as amont:
            await amont.send(json.dumps({
                "type": "session.update",
                "session": {
                    "modalities": ["text", "audio"],
                    "instructions": _INSTRUCTIONS.format(agent=nom_agent()),
                    "voice": "alloy",
                    "input_audio_format": "pcm16",
                    "output_audio_format": "pcm16",
                    "input_audio_transcription": {"model": "whisper-1"},
                    "turn_detection": {"type": "server_vad", "threshold": 0.5},
                    "temperature": 0.7,
                    "max_response_output_tokens": 512,
                },
            }))
            await ws.send_json({"type": "session.ready", "provider": "openai", "voice": "alloy"})
            await _pont_transparent(ws, amont)
    except Exception as e:  # noqa: BLE001
        logger.error(f"OpenAI Realtime: {e}")
        await _refuser(ws, str(e)[:200])


async def relai_grok(ws: WebSocket):
    """Relais transparent navigateur ↔ xAI Grok Realtime (protocole OpenAI-compatible)."""
    cle = await _preambule(ws, "grok")
    if not cle:
        return
    import websockets
    try:
        async with websockets.connect(
            "wss://api.x.ai/v1/realtime",
            additional_headers={"Authorization": f"Bearer {cle}"},
        ) as amont:
            await amont.send(json.dumps({
                "type": "session.update",
                "session": {
                    "modalities": ["text", "audio"],
                    "instructions": _INSTRUCTIONS.format(agent=nom_agent()),
                    "voice": "alloy",
                    "input_audio_format": "pcm16",
                    "output_audio_format": "pcm16",
                    "turn_detection": {"type": "server_vad"},
                    "temperature": 0.7,
                },
            }))
            await ws.send_json({"type": "session.ready", "provider": "grok"})
            await _pont_transparent(ws, amont)
    except Exception as e:  # noqa: BLE001
        logger.error(f"Grok Realtime: {e}")
        await _refuser(ws, str(e)[:200])


async def relai_google(ws: WebSocket):
    """Relais navigateur ↔ Gemini Multimodal Live (événements normalisés)."""
    cle = await _preambule(ws, "google")
    if not cle:
        return
    import websockets
    url = ("wss://generativelanguage.googleapis.com/ws/"
           "google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent"
           f"?key={cle}")
    try:
        async with websockets.connect(url) as amont:
            await amont.send(json.dumps({
                "setup": {
                    "model": "models/gemini-2.0-flash-live-001",
                    "generationConfig": {"temperature": 0.7, "responseModalities": ["AUDIO"]},
                    "systemInstruction": {"parts": [{"text": _INSTRUCTIONS.format(agent=nom_agent())}]},
                    "realtimeInputConfig": {
                        "automaticActivityDetection": {
                            "disabled": False,
                            "startOfSpeechSensitivity": "START_SENSITIVITY_HIGH",
                            "endOfSpeechSensitivity": "END_SENSITIVITY_HIGH",
                            "prefixPaddingMs": 20,
                            "silenceDurationMs": 500,
                        },
                        "activityHandling": "START_OF_ACTIVITY_INTERRUPTS",
                    },
                    "inputAudioTranscription": {},
                    "outputAudioTranscription": {},
                },
            }))
            resp = await asyncio.wait_for(amont.recv(), timeout=10)
            if "setupComplete" not in json.loads(resp):
                await _refuser(ws, f"Setup Gemini échoué : {resp[:200]}")
                return
            await ws.send_json({"type": "session.ready", "provider": "google"})

            async def client_vers_gemini():
                try:
                    while True:
                        msg = json.loads(await ws.receive_text())
                        if msg.get("type") == "audio" and msg.get("data"):
                            await amont.send(json.dumps({"realtimeInput": {"audio": {
                                "data": msg["data"], "mimeType": "audio/pcm;rate=16000"}}}))
                        elif msg.get("type") == "text" and msg.get("text"):
                            await amont.send(json.dumps({"clientContent": {
                                "turns": [{"role": "user", "parts": [{"text": msg["text"]}]}],
                                "turnComplete": True}}))
                except (WebSocketDisconnect, Exception):  # noqa: BLE001
                    pass

            async def gemini_vers_client():
                try:
                    async for message in amont:
                        sc = json.loads(message).get("serverContent", {})
                        for part in sc.get("modelTurn", {}).get("parts", []):
                            if "inlineData" in part:
                                await ws.send_json({"type": "audio",
                                                    "data": part["inlineData"].get("data", ""),
                                                    "mime": part["inlineData"].get("mimeType", "audio/pcm")})
                            elif "text" in part:
                                await ws.send_json({"type": "transcript", "role": "assistant",
                                                    "text": part["text"]})
                        if sc.get("turnComplete"):
                            await ws.send_json({"type": "turn_complete"})
                        if sc.get("interrupted"):
                            await ws.send_json({"type": "interruption"})
                        for champ, role in (("inputTranscription", "user"),
                                            ("outputTranscription", "assistant")):
                            txt = sc.get(champ, {}).get("text")
                            if txt:
                                await ws.send_json({"type": "transcript", "role": role, "text": txt})
                except Exception:  # noqa: BLE001
                    pass

            await asyncio.gather(client_vers_gemini(), gemini_vers_client())
    except Exception as e:  # noqa: BLE001
        logger.error(f"Gemini Live: {e}")
        await _refuser(ws, str(e)[:200])


async def _pont_transparent(ws: WebSocket, amont):
    """Pompe bidirectionnelle texte (protocoles OpenAI-compatibles : on relaie tel quel)."""
    async def client_vers_amont():
        try:
            while True:
                await amont.send(await ws.receive_text())
        except (WebSocketDisconnect, Exception):  # noqa: BLE001
            pass

    async def amont_vers_client():
        try:
            async for message in amont:
                await ws.send_text(message)
        except Exception:  # noqa: BLE001
            pass

    await asyncio.gather(client_vers_amont(), amont_vers_client())
