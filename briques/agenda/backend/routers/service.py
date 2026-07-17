"""Surface `/service` — pilotée par le Cœur via le manifest (S168).

Deux endpoints d'ORCHESTRATION que le dispatcher générique du Cœur ne sait pas exprimer :
agrégation multi-calendriers (GET) et création avec résolution du calendrier par défaut
(POST). Le contrat est en FRANÇAIS (mêmes noms de champs que les outils LLM historiques :
`titre`, `debut`, `fin`, `lieu`…) pour une bascule ISO-fonctionnelle. Auth : le dialecte
S2S Workplace (`AGENDA_KEY` + `X-Compte-Id`) est résolu par `get_current_user`, qui pinne
l'identité de calendrier sur `AGENDA_USER_ID`. Cf. ADR 2026-07-14-agenda-surface-de-service.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from config import settings
from db import get_db
from models.orm import Calendar, CalendarInvitation, Event
from models.schemas import EventOut, normaliser_rappels
from services import agregation
from services.occurrences import (
    creer_ou_maj_override,
    exclure_occurrence,
    occurrence_en_dict,
    occurrence_naive,
    occurrence_valide,
)
from services.pubsub import publish_change
from services.recurrence import Occurrence, valider_rrule
from utils.access import require_calendar_access

router = APIRouter(prefix="/service", tags=["service"])


class EvenementServiceIn(BaseModel):
    """Événement dicté par l'assistant. Champs français → traduits vers l'ORM. `debut`/`fin`
    obligatoires ; le calendrier est résolu (défaut) si `calendrier_id` n'est pas fourni."""
    titre: str
    debut: datetime
    fin: datetime
    lieu: Optional[str] = None
    description: Optional[str] = None
    couleur: Optional[str] = None
    etiquette_id: Optional[str] = None
    journee_entiere: bool = False
    rappels: Optional[list[int]] = None
    calendrier_id: Optional[str] = None
    recurrence: Optional[str] = None

    @field_validator("rappels")
    @classmethod
    def _rappels(cls, v):
        return normaliser_rappels(v)

    @field_validator("recurrence")
    @classmethod
    def _rrule(cls, v):
        return valider_rrule(v) if v else v


@router.get("/events")
async def service_lister_evenements(
    debut: Optional[datetime] = Query(None),
    fin: Optional[datetime] = Query(None),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Agrège les événements de TOUS les calendriers accessibles (perso + Google + TimeTree
    + partagés) sur [debut, fin], enrichis (calendrier, étiquette, couleur). Lecture seule."""
    return await agregation.evenements_agreges(db, user["sub"], debut, fin)


@router.post("/events", response_model=EventOut, status_code=status.HTTP_201_CREATED)
async def service_creer_evenement(
    corps: EvenementServiceIn,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Crée un événement — dans le calendrier demandé, sinon celui par défaut (créé au
    besoin). Effet immédiat (choix produit : create sans confirmation, cf. ADR)."""
    if corps.debut >= corps.fin:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="fin doit être après debut")
    if corps.calendrier_id:
        # Calendrier explicite → exige un droit d'écriture (404 si inaccessible/inexistant).
        await require_calendar_access(db, corps.calendrier_id, user["sub"], min_role="editor")
        cal_id = corps.calendrier_id
    else:
        cal_id = (await agregation.calendrier_defaut(db, user["sub"])).id
    evt = Event(
        calendar_id=cal_id, title=corps.titre, start_at=corps.debut, end_at=corps.fin,
        location=corps.lieu, description=corps.description, color=corps.couleur,
        label_id=corps.etiquette_id or None, all_day=corps.journee_entiere,
        rappels=corps.rappels or [], created_by=user["sub"],
        recurrence_rule=corps.recurrence,
    )
    db.add(evt)
    await db.flush()  # matérialise evt.id (default=_uuid appliqué au flush)
    from services.participants_auto import assurer_participant
    await assurer_participant(db, evt.id, user["sub"])
    await db.commit()
    await db.refresh(evt)
    out = EventOut.model_validate(evt)
    await publish_change(cal_id, "event.created", out.model_dump(mode="json"))
    return evt


