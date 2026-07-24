"""Client de l'assistant du Cœur — consomme le flux SSE de `POST /assistant/chat`.

L'assistant répond en `text/event-stream` : des lignes `data: {json}` typées
(`texte_delta`, `texte`, `outil`, `resultat_outil`, `fin`, `erreur`) — cf. core/main.py.
Ici on RELAIE vers une messagerie : on n'a besoin que du texte. On accumule donc les
fragments `texte_delta`/`texte`, on condense les appels d'outils en une ligne (mode verbeux),
et on s'arrête sur `fin`. Une `erreur` lève — le pont retombera sur un repli honnête.

Pièces jointes (S196) : un `resultat_outil` d'une brique media (images/video/export) porte
`url_interne` — cf. `core/outils_communs.py::_reecrire_url_media`. Si l'appelant passe
`medias=[]`, on y ajoute chaque média rencontré ; le pont (`pont.py`) les télécharge et les
relaie en pièce jointe (`envoyer_photo`/`envoyer_document`). Sans `medias`, comportement
inchangé (rétrocompatible).
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


def _extraire_media(evt: dict, medias: list) -> None:
    """Un `resultat_outil` d'une brique media porte `url_interne` (S196) : on le collecte
    tel quel, le pont décidera comment le relayer (extension → sendPhoto/sendDocument)."""
    try:
        data = json.loads(evt.get("resultat") or "{}")
    except json.JSONDecodeError:
        return
    if isinstance(data, dict) and isinstance(data.get("url_interne"), str):
        medias.append({"url": data["url_interne"], "nom": evt.get("nom")})


def accumuler(evenements: list, *, verbeux: bool = False, medias: list | None = None) -> str:
    """Reconstruit le texte de réponse à partir des événements (gère deltas + outils)."""
    morceaux = []
    for evt in evenements:
        t = evt.get("type")
        if t in ("texte_delta", "texte"):
            morceaux.append(evt.get("contenu", ""))
        elif t == "outil" and verbeux:
            morceaux.append(f"\n🔧 {evt.get('nom', 'outil')}…\n")
        elif t == "resultat_outil" and medias is not None:
            _extraire_media(evt, medias)
        elif t == "erreur":
            raise RuntimeError(evt.get("contenu", "erreur de l'assistant"))
    return "".join(morceaux).strip()


async def converser(messages: list, *, verbeux: bool = False, timeout: float = 120.0,
                    surface: str | None = None, interlocuteur: str | None = None,
                    utilisateur: str | None = None, medias: list | None = None) -> str:
    """Envoie l'historique à l'assistant et renvoie sa réponse texte (flux SSE consommé).

    `surface`/`interlocuteur`/`utilisateur` alimentent la TRACE unifiée du Cœur (S78) : la
    conversation de cette messagerie est journalisée côté cerveau comme celle du dashboard.
    Lève en cas d'événement `erreur` ou d'échec réseau — l'appelant gère le repli honnête."""
    corps = {"messages": messages}
    if surface:
        corps["surface"] = surface
    if interlocuteur:
        corps["interlocuteur"] = interlocuteur
    if utilisateur:
        corps["utilisateur"] = utilisateur
    morceaux = []
    async with httpx.AsyncClient(timeout=timeout) as c:
        async with c.stream("POST", url_chat(), json=corps) as r:
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
                elif t == "resultat_outil" and medias is not None:
                    _extraire_media(evt, medias)
                elif t == "erreur":
                    raise RuntimeError(evt.get("contenu", "erreur de l'assistant"))
                elif t == "fin":
                    break
    return "".join(morceaux).strip()


def url_historique_utilisateur() -> str:
    base = os.getenv("NOYAU_ASSISTANT_URL", "http://host.docker.internal:5100").rstrip("/")
    return f"{base}/assistant/historique_utilisateur"


async def historique_utilisateur(utilisateur: str, limite: int = 40,
                                  timeout: float = 10.0) -> list:
    """Historique CROSS-SURFACE d'un compte, tenu par le journal unifié du Cœur (web +
    Telegram + tout autre canal). Lève en cas d'échec réseau — l'appelant (`pont.py`) gère
    le repli honnête sur son fil local à CE seul canal."""
    async with httpx.AsyncClient(timeout=timeout) as c:
        r = await c.get(url_historique_utilisateur(), params={"utilisateur": utilisateur,
                                                                "limite": limite})
        r.raise_for_status()
        data = r.json()
    msgs = data.get("messages")
    return msgs if isinstance(msgs, list) else []
