"""Historique de conversation par interlocuteur — persisté, fenêtre bornée.

L'assistant du Cœur est STATELESS : il ne retient rien entre deux appels, c'est au client
de tenir l'historique `messages`. Cette brique étant ce client pour les messageries, c'est
ICI qu'on garde le fil de chaque interlocuteur, séparément, clé = (réseau, id externe).

On borne la fenêtre (`CONNEXION_HISTORIQUE_MAX` messages) pour contenir le coût en tokens :
on ne garde que les N derniers tours. Le message *système* « qui parle » n'est PAS stocké
ici (il est reconstruit à chaque appel par le pont) — on ne range que user/assistant.
"""
import os

import stockage


def _max() -> int:
    try:
        return max(2, int(os.getenv("CONNEXION_HISTORIQUE_MAX", "40")))
    except ValueError:
        return 40


def _nom(reseau: str, id_externe: str) -> str:
    return f"conversations/{stockage.slug(reseau)}__{stockage.slug(id_externe)}.json"


def charger(reseau: str, id_externe: str) -> list:
    """Renvoie les messages user/assistant déjà échangés (les plus récents, bornés)."""
    data = stockage.lire_json(_nom(reseau, id_externe), {})
    msgs = data.get("messages") if isinstance(data, dict) else None
    return msgs if isinstance(msgs, list) else []


def ajouter(reseau: str, id_externe: str, role: str, contenu: str) -> list:
    """Ajoute un message au fil et persiste (en gardant les `_max()` derniers)."""
    msgs = charger(reseau, id_externe)
    msgs.append({"role": role, "content": contenu})
    if len(msgs) > _max():
        msgs = msgs[-_max():]
    stockage.ecrire_json(_nom(reseau, id_externe), {"messages": msgs})
    return msgs


def effacer(reseau: str, id_externe: str) -> None:
    """Oublie le fil d'un interlocuteur (repart de zéro)."""
    stockage.ecrire_json(_nom(reseau, id_externe), {"messages": []})
