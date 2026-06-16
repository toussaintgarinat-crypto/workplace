"""Fournisseurs de TRANSCRIPTION — registre PROVIDER-AGNOSTIQUE (miroir images/vidéo).

Un audio peut être transcrit par plusieurs moteurs, essayés dans un ORDRE de préférence
configurable (`TRANSCRIPTION_PROVIDERS`). Chaque fournisseur expose la même interface :

    nom               : identifiant court (clé du registre, valeur de `backend`) ;
    disponible()      : la config est-elle là ? — sync, SANS réseau ;
    async transcrire(audio, nom_fichier, langue, diarisation) -> dict | LÈVE

La grande différence avec images/vidéo : **la transcription a un moteur SOUVERAIN local**
(Whisper tourne très bien sur CPU/Metal, pas besoin de GPU). Donc `local` est le DÉFAUT,
en tête de l'ordre — l'audio ne sort pas de la maison. Les fournisseurs hébergés ne sont
qu'un repli OPT-IN pour qui les configure. Sans rien, le moteur (moteur.py) rend un repli
HONNÊTE qui le DIT (jamais de fausse transcription, jamais de texte inventé).

Le résultat normalisé d'un `transcrire(...)` :

    {
      "texte":       "transcription complète",
      "segments":    [{"debut": 0.0, "fin": 3.2, "texte": "...", "locuteur": "A"?}],
      "langue":      "fr",            # langue détectée ou imposée
      "diarisation": true | false,    # des locuteurs sont-ils identifiés ?
    }

Fournisseurs livrés :
  • local      — Whisper local (faster-whisper, CPU/Metal). SOUVERAIN. Diarisation pyannote
                 best-effort si installée + HF_TOKEN, sinon diarisation honnêtement false ;
  • openai     — OpenAI /audio/transcriptions (whisper-1 / gpt-4o-transcribe). Pas de
                 diarisation côté API → diarisation false ;
  • deepgram   — Deepgram /v1/listen (diarize=true) : segments AVEC locuteurs ;
  • assemblyai — AssemblyAI (speaker_labels=true) : soumission + polling, AVEC locuteurs ;
  • gateway    — via la GATEWAY Workplace (proxy OpenAI-compatible /audio/transcriptions),
                 zéro clé propre : réutilise la clé posée côté Gateway.

Aucune clé n'est embarquée : tout se configure par variables d'env (cf. docker-compose.yml).
"""
import asyncio
import importlib.util
import os
import tempfile
from typing import Optional

import httpx


# ── Helpers de normalisation ────────────────────────────────────
def _texte_de_segments(segments: list) -> str:
    return " ".join(s.get("texte", "").strip() for s in segments if s.get("texte")).strip()


# ── Moteur SOUVERAIN local : Whisper (faster-whisper) ───────────
class Local:
    """Whisper en local (faster-whisper). SOUVERAIN : l'audio ne quitte pas la machine.

    Le modèle est chargé PARESSEUSEMENT (au 1er appel) et mis en cache process — pas de
    coût au démarrage ni en /sante. Taille du modèle paramétrable (WHISPER_MODEL, défaut
    `base` : bon compromis CPU). Diarisation pyannote en best-effort : si elle échoue ou
    n'est pas installée, on rend la transcription SANS locuteurs (diarisation: false) —
    jamais d'invention."""
    nom = "local"
    _modele = None  # cache process du WhisperModel

    def disponible(self) -> bool:
        # Désactivable par env (tests déterministes / opt-out). Sinon : présent ssi la lib
        # faster-whisper est installée. Aucun réseau, aucun chargement de modèle ici.
        if os.getenv("TRANSCRIPTION_LOCAL", "1") in ("0", "", "false", "no"):
            return False
        return importlib.util.find_spec("faster_whisper") is not None

    def _charger(self):
        if Local._modele is None:
            from faster_whisper import WhisperModel  # import tardif (lib lourde)
            taille = os.getenv("WHISPER_MODEL", "base")
            device = os.getenv("WHISPER_DEVICE", "cpu")
            calcul = os.getenv("WHISPER_COMPUTE", "int8")
            Local._modele = WhisperModel(taille, device=device, compute_type=calcul)
        return Local._modele

    def _diariser(self, chemin: str, segments: list) -> bool:
        """Best-effort pyannote : étiquette chaque segment d'un locuteur. Retourne True si
        des locuteurs ont été posés, False sinon (lib absente / pas de HF_TOKEN / erreur)."""
        if os.getenv("DIARISATION_LOCAL", "") in ("", "0", "false", "no"):
            return False
        if not os.getenv("HF_TOKEN"):
            return False
        try:                       # find_spec LÈVE si le parent `pyannote` est absent
            if importlib.util.find_spec("pyannote.audio") is None:
                return False
        except ModuleNotFoundError:
            return False
        try:
            from pyannote.audio import Pipeline
            pipe = Pipeline.from_pretrained(
                os.getenv("PYANNOTE_MODEL", "pyannote/speaker-diarization-3.1"),
                use_auth_token=os.getenv("HF_TOKEN"))
            diar = pipe(chemin)
            tours = [(t.start, t.end, lab) for t, _, lab in diar.itertracks(yield_label=True)]
            for seg in segments:
                centre = (seg["debut"] + seg["fin"]) / 2
                loc = next((lab for d, f, lab in tours if d <= centre <= f), None)
                if loc is not None:
                    seg["locuteur"] = str(loc)
            return any("locuteur" in s for s in segments)
        except Exception:  # noqa: BLE001 — diarisation best-effort : on dégrade honnêtement
            return False

    async def transcrire(self, audio: bytes, nom_fichier: str,
                         langue: Optional[str], diarisation: bool) -> dict:
        # faster-whisper est synchrone et CPU-lourd → on le sort de la boucle asyncio.
        return await asyncio.to_thread(self._transcrire_bloquant, audio, langue, diarisation)

    def _transcrire_bloquant(self, audio, langue, diarisation) -> dict:
        modele = self._charger()
        with tempfile.NamedTemporaryFile(suffix=".audio", delete=True) as tmp:
            tmp.write(audio)
            tmp.flush()
            segs, info = modele.transcribe(tmp.name, language=langue or None)
            segments = [{"debut": round(s.start, 2), "fin": round(s.end, 2),
                         "texte": s.text.strip()} for s in segs]
            diarise = self._diariser(tmp.name, segments) if diarisation else False
        return {"texte": _texte_de_segments(segments), "segments": segments,
                "langue": getattr(info, "language", None) or langue, "diarisation": diarise}


