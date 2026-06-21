"""Task trace (S89) : la narration pas-à-pas en français de ce que fait l'agent.

Interrupteur on/off par chantier (`Chantier.trace_active`). Quand c'est ON, chaque pas est
**raconté en français** (« je lis le fichier… », « je crée l'entité X… ») et :
  • **persisté** dans un journal JSONL par chantier (l'archive durable, relisible plus tard) ;
  • **diffusé en direct** via SSE (`GET /chantiers/{id}/trace`) — pour APPRENDRE le code en
    regardant l'agent travailler.
Quand c'est OFF, l'agent bosse en silence : on ne montre que le diff final.

Le module est sans état partagé : tout vit dans un fichier `<DEV_TRACES>/<cid>.jsonl`. Les agents
(factice / Claude Code via hooks / OpenCode) y écrivent ; l'endpoint SSE le suit (tail -f).
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone

DEV_TRACES = os.environ.get("DEV_TRACES", os.path.join(tempfile.gettempdir(), "traces-dev"))


def fichier_pour(cid: str) -> str:
    """Chemin du journal de trace d'un chantier (un JSONL par chantier)."""
    return os.path.join(DEV_TRACES, f"{cid}.jsonl")


# ── Traduction des outils d'un agent → phrases françaises (pour les hooks) ───────
def phrase_pour_outil(nom_outil: str, entree: dict | None = None) -> str:
    """Traduit un appel d'outil (Read/Edit/Bash…) en une phrase FR à la première personne."""
    e = entree or {}
    chemin = e.get("file_path") or e.get("path") or ""
    nom = (nom_outil or "").lower()
    if nom in ("read", "lire"):
        return f"Je lis le fichier {chemin}." if chemin else "Je lis un fichier."
    if nom in ("write", "ecrire"):
        return f"J'écris le fichier {chemin}." if chemin else "J'écris un fichier."
    if nom in ("edit", "multiedit", "modifier"):
        return f"Je modifie {chemin}." if chemin else "Je modifie un fichier."
    if nom in ("bash", "shell"):
        cmd = (e.get("command") or "").strip().replace("\n", " ")
        return f"Je lance la commande : {cmd[:90]}" if cmd else "Je lance une commande shell."
    if nom in ("grep", "search"):
        return f"Je cherche « {e.get('pattern', '')} » dans le code."
    if nom in ("glob",):
        return f"Je liste les fichiers ({e.get('pattern', '')})."
    if nom in ("task", "agent"):
        return "Je délègue une sous-tâche à un agent."
    return f"J'utilise l'outil {nom_outil}."


def phrase_pour_evenement(payload: dict) -> str:
    """Traduit un évènement de hook Claude Code (PreToolUse) en phrase FR. '' si à ignorer."""
    if payload.get("hook_event_name") not in (None, "", "PreToolUse"):
        return ""  # on narre l'INTENTION (PreToolUse) ; PostToolUse n'ajoute rien d'utile
    return phrase_pour_outil(payload.get("tool_name", ""), payload.get("tool_input") or {})


class Traceur:
    """Écrit/relit le journal de trace d'un chantier. Honnête : si OFF, on n'écrit rien."""

    def __init__(self, fichier: str):
        self.fichier = fichier
        os.makedirs(os.path.dirname(fichier) or ".", exist_ok=True)

    def noter(self, phrase: str, type: str = "etape") -> dict:
        """Ajoute un pas narré au journal (horodaté). Renvoie l'évènement écrit."""
        evt = {"t": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "type": type, "phrase": phrase}
        with open(self.fichier, "a", encoding="utf-8") as f:
            f.write(json.dumps(evt, ensure_ascii=False) + "\n")
        return evt

    def lire(self) -> list:
        """Tous les évènements déjà notés (vide si le chantier n'a rien tracé)."""
        try:
            with open(self.fichier, encoding="utf-8") as f:
                return [json.loads(l) for l in f if l.strip()]
        except FileNotFoundError:
            return []

    def phrases(self) -> list:
        """Juste les phrases, dans l'ordre (ce qu'on archive dans `Chantier.journal`)."""
        return [e["phrase"] for e in self.lire()]

    def effacer(self) -> None:
        try:
            os.remove(self.fichier)
        except FileNotFoundError:
            pass


def lire(fichier: str) -> list:
    """Lit les évènements d'un fichier de trace SANS effet de bord (ni création de dossier)."""
    try:
        with open(fichier, encoding="utf-8") as f:
            return [json.loads(l) for l in f if l.strip()]
    except FileNotFoundError:
        return []
