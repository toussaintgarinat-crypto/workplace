"""Journal « brut » des appels LLM (2e chantier veille deepseek-harness/Cordis, 2026-08-21).

Invariant : tout ce qui atteint une requête modèle doit être reconstructible depuis un
journal append-only. `journal_conversations.py` (S78) ne garde que le texte final
user/assistant d'un tour — pas le contexte système injecté à chaud (persona, digest,
date…), ni les tool_calls/tool_results échangés en cours de tour. Ce module comble ce
trou : PAR APPEL LLM réellement abouti, il journalise exactement ce qui a été envoyé
(`messages`, post résumé/trim/cache-préfixe) et ce qui a été reçu (`message_recu`).

Séparé de `journal_conversations.py` à dessein : celui-ci sert aussi de mémoire
cross-surface (`messages_utilisateur()` réinjecte du texte dans un futur prompt) — y
mélanger des tool_calls/contenus système casserait ce contrat.

Accroché dans `llm_pipeline.completer()`/`completer_flux()`, au même point que
`journal_usage.enregistrer()` : c'est le seul endroit où les messages sont RÉELLEMENT
finalisés (après résumé à froid, trim, cache-préfixe), et le seul point de passage de
TOUS les appels LLM du Cœur (chat, classement, MOA, briefing, proprioception…).

Runtime check vivant : après CHAQUE écriture, on relit immédiatement la dernière ligne
et on vérifie qu'elle égale ce qu'on vient de sérialiser. Un écart (troncature disque,
écriture concurrente corrompue) loggue une erreur — jamais une exception, même
convention best-effort non bloquante que le reste des journaux du Cœur.

Best-effort et NON bloquant : journaliser ne doit jamais casser un appel LLM. Borné en
taille (`MODELE_JOURNAL_MAX` lignes, plus bas que les journaux texte vu la taille des
lignes qui embarquent des historiques de messages entiers).
"""
import json
import logging
import os
import threading
from pathlib import Path
from time import time

logger = logging.getLogger(__name__)

CHEMIN = Path(os.getenv("MODELE_JOURNAL_PATH", "/data/journal_modele.jsonl"))

_verrou = threading.Lock()


def _max() -> int:
    try:
        return max(50, int(os.getenv("MODELE_JOURNAL_MAX", "2000")))
    except ValueError:
        return 2000


def _verifier_derniere_ligne(attendue: dict) -> bool:
    """Runtime check : relit la dernière ligne PHYSIQUE du fichier et vérifie qu'elle
    égale exactement ce qu'on vient de sérialiser. Appelé sous le verrou, juste après
    l'écriture."""
    try:
        contenu = CHEMIN.read_text(encoding="utf-8")
    except OSError:
        logger.error("journal_modele: invariant violé — relecture impossible juste après écriture")
        return False
    lignes = [l for l in contenu.splitlines() if l.strip()]
    if not lignes:
        logger.error("journal_modele: invariant violé — fichier vide juste après écriture")
        return False
    try:
        relue = json.loads(lignes[-1])
    except json.JSONDecodeError:
        logger.error("journal_modele: invariant violé — dernière ligne illisible juste après écriture")
        return False
    if relue != attendue:
        logger.error("journal_modele: invariant violé — la dernière ligne relue diffère de "
                     "ce qui vient d'être écrit")
        return False
    return True


def enregistrer_appel(*, fil: str | None, etiquette: str, modele: str | None,
                       messages: list[dict], outils_offerts: list[str] | None = None,
                       message_recu: dict | None = None, erreur: str | None = None) -> bool:
    """Ajoute une ligne au journal brut. Ne lève jamais (best-effort). Renvoie True si la
    ligne a été écrite ET relue à l'identique (runtime check), False sinon — jamais
    utilisé pour bloquer l'appelant, seulement pour logger/tester l'invariant."""
    ligne = {
        "ts": time(),
        "fil": fil,
        "etiquette": etiquette,
        "modele": modele,
        "messages": messages,
        "outils_offerts": list(outils_offerts or []),
        "message_recu": message_recu,
        "erreur": erreur,
    }
    try:
        with _verrou:
            CHEMIN.parent.mkdir(parents=True, exist_ok=True)
            with CHEMIN.open("a", encoding="utf-8") as f:
                f.write(json.dumps(ligne, ensure_ascii=False) + "\n")
            ok = _verifier_derniere_ligne(ligne)
            _borner()
            return ok
    except OSError as e:
        logger.warning("journal_modele: écriture impossible : %s", e)
        return False


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
    except OSError:
        return []
    return out


def _borner() -> None:
    """Garde au plus `_max()` lignes (réécrit le fichier quand il déborde nettement).
    Appelé sous le verrou, après l'écriture+vérification."""
    mx = _max()
    lignes = _lignes()
    if len(lignes) <= int(mx * 1.2):
        return
    try:
        CHEMIN.write_text("\n".join(json.dumps(x, ensure_ascii=False)
                                    for x in lignes[-mx:]) + "\n", encoding="utf-8")
    except OSError:
        pass


def appels(fil: str, limite: int = 100) -> list[dict]:
    """Les derniers appels LLM journalisés pour CE fil (ordre chronologique)."""
    lignes = [l for l in _lignes() if l.get("fil") == fil]
    return lignes[-max(1, limite):]
