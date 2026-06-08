"""Réduction du contexte avant l'appel LLM (Sprint S138, chantier 3 — version pure).

Les tokens d'ENTRÉE forment souvent la majorité de la facture, et un historique
d'agent qui gonfle dégrade aussi la qualité (« lost in the middle »). On applique
ici les stratégies **non destructives et sans appel réseau** :

  1. Dédup / nettoyage léger (espaces superflus).
  2. Fenêtre glissante : on garde TOUS les messages système (prompt, contexte
     date) + les N derniers tours utiles.

La summarization à froid via petit modèle (chantier 3, étage 4) demande un appel
LLM : elle est laissée en crochet `# [S138-3b]` pour un incrément ultérieur, afin
de ne pas introduire ici de coût caché.

`estimer_tokens()` est une approximation locale (≈ 4 caractères/token) : suffisante
pour piloter une fenêtre et chiffrer l'économie, sans dépendance tokenizer.
"""

import re

# Nb de messages NON-système conservés en fin d'historique. Un « tour » d'agent
# = message utilisateur + éventuels assistant/tool : on garde large pour ne pas
# casser une boucle d'outils en cours.
DERNIERS_MESSAGES = 12

_ESPACES = re.compile(r"[ \t]+")
_LIGNES_VIDES = re.compile(r"\n{3,}")


def estimer_tokens(messages: list[dict]) -> int:
    """Approximation locale : ~4 caractères par token (anglais/français mêlés)."""
    total = 0
    for m in messages:
        contenu = m.get("content")
        if isinstance(contenu, str):
            total += len(contenu)
        elif contenu is not None:
            total += len(str(contenu))
    return total // 4


def _nettoyer(texte: str) -> str:
    texte = _ESPACES.sub(" ", texte)
    texte = _LIGNES_VIDES.sub("\n\n", texte)
    return texte.strip()


def trim(messages: list[dict], *, derniers: int = DERNIERS_MESSAGES) -> tuple[list[dict], int]:
    """Renvoie (messages_réduits, tokens_economises).

    Garantit l'intégrité de l'appel : tous les messages `system` sont conservés,
    et la fenêtre ne coupe jamais un message `tool` de sa réponse attendue côté
    modèle (on garde un bloc continu de fin d'historique)."""
    avant = estimer_tokens(messages)

    # 1) Nettoyage léger des contenus texte.
    nettoyes = []
    for m in messages:
        if isinstance(m.get("content"), str):
            m = {**m, "content": _nettoyer(m["content"])}
        nettoyes.append(m)

    # 2) Fenêtre glissante : système toujours gardé, reste tronqué par la fin.
    systeme = [m for m in nettoyes if m.get("role") == "system"]
    autres = [m for m in nettoyes if m.get("role") != "system"]
    if len(autres) > derniers:
        autres = autres[-derniers:]
        # Ne pas démarrer la fenêtre sur un message `tool` orphelin (sans l'appel
        # assistant qui l'a déclenché) : le modèle rejetterait l'historique.
        while autres and autres[0].get("role") == "tool":
            autres = autres[1:]

    reduits = systeme + autres
    apres = estimer_tokens(reduits)
    return reduits, max(0, avant - apres)
