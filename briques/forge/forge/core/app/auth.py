"""Authentification & contexte utilisateur — portage du middleware Bun (S127).

Réplique ``forge/core/src/api/middleware/auth.ts`` :
1. vérifie le JWT Keycloak (JWKS, via ``shared.workplace_auth``, lib partagée S120) ;
2. provisionne l'utilisateur Forge (par keycloak_sub, sinon par email, sinon insert) ;
3. auto-crée l'organisation personnelle + membership au premier login ;
4. résout l'org active : header ``X-Org-ID`` (si membre) → sinon org personnelle ;
5. expose un ``UserContext`` {sub, nom, avatar_emoji, org_id} aux routers.

`sub` = ``users.id`` Forge (UUID en str), PAS le sub Keycloak — cohérent avec le
Bun (toutes les colonnes user_id stockent l'UUID Forge).
"""

from __future__ import annotations

import logging
import time
import uuid as uuidlib
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

# JWT Keycloak : lib partagée unique du monorepo (S120). Remplace la copie vendored
# agent_personnel_shared.keycloak_auth (le reste du paquet vendored reste utilisé).
from shared.workplace_auth import KeycloakSettings, verify_token

from app.config import settings
from app.db import SessionLocal
from app.models import OrganizationMembers, Organizations, Users

logger = logging.getLogger(__name__)

_KC = KeycloakSettings(
    url=settings.KEYCLOAK_URL,
    realm=settings.KEYCLOAK_REALM,
    audience=settings.KEYCLOAK_AUDIENCE,  # vide ⇒ verify_aud désactivé (multi-tenant)
)

_bearer = HTTPBearer(auto_error=False)


@dataclass
class UserContext:
    sub: str          # users.id (UUID Forge en str)
    nom: str
    avatar_emoji: str
    org_id: str | None
    venture_scopes: frozenset[str] = frozenset()  # S227 — role client_lecture
    # S230 — jeton client_credentials émis directement au client `forge-service`
    # (distinct d'un jeton utilisateur qui transite PAR ce client). Permet aux routes
    # scopées par owner_id de reconnaître un appelant de service de confiance sans
    # élargir `client_lecture` (qui reste lecture-seule, inchangé).
    est_service: bool = False


def _membre_actif(query):
    """S227 (revue post-fusion whole-branch, wave 2) — exclut les memberships
    ``client_lecture`` de toute requête qui teste "l'utilisateur est-il membre
    actif de cette org ?" pour en déduire un droit (org active résolue,
    visibilité d'une org, liste des orgs...).

    Ce rôle est un accès en lecture seule scopé à UNE venture précise (cf.
    ``_resolve_venture_scopes`` ci-dessous, qui fait l'inverse : il sélectionne
    *seulement* les memberships ``client_lecture`` pour construire les scopes).
    Une appartenance ``client_lecture`` ne doit JAMAIS compter comme
    appartenance active à l'organisation elle-même.

    Centralisé ici après que la revue a trouvé ce même bug (rôle non vérifié
    dans une requête ``OrganizationMembers``) à plusieurs sites indépendants :
    ``_resolve_org`` (celui-ci), ``ventures._resolve_org_id``,
    ``organizations.get_org``, ``organizations.list_orgs``. Toute nouvelle
    requête qui résout/autorise via appartenance à une org doit passer par ici
    plutôt que réinventer le filtre.

    Prend un ``select(...)`` (éventuellement déjà ``.join()``é) et renvoie la
    même query avec le filtre ajouté — chainable comme n'importe quel
    ``.where()`` supplémentaire.
    """
    return query.where(OrganizationMembers.role != "client_lecture")


