"""Pydantic schemas — requêtes / réponses API."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, field_validator


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
    rappels: list[int] = []
    created_by: str
    created_at: datetime
    updated_at: datetime

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
    status: str

    @field_validator("status")
    @classmethod
    def valid_status(cls, v: str) -> str:
        if v not in ("accepted", "declined", "maybe"):
            raise ValueError("status must be accepted, declined or maybe")
        return v


class ParticipantOut(BaseModel):
    id: str
    event_id: str
    user_id: str
    status: str
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
