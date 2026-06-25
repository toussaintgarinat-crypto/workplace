"""Bibliothèque de VOIX CLONÉES — enregistrer un timbre une fois, le rappeler partout (S107).

Coqui XTTS sait reproduire un timbre à partir d'un court échantillon (`speaker_wav`, cf.
`fournisseurs.Coqui`). Ce module rend ce clonage RÉUTILISABLE : on range les échantillons de
référence dans `VOIX_DIR/voix-clonees/<slug>.wav` avec un index `voix-clonees.json` (nom lisible,
date, durée, notes), pour les rappeler dans plusieurs contextes (assistant, lecture de résumés,
personnages des séries du Studio).

CRUD PUR et testable, AUCUN moteur importé ici : la synthèse reste dans `moteur`/`fournisseurs`.
On résout simplement la convention `voix: "clone:<nom>"` vers le chemin du WAV de référence ;
`moteur` force alors le moteur Coqui (seul à savoir cloner). Repli HONNÊTE partout : dossier
absent/illisible → bibliothèque vide ; jamais d'exception qui casse l'appelant en LECTURE.

ÉTHIQUE : ne cloner que des voix qu'on a le DROIT d'utiliser (consentement de la personne). Ce
n'est pas optionnel — l'UI le DIT, et ce module ne lève aucune barrière technique à la place de
ce consentement : c'est une responsabilité humaine, rendue explicite.
"""
import io
import json
import os
import re
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

PREFIXE = "clone:"                       # convention de référence dans `voix` (ex. "clone:marina")
_DUREE_MIN_S = 1.0                       # un échantillon plus court ne clone rien d'utile
_TAILLE_MAX = 25 * 1024 * 1024           # garde-fou : 25 Mo (un échantillon de clonage est court)


def _dossier() -> Path:
    return Path(os.getenv("VOIX_DIR", "/data/voix")) / "voix-clonees"


def _index_path() -> Path:
    return _dossier() / "voix-clonees.json"


def slug(nom: str) -> str:
    """Nom lisible → identifiant de fichier sûr (minuscules, alphanumérique + tirets).
    Lève `ValueError` si rien d'exploitable ne reste (nom vide / que des symboles)."""
    s = re.sub(r"[^a-z0-9]+", "-", (nom or "").strip().lower()).strip("-")
    if not s:
        raise ValueError("Nom de voix vide ou invalide (mets au moins une lettre ou un chiffre).")
    return s


def _lire_index() -> dict:
    try:
        data = json.loads(_index_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001 — index absent/corrompu → bibliothèque vide (repli honnête)
        return {}


def _ecrire_index(data: dict) -> None:
    _dossier().mkdir(parents=True, exist_ok=True)
    _index_path().write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def duree_wav(octets: bytes) -> float:
    """Durée (secondes) d'un WAV — sert AUSSI de validation : un non-WAV lève `wave.Error`."""
    with wave.open(io.BytesIO(octets), "rb") as w:
        cadres = w.getnframes()
        cadence = w.getframerate() or 1
    return cadres / float(cadence)


def lister() -> list:
    """Voix clonées enregistrées (la plus récente d'abord). Jamais d'exception en lecture."""
    items = list(_lire_index().values())
    items.sort(key=lambda e: e.get("date", ""), reverse=True)
    return items


def obtenir(nom: str) -> Optional[dict]:
    """Entrée d'index d'une voix (par slug OU par nom lisible), ou None."""
    try:
        cle = slug(nom)
    except ValueError:
        return None
    return _lire_index().get(cle)


def chemin(nom: str) -> Optional[str]:
    """Chemin du WAV de référence d'une voix clonée s'il existe sur le disque, sinon None."""
    e = obtenir(nom)
    if not e:
        return None
    p = _dossier() / e["fichier"]
    return str(p) if p.exists() else None


def enregistrer(nom: str, octets: bytes, notes: str = "") -> dict:
    """Enregistre (ou remplace) un échantillon de référence sous `nom`. Valide que c'est un
    WAV exploitable (entête + durée mini). Renvoie l'entrée d'index. Lève `ValueError` (entrée
    invalide → 4xx honnête) en cas de WAV illisible / trop court / trop gros / nom vide."""
    cle = slug(nom)
    if not octets:
        raise ValueError("Échantillon vide.")
    if len(octets) > _TAILLE_MAX:
        raise ValueError(f"Échantillon trop volumineux (max {_TAILLE_MAX // (1024 * 1024)} Mo) — "
                         "un extrait de 10-20 s suffit pour cloner.")
    try:
        duree = duree_wav(octets)
    except Exception:  # noqa: BLE001 — pas un WAV valide
        raise ValueError("Fichier non reconnu : fournis un WAV (PCM). Convertis-le si besoin.")
    if duree < _DUREE_MIN_S:
        raise ValueError(f"Échantillon trop court ({duree:.1f} s) : vise ~10-20 s de parole nette.")

    _dossier().mkdir(parents=True, exist_ok=True)
    fichier = f"{cle}.wav"
    (_dossier() / fichier).write_bytes(octets)
    entree = {"nom": (nom or "").strip(), "slug": cle, "fichier": fichier,
              "date": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "duree_s": round(duree, 2), "taille_octets": len(octets),
              "notes": (notes or "").strip()}
    index = _lire_index()
    index[cle] = entree
    _ecrire_index(index)
    return entree


def supprimer(nom: str) -> bool:
    """Retire une voix clonée (fichier + index). Renvoie False si elle n'existait pas."""
    try:
        cle = slug(nom)
    except ValueError:
        return False
    index = _lire_index()
    entree = index.pop(cle, None)
    if entree is None:
        return False
    try:
        (_dossier() / entree["fichier"]).unlink()
    except OSError:
        pass                                  # fichier déjà absent → on a quand même nettoyé l'index
    _ecrire_index(index)
    return True


def est_reference_clone(voix: Optional[str]) -> bool:
    """True si `voix` désigne une voix clonée (convention `clone:<nom>`)."""
    return bool(voix) and voix.strip().lower().startswith(PREFIXE)


def resoudre(voix: Optional[str]) -> Optional[str]:
    """`clone:<nom>` → chemin du WAV de référence (pour `speaker_wav` Coqui), sinon None."""
    if not est_reference_clone(voix):
        return None
    return chemin(voix.strip()[len(PREFIXE):])