class EvenementPatchIn(BaseModel):
    """Modification partielle (champs français). Sert `agenda_deplacer_evenement`
    (`debut`/`fin`) ET `agenda_definir_rappels` (`rappels`). None = champ non touché ;
    `rappels: []` efface tous les rappels (≠ non fourni)."""
    titre: Optional[str] = None
    debut: Optional[datetime] = None
    fin: Optional[datetime] = None
    lieu: Optional[str] = None
    description: Optional[str] = None
    couleur: Optional[str] = None
    etiquette_id: Optional[str] = None
    rappels: Optional[list[int]] = None
    recurrence: Optional[str] = None

    @field_validator("rappels")
    @classmethod
    def _rappels(cls, v):
        return normaliser_rappels(v)

    @field_validator("recurrence")
    @classmethod
    def _rrule(cls, v):
        return valider_rrule(v) if v else v


# Champ français → colonne ORM (seuls les champs fournis sont appliqués).
_PATCH_MAP = {"titre": "title", "debut": "start_at", "fin": "end_at", "lieu": "location",
              "description": "description", "couleur": "color", "etiquette_id": "label_id",
              "rappels": "rappels", "recurrence": "recurrence_rule"}


async def _charger_event_editable(db: AsyncSession, event_id: str, user_id: str) -> Event:
    evt = await db.get(Event, event_id)
    if not evt:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Événement introuvable")
    await require_calendar_access(db, evt.calendar_id, user_id, min_role="editor")
    return evt


@router.patch("/events/{event_id}", response_model=EventOut)
async def service_modifier_evenement(
    event_id: str,
    corps: EvenementPatchIn,
    scope: str = "all",
    occurrence: Optional[datetime] = Query(None),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Replanifie (debut/fin) ou re-règle les rappels d'un événement existant. Effet
    immédiat (choix produit). `etiquette_id`/`couleur` vides explicites = « aucune ».
    `scope="this"` sur une série récurrente isole une occurrence (event-override), le
    maître reste intact ; `scope="all"` (défaut) modifie la série/l'événement entier."""
    evt = await _charger_event_editable(db, event_id, user["sub"])
    if scope not in ("all", "this"):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="scope doit être 'all' ou 'this'")
    # exclude_unset : uniquement les champs RÉELLEMENT fournis (rappels:[] = effacement
    # explicite, distinct de « non fourni » qui laisse les rappels inchangés).
    fournis = corps.model_dump(exclude_unset=True)
    if not fournis:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="Aucun champ à modifier")
    debut = fournis.get("debut", evt.start_at)
    fin = fournis.get("fin", evt.end_at)
    if debut and fin and debut >= fin:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="fin doit être après debut")
    if scope == "this" and evt.recurrence_rule:
        # Portée « cette occurrence » : crée/maj un event-override, le maître (la
        # série) reste intact. L'occurrence doit être produite par la règle.
        occ = occurrence_naive(occurrence)
        if not occ or not occurrence_valide(evt, occ):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                                detail="occurrence invalide")
        champs = {}
        for champ_fr, valeur in fournis.items():
            col = _PATCH_MAP[champ_fr]
            if champ_fr == "etiquette_id":
                champs[col] = valeur or None            # "" ⇒ « aucune étiquette »
            elif champ_fr == "rappels":
                champs[col] = valeur if isinstance(valeur, list) else []
            else:
                champs[col] = valeur
        ov = await creer_ou_maj_override(db, evt, occ, champs)
        out = occurrence_en_dict(Occurrence(ov, ov.start_at, ov.end_at, occ, True))
        await publish_change(evt.calendar_id, "event.updated", out)
        return out
    for champ_fr, valeur in fournis.items():
        col = _PATCH_MAP[champ_fr]
        if champ_fr == "etiquette_id":
            setattr(evt, col, valeur or None)          # "" ⇒ « aucune étiquette »
        elif champ_fr == "rappels":
            setattr(evt, col, valeur if isinstance(valeur, list) else [])
        else:
            setattr(evt, col, valeur)
    await db.commit()
    await db.refresh(evt)
    out = EventOut.model_validate(evt)
    await publish_change(evt.calendar_id, "event.updated", out.model_dump(mode="json"))
    return evt