# ── Base HTTP pour les fournisseurs hébergés ────────────────────
class _HTTP:
    nom = ""
    timeout = 300

    def disponible(self) -> bool:
        raise NotImplementedError

    async def transcrire(self, audio, nom_fichier, langue, diarisation) -> dict:
        raise NotImplementedError


class OpenAI(_HTTP):
    """OpenAI /v1/audio/transcriptions. `verbose_json` rend des segments horodatés. L'API
    Whisper d'OpenAI n'identifie PAS les locuteurs → diarisation honnêtement false."""
    nom = "openai"

    def disponible(self):
        return bool(os.getenv("OPENAI_API_KEY"))

    def _base(self):
        return os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")

    async def transcrire(self, audio, nom_fichier, langue, diarisation):
        modele = os.getenv("OPENAI_TRANSCRIBE_MODEL", "whisper-1")
        data = {"model": modele, "response_format": "verbose_json"}
        if langue:
            data["language"] = langue
        files = {"file": (nom_fichier or "audio.wav", audio)}
        async with httpx.AsyncClient(timeout=self.timeout) as c:
            r = await c.post(f"{self._base()}/audio/transcriptions",
                             headers={"Authorization": f"Bearer {os.getenv('OPENAI_API_KEY')}"},
                             data=data, files=files)
            r.raise_for_status()
            rep = r.json()
        segments = [{"debut": round(s.get("start", 0), 2), "fin": round(s.get("end", 0), 2),
                     "texte": (s.get("text") or "").strip()} for s in rep.get("segments", [])]
        return {"texte": (rep.get("text") or _texte_de_segments(segments)).strip(),
                "segments": segments, "langue": rep.get("language") or langue,
                "diarisation": False}


class Deepgram(_HTTP):
    """Deepgram /v1/listen avec diarize=true : rend des MOTS étiquetés d'un locuteur, qu'on
    regroupe en segments par locuteur. Diarisation native → diarisation true."""
    nom = "deepgram"

    def disponible(self):
        return bool(os.getenv("DEEPGRAM_API_KEY"))

    async def transcrire(self, audio, nom_fichier, langue, diarisation):
        params = {"model": os.getenv("DEEPGRAM_MODEL", "nova-2"),
                  "smart_format": "true", "punctuate": "true"}
        if diarisation:
            params["diarize"] = "true"
        if langue:
            params["language"] = langue
        async with httpx.AsyncClient(timeout=self.timeout) as c:
            r = await c.post("https://api.deepgram.com/v1/listen", params=params, content=audio,
                             headers={"Authorization": f"Token {os.getenv('DEEPGRAM_API_KEY')}",
                                      "Content-Type": "audio/*"})
            r.raise_for_status()
            rep = r.json()
        alt = (((rep.get("results") or {}).get("channels") or [{}])[0].get("alternatives")
               or [{}])[0]
        mots = alt.get("words") or []
        segments, courant = [], None
        for m in mots:
            loc = str(m.get("speaker")) if m.get("speaker") is not None else None
            mot = m.get("punctuated_word") or m.get("word") or ""
            if courant is None or courant.get("locuteur") != loc:
                courant = {"debut": round(m.get("start", 0), 2), "fin": round(m.get("end", 0), 2),
                           "texte": mot}
                if loc is not None:
                    courant["locuteur"] = loc
                segments.append(courant)
            else:
                courant["texte"] = (courant["texte"] + " " + mot).strip()
                courant["fin"] = round(m.get("end", 0), 2)
        return {"texte": (alt.get("transcript") or _texte_de_segments(segments)).strip(),
                "segments": segments, "langue": langue,
                "diarisation": any("locuteur" in s for s in segments)}


