"""Client de la brique Agenda (Sprint S10).

La brique `agenda` (port 8400, reprise de workspace/calendar) gère calendriers et
événements. Auth désactivée sur le réseau interne → l'identité vient de l'en-tête
**X-User-Id** ; l'assistant est mono-utilisateur « perso ».

Ce module ne fait qu'appeler les contrats HTTP de la brique (aucune logique métier
réécrite). Il garantit l'existence d'un **calendrier par défaut** (la brique n'en crée
pas tout seul) et expose des helpers consommés par les outils de l'assistant.
"""

import os

import httpx

import orchestrateur

USER_ID = "perso"
# Identité S2S : X-User-Id ; et, si l'auth de la brique est active, le service-token
# (CALENDAR_SERVICE_TOKEN) qui autorise les appels inter-services. Inoffensif si vide.
_ENTETES = {"X-User-Id": USER_ID}
_SERVICE_TOKEN = os.environ.get("CALENDAR_SERVICE_TOKEN", "")
if _SERVICE_TOKEN:
    _ENTETES["Authorization"] = f"Bearer {_SERVICE_TOKEN}"
_cal_defaut: str | None = None  # mémoïsé après première résolution


def _base(registre) -> str:
    return orchestrateur._brique_base(registre, "agenda")


def _lien_invitation(base: str, token: str) -> str:
    """Lien d'acceptation d'une invitation. Privilégie AGENDA_URL_PUBLIQUE (host
    joignable par l'invité, p. ex. via la gateway) ; à défaut l'URL interne de la
    brique — honnête, mais valable seulement sur le réseau interne."""
    racine = os.environ.get("AGENDA_URL_PUBLIQUE", "").rstrip("/") or base
    return f"{racine}/invitations/{token}/page"


async def _calendrier_defaut(client: httpx.AsyncClient, registre) -> str:
    """Renvoie l'id du calendrier par défaut, en le créant au besoin."""
    global _cal_defaut
    if _cal_defaut:
        return _cal_defaut
    base = _base(registre)
    r = await client.get(f"{base}/calendars", headers=_ENTETES)
    cals = r.json() if r.status_code < 400 else []
    if cals:
        # Préfère un calendrier marqué par défaut, sinon le premier.
        cal = next((c for c in cals if c.get("is_default")), cals[0])
        _cal_defaut = cal["id"]
        return _cal_defaut
    r = await client.post(f"{base}/calendars", headers=_ENTETES,
                          json={"name": "Perso", "is_default": True})
    r.raise_for_status()
    _cal_defaut = r.json()["id"]
    return _cal_defaut


# ── Partage : calendriers, membres, invitations ──────────────────────────────

async def lister_agendas(registre) -> list[dict]:
    """Tous les calendriers accessibles (possédés + partagés), avec le rôle de
    l'utilisateur sur chacun ('owner' | 'editor' | 'viewer')."""
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(f"{_base(registre)}/calendars", headers=_ENTETES)
        return r.json() if r.status_code < 400 else []


async def creer_agenda_partage(registre, nom: str, description: str | None = None,
                               couleur: str | None = None) -> dict:
    """Crée un nouveau calendrier (partageable). Le créateur en est 'owner' et
    peut ensuite générer des invitations. Renvoie le calendrier créé."""
    async with httpx.AsyncClient(timeout=15) as client:
        corps: dict = {"name": nom}
        if description:
            corps["description"] = description
        if couleur:
            corps["color"] = couleur
        r = await client.post(f"{_base(registre)}/calendars", headers=_ENTETES, json=corps)
        r.raise_for_status()
        return r.json()


async def inviter(registre, calendar_id: str, role: str = "viewer",
                  expire_heures: int | None = 72, email: str | None = None) -> dict:
    """Génère un lien d'invitation à un calendrier (rôle 'editor' ou 'viewer').
    Renvoie l'invitation enrichie d'un champ `lien` d'acceptation."""
    async with httpx.AsyncClient(timeout=15) as client:
        base = _base(registre)
        corps: dict = {"role": role}
        if expire_heures is not None:
            corps["expires_in_hours"] = expire_heures
        if email:
            corps["email"] = email
        r = await client.post(f"{base}/calendars/{calendar_id}/invitations",
                             headers=_ENTETES, json=corps)
        r.raise_for_status()
        inv = r.json()
        inv["lien"] = _lien_invitation(base, inv["token"])
        return inv


async def lister_membres(registre, calendar_id: str) -> list[dict]:
    """Membres d'un calendrier partagé (user_id + rôle)."""
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(f"{_base(registre)}/calendars/{calendar_id}/members",
                             headers=_ENTETES)
        return r.json() if r.status_code < 400 else []


async def lister_evenements(registre, debut: str | None = None, fin: str | None = None) -> list[dict]:
    """Événements du calendrier par défaut, filtrés sur [debut, fin] (ISO 8601)."""
    async with httpx.AsyncClient(timeout=15) as client:
        cal = await _calendrier_defaut(client, registre)
        params = {}
        if debut:
            params["start"] = debut
        if fin:
            params["end"] = fin
        r = await client.get(f"{_base(registre)}/calendars/{cal}/events",
                             headers=_ENTETES, params=params)
        return r.json() if r.status_code < 400 else []


async def creer_evenement(registre, titre: str, debut: str, fin: str,
                          lieu: str | None = None, description: str | None = None) -> dict:
    """Crée un événement dans le calendrier par défaut. Renvoie l'événement créé."""
    async with httpx.AsyncClient(timeout=15) as client:
        cal = await _calendrier_defaut(client, registre)
        corps = {"title": titre, "start_at": debut, "end_at": fin}
        if lieu:
            corps["location"] = lieu
        if description:
            corps["description"] = description
        r = await client.post(f"{_base(registre)}/calendars/{cal}/events",
                             headers=_ENTETES, json=corps)
        r.raise_for_status()
        return r.json()


async def deplacer_evenement(registre, event_id: str, debut: str, fin: str) -> dict:
    """Replanifie un événement (PATCH des dates)."""
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.patch(f"{_base(registre)}/events/{event_id}",
                             headers=_ENTETES, json={"start_at": debut, "end_at": fin})
        r.raise_for_status()
        return r.json()


async def supprimer_evenement(registre, event_id: str) -> bool:
    """Annule (supprime) un événement."""
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.delete(f"{_base(registre)}/events/{event_id}", headers=_ENTETES)
        return r.status_code < 400
