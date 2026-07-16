"""Pydantic schemas — requêtes / réponses API."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, field_serializer, field_validator

from services.horaires import vers_paris, vers_utc_naif
from services.recurrence import valider_rrule


# ── Calendars ─────────────────────────────────────────────────────────────────

class CalendarCreate(BaseModel):
    name: str
    color: str = "#3B82F6"
    description: Optional[str] = None
    is_default: bool = False


class CalendarUpdate(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None
    description: Optional[str] = None
    is_default: Optional[bool] = None


class CalendarOut(BaseModel):
    id: str
    user_id: str
    name: str
    color: str
    description: Optional[str]
    is_default: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CalendarWithRoleOut(CalendarOut):
    role: str  # "owner" | "editor" | "viewer"


# ── S176 : listes de courses/tâches ───────────────────────────────────────────

class ShoppingListCreate(BaseModel):
    name: str
    kind: str = "courses"  # "courses" | "taches"


class ShoppingListUpdate(BaseModel):
    name: Optional[str] = None


class ShoppingListOut(BaseModel):
    id: str
    kind: str
    name: str
    created_by: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ShoppingListWithMetaOut(ShoppingListOut):
    role: str
    nb_a_prendre: int = 0  # items non cochés


class ShoppingItemCreate(BaseModel):
    name: Optional[str] = None
    catalog_item_id: Optional[str] = None
    emoji: Optional[str] = None
    rayon: Optional[str] = None
    note: Optional[str] = None


class ShoppingItemUpdate(BaseModel):
    name: Optional[str] = None
    emoji: Optional[str] = None
    rayon: Optional[str] = None
    note: Optional[str] = None
    checked: Optional[bool] = None


class ShoppingItemOut(BaseModel):
    id: str
    list_id: str
    name: str
    emoji: Optional[str]
    rayon: Optional[str]
    note: Optional[str]
    checked: bool
    checked_by: Optional[str]
    checked_at: Optional[datetime]
    added_by: str
    position: int

    class Config:
        from_attributes = True


class ListInvitationCreate(BaseModel):
    role: str = "viewer"
    email: Optional[str] = None
    expire_heures: int = 72


class ListMemberOut(BaseModel):
    user_id: str
    role: str
    display_name: Optional[str] = None
    avatar_color: Optional[str] = None


class CatalogItemOut(BaseModel):
    id: str
    name: str
    emoji: str
    rayon: str

    class Config:
        from_attributes = True


# ── S176 : cartes de fidélité ─────────────────────────────────────────────────

class LoyaltyCardCreate(BaseModel):
    enseigne: str
    numero: str
    format: str = "code128"  # "code128" | "ean13" | "qr"
    couleur: str = "#3B82F6"
    note: Optional[str] = None


class LoyaltyCardUpdate(BaseModel):
    enseigne: Optional[str] = None
    numero: Optional[str] = None
    format: Optional[str] = None
    couleur: Optional[str] = None
    note: Optional[str] = None


class LoyaltyCardOut(BaseModel):
    id: str
    enseigne: str
    numero: str
    format: str
    couleur: str
    note: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


# ── Labels (étiquettes nommées / catégories) ──────────────────────────────────

class LabelCreate(BaseModel):
    name: str
    color: str = "#5865F2"


class LabelUpdate(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None


class LabelOut(BaseModel):
    id: str
    calendar_id: str
    name: str
    color: str
    created_at: datetime

    class Config:
        from_attributes = True


# ── Members ───────────────────────────────────────────────────────────────────

class MemberAdd(BaseModel):
    user_id: str
    role: str = "viewer"

    @field_validator("role")
    @classmethod
    def valid_role(cls, v: str) -> str:
        if v not in ("owner", "editor", "viewer"):
            raise ValueError("role must be owner, editor or viewer")
        return v


class MemberOut(BaseModel):
    id: str
    calendar_id: str
    user_id: str
    role: str
    joined_at: datetime

    class Config:
        from_attributes = True


# ── Invitations ───────────────────────────────────────────────────────────────

class InvitationCreate(BaseModel):
    email: Optional[str] = None
    expires_in_hours: Optional[int] = 72
    role: str = "viewer"

    @field_validator("role")
    @classmethod
    def valid_role(cls, v: str) -> str:
        if v not in ("editor", "viewer"):
            raise ValueError("role must be editor or viewer")
        return v


class InvitationOut(BaseModel):
    id: str
    calendar_id: str
    token: str
    email: Optional[str]
    role: str
    created_by: str
    expires_at: Optional[datetime]
    used_at: Optional[datetime]
    created_at: datetime
    calendar_name: Optional[str] = None  # rempli par GET /invitations/{token}

    class Config:
        from_attributes = True


# ── Events ────────────────────────────────────────────────────────────────────

# Rappels : liste de « minutes avant le début ». Plafond 4 semaines (40320 min),
# maximum 5 rappels par événement (comme Google Agenda). On dédoublonne et on trie.
RAPPEL_MAX_MINUTES = 40320
RAPPELS_MAX_NB = 5


def normaliser_rappels(v):
    """Valide/normalise une liste de rappels (entiers ≥ 0, ≤ 4 sem, uniques, triés, ≤ 5).

    `None` est laissé tel quel (champ non fourni au PATCH) ; une liste vide signifie
    explicitement « aucun rappel ». Utilisé par les trois schémas via field_validator.
    """
    if v is None:
        return v
    if not isinstance(v, (list, tuple)):
        raise ValueError("rappels doit être une liste de minutes (entiers)")
    minutes = set()
    for m in v:
        if isinstance(m, bool) or not isinstance(m, int):
            raise ValueError("chaque rappel doit être un nombre entier de minutes")
        if m < 0 or m > RAPPEL_MAX_MINUTES:
            raise ValueError(f"rappel hors bornes (0..{RAPPEL_MAX_MINUTES} minutes)")
        minutes.add(m)
    if len(minutes) > RAPPELS_MAX_NB:
        raise ValueError(f"au plus {RAPPELS_MAX_NB} rappels par événement")
    return sorted(minutes)


class EventCreate(BaseModel):
    calendar_id: str
    title: str
    description: Optional[str] = None
    start_at: datetime
    end_at: datetime
    location: Optional[str] = None
    color: Optional[str] = None
    label_id: Optional[str] = None
    all_day: bool = False
    recurrence_rule: Optional[str] = None
    rappels: Optional[list[int]] = None

    @field_validator("rappels")
    @classmethod
    def _rappels(cls, v):
        return normaliser_rappels(v)

    @field_validator("recurrence_rule")
    @classmethod
    def _rrule(cls, v):
        return valider_rrule(v) if v else v

    @field_validator("start_at", "end_at")
    @classmethod
    def _utc(cls, v):
        # Heure murale Europe/Paris (saisie humaine) ou aware → naïf UTC (stockage).
        return vers_utc_naif(v)


class EventUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None
    location: Optional[str] = None
    color: Optional[str] = None
    label_id: Optional[str] = None
    all_day: Optional[bool] = None
    recurrence_rule: Optional[str] = None
    calendar_id: Optional[str] = None
    rappels: Optional[list[int]] = None

    @field_validator("rappels")
    @classmethod
    def _rappels(cls, v):
        return normaliser_rappels(v)

    @field_validator("recurrence_rule")
    @classmethod
    def _rrule(cls, v):
        return valider_rrule(v) if v else v

    @field_validator("start_at", "end_at")
    @classmethod
    def _utc(cls, v):
        # None = champ non fourni au PATCH ; sinon → naïf UTC (cf. EventCreate).
        return vers_utc_naif(v) if v is not None else v


class EventOut(BaseModel):
    id: str
    calendar_id: str
    title: str
    description: Optional[str]
    start_at: datetime
    end_at: datetime
    location: Optional[str]
    color: Optional[str]
    label_id: Optional[str] = None
    all_day: bool
    recurrence_rule: Optional[str]
    exdates: list[datetime] = []
    occurrence_start: Optional[datetime] = None
    recurrent: bool = False
    rappels: list[int] = []
    created_by: str
    created_at: datetime
    updated_at: datetime

    @field_serializer("start_at", "end_at", "occurrence_start")
    def _heure_locale(self, v: datetime):
        # Stocké en UTC naïf → exposé en Europe/Paris (avec offset), pour que le
        # navigateur ET les lecteurs par découpage de chaîne voient l'heure locale.
        return vers_paris(v) if v is not None else v

    class Config:
        from_attributes = True


# ── Participants ──────────────────────────────────────────────────────────────

class ParticipantAdd(BaseModel):
    user_id: str
    status: str = "pending"

    @field_validator("status")
    @classmethod
    def valid_status(cls, v: str) -> str:
        if v not in ("pending", "accepted", "declined", "maybe"):
            raise ValueError("status must be pending, accepted, declined or maybe")
        return v


class ParticipantStatusUpdate(BaseModel):
    status: Optional[str] = None
    # None = champ non fourni (rappels/status inchangés) ; pour rappels, [] = aucun,
    # [m,…] = override perso. Un PATCH peut ne toucher que l'un des deux.
    rappels: Optional[list[int]] = None

    @field_validator("status")
    @classmethod
    def valid_status(cls, v):
        if v is not None and v not in ("accepted", "declined", "maybe"):
            raise ValueError("status must be accepted, declined or maybe")
        return v

    @field_validator("rappels")
    @classmethod
    def _rappels(cls, v):
        return normaliser_rappels(v)


class ParticipantOut(BaseModel):
    id: str
    event_id: str
    user_id: str
    status: str
    rappels: Optional[list[int]] = None
    responded_at: Optional[datetime]

    class Config:
        from_attributes = True


# ── Comments ──────────────────────────────────────────────────────────────────

class CommentCreate(BaseModel):
    content: str


class CommentUpdate(BaseModel):
    content: str


class CommentOut(BaseModel):
    id: str
    event_id: str
    user_id: str
    content: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ── Attachments ───────────────────────────────────────────────────────────────

class AttachmentOut(BaseModel):
    id: str
    event_id: str
    filename: str
    mimetype: str
    size_bytes: int
    uploaded_by: str
    created_at: datetime

    class Config:
        from_attributes = True


# ── Profils (S174) ────────────────────────────────────────────────────────────

class ProfileOut(BaseModel):
    user_id: str
    display_name: str
    avatar_color: str

    class Config:
        from_attributes = True


# ── Journal d'activité (S174) ─────────────────────────────────────────────────

class ActivityLogOut(BaseModel):
    id: str
    event_id: str
    user_id: str
    user_nom: str
    action: str
    details: Optional[dict] = None
    created_at: datetime

    class Config:
        from_attributes = True