class AssemblyAI(_HTTP):
    """AssemblyAI : on téléverse l'audio, on soumet un job (speaker_labels=true), puis on
    interroge le statut jusqu'à `completed`. `utterances` = segments AVEC locuteurs."""
    nom = "assemblyai"
    attente_s = int(os.getenv("TRANSCRIPTION_ATTENTE_S", "600"))
    intervalle_s = 3

    def disponible(self):
        return bool(os.getenv("ASSEMBLYAI_API_KEY"))

    def _entetes(self):
        return {"authorization": os.getenv("ASSEMBLYAI_API_KEY")}

    async def transcrire(self, audio, nom_fichier, langue, diarisation):
        base = "https://api.assemblyai.com/v2"
        async with httpx.AsyncClient(timeout=self.timeout) as c:
            up = await c.post(f"{base}/upload", headers=self._entetes(), content=audio)
            up.raise_for_status()
            body = {"audio_url": up.json()["upload_url"], "speaker_labels": bool(diarisation)}
            if langue:
                body["language_code"] = langue
            sub = await c.post(f"{base}/transcript", headers=self._entetes(), json=body)
            sub.raise_for_status()
            tid = sub.json()["id"]
            for _ in range(max(1, self.attente_s // self.intervalle_s)):
                await asyncio.sleep(self.intervalle_s)
                g = await c.get(f"{base}/transcript/{tid}", headers=self._entetes())
                g.raise_for_status()
                rep = g.json()
                if rep.get("status") == "completed":
                    break
                if rep.get("status") == "error":
                    raise RuntimeError(rep.get("error", "AssemblyAI a échoué"))
            else:
                raise TimeoutError("Transcription AssemblyAI trop longue (timeout)")
        utt = rep.get("utterances") or []
        segments = [{"debut": round(u.get("start", 0) / 1000, 2),
                     "fin": round(u.get("end", 0) / 1000, 2),
                     "texte": (u.get("text") or "").strip(),
                     "locuteur": str(u.get("speaker"))} for u in utt]
        return {"texte": (rep.get("text") or _texte_de_segments(segments)).strip(),
                "segments": segments, "langue": rep.get("language_code") or langue,
                "diarisation": bool(segments)}


class Gateway(_HTTP):
    """Passe par la GATEWAY Workplace (proxy OpenAI-compatible). AUCUNE clé propre : réutilise
    la clé posée côté Gateway. Pas de diarisation → diarisation false."""
    nom = "gateway"

    def disponible(self):
        return bool(os.getenv("GATEWAY_KEY"))

    def _url(self):
        return os.getenv("GATEWAY_URL", "http://host.docker.internal:4001").rstrip("/")

    async def transcrire(self, audio, nom_fichier, langue, diarisation):
        modele = os.getenv("TRANSCRIPTION_GATEWAY_MODEL", "whisper-1")
        data = {"model": modele, "response_format": "verbose_json"}
        if langue:
            data["language"] = langue
        files = {"file": (nom_fichier or "audio.wav", audio)}
        async with httpx.AsyncClient(timeout=self.timeout) as c:
            r = await c.post(f"{self._url()}/v1/audio/transcriptions",
                             headers={"Authorization": f"Bearer {os.getenv('GATEWAY_KEY')}"},
                             data=data, files=files)
            r.raise_for_status()
            rep = r.json()
        segments = [{"debut": round(s.get("start", 0), 2), "fin": round(s.get("end", 0), 2),
                     "texte": (s.get("text") or "").strip()} for s in rep.get("segments", [])]
        return {"texte": (rep.get("text") or _texte_de_segments(segments)).strip(),
                "segments": segments, "langue": rep.get("language") or langue,
                "diarisation": False}


# ── Registre + ordre de préférence ──────────────────────────────
REGISTRE = {f.nom: f for f in (Local(), OpenAI(), Deepgram(), AssemblyAI(), Gateway())}

# Défaut : SOUVERAIN d'abord (`local`), puis les hébergés. Surchargé par TRANSCRIPTION_PROVIDERS.
ORDRE_DEFAUT = ["local", "openai", "deepgram", "assemblyai", "gateway"]


def ordre() -> list:
    """Ordre de préférence effectif (filtré sur les fournisseurs connus du registre)."""
    brut = [n.strip().lower()
            for n in os.getenv("TRANSCRIPTION_PROVIDERS", "").split(",") if n.strip()]
    noms = brut or ORDRE_DEFAUT
    return [n for n in noms if n in REGISTRE]


def disponibles() -> list:
    """Fournisseurs configurés (clé/lib présente), dans l'ordre de préférence."""
    return [n for n in ordre() if REGISTRE[n].disponible()]
