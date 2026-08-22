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

Exception connue : `shadow.py` (rejeu d'un candidat moins cher en tâche de fond,
déclenché depuis le chemin de succès de `llm_pipeline`) appelle la Gateway
directement (`{GATEWAY_URL}/v1/chat/completions`), hors de ce point de passage — non
couvert par cet invariant à ce jour.

Asymétrie de forme à connaître en lisant le journal : sur le chemin de succès,
`messages` loggué est `payload["messages"]`, c'est-à-dire APRÈS application du
préfixe de cache par modèle (`cache_prefixe.appliquer`) ; sur les 2 chemins d'échec
(budget épuisé, aucun modèle joignable), c'est la version PRÉ-préfixe-cache — cohérent
puisque rien n'a été réellement envoyé dans ces cas, mais la forme de `messages` diffère
donc selon que `erreur` est présent ou non.

Runtime check vivant : après CHAQUE écriture, on relit immédiatement la QUEUE du
fichier (pas tout le fichier — coûteux dès qu'il grossit) et on vérifie que sa
dernière ligne égale ce qu'on vient de sérialiser. Un écart (troncature disque,
écriture concurrente corrompue) loggue une erreur — jamais une exception, même
convention best-effort non bloquante que le reste des journaux du Cœur.

Best-effort et NON bloquant : journaliser ne doit jamais casser un appel LLM. Borné en
taille (`MODELE_JOURNAL_MAX` lignes, plus bas que les journaux texte vu la taille des
lignes qui embarquent des historiques de messages entiers) — le bornage réel
(lecture+réécriture intégrale, coûteux) n'est vérifié qu'une fois tous les
`INTERVALLE_BORNAGE` appels (compteur en mémoire de process), pas à chaque écriture.
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

# Taille de la queue relue pour le check vivant (pas tout le fichier — cf. module docstring).
# 1 Mo est largement suffisant même pour une ligne embarquant un gros historique de messages.
_TAILLE_QUEUE_CHECK = 1024 * 1024

# Le bornage réel (lecture+réécriture intégrale, coûteux) n'est vérifié qu'une fois tous les
# INTERVALLE_BORNAGE appels — pas à CHAQUE écriture. Compteur en mémoire de process : remis à
# zéro implicitement à chaque redémarrage (pas besoin de persistance, un léger dépassement du
# bornage au redémarrage n'est pas un problème).
INTERVALLE_BORNAGE = 50
_compteur_depuis_bornage = 0


def _max() -> int:
    try:
        return max(50, int(os.getenv("MODELE_JOURNAL_MAX", "2000")))
    except ValueError:
        return 2000


def _verifier_derniere_ligne(attendue: dict) -> bool:
    """Runtime check bon marché : lit seulement la QUEUE du fichier (pas tout le fichier —
    lecture+parse intégrale coûteuse, cf. revue finale S234) et vérifie que sa dernière
    ligne égale exactement ce qu'on vient de sérialiser. Appelé sous le verrou, juste après
    l'écriture.

    Si la queue relue ne contient aucune ligne complète (cas extrême d'une ligne
    individuelle plus grosse que la queue), c'est un échec de vérification honnête —
    log + False, jamais une exception ni une supposition optimiste."""
    try:
        taille = CHEMIN.stat().st_size
        taille_lue = min(taille, _TAILLE_QUEUE_CHECK)
        with CHEMIN.open("rb") as f:
            f.seek(taille - taille_lue)
            bloc = f.read()
    except OSError:
        logger.error("journal_modele: invariant violé — relecture impossible juste après écriture")
        return False

    texte = bloc.decode("utf-8", errors="replace")
    if taille > taille_lue:
        # Le bloc peut commencer au milieu d'une ligne : on jette le fragment initial
        # potentiellement tronqué. La DERNIÈRE ligne, elle, est forcément complète — le
        # fichier se termine toujours par un "\n" (cf. écriture ci-dessous).
        idx = texte.find("\n")
        texte = texte[idx + 1:] if idx != -1 else ""

    lignes = [l for l in texte.splitlines() if l.strip()]
    if not lignes:
        logger.error("journal_modele: invariant violé — aucune ligne complète dans la queue "
                     "relue (ligne individuelle probablement > %d octets)", _TAILLE_QUEUE_CHECK)
        return False
    try:
        derniere = json.loads(lignes[-1])
    except json.JSONDecodeError:
        logger.error("journal_modele: invariant violé — dernière ligne illisible juste après écriture")
        return False
    if derniere != attendue:
        logger.error("journal_modele: invariant violé — la dernière ligne relue diffère de "
                     "ce qui vient d'être écrit")
        return False
    return True


def _borner_si_necessaire() -> None:
    """Bornage best-effort — coûteux (lecture+réécriture intégrale du fichier), donc pas
    évalué à CHAQUE écriture : seulement une fois tous les INTERVALLE_BORNAGE appels
    (compteur en mémoire de process). Le fichier reste borné à ~MODELE_JOURNAL_MAX lignes
    À TERME, avec une tolérance de l'ordre d'INTERVALLE_BORNAGE lignes entre 2 vérifications
    — pas garanti exactement après chaque appel individuel.

    DOIT tourner INCONDITIONNELLEMENT, y compris quand le check vivant échoue (c'est le
    cas où on en a le plus besoin). Appelé sous le verrou, indépendamment de la vérification
    d'intégrité."""
    global _compteur_depuis_bornage
    _compteur_depuis_bornage += 1
    if _compteur_depuis_bornage < INTERVALLE_BORNAGE:
        return
    _compteur_depuis_bornage = 0

    lignes = _lignes()
    mx = _max()
    if len(lignes) > int(mx * 1.2):
        try:
            CHEMIN.write_text("\n".join(json.dumps(x, ensure_ascii=False)
                                        for x in lignes[-mx:]) + "\n", encoding="utf-8")
        except OSError:
            pass


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
            # Bornage INCONDITIONNEL, même si le check vivant a échoué (cf. docstring).
            _borner_si_necessaire()
            return ok
    except Exception as e:
        # Volontairement large (pas juste OSError/TypeError/ValueError) : le module
        # promet « Ne lève jamais » ABSOLUMENT (best-effort) — cf. docstring.
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


def appels(fil: str, limite: int = 100) -> list[dict]:
    """Les derniers appels LLM journalisés pour CE fil (ordre chronologique)."""
    lignes = [l for l in _lignes() if l.get("fil") == fil]
    return lignes[-max(1, limite):]
