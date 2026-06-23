"""Projets de l'assistant (façon Claude Projects / Perplexity Spaces).

Un PROJET regroupe des conversations autour d'un même sujet et leur donne un CONTEXTE
commun : des instructions personnalisées (un prompt propre au projet, injecté dans chaque
conversation rattachée) et, optionnellement, des documents de référence (knowledge).

C'est l'overlay « organisationnel » du journal de conversations ([[journal_conversations]]) :
le journal garde les messages par fil ; ici on tient la liste des projets et, sur chaque
conversation, son `projet_id` (cf. `journal_conversations.assigner_projet`).

Stockage : un side-car JSON unique, best-effort et borné en pratique par l'usage humain.
    {"projets": {"<id>": {id, nom, instructions, documents[], couleur, cree_le, maj_le}}}

Best-effort : un échec d'écriture ne doit jamais casser une conversation — on log en debug.
"""
import json
import logging
import os
import time
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

CHEMIN = Path(os.getenv("PROJETS_PATH", "/data/projets.json"))

# Palette douce alignée sur le dashboard (accents froids/chauds discrets).
COULEURS = ["#7c83ff", "#22d3ee", "#4ade80", "#facc15", "#fb923c", "#f472b6", "#a78bfa"]


def _charger() -> dict:
    if not CHEMIN.exists():
        return {"projets": {}}
    try:
        d = json.loads(CHEMIN.read_text(encoding="utf-8"))
        if isinstance(d, dict) and isinstance(d.get("projets"), dict):
            return d
    except Exception:  # noqa: BLE001
        logger.debug("projets: lecture impossible", exc_info=True)
    return {"projets": {}}


def _ecrire(d: dict) -> None:
    try:
        CHEMIN.parent.mkdir(parents=True, exist_ok=True)
        CHEMIN.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:  # noqa: BLE001 — la persistance ne doit jamais casser un tour
        logger.debug("projets: écriture impossible", exc_info=True)


def lister() -> list[dict]:
    """Tous les projets, plus récent d'abord (par date de création)."""
    projets = list(_charger()["projets"].values())
    return sorted(projets, key=lambda p: p.get("cree_le") or 0, reverse=True)


def obtenir(projet_id: str | None) -> dict | None:
    if not projet_id:
        return None
    return _charger()["projets"].get(projet_id)


def instructions_de(projet_id: str | None) -> str:
    """Les instructions personnalisées d'un projet (chaîne vide si aucune / projet absent)."""
    p = obtenir(projet_id)
    return (p or {}).get("instructions", "") or ""


def contexte_de(projet_id: str | None) -> str:
    """Le contexte complet d'un projet pour le prompt : instructions + rappel des dossiers
    de référence rattachés (que le LLM consultera via l'outil `chercher_documents`).

    Chaîne vide si aucun contexte. On NE recopie PAS les documents (coût LLM) : on signale
    juste leur existence et le filtre à utiliser, façon « knowledge » Claude Projects."""
    p = obtenir(projet_id)
    if not p:
        return ""
    bouts = []
    if (p.get("instructions") or "").strip():
        bouts.append(p["instructions"].strip())
    docs = p.get("documents") or []
    if docs:
        refs = ", ".join(f"« {d.get('nom')} » ({d.get('type', 'dossier')})"
                         for d in docs if d.get("nom"))
        if refs:
            bouts.append("Documents de référence de ce projet — consulte-les si utile via "
                         f"l'outil chercher_documents (filtre projet/catégorie) : {refs}.")
    return "\n\n".join(bouts)


def creer(nom: str, instructions: str = "", documents: list | None = None,
          couleur: str | None = None) -> dict:
    """Crée un projet et le renvoie. `nom` obligatoire (sinon « Projet sans nom »)."""
    d = _charger()
    pid = uuid.uuid4().hex[:12]
    n = len(d["projets"])
    projet = {
        "id": pid,
        "nom": (nom or "").strip() or "Projet sans nom",
        "instructions": (instructions or "").strip(),
        "documents": list(documents or []),
        "couleur": couleur or COULEURS[n % len(COULEURS)],
        "cree_le": time.time(),
        "maj_le": time.time(),
    }
    d["projets"][pid] = projet
    _ecrire(d)
    return projet


def modifier(projet_id: str, *, nom: str | None = None, instructions: str | None = None,
             documents: list | None = None, couleur: str | None = None) -> dict | None:
    """Met à jour les champs fournis (les autres restent). Renvoie le projet ou None."""
    d = _charger()
    p = d["projets"].get(projet_id)
    if not p:
        return None
    if nom is not None:
        p["nom"] = nom.strip() or p["nom"]
    if instructions is not None:
        p["instructions"] = instructions.strip()
    if documents is not None:
        p["documents"] = list(documents)
    if couleur is not None:
        p["couleur"] = couleur
    p["maj_le"] = time.time()
    _ecrire(d)
    return p


def supprimer(projet_id: str) -> bool:
    """Supprime le projet (les conversations rattachées sont détachées par l'appelant)."""
    d = _charger()
    if projet_id not in d["projets"]:
        return False
    del d["projets"][projet_id]
    _ecrire(d)
    return True
