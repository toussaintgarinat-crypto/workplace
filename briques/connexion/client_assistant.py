"""Client de l'assistant du Cœur — consomme le flux SSE de `POST /assistant/chat`.

L'assistant répond en `text/event-stream` : des lignes `data: {json}` typées
(`texte_delta`, `texte`, `outil`, `resultat_outil`, `fin`, `erreur`) — cf. core/main.py.
Ici on RELAIE vers une messagerie : on n'a besoin que du texte. On accumule donc les
fragments `texte_delta`/`texte`, on condense les appels d'outils en une ligne (mode verbeux),
et on s'arrête sur `fin`. Une `erreur` lève — le pont retombera sur un repli honnête.
"""
import json
import os

import httpx


def url_chat() -> str:
    base = os.getenv("NOYAU_ASSISTANT_URL", "http://host.docker.internal:5100").rstrip("/")
    return f"{base}/assistant/chat"


def lire_sse(texte: str) -> list:
    """Découpe un flux SSE brut en liste d'événements JSON (utilitaire testable hors réseau)."""
    evts = []
    for ligne in texte.splitlines():
        ligne = ligne.strip()
        if not ligne.startswith("data:"):
            continue
        charge = ligne[len("data:"):].strip()
        if not charge:
            continue
        try:
            evts.append(json.loads(charge))
        except json.JSONDecodeError:
            continue
    return evts


def accumuler(evenements: list, *, verbeux: bool = False) -> str:
    """Reconstruit le texte de réponse à partir des événements (gère deltas + outils)."""
    morceaux = []
    for evt in evenements:
        t = evt.get("type")
        if t in ("texte_delta", "texte"):
            morceaux.append(evt.get("contenu", ""))
        elif t == "outil" and verbeux:
            morceaux.append(f"\n🔧 {evt.get('nom', 'outil')}…\n")
        elif t == "erreur":
            raise RuntimeError(evt.get("contenu", "erreur de l'assistant"))
    return "".join(morceaux).strip()


async def converser(messages: list, *, verbeux: bool = False, timeout: float = 120.0) -> str:
    """Envoie l'historique à l'assistant et renvoie sa réponse texte (flux SSE consommé).

    Lève en cas d'événement `erreur` ou d'échec réseau — l'appelant gère le repli honnête."""
    morceaux = []
    async with httpx.AsyncClient(timeout=timeout) as c:
        async with c.stream("POST", url_chat(), json={"messages": messages}) as r:
            r.raise_for_status()
            async for ligne in r.aiter_lines():
                if not ligne or not ligne.startswith("data:"):
                    continue
                charge = ligne[len("data:"):].strip()
                if not charge:
                    continue
                try:
                    evt = json.loads(charge)
                except json.JSONDecodeError:
                    continue
                t = evt.get("type")
                if t in ("texte_delta", "texte"):
                    morceaux.append(evt.get("contenu", ""))
                elif t == "outil" and verbeux:
                    morceaux.append(f"\n🔧 {evt.get('nom', 'outil')}…\n")
                elif t == "erreur":
                    raise RuntimeError(evt.get("contenu", "erreur de l'assistant"))
                elif t == "fin":
                    break
    return "".join(morceaux).strip()
