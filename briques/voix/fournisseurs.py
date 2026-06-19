"""Fournisseurs de SYNTHÈSE VOCALE (TTS) — registre PROVIDER-AGNOSTIQUE (miroir transcription).

Un texte peut être vocalisé par plusieurs moteurs, essayés dans un ORDRE de préférence
configurable (`VOIX_PROVIDERS`). Chaque fournisseur expose la même interface minimale :

    nom            : identifiant court (clé du registre, valeur de `backend`) ;
    disponible()   : la config est-elle là (binaire/modèle/clé) ? — sync, SANS réseau ;
    async synthetiser(texte, voix, langue, format) -> (octets_audio, format) | LÈVE

Comme la transcription, la synthèse a un moteur SOUVERAIN local : **Piper** (TTS neuronal
rapide, CPU). Donc `piper` est le DÉFAUT, en tête de l'ordre — le texte ne sort pas de la
maison. Les fournisseurs hébergés (OpenAI, ElevenLabs, la Gateway) ne sont qu'un repli
OPT-IN pour qui les configure. Sans rien, le moteur (moteur.py) rend un repli HONNÊTE qui
le DIT (audio absent, `place_holder: true`) — jamais d'audio inventé, jamais de fausse voix.

Aucune clé n'est embarquée : tout se configure par variables d'env (cf. docker-compose.yml).
Piper a besoin d'un modèle de voix (`PIPER_VOICE` = chemin d'un .onnx) — sans lui, le moteur
souverain est simplement « non disponible » et on retombe sur le suivant, puis le placeholder.
"""
import asyncio
import os
import shutil
import subprocess
import tempfile
from typing import Optional

import httpx

_FMT_OPUS = {"opus", "ogg", "oga"}


def _vers_opus(wav: bytes) -> Optional[bytes]:
    """WAV → Ogg/Opus via ffmpeg (pour la bulle vocale Telegram `sendVoice`).

    Renvoie les octets Ogg/Opus, ou None si ffmpeg est absent / échoue (repli HONNÊTE :
    l'appelant garde alors le WAV, envoyé en fichier audio plutôt qu'en bulle vocale)."""
    binaire = os.getenv("FFMPEG_BIN", "ffmpeg")
    if not shutil.which(binaire):
        return None
    try:
        p = subprocess.run(
            [binaire, "-hide_banner", "-loglevel", "error", "-i", "pipe:0",
             "-c:a", "libopus", "-f", "ogg", "pipe:1"],
            input=wav, capture_output=True, timeout=int(os.getenv("FFMPEG_TIMEOUT_S", "60")))
        return p.stdout if (p.returncode == 0 and p.stdout) else None
    except Exception:  # noqa: BLE001 — ffmpeg KO → repli honnête (on garde le WAV)
        return None


# ── Moteur SOUVERAIN local : Piper ──────────────────────────────
class Piper:
    """Piper TTS en local (binaire `piper`, installé via `piper-tts`). SOUVERAIN : le texte
    ne quitte pas la machine. On pilote le binaire en sous-processus (interface stable, à
    l'abri des changements d'API Python), sortie WAV. La voix est un modèle .onnx désigné
    par `PIPER_VOICE` (téléchargé une fois) ; sans modèle, le moteur est « non disponible »."""
    nom = "piper"

    def _bin(self) -> str:
        return os.getenv("PIPER_BIN", "piper")

    def _voix(self, voix: Optional[str] = None) -> Optional[str]:
        return voix or os.getenv("PIPER_VOICE") or None

    def disponible(self) -> bool:
        # Désactivable par env (tests déterministes / opt-out). Sinon : présent ssi le binaire
        # piper est dans le PATH ET un modèle de voix est configuré. Aucun réseau ici.
        if os.getenv("VOIX_LOCAL", "1") in ("0", "", "false", "no"):
            return False
        return bool(self._voix()) and shutil.which(self._bin()) is not None

    async def synthetiser(self, texte, voix, langue, format) -> tuple[bytes, str]:
        # Piper est synchrone → on le sort de la boucle asyncio.
        cible = (format or os.getenv("VOIX_FORMAT", "opus") or "").lower()
        return await asyncio.to_thread(self._bloquant, texte, voix, cible)

    def _bloquant(self, texte: str, voix: Optional[str], cible: str) -> tuple[bytes, str]:
        modele = self._voix(voix)
        if not modele or not os.path.exists(modele):
            raise RuntimeError("Modèle Piper introuvable (PIPER_VOICE).")
        chemin = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name
        try:
            p = subprocess.run(
                [self._bin(), "--model", modele, "--output_file", chemin],
                input=texte.encode("utf-8"), capture_output=True,
                timeout=int(os.getenv("PIPER_TIMEOUT_S", "120")))
            if p.returncode != 0:
                raise RuntimeError("Piper a échoué : "
                                   + p.stderr.decode("utf-8", "ignore")[:160])
            with open(chemin, "rb") as f:
                audio = f.read()
        finally:
            try:
                os.unlink(chemin)
            except OSError:
                pass
        if not audio:
            raise RuntimeError("Piper n'a produit aucun audio.")
        # Piper sort du WAV ; pour une bulle vocale Telegram on convertit en Ogg/Opus.
        # Repli HONNÊTE : si ffmpeg manque, on garde le WAV (envoyé en fichier audio).
        if cible in _FMT_OPUS:
            opus = _vers_opus(audio)
            if opus:
                return opus, "ogg"
        return audio, "wav"


