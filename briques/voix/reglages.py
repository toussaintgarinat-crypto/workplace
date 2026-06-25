"""Réglages RUNTIME de la voix — bascule « en un clic », sans redémarrage.

Deux RÔLES de voix (idée « la bonne voix selon l'usage ») :
  • CONVERSATION — réponses courtes, allers-retours (Telegram…) : on privilégie la RAPIDITÉ
    (Piper/Kokoro). Clé `moteur`.
  • LECTURE — résumés, longs textes qu'on écoute posément : la latence n'importe pas, on
    privilégie la BEAUTÉ (Coqui local ou une voix hébergée). Clé `moteur_lecture`.

`VOIX_PROVIDERS` (env) fixe l'ordre au démarrage ; ces réglages le surchargent à la volée et
sont persistés dans un petit JSON (`VOIX_DIR`, défaut `/data/voix`). `moteur.synthetiser`
route ensuite par usage : texte long (≥ `VOIX_SEUIL_LECTURE`) → voix de LECTURE, sinon
CONVERSATION. Repli HONNÊTE partout : fichier absent/illisible → aucun choix (ordre par
défaut, Piper souverain en tête) ; jamais d'exception qui casse l'appelant.
"""
import json
import os
from pathlib import Path
from typing import Optional

_SEUIL_DEFAUT = 280                                  # caractères : au-delà = « lecture »


def _dossier() -> Path:
    return Path(os.getenv("VOIX_DIR", "/data/voix"))


def _fichier() -> Path:
    return _dossier() / "moteur.json"


def _lire() -> dict:
    try:
        data = json.loads(_fichier().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001 — fichier absent/corrompu → réglages vides (défaut)
        return {}


def _ecrire(data: dict) -> None:
    _dossier().mkdir(parents=True, exist_ok=True)
    _fichier().write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _norme(v) -> Optional[str]:
    v = (v or "").strip().lower()
    return v or None


def moteur_choisi() -> Optional[str]:
    """Moteur de la voix de CONVERSATION (clé `moteur`), ou None."""
    return _norme(_lire().get("moteur"))


def moteur_lecture() -> Optional[str]:
    """Moteur de la voix de LECTURE/narration (clé `moteur_lecture`), ou None."""
    return _norme(_lire().get("moteur_lecture"))


def definir_moteur(nom: Optional[str], role: str = "conversation") -> Optional[str]:
    """Persiste le moteur d'un RÔLE. `None`/``/`auto` efface ce rôle (retour au défaut).
    `role` = `conversation` (défaut) ou `lecture`. Renvoie la valeur enregistrée. Lève si le
    dossier est non inscriptible — l'appelant (endpoint) traduit en erreur honnête."""
    nom = (nom or "").strip().lower()
    if nom in ("", "auto", "defaut", "défaut"):
        nom = None
    cle = "moteur_lecture" if role == "lecture" else "moteur"
    data = _lire()
    if nom is None:
        data.pop(cle, None)
    else:
        data[cle] = nom
    _ecrire(data)
    return nom


def seuil_lecture() -> int:
    """Seuil (en caractères du texte à dire) au-delà duquel on bascule sur la voix de LECTURE.
    Réglable par `VOIX_SEUIL_LECTURE`. Repli honnête sur le défaut si la valeur est invalide."""
    try:
        return max(1, int(os.getenv("VOIX_SEUIL_LECTURE", str(_SEUIL_DEFAUT))))
    except (TypeError, ValueError):
        return _SEUIL_DEFAUT
