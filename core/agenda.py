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

import contexte_tenant
import orchestrateur

USER_ID = "perso"  # défaut rétrocompatible (mono-user) quand aucun contexte n'est posé
# Service-token S2S : si l'auth de la brique est active, autorise les appels
# inter-services. Inoffensif si vide.
_SERVICE_TOKEN = os.environ.get("CALENDAR_SERVICE_TOKEN", "")


def _entetes() -> dict:
    """En-têtes S2S vers la brique agenda, à chaque appel.

    Identité S2S : `X-User-Id` = utilisateur du contexte de tenant (S121), défaut
    `perso` quand le Cœur tourne mono-user. Le service-token, lui, est fixe.
    """
    e = contexte_tenant.entetes_par_personne()  # {"X-User-Id": <utilisateur courant ou perso>}
    if _SERVICE_TOKEN:
        e["Authorization"] = f"Bearer {_SERVICE_TOKEN}"
    return e


_cal_defaut: str | None = None  # mémoïsé après première résolution


def _base(registre) -> str:
    return orchestrateur._brique_base(registre, "agenda")


async def _calendrier_defaut(client: httpx.AsyncClient, registre) -> str:
    """Renvoie l'id du calendrier par défaut, en le créant au besoin."""
    global _cal_defaut
    if _cal_defaut:
        return _cal_defaut
    base = _base(registre)
    r = await client.get(f"{base}/calendars", headers=_entetes())
    cals = r.json() if r.status_code < 400 else []
    if cals:
        # Préfère un calendrier marqué par défaut, sinon le premier.
        cal = next((c for c in cals if c.get("is_default")), cals[0])
        _cal_defaut = cal["id"]
        return _cal_defaut
    r = await client.post(f"{base}/calendars", headers=_entetes(),
                          json={"name": "Perso", "is_default": True})
    r.raise_for_status()
    _cal_defaut = r.json()["id"]
    return _cal_defaut


# ── Calendriers (lecture — servie au dashboard) ──────────────────────────────
# NB (S168) : la CRÉATION d'agenda partagé et les INVITATIONS pilotées par l'assistant
# ont migré vers la surface `/service` de la brique (capacités agenda_creer_partage /
# agenda_inviter). Ne restent ici que les proxys encore consommés par le routeur dashboard.

async def lister_agendas(registre) -> list[dict]:
    """Tous les calendriers accessibles (possédés + partagés), avec le rôle de
    l'utilisateur sur chacun ('owner' | 'editor' | 'viewer')."""
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(f"{_base(registre)}/calendars", headers=_entetes())
        return r.json() if r.status_code < 400 else []


async def creer_agenda(registre, nom: str, couleur: str | None = None,
                       description: str | None = None) -> dict:
    """Crée un calendrier partageable au nom de l'utilisateur de session (S182b) : le
    créateur en est owner et peut ensuite y inviter des personnes. Proxy vers la brique
    (`POST /calendars`), identité portée par `_entetes()` (X-User-Id de session)."""
    corps: dict = {"name": nom}
    if couleur:
        corps["color"] = couleur
    if description:
        corps["description"] = description
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(f"{_base(registre)}/calendars", headers=_entetes(), json=corps)
        r.raise_for_status()
        return r.json()


async def creer_invitation(registre, calendar_id: str, role: str = "viewer",
                           expire_heures: int | None = 72, email: str | None = None) -> dict:
    """Génère un lien d'invitation à un calendrier (S182b). Proxy vers la surface
    `/service` de la brique (owner requis) sous l'identité de session : cette surface
    renvoie le `lien` d'acceptation prêt à transmettre (construit depuis
    `AGENDA_URL_PUBLIQUE`), en plus du `token`."""
    corps: dict = {"role": role}
    if expire_heures is not None:
        corps["expire_heures"] = expire_heures
    if email:
        corps["email"] = email
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(f"{_base(registre)}/service/calendars/{calendar_id}/invitations",
                              headers=_entetes(), json=corps)
        r.raise_for_status()
        return r.json()


async def accepter_invitation(registre, token: str) -> dict:
    """Accepte une invitation au nom de l'utilisateur de session (S182b) : il devient
    membre du calendrier avec le rôle de l'invitation. Proxy vers `POST
    /invitations/{token}/accept`, identité portée par `_entetes()` (X-User-Id de session).
    Lève pour un token inconnu/expiré/déjà utilisé (4xx propagé par la brique)."""
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(f"{_base(registre)}/invitations/{token}/accept", headers=_entetes())
        r.raise_for_status()
        return r.json()