# ── Base HTTP pour les fournisseurs hébergés ────────────────────
class _HTTP:
    nom = ""
    timeout = 120

    def disponible(self) -> bool:
        raise NotImplementedError

    async def synthetiser(self, texte, voix, langue, format) -> tuple[bytes, str]:
        raise NotImplementedError


class OpenAI(_HTTP):
    """OpenAI /v1/audio/speech (tts-1 / tts-1-hd). Formats : opus (idéal message vocal Telegram),
    mp3, aac, flac, wav, pcm. Voix par défaut paramétrable (OPENAI_TTS_VOICE)."""
    nom = "openai"

    def disponible(self):
        return bool(os.getenv("OPENAI_API_KEY"))

    def _base(self):
        return os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")

    async def synthetiser(self, texte, voix, langue, format):
        fmt = format or os.getenv("VOIX_FORMAT", "opus")
        body = {"model": os.getenv("OPENAI_TTS_MODEL", "tts-1"), "input": texte,
                "voice": voix or os.getenv("OPENAI_TTS_VOICE", "alloy"),
                "response_format": fmt}
        async with httpx.AsyncClient(timeout=self.timeout) as c:
            r = await c.post(f"{self._base()}/audio/speech",
                             headers={"Authorization": f"Bearer {os.getenv('OPENAI_API_KEY')}"},
                             json=body)
            r.raise_for_status()
            return r.content, fmt


class ElevenLabs(_HTTP):
    """ElevenLabs text-to-speech. Voix multilingue de qualité. Sortie mp3 par défaut
    (output_format paramétrable). `ELEVENLABS_VOICE_ID` choisit la voix, `ELEVENLABS_MODEL`
    le modèle (eleven_multilingual_v2 par défaut)."""
    nom = "elevenlabs"

    def disponible(self):
        return bool(os.getenv("ELEVENLABS_API_KEY"))

    async def synthetiser(self, texte, voix, langue, format):
        voix_id = voix or os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")
        sortie = os.getenv("ELEVENLABS_FORMAT", "mp3_44100_128")
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voix_id}"
        body = {"text": texte, "model_id": os.getenv("ELEVENLABS_MODEL",
                                                      "eleven_multilingual_v2")}
        async with httpx.AsyncClient(timeout=self.timeout) as c:
            r = await c.post(url, params={"output_format": sortie},
                             headers={"xi-api-key": os.getenv("ELEVENLABS_API_KEY")}, json=body)
            r.raise_for_status()
            # output_format "opus_48000_..." → conteneur ogg ; sinon mp3.
            return r.content, ("opus" if sortie.startswith("opus") else "mp3")


class Gateway(_HTTP):
    """Passe par la GATEWAY Workplace (proxy OpenAI-compatible /audio/speech). AUCUNE clé
    propre : réutilise la clé posée côté Gateway. Honnête : si la Gateway ne route pas le
    TTS, l'appel échoue et on retombe sur le fournisseur suivant (jamais de fausse voix)."""
    nom = "gateway"

    def disponible(self):
        return bool(os.getenv("GATEWAY_KEY"))

    def _url(self):
        return os.getenv("GATEWAY_URL", "http://host.docker.internal:4001").rstrip("/")

    async def synthetiser(self, texte, voix, langue, format):
        fmt = format or os.getenv("VOIX_FORMAT", "opus")
        body = {"model": os.getenv("VOIX_GATEWAY_MODEL", "tts-1"), "input": texte,
                "voice": voix or os.getenv("VOIX_GATEWAY_VOICE", "alloy"),
                "response_format": fmt}
        async with httpx.AsyncClient(timeout=self.timeout) as c:
            r = await c.post(f"{self._url()}/v1/audio/speech",
                             headers={"Authorization": f"Bearer {os.getenv('GATEWAY_KEY')}"},
                             json=body)
            r.raise_for_status()
            return r.content, fmt


# ── Registre + ordre de préférence ──────────────────────────────
REGISTRE = {f.nom: f for f in (Piper(), OpenAI(), ElevenLabs(), Gateway())}

# Défaut : SOUVERAIN d'abord (`piper`), puis les hébergés. Surchargé par VOIX_PROVIDERS.
ORDRE_DEFAUT = ["piper", "openai", "elevenlabs", "gateway"]


def ordre() -> list:
    """Ordre de préférence effectif (filtré sur les fournisseurs connus du registre)."""
    brut = [n.strip().lower() for n in os.getenv("VOIX_PROVIDERS", "").split(",") if n.strip()]
    noms = brut or ORDRE_DEFAUT
    return [n for n in noms if n in REGISTRE]


def disponibles() -> list:
    """Fournisseurs configurés (binaire/modèle/clé présent), dans l'ordre de préférence."""
    return [n for n in ordre() if REGISTRE[n].disponible()]
