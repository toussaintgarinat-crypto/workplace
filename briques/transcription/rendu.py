"""Mise en forme des NOTES — fonctions PURES (aucun réseau, aucune I/O), donc testables.

On sépare « comment présenter les notes » (ici) de « où les déposer » (destinations.py).
Un `paquet` normalisé (résumé + points d'action + thèmes + décisions + transcription) est
rendu soit en Markdown (pour un fichier / un dossier synchronisé), soit prêt pour la mémoire.
"""
import re
import unicodedata
from datetime import datetime, timezone


def paquet(notes: dict | None, transcription: dict | None = None,
           titre: str | None = None, langue: str | None = None) -> dict:
    """Construit le paquet normalisé à partir des sorties de /notes (ou /resumer)."""
    notes = notes or {}
    transcription = transcription or {}
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    titre = (titre or "").strip() or f"Notes du {date}"
    return {
        "titre": titre,
        "date": date,
        "langue": langue or transcription.get("langue") or notes.get("langue"),
        "resume": (notes.get("resume") or "").strip(),
        "points_action": list(notes.get("points_action") or []),
        "themes": list(notes.get("themes") or []),
        "decisions": list(notes.get("decisions") or []),
        "transcription": (transcription.get("texte") or "").strip(),
        "source_notes": notes.get("source"),          # llm | heuristique | vide
        "backend_transcription": transcription.get("backend"),
    }


def slug(titre: str) -> str:
    """Nom de fichier sûr (ascii, minuscules, tirets) à partir d'un titre."""
    base = unicodedata.normalize("NFKD", titre or "").encode("ascii", "ignore").decode()
    base = re.sub(r"[^a-zA-Z0-9]+", "-", base).strip("-").lower()
    return base or "notes"


def markdown(p: dict) -> str:
    """Rend le paquet en Markdown lisible (frontmatter léger + sections)."""
    lignes = [f"# {p['titre']}", "", f"*{p['date']}*"]
    if p.get("langue"):
        lignes[-1] += f" · langue : {p['langue']}"
    lignes.append("")
    if p.get("resume"):
        lignes += ["## Résumé", "", p["resume"], ""]
    if p.get("decisions"):
        lignes += ["## Décisions", ""] + [f"- {d}" for d in p["decisions"]] + [""]
    if p.get("points_action"):
        lignes += ["## Points d'action", ""] + [f"- [ ] {a}" for a in p["points_action"]] + [""]
    if p.get("themes"):
        lignes += ["## Thèmes", "", ", ".join(p["themes"]), ""]
    if p.get("transcription"):
        lignes += ["## Transcription", "", p["transcription"], ""]
    return "\n".join(lignes).strip() + "\n"