async def lister_evenements(registre, debut: str | None = None, fin: str | None = None) -> list[dict]:
    """Événements de TOUS les calendriers accessibles, filtrés sur [debut, fin] (ISO 8601).

    L'AGRÉGATION multi-calendriers (perso + Google + TimeTree + partagés) + la jointure
    étiquette/couleur vivent désormais DANS la brique (surface `/service/events`, S168) :
    ce client ne fait plus qu'un GET. La forme renvoyée est inchangée (événements enrichis
    de `calendrier`, `etiquette`, `couleur`) — consommée à l'identique par le dashboard,
    le briefing et le proactif. Cf. ADR docs/decisions/2026-07-14-agenda-surface-de-service.md."""
    async with httpx.AsyncClient(timeout=15) as client:
        params = {}
        if debut:
            params["debut"] = debut
        if fin:
            params["fin"] = fin
        r = await client.get(f"{_base(registre)}/service/events",
                             headers=_entetes(), params=params)
        return r.json() if r.status_code < 400 else []


async def definir_rappels(registre, event_id: str, rappels: list[int]) -> dict:
    """Remplace la liste des rappels d'un événement (minutes avant le début).
    Liste vide = supprime tous les rappels. Renvoie l'événement mis à jour."""
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.patch(f"{_base(registre)}/events/{event_id}",
                             headers=_entetes(), json={"rappels": rappels})
        r.raise_for_status()
        return r.json()


async def creer_evenement_dans(registre, calendar_id: str | None, corps: dict) -> dict:
    """Crée un événement dans un calendrier donné (ou le défaut) — `corps` = champs bruts
    de la brique (title, start_at, end_at, location, description, color, all_day, rappels)."""
    async with httpx.AsyncClient(timeout=15) as client:
        cal = calendar_id or await _calendrier_defaut(client, registre)
        r = await client.post(f"{_base(registre)}/calendars/{cal}/events",
                             headers=_entetes(), json=corps)
        r.raise_for_status()
        return r.json()


async def modifier_evenement(registre, event_id: str, corps: dict) -> dict:
    """Met à jour un événement (PATCH partiel) — `corps` = champs bruts de la brique."""
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.patch(f"{_base(registre)}/events/{event_id}",
                             headers=_entetes(), json=corps)
        r.raise_for_status()
        return r.json()


# ── Étiquettes nommées (catégories) ──────────────────────────────────────────

async def lister_etiquettes(registre, calendar_id: str) -> list[dict]:
    """Étiquettes d'un calendrier ({id, name, color, …})."""
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(f"{_base(registre)}/calendars/{calendar_id}/labels",
                             headers=_entetes())
        return r.json() if r.status_code < 400 else []


async def creer_etiquette(registre, calendar_id: str, nom: str,
                          couleur: str | None = None) -> dict:
    """Crée une étiquette nommée dans un calendrier."""
    async with httpx.AsyncClient(timeout=15) as client:
        corps: dict = {"name": nom}
        if couleur:
            corps["color"] = couleur
        r = await client.post(f"{_base(registre)}/calendars/{calendar_id}/labels",
                             headers=_entetes(), json=corps)
        r.raise_for_status()
        return r.json()


async def modifier_etiquette(registre, label_id: str, corps: dict) -> dict:
    """Renomme / recolore une étiquette (PATCH partiel : name, color)."""
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.patch(f"{_base(registre)}/labels/{label_id}",
                             headers=_entetes(), json=corps)
        r.raise_for_status()
        return r.json()


async def supprimer_etiquette(registre, label_id: str) -> bool:
    """Supprime une étiquette ; les événements concernés repassent « sans étiquette »."""
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.delete(f"{_base(registre)}/labels/{label_id}", headers=_entetes())
        return r.status_code < 400


# ── Pièces jointes (documents) ───────────────────────────────────────────────

async def lister_documents(registre, event_id: str) -> list[dict]:
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(f"{_base(registre)}/events/{event_id}/attachments",
                             headers=_entetes())
        return r.json() if r.status_code < 400 else []


async def televerser_document(registre, event_id: str, nom: str, octets: bytes,
                              mimetype: str | None = None) -> dict:
    async with httpx.AsyncClient(timeout=60) as client:
        files = {"file": (nom, octets, mimetype or "application/octet-stream")}
        r = await client.post(f"{_base(registre)}/events/{event_id}/attachments",
                             headers=_entetes(), files=files)
        r.raise_for_status()
        return r.json()


async def telecharger_document(registre, att_id: str):
    """Renvoie (octets, nom, mimetype) d'une pièce jointe, ou (None, None, None)."""
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.get(f"{_base(registre)}/attachments/{att_id}/download",
                             headers=_entetes())
        if r.status_code >= 400:
            return None, None, None
        cd = r.headers.get("content-disposition", "")
        nom = "fichier"
        if "filename=" in cd:
            nom = cd.split("filename=", 1)[1].strip('"; ')
        return r.content, nom, r.headers.get("content-type", "application/octet-stream")


async def supprimer_document(registre, att_id: str) -> bool:
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.delete(f"{_base(registre)}/attachments/{att_id}", headers=_entetes())
        return r.status_code < 400