async def _provision_user(session, payload: dict) -> Users:
    keycloak_sub = payload["sub"]

    async def _par_sub():
        return (
            await session.execute(select(Users).where(Users.keycloak_sub == keycloak_sub))
        ).scalar_one_or_none()

    async def _par_email(email):
        return (
            await session.execute(select(Users).where(Users.email == email))
        ).scalar_one_or_none()

    user = await _par_sub()
    if user:
        return user

    nom = payload.get("nom") or payload.get("preferred_username") or payload.get("name") or "Utilisateur"
    email = payload.get("email") or f"{keycloak_sub}@forge.local"
    avatar_emoji = payload.get("avatarEmoji") or "👤"

    by_email = await _par_email(email)
    if by_email:
        by_email.keycloak_sub = keycloak_sub
        await session.flush()
        return by_email

    # Course concurrente (bug S19) : deux 1ers logins du même utilisateur passent tous
    # deux le select ci-dessus, puis insèrent → violation d'unicité (keycloak_sub/email)
    # → 500 « auto-réparé » au retry. On isole l'insert dans un savepoint : si l'unicité
    # saute, l'autre transaction a gagné — on récupère l'utilisateur déjà créé.
    try:
        async with session.begin_nested():
            user = Users(email=email, nom=nom, avatar_emoji=avatar_emoji, keycloak_sub=keycloak_sub)
            session.add(user)
            await session.flush()
        return user
    except IntegrityError:
        gagnant = await _par_sub() or await _par_email(email)
        if gagnant is None:
            raise  # unicité violée pour une autre raison : ne pas masquer
        logger.info("[forge:auth] provision concurrente résolue pour sub=%s", keycloak_sub)
        return gagnant


async def _ensure_personal_org(session, user: Users) -> None:
    async def _org_existante():
        return (
            await session.execute(select(Organizations).where(Organizations.owner_id == str(user.id)))
        ).scalars().first()

    if await _org_existante():
        return
    local = user.email.split("@")[0].lower()
    slug_base = "".join(ch if ch.isalnum() else "-" for ch in local)
    slug = f"{slug_base}-{int(time.time() * 1000)}"
    # Même course que pour l'utilisateur (S19) : isole la création dans un savepoint. Si
    # un login concurrent a créé l'org personnelle entre-temps (collision de slug ou org
    # déjà présente), on récupère l'existante au lieu de planter en 500.
    try:
        async with session.begin_nested():
            org = Organizations(nom=user.nom, slug=slug, emoji="🏠", owner_id=str(user.id), plan="personal")
            session.add(org)
            await session.flush()
            session.add(OrganizationMembers(org_id=org.id, user_id=str(user.id), role="owner"))
            await session.flush()
    except IntegrityError:
        if await _org_existante() is None:
            raise
        logger.info("[forge:auth] org personnelle concurrente résolue pour user=%s", user.id)


async def _resolve_org(session, user: Users, requested_org_id: str | None) -> str | None:
    if requested_org_id:
        try:
            req_uuid = uuidlib.UUID(requested_org_id)
        except ValueError:
            req_uuid = None
        if req_uuid is not None:
            # S227 — une appartenance client_lecture (accès en lecture, scopé à
            # une venture précise) ne doit JAMAIS résoudre en org active : sinon
            # X-Org-ID rouvrirait tous les routers org-scopés (automation,
            # dev_team, sessions, rapport, ...) pour cette org, pas seulement le
            # dossier de la venture concernée. Repli honnête et sans erreur sur
            # l'org personnelle (cf. docstring _resolve_org ci-dessus).
            membership = (
                await session.execute(
                    _membre_actif(
                        select(OrganizationMembers).where(
                            OrganizationMembers.org_id == req_uuid,
                            OrganizationMembers.user_id == str(user.id),
                        )
                    )
                )
            ).scalar_one_or_none()
            if membership:
                return requested_org_id

    default_org = (
        await session.execute(
            select(Organizations).where(Organizations.owner_id == str(user.id)).limit(1)
        )
    ).scalars().first()
    return str(default_org.id) if default_org else None


