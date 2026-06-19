"""Journal de conversations UNIFIÉ (S78) — une trace, toutes les surfaces.

L'assistant du Cœur est stateless et chaque surface tenait son fil dans son coin (le
navigateur pour le dashboard — éphémère ; la brique connexion pour Telegram/WhatsApp…).
Résultat : aucune trace commune. Ici, le Cœur — le cerveau — enregistre CHAQUE échange,
quelle que soit la surface, dans un seul journal. Le dashboard peut alors montrer
l'historique Telegram à côté de l'historique web.

Chaque ligne (JSONL side-car, façon `proprioception`/`shadow`) :
    {ts, fil, surface, interlocuteur, utilisateur, role, content}
`fil` = "{surface}:{interlocuteur}" identifie une conversation. `utilisateur` prépare le
multi-tenant (cf. roadmap) : aujourd'hui souvent vide, demain la clé d'isolation.

Best-effort et NON bloquant : journaliser ne doit jamais casser une conversation. Borné
en taille (`CONVERSATIONS_JOURNAL_MAX` lignes) pour ne pas grossir sans fin.
"""
import json
import logging
import os
import time
from pathlib import Path

logger = logging.getLogger(__name__)

CHEMIN = Path(os.getenv("CONVERSATIONS_JOURNAL_PATH", "/data/conversations_journal.jsonl"))


def _max() -> int:
    try:
        return max(100, int(os.getenv("CONVERSATIONS_JOURNAL_MAX", "5000")))
    except ValueError:
        return 5000


def fil(surface: str, interlocuteur: str) -> str:
    return f"{surface or 'web'}:{interlocuteur or 'inconnu'}"


def enregistrer(surface: str, interlocuteur: str, role: str, content: str,
                *, utilisateur: str | None = None) -> None:
    """Ajoute un message au journal. Silencieux en cas d'échec (best-effort)."""
    if not (content or "").strip():
        return
    ligne = {"ts": time.time(), "fil": fil(surface, interlocuteur),
             "surface": surface or "web", "interlocuteur": interlocuteur or "inconnu",
             "utilisateur": utilisateur, "role": role, "content": content}
    try:
        CHEMIN.parent.mkdir(parents=True, exist_ok=True)
        with CHEMIN.open("a", encoding="utf-8") as f:
            f.write(json.dumps(ligne, ensure_ascii=False) + "\n")
        _borner()
    except Exception:  # noqa: BLE001 — la trace ne doit jamais casser un tour
        logger.debug("journal_conversations: écriture impossible", exc_info=True)


def _lignes() -> list[dict]:
    if not CHEMIN.exists():
        return []
    out = []
    try:
        for l in CHEMIN.read_text(encoding="utf-8").splitlines():
            l = l.strip()
            if not l:
                continue
            try:
                out.append(json.loads(l))
            except json.JSONDecodeError:
                continue
    except Exception:  # noqa: BLE001
        return []
    return out


def _borner() -> None:
    """Garde au plus `_max()` lignes (réécrit le fichier quand il déborde nettement)."""
    mx = _max()
    lignes = _lignes()
    if len(lignes) <= int(mx * 1.2):
        return
    try:
        CHEMIN.write_text("\n".join(json.dumps(x, ensure_ascii=False)
                                    for x in lignes[-mx:]) + "\n", encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def messages(fil_: str, limite: int = 100) -> list[dict]:
    """Les derniers messages d'un fil (ordre chronologique)."""
    lignes = [l for l in _lignes() if l.get("fil") == fil_]
    return lignes[-max(1, limite):]


def fils(limite: int = 50) -> list[dict]:
    """Liste des conversations (plus récente d'abord) avec un aperçu du dernier message."""
    par_fil: dict[str, dict] = {}
    for l in _lignes():
        f = l.get("fil")
        if not f:
            continue
        e = par_fil.setdefault(f, {"fil": f, "surface": l.get("surface"),
                                   "interlocuteur": l.get("interlocuteur"),
                                   "utilisateur": l.get("utilisateur"), "nombre": 0})
        e["nombre"] += 1
        e["dernier"] = (l.get("content") or "")[:140]
        e["horodatage"] = l.get("ts")
    classes = sorted(par_fil.values(), key=lambda x: x.get("horodatage") or 0, reverse=True)
    return classes[:max(1, limite)]
