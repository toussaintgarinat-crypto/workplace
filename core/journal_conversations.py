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
# Side-car « méta » : un overlay par fil (titre lisible, projet rattaché, épingle, archive).
# Séparé du journal de messages pour ne pas réécrire le JSONL à chaque renommage.
META = Path(os.getenv("CONVERSATIONS_META_PATH",
                       str(CHEMIN.with_name("conversations_meta.json"))))


def _max() -> int:
    try:
        return max(100, int(os.getenv("CONVERSATIONS_JOURNAL_MAX", "5000")))
    except ValueError:
        return 5000


def fil(surface: str, interlocuteur: str) -> str:
    return f"{surface or 'web'}:{interlocuteur or 'inconnu'}"


# ── Méta des conversations (titre, projet, épingle, archive) ─────────────────────
def _charger_meta() -> dict:
    if not META.exists():
        return {}
    try:
        d = json.loads(META.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _ecrire_meta(d: dict) -> None:
    try:
        META.parent.mkdir(parents=True, exist_ok=True)
        META.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:  # noqa: BLE001 — la méta ne doit jamais casser un tour
        logger.debug("journal_conversations: méta non écrite", exc_info=True)


def _titre_auto(content: str) -> str:
    """Un titre court dérivé du premier message (façon Claude/Perplexity), sans LLM."""
    t = " ".join((content or "").split())
    return (t[:48].rstrip() + "…") if len(t) > 48 else t


def meta(fil_: str) -> dict:
    """La méta d'un fil (titre/projet_id/epingle/archive), dict vide si aucune."""
    return _charger_meta().get(fil_, {})


def definir_meta(fil_: str, **champs) -> dict:
    """Met à jour la méta d'un fil (titre, projet_id, epingle, archive). Renvoie la méta."""
    d = _charger_meta()
    m = d.setdefault(fil_, {})
    for k, v in champs.items():
        m[k] = v
    _ecrire_meta(d)
    return m


def renommer(fil_: str, titre: str) -> dict:
    return definir_meta(fil_, titre=(titre or "").strip())


def assigner_projet(fil_: str, projet_id: str | None) -> dict:
    return definir_meta(fil_, projet_id=projet_id or None)


def detacher_projet(projet_id: str) -> int:
    """Détache toutes les conversations d'un projet supprimé. Renvoie le nombre détaché."""
    d = _charger_meta()
    n = 0
    for m in d.values():
        if m.get("projet_id") == projet_id:
            m["projet_id"] = None
            n += 1
    if n:
        _ecrire_meta(d)
    return n


def supprimer_fil(fil_: str) -> None:
    """Supprime une conversation : ses messages du journal ET sa méta."""
    lignes = [l for l in _lignes() if l.get("fil") != fil_]
    try:
        CHEMIN.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in lignes),
                          encoding="utf-8")
    except Exception:  # noqa: BLE001
        logger.debug("journal_conversations: suppression impossible", exc_info=True)
    d = _charger_meta()
    if d.pop(fil_, None) is not None:
        _ecrire_meta(d)


def enregistrer(surface: str, interlocuteur: str, role: str, content: str,
                *, utilisateur: str | None = None) -> None:
    """Ajoute un message au journal. Silencieux en cas d'échec (best-effort).

    Pose AUSSI un titre automatique au premier message utilisateur d'un fil qui n'en a
    pas (façon Claude/Perplexity) — sans LLM, dérivé du contenu."""
    if not (content or "").strip():
        return
    f = fil(surface, interlocuteur)
    ligne = {"ts": time.time(), "fil": f,
             "surface": surface or "web", "interlocuteur": interlocuteur or "inconnu",
             "utilisateur": utilisateur, "role": role, "content": content}
    try:
        CHEMIN.parent.mkdir(parents=True, exist_ok=True)
        with CHEMIN.open("a", encoding="utf-8") as fic:
            fic.write(json.dumps(ligne, ensure_ascii=False) + "\n")
        _borner()
    except Exception:  # noqa: BLE001 — la trace ne doit jamais casser un tour
        logger.debug("journal_conversations: écriture impossible", exc_info=True)
    # Titre auto au 1er message humain si la conversation n'en a pas encore.
    if role == "user" and not meta(f).get("titre"):
        try:
            definir_meta(f, titre=_titre_auto(content))
        except Exception:  # noqa: BLE001
            pass


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


def messages_utilisateur(utilisateur: str, limite: int = 100) -> list[dict]:
    """Les derniers messages d'un COMPTE, tous fils/surfaces confondus (ordre chronologique).

    Contrairement à `messages()` (un seul fil), fusionne web + Telegram + tout autre canal
    relié au même compte — sert à donner à un nouveau canal la mémoire de ce qui a été dit
    ailleurs par ce même compte (cf. `briques/connexion/pont.py`). `utilisateur` vide → liste
    vide (rien à fusionner, repli honnête côté appelant)."""
    if not utilisateur:
        return []
    lignes = [l for l in _lignes() if l.get("utilisateur") == utilisateur]
    lignes.sort(key=lambda l: l.get("ts") or 0)
    return lignes[-max(1, limite):]


def fils(limite: int = 50, projet_id: str | None = None) -> list[dict]:
    """Liste des conversations (plus récente d'abord) avec aperçu, titre et projet.

    Chaque fil est enrichi de sa méta (titre, projet_id, epingle, archive). Filtre
    optionnel par `projet_id` (les conversations rattachées à ce projet)."""
    metas = _charger_meta()
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
    for f, e in par_fil.items():
        m = metas.get(f, {})
        e["titre"] = m.get("titre") or ""
        e["projet_id"] = m.get("projet_id")
        e["epingle"] = bool(m.get("epingle"))
        e["archive"] = bool(m.get("archive"))
        e["ordre"] = m.get("ordre")
    valeurs = list(par_fil.values())
    if projet_id is not None:
        valeurs = [e for e in valeurs if e.get("projet_id") == projet_id]
    # S104 — tri stable en 3 passes : récence, puis `ordre` manuel (cliquer-déposer ;
    # non rangées = ordre None → restent en tête par récence), puis épinglées tout en haut.
    valeurs.sort(key=lambda x: x.get("horodatage") or 0, reverse=True)
    valeurs.sort(key=lambda x: x["ordre"] if x.get("ordre") is not None else -1)
    valeurs.sort(key=lambda x: x.get("epingle", False), reverse=True)
    return valeurs[:max(1, limite)]


def reordonner(fils_: list[str]) -> int:
    """Fixe l'ordre d'affichage des conversations (S104). `fils_` = la nouvelle suite ;
    chaque fil reçoit son rang comme `ordre`. Renvoie le nombre de fils rangés."""
    d = _charger_meta()
    for rang, f in enumerate(fils_):
        d.setdefault(f, {})["ordre"] = rang
    _ecrire_meta(d)
    return len(fils_)