async def verify_ws_token(token: str | None) -> dict | None:
    """Vérifie un JWT passé en query string (WebSocket) — pas de header Bearer.

    Renvoie le payload décodé, ou ``None`` si invalide/absent. Utilisé par les
    routes WS (ws, voice-realtime) où le token transite via ``?token=`` (S134).
    """
    if not token:
        return None
    try:
        return await verify_token(token, _KC)
    except Exception as exc:
        logger.info("[forge:auth:ws] verify failed: %s", str(exc)[:120])
        return None


async def provision_ws_user(token: str | None) -> str | None:
    """Vérifie le token WS puis provisionne l'utilisateur Forge (id en str).

    Réplique le flux d'``ws.ts`` : verify → provision (sub/email/insert) → org
    personnelle. Renvoie ``users.id`` (UUID Forge str) ou ``None`` si non autorisé.
    """
    payload = await verify_ws_token(token)
    if payload is None:
        return None
    async with SessionLocal() as session:
        user = await _provision_user(session, payload)
        await _ensure_personal_org(session, user)
        await session.commit()
        return str(user.id)


async def _resolve_venture_scopes(session, user_id: str) -> frozenset[str]:
    """S227 — ventures accessibles en lecture seule via le rôle client_lecture."""
    rows = (
        await session.execute(
            select(OrganizationMembers.venture_scope).where(
                OrganizationMembers.user_id == user_id,
                OrganizationMembers.role == "client_lecture",
                OrganizationMembers.venture_scope.is_not(None),
            )
        )
    ).scalars().all()
    return frozenset(rows)


def _est_compte_service(payload: dict) -> bool:
    """`azp` (authorized party) porte le client_id qui a demandé le jeton — stable pour
    un jeton client_credentials émis directement au client `forge-service` (contrairement
    à `sub`, qui varie par utilisateur provisionné). Un jeton utilisateur normal, même
    émis pour un AUTRE client public (ex. `coeur-web`), a un `azp` différent."""
    return payload.get("azp") == settings.FORGE_SERVICE_CLIENT_ID


async def get_current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> UserContext:
    if creds is None or not creds.credentials:
        raise HTTPException(status_code=401, detail="Unauthorized")
    try:
        payload = await verify_token(creds.credentials, _KC)
    except Exception as exc:  # JWTError & co. → 401 (parité Bun "Invalid token")
        logger.info("[forge:auth] verify failed: %s", str(exc)[:120])
        raise HTTPException(status_code=401, detail="Invalid token")

    async with SessionLocal() as session:
        user = await _provision_user(session, payload)
        await _ensure_personal_org(session, user)
        org_id = await _resolve_org(session, user, request.headers.get("X-Org-ID"))
        venture_scopes = await _resolve_venture_scopes(session, str(user.id))
        await session.commit()
        return UserContext(
            sub=str(user.id),
            nom=user.nom,
            avatar_emoji=user.avatar_emoji or "👤",
            org_id=org_id,
            venture_scopes=venture_scopes,
            est_service=_est_compte_service(payload),
        )


async def require_org(user: UserContext = Depends(get_current_user)) -> str:
    """Org active **validée** de la requête (S18, Chantier 1).

    Renvoie ``user.org_id`` — résolu par ``_resolve_org`` qui n'honore le header
    ``X-Org-ID`` *que si l'appelant est membre* de l'org (sinon org personnelle).
    C'est la **seule** source d'``org_id`` de confiance.

    Les routers data-bearing **doivent** dépendre de ceci au lieu de relire
    ``X-Org-ID`` brut depuis le header : relire le header court-circuite la
    validation d'appartenance et ouvre une fuite inter-tenant.

    Lève 400 si aucune org active (cas normalement impossible : une org perso est
    toujours provisionnée au login — mais on refuse plutôt que de requêter en
    ``sql 1=1`` global, qui exposerait tous les tenants).
    """
    if not user.org_id:
        raise HTTPException(status_code=400, detail="No active organization")
    return user.org_id