@router.delete("/events/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def service_supprimer_evenement(
    event_id: str,
    scope: str = "all",
    occurrence: Optional[datetime] = Query(None),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Annule (supprime) un événement. Destructif → gate de confirmation côté Cœur.
    `scope="this"` sur une série récurrente exclut seulement cette occurrence (EXDATE),
    la série survit ; `scope="all"` (défaut) supprime l'événement entier."""
    evt = await _charger_event_editable(db, event_id, user["sub"])
    if scope not in ("all", "this"):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="scope doit être 'all' ou 'this'")
    cal_id = evt.calendar_id
    if scope == "this" and evt.recurrence_rule:
        # Portée « cette occurrence » : EXDATE sur le maître, la série survit.
        occ = occurrence_naive(occurrence)
        if not occ or not occurrence_valide(evt, occ):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                                detail="occurrence invalide")
        await exclure_occurrence(db, evt, occ)
        await publish_change(cal_id, "event.updated", {"id": event_id})
        return
    await db.delete(evt)
    await db.commit()
    await publish_change(cal_id, "event.deleted", {"id": event_id})


@router.get("/calendars")
async def service_lister_calendriers(
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Calendriers accessibles (perso + partagés), avec id, nom, couleur et défaut.
    À appeler avant d'inviter quelqu'un ou de cibler un calendrier précis. Lecture seule."""
    cals = await agregation.calendriers_accessibles(db, user["sub"])
    return [{"id": c.id, "nom": c.name, "couleur": c.color,
             "description": c.description, "par_defaut": c.is_default,
             "proprietaire": c.user_id == user["sub"]} for c in cals]


class CalendrierServiceIn(BaseModel):
    nom: str
    description: Optional[str] = None
    couleur: Optional[str] = None


@router.post("/calendars", status_code=status.HTTP_201_CREATED)
async def service_creer_calendrier(
    corps: CalendrierServiceIn,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Crée un agenda (calendrier) partageable, distinct du perso. Effet immédiat."""
    cal = Calendar(user_id=user["sub"], name=corps.nom, description=corps.description,
                   **({"color": corps.couleur} if corps.couleur else {}))
    db.add(cal)
    await db.commit()
    await db.refresh(cal)
    return {"id": cal.id, "nom": cal.name, "couleur": cal.color,
            "description": cal.description, "par_defaut": cal.is_default}


class InvitationServiceIn(BaseModel):
    role: str = "viewer"
    expire_heures: Optional[int] = 72
    email: Optional[str] = None

    @field_validator("role")
    @classmethod
    def _role(cls, v):
        if v not in ("editor", "viewer"):
            raise ValueError("role doit être editor ou viewer")
        return v


def _lien_invitation(request: Request, token: str) -> str:
    """Lien d'acceptation. Privilégie AGENDA_URL_PUBLIQUE (joignable par l'invité) ;
    à défaut l'URL de la requête — honnête, mais valable seulement en interne."""
    racine = (settings.AGENDA_URL_PUBLIQUE or "").rstrip("/") or str(request.base_url).rstrip("/")
    return f"{racine}/invitations/{token}/page"


@router.post("/calendars/{calendar_id}/invitations", status_code=status.HTTP_201_CREATED)
async def service_inviter(
    calendar_id: str,
    corps: InvitationServiceIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Génère un lien d'invitation à un agenda partagé (viewer/editor). Renvoie le token
    ET le lien d'acceptation prêt à transmettre. Donne un accès → gate côté Cœur."""
    await require_calendar_access(db, calendar_id, user["sub"], min_role="owner")
    expires_at = None
    if corps.expire_heures:
        expires_at = datetime.now(timezone.utc) + timedelta(hours=corps.expire_heures)
    inv = CalendarInvitation(calendar_id=calendar_id, email=corps.email, role=corps.role,
                             created_by=user["sub"], expires_at=expires_at)
    db.add(inv)
    await db.commit()
    await db.refresh(inv)
    return {"id": inv.id, "token": inv.token, "role": inv.role,
            "expire_le": inv.expires_at.isoformat() if inv.expires_at else None,
            "lien": _lien_invitation(request, inv.token)}


# ── S176 : listes de courses/tâches (surface LLM, identité pinnée perso) ───────

from sqlalchemy import func as _func, select as _select  # noqa: E402
from models.orm import ShoppingItem, ShoppingList  # noqa: E402
from services.pubsub import publish_list_change  # noqa: E402


class ServiceListeCreate(BaseModel):
    nom: str
    kind: str = "courses"


class ServiceItemAjout(BaseModel):
    nom: str
    note: Optional[str] = None


class ServiceItemCoche(BaseModel):
    checked: bool = True


@router.get("/lists")
async def service_lister_listes(db: AsyncSession = Depends(get_db),
                                user: dict = Depends(get_current_user)):
    """Liste les listes de courses/tâches de l'utilisateur pinné + le nb d'articles à prendre."""
    uid = user["sub"]
    owned = (await db.execute(_select(ShoppingList).where(ShoppingList.created_by == uid))).scalars().all()
    sortie = []
    for l in owned:
        nb = await db.scalar(_select(_func.count()).select_from(ShoppingItem).where(
            ShoppingItem.list_id == l.id, ShoppingItem.checked.is_(False)))
        sortie.append({"id": l.id, "name": l.name, "kind": l.kind, "a_prendre": nb or 0})
    return sortie


@router.post("/lists", status_code=status.HTTP_201_CREATED)
async def service_creer_liste(corps: ServiceListeCreate, db: AsyncSession = Depends(get_db),
                              user: dict = Depends(get_current_user)):
    """Crée une liste de courses (ou tâches). Effet immédiat."""
    kind = corps.kind if corps.kind in ("courses", "taches") else "courses"
    l = ShoppingList(name=corps.nom, kind=kind, created_by=user["sub"])
    db.add(l)
    await db.commit()
    await db.refresh(l)
    return {"id": l.id, "name": l.name, "kind": l.kind, "created_by": l.created_by}


@router.post("/lists/{list_id}/items", status_code=status.HTTP_201_CREATED)
async def service_ajouter_item(list_id: str, corps: ServiceItemAjout,
                               db: AsyncSession = Depends(get_db),
                               user: dict = Depends(get_current_user)):
    """Ajoute un article à une liste. Effet immédiat."""
    l = await db.get(ShoppingList, list_id)
    if l is None or l.created_by != user["sub"]:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Liste introuvable")
    it = ShoppingItem(list_id=list_id, name=corps.nom.strip(), note=corps.note, added_by=user["sub"])
    db.add(it)
    await db.commit()
    await db.refresh(it)
    await publish_list_change(list_id, "item.added", {"id": it.id, "name": it.name})
    return {"id": it.id, "name": it.name, "checked": it.checked}


@router.patch("/lists/{list_id}/items/{item_id}")
async def service_cocher_item(list_id: str, item_id: str, corps: ServiceItemCoche,
                              db: AsyncSession = Depends(get_db),
                              user: dict = Depends(get_current_user)):
    """Coche/décoche un article comme pris. Effet immédiat."""
    l = await db.get(ShoppingList, list_id)
    if l is None or l.created_by != user["sub"]:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Liste introuvable")
    it = await db.get(ShoppingItem, item_id)
    if it is None or it.list_id != list_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Article introuvable")
    it.checked = corps.checked
    await db.commit()
    await db.refresh(it)
    await publish_list_change(list_id, "item.checked" if it.checked else "item.unchecked",
                              {"id": it.id, "name": it.name})
    return {"id": it.id, "name": it.name, "checked": it.checked}


# ── S177 : sondages de disponibilité (façon Doodle) ───────────────────────────
from routers import polls as _polls  # noqa: E402
from routers.polls import FinalizeIn as _FinalizeIn  # noqa: E402


class _CreneauServiceIn(BaseModel):
    debut: datetime
    fin: datetime


class ServiceSondageFinalize(BaseModel):
    creneau_id: str
    calendrier_id: Optional[str] = None


class ServiceSondageCreate(BaseModel):
    titre: str
    creneaux: list[_CreneauServiceIn] = []
    description: Optional[str] = None
    lieu: Optional[str] = None


def _lien_sondage(request: Request, token: str) -> str:
    base = (settings.AGENDA_URL_PUBLIQUE or str(request.base_url)).rstrip("/")
    return f"{base}/polls/p/{token}"


@router.get("/polls")
async def service_lister_sondages(db: AsyncSession = Depends(get_db),
                                  user: dict = Depends(get_current_user)):
    """Liste mes sondages de disponibilité + nb de créneaux/votants. Lecture seule."""
    resu = await _polls.list_polls(db=db, user=user)
    return [{"id": p.id, "titre": p.title, "statut": p.status, "nb_creneaux": p.nb_slots,
             "nb_votants": p.nb_voters, "final_creneau_id": p.final_slot_id} for p in resu]


@router.post("/polls", status_code=status.HTTP_201_CREATED)
async def service_creer_sondage(corps: ServiceSondageCreate, request: Request,
                                db: AsyncSession = Depends(get_db),
                                user: dict = Depends(get_current_user)):
    """Crée un sondage de disponibilité (créneaux à proposer). Renvoie l'id + le lien
    public à transmettre aux personnes à sonder. Effet immédiat."""
    from models.schemas import PollCreate as _PollCreate, PollSlotIn as _PollSlotIn
    slots = [_PollSlotIn(start_at=c.debut, end_at=c.fin) for c in corps.creneaux]
    out = await _polls.create_poll(
        _PollCreate(title=corps.titre, description=corps.description, location=corps.lieu,
                    slots=slots), db=db, user=user)
    return {"id": out.id, "titre": out.title, "share_token": out.share_token,
            "lien": _lien_sondage(request, out.share_token)}


@router.post("/polls/{poll_id}/finalize")
async def service_finaliser_sondage(poll_id: str, corps: ServiceSondageFinalize,
                                    db: AsyncSession = Depends(get_db),
                                    user: dict = Depends(get_current_user)):
    """Retient un créneau gagnant : crée l'événement agenda et clôture le sondage.
    ACTION : confirme=true requis côté Cœur. Récupère creneau_id via sondage_consulter."""
    return await _polls.finalize_poll(
        poll_id, _FinalizeIn(slot_id=corps.creneau_id, calendar_id=corps.calendrier_id),
        db=db, user=user)


# ── S179 : présence + abonnement webcal ───────────────────────────────────────
from services import abonnement as _abonnement  # noqa: E402
from services import presence as _presence  # noqa: E402


@router.get("/presence")
async def service_presence_consulter(db: AsyncSession = Depends(get_db),
                                     user: dict = Depends(get_current_user)):
    """Qui a partagé sa position (visible par l'identité pinnée), non expirées. Lecture seule."""
    return await _presence.positions_visibles(db, user["sub"])


@router.get("/ics")
async def service_ics_lien(request: Request, db: AsyncSession = Depends(get_db),
                           user: dict = Depends(get_current_user)):
    """URL d'abonnement webcal de l'agenda (à coller dans un client calendrier). Lecture seule."""
    base = (settings.AGENDA_URL_PUBLIQUE or str(request.base_url)).rstrip("/")
    token = await _abonnement.obtenir_ou_creer_token(db, user["sub"])
    return {"token": token, "https": _abonnement.url_https(base, token),
            "webcal": _abonnement.url_webcal(base, token)}