# ── Commentaires ─────────────────────────────────────────────────────────────

async def lister_commentaires(registre, event_id: str) -> list[dict]:
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(f"{_base(registre)}/events/{event_id}/comments",
                             headers=_entetes())
        return r.json() if r.status_code < 400 else []


async def ajouter_commentaire(registre, event_id: str, contenu: str) -> dict:
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(f"{_base(registre)}/events/{event_id}/comments",
                             headers=_entetes(), json={"content": contenu})
        r.raise_for_status()
        return r.json()


async def supprimer_commentaire(registre, comment_id: str) -> bool:
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.delete(f"{_base(registre)}/comments/{comment_id}", headers=_entetes())
        return r.status_code < 400


async def supprimer_evenement(registre, event_id: str) -> bool:
    """Annule (supprime) un événement."""
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.delete(f"{_base(registre)}/events/{event_id}", headers=_entetes())
        return r.status_code < 400


# ── Pont TimeTree (lecture seule, non officiel) ──────────────────────────────

async def timetree_etat(registre) -> dict:
    """Connecté à TimeTree ? Quel calendrier partagé sélectionné ?"""
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(f"{_base(registre)}/timetree/status", headers=_entetes())
        return r.json() if r.status_code < 400 else {"connected": False}


async def timetree_connecter(registre, email: str, password: str,
                             calendar_id: str | None = None) -> dict:
    """Valide les identifiants TimeTree et les range au coffre. Renvoie la liste des
    calendriers (pour en choisir un) ou une erreur lisible si le login échoue."""
    async with httpx.AsyncClient(timeout=30) as client:
        corps: dict = {"email": email, "password": password}
        if calendar_id:
            corps["calendar_id"] = calendar_id
        r = await client.post(f"{_base(registre)}/timetree/connect",
                             headers=_entetes(), json=corps)
        if r.status_code >= 400:
            detail = r.json().get("detail") if "application/json" in r.headers.get("content-type", "") else r.text
            return {"connected": False, "erreur": detail}
        return r.json()


async def timetree_choisir_calendrier(registre, calendar_id: str) -> dict:
    """Choisit le calendrier partagé TimeTree à synchroniser."""
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(f"{_base(registre)}/timetree/select",
                             headers=_entetes(), json={"calendar_id": calendar_id})
        r.raise_for_status()
        return r.json()


async def timetree_synchroniser(registre) -> dict:
    """Déclenche un pull TimeTree → calendrier « TimeTree » (lecture seule)."""
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(f"{_base(registre)}/timetree/sync", headers=_entetes())
        if r.status_code >= 400:
            detail = r.json().get("detail") if "application/json" in r.headers.get("content-type", "") else r.text
            return {"ok": False, "erreur": detail}
        return {"ok": True, **r.json()}


async def timetree_deconnecter(registre) -> bool:
    """Purge les identifiants TimeTree du coffre (révocation)."""
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.delete(f"{_base(registre)}/timetree/disconnect", headers=_entetes())
        return r.status_code < 400


# ── Pont Google Agenda (consenti, lecture seule, OAuth) ──────────────────────

async def google_etat(registre) -> dict:
    """Connecté à Google ? (+ expiration / scope si oui)."""
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(f"{_base(registre)}/google/status", headers=_entetes())
        return r.json() if r.status_code < 400 else {"connected": False}


async def google_url_consentement(registre) -> dict:
    """URL de consentement Google à ouvrir côté navigateur (flux OAuth, ≠ TimeTree).

    Renvoie {ok, authorization_url} ou {ok: False, erreur} si le pont n'est pas
    configuré (GOOGLE_CLIENT_ID/SECRET absents)."""
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(f"{_base(registre)}/google/connect", headers=_entetes())
        if r.status_code >= 400:
            detail = r.json().get("detail") if "application/json" in r.headers.get("content-type", "") else r.text
            return {"ok": False, "erreur": detail}
        return {"ok": True, **r.json()}


async def google_synchroniser(registre, debut: str | None = None, fin: str | None = None) -> dict:
    """Déclenche un pull Google → calendrier « Google » (lecture seule, idempotent)."""
    async with httpx.AsyncClient(timeout=60) as client:
        params = {}
        if debut:
            params["time_min"] = debut
        if fin:
            params["time_max"] = fin
        r = await client.post(f"{_base(registre)}/google/sync", headers=_entetes(), params=params)
        if r.status_code >= 400:
            detail = r.json().get("detail") if "application/json" in r.headers.get("content-type", "") else r.text
            return {"ok": False, "erreur": detail}
        return {"ok": True, **r.json()}


async def google_deconnecter(registre) -> bool:
    """Purge les tokens Google du coffre (révocation du consentement)."""
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.delete(f"{_base(registre)}/google/disconnect", headers=_entetes())
        return r.status_code < 400
