"""ORM SQLAlchemy 2.0 — tables du service calendar (calendriers, étiquettes, événements…)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db import Base
from crypto import Chiffre, ChiffreFloat, ChiffreJSON


def _uuid() -> str:
    return str(uuid.uuid4())


class Calendar(Base):
    __tablename__ = "calendars"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    color: Mapped[str] = mapped_column(String(20), nullable=False, default="#3B82F6")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    members: Mapped[list["CalendarMember"]] = relationship(back_populates="calendar", cascade="all, delete-orphan")
    invitations: Mapped[list["CalendarInvitation"]] = relationship(back_populates="calendar", cascade="all, delete-orphan")
    events: Mapped[list["Event"]] = relationship(back_populates="calendar", cascade="all, delete-orphan")
    labels: Mapped[list["Label"]] = relationship(back_populates="calendar", cascade="all, delete-orphan")


class Label(Base):
    """Étiquette nommée réutilisable d'un calendrier (les *catégories* TimeTree).

    Une étiquette = un nom + une couleur, propre à un calendrier. Un événement peut
    porter une étiquette (`Event.label_id`) ; sa couleur d'affichage dérive alors du
    label, sinon on retombe sur `Event.color` (couleur libre ponctuelle). On garde
    donc les deux mécanismes (étiquette nommée OU couleur ad hoc)."""

    __tablename__ = "labels"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    calendar_id: Mapped[str] = mapped_column(String(36), ForeignKey("calendars.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    color: Mapped[str] = mapped_column(String(20), nullable=False, default="#5865F2")
    # Identifiant de l'étiquette chez la source externe (id du label TimeTree). Clé
    # d'idempotence : une re-sync met à jour l'étiquette importée au lieu de la dupliquer.
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    calendar: Mapped["Calendar"] = relationship(back_populates="labels")


class CalendarMember(Base):
    __tablename__ = "calendar_members"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    calendar_id: Mapped[str] = mapped_column(String(36), ForeignKey("calendars.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    role: Mapped[str] = mapped_column(
        Enum("owner", "editor", "viewer", name="member_role"),
        nullable=False,
        default="viewer",
    )
    joined_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    calendar: Mapped["Calendar"] = relationship(back_populates="members")


class CalendarInvitation(Base):
    __tablename__ = "calendar_invitations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    calendar_id: Mapped[str] = mapped_column(String(36), ForeignKey("calendars.id", ondelete="CASCADE"), nullable=False)
    token: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, default=_uuid)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="viewer")
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    calendar: Mapped["Calendar"] = relationship(back_populates="invitations")


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        UniqueConstraint("recurrence_parent_id", "recurrence_date",
                         name="uq_event_override"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    calendar_id: Mapped[str] = mapped_column(String(36), ForeignKey("calendars.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(Chiffre, nullable=False)
    description: Mapped[str | None] = mapped_column(Chiffre, nullable=True)
    start_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    end_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    location: Mapped[str | None] = mapped_column(Chiffre, nullable=True)
    color: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Étiquette nommée (catégorie) facultative. Si posée, la couleur d'affichage vient
    # du label ; sinon repli sur `color`. ondelete=SET NULL : supprimer un label ne
    # supprime pas les événements, il les laisse simplement « sans étiquette ».
    label_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("labels.id", ondelete="SET NULL"), nullable=True, index=True)
    all_day: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    recurrence_rule: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Récurrence (S175). exdates = occurrences exclues de la série (naïf UTC, JSON).
    # recurrence_parent_id non-NULL ⇒ cet event est un OVERRIDE d'une occurrence du
    # maître ; recurrence_date = la date d'occurrence d'origine qu'il remplace.
    exdates: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    recurrence_parent_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("events.id", ondelete="CASCADE"), nullable=True, index=True)
    recurrence_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Rappels configurables : liste de « minutes avant le début » (ex. [10, 1440] =
    # 10 min + 1 jour avant). Modèle commun à Google Agenda / Apple Calendar / VALARM.
    # Le Cœur (proactif.py) déclenche le 🔔 + le push Telegram ; ici on ne stocke que
    # la config. Liste vide = aucun rappel (pas de défaut imposé). JSON → portable
    # SQLite (dev/tests) et Postgres (prod).
    rappels: Mapped[list[int]] = mapped_column(JSON, nullable=False, default=list)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    # Provenance de l'événement : "manuel" (saisi dans la brique) ou "google"
    # (rapatrié par le pont). Permet de ne jamais écraser le travail de l'user.
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="manuel")
    # Identifiant de l'événement chez la source externe (id Google). Sert de clé
    # d'idempotence : une re-sync met à jour au lieu de dupliquer.
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    calendar: Mapped["Calendar"] = relationship(back_populates="events")
    participants: Mapped[list["EventParticipant"]] = relationship(back_populates="event", cascade="all, delete-orphan")
    comments: Mapped[list["EventComment"]] = relationship(back_populates="event", cascade="all, delete-orphan")
    attachments: Mapped[list["EventAttachment"]] = relationship(back_populates="event", cascade="all, delete-orphan")


class EventParticipant(Base):
    __tablename__ = "event_participants"
    __table_args__ = (UniqueConstraint("event_id", "user_id", name="uq_event_participant"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    event_id: Mapped[str] = mapped_column(String(36), ForeignKey("events.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        Enum("pending", "accepted", "declined", "maybe", name="participant_status"),
        nullable=False,
        default="pending",
    )
    responded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Override personnel des rappels (minutes avant le début). NULL = hérite de
    # Event.rappels (le défaut de l'événement) ; [] = aucun rappel (choix explicite) ;
    # [10, 1440] = réglage propre à cette personne. Voir services/rappels.py.
    rappels: Mapped[list[int] | None] = mapped_column(JSON, nullable=True, default=None)

    event: Mapped["Event"] = relationship(back_populates="participants")


class EventComment(Base):
    __tablename__ = "event_comments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    event_id: Mapped[str] = mapped_column(String(36), ForeignKey("events.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    content: Mapped[str] = mapped_column(Chiffre, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    event: Mapped["Event"] = relationship(back_populates="comments")


class EventAttachment(Base):
    __tablename__ = "event_attachments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    event_id: Mapped[str] = mapped_column(String(36), ForeignKey("events.id", ondelete="CASCADE"), nullable=False)
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    mimetype: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    uploaded_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    event: Mapped["Event"] = relationship(back_populates="attachments")


class UserToken(Base):
    """Coffre de tokens OAuth par utilisateur (rapatrié de l'assistant).

    Les tokens (access + refresh) sont chiffrés AES-GCM au repos via vault.py ;
    seul l'enregistrement chiffré transite par la base. Une ligne par
    (user_id, provider) — l'upsert remplace, le disconnect supprime.
    """

    __tablename__ = "user_tokens"
    __table_args__ = (UniqueConstraint("user_id", "provider", name="uq_user_provider"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(50), nullable=False, default="google")
    access_token_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    refresh_token_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    scope: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class UserProfile(Base):
    """Profil affichable d'un utilisateur (S174) : résout un user_id (sub Keycloak ou
    « perso ») en nom lisible + pastille couleur. Semé au login depuis les claims du
    token ; résolution 100 % locale (aucun appel réseau au runtime)."""

    __tablename__ = "user_profiles"

    user_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    avatar_color: Mapped[str] = mapped_column(String(20), nullable=False, default="#3B82F6")
    # S178 : email semé depuis les claims Keycloak (destinataire des digests). Préférences
    # push/digest — défauts qui préservent le comportement actuel (push actif, email inactif,
    # cadence « off » = pas de digest tant que l'utilisateur ne l'active pas explicitement).
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    digest_cadence: Mapped[str] = mapped_column(String(10), nullable=False, default="off")
    digest_push: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    digest_email: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    heures_calmes: Mapped[str | None] = mapped_column(String(20), nullable=True)
    dernier_digest_quotidien: Mapped[str | None] = mapped_column(String(10), nullable=True)
    dernier_digest_hebdo: Mapped[str | None] = mapped_column(String(10), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
    # S179 : jeton du flux d'abonnement webcal (ICS). NULL tant que l'utilisateur n'a pas
    # demandé son lien ; révocable (régénérer = nouveau jeton, l'ancien cesse de résoudre).
    ics_token: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)


class EventActivityLog(Base):
    """Journal d'activité d'un événement (S174) : qui a changé quoi, quand. Gabarit
    repris d'AuditLogs (brique Forge). user_nom est un SNAPSHOT du nom au moment de
    l'action (robuste si le profil change/disparaît ensuite)."""

    __tablename__ = "event_activity_log"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    event_id: Mapped[str] = mapped_column(String(36), ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    user_nom: Mapped[str] = mapped_column(String(255), nullable=False)
    action: Mapped[str] = mapped_column(String(30), nullable=False)
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


# ── S176 : listes de courses/tâches partagées ─────────────────────────────────

class ShoppingList(Base):
    __tablename__ = "shopping_lists"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    kind: Mapped[str] = mapped_column(
        Enum("courses", "taches", name="list_kind"), nullable=False, default="courses")
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    members: Mapped[list["ShoppingListMember"]] = relationship(back_populates="liste", cascade="all, delete-orphan")
    invitations: Mapped[list["ShoppingListInvitation"]] = relationship(back_populates="liste", cascade="all, delete-orphan")
    items: Mapped[list["ShoppingItem"]] = relationship(back_populates="liste", cascade="all, delete-orphan")


class ShoppingListMember(Base):
    __tablename__ = "shopping_list_members"
    __table_args__ = (UniqueConstraint("list_id", "user_id", name="uq_list_member"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    list_id: Mapped[str] = mapped_column(String(36), ForeignKey("shopping_lists.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    role: Mapped[str] = mapped_column(
        Enum("owner", "editor", "viewer", name="list_member_role"), nullable=False, default="viewer")
    joined_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    liste: Mapped["ShoppingList"] = relationship(back_populates="members")


class ShoppingListInvitation(Base):
    __tablename__ = "shopping_list_invitations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    list_id: Mapped[str] = mapped_column(String(36), ForeignKey("shopping_lists.id", ondelete="CASCADE"), nullable=False)
    token: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, default=_uuid)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="viewer")
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    liste: Mapped["ShoppingList"] = relationship(back_populates="invitations")


class ShoppingItem(Base):
    __tablename__ = "shopping_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    list_id: Mapped[str] = mapped_column(String(36), ForeignKey("shopping_lists.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    emoji: Mapped[str | None] = mapped_column(String(16), nullable=True)
    rayon: Mapped[str | None] = mapped_column(String(50), nullable=True)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    checked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    checked_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    added_by: Mapped[str] = mapped_column(String(255), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    liste: Mapped["ShoppingList"] = relationship(back_populates="items")


class CatalogItem(Base):
    """Catalogue tap-to-add. list_id NULL = entrée intégrée (catalogue FR par défaut,
    partagé) ; non-NULL = entrée perso mémorisée pour une liste précise."""

    __tablename__ = "catalog_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    list_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("shopping_lists.id", ondelete="CASCADE"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    emoji: Mapped[str] = mapped_column(String(16), nullable=False, default="🛒")
    rayon: Mapped[str] = mapped_column(String(50), nullable=False, default="Autre")
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class LoyaltyCard(Base):
    """Carte de fidélité personnelle (scope user_id). Pas de collaboration."""

    __tablename__ = "loyalty_cards"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    enseigne: Mapped[str] = mapped_column(String(255), nullable=False)
    numero: Mapped[str] = mapped_column(String(255), nullable=False)
    format: Mapped[str] = mapped_column(
        Enum("code128", "ean13", "qr", name="barcode_format"), nullable=False, default="code128")
    couleur: Mapped[str] = mapped_column(String(20), nullable=False, default="#3B82F6")
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


# ── S177 : sondages de disponibilité (façon Doodle) ───────────────────────────

class AvailabilityPoll(Base):
    """Sondage de disponibilité : l'organisateur propose des créneaux (`PollSlot`),
    chacun vote par créneau (`PollVote`), puis on finalise sur un créneau — ce qui crée
    un `Event` dans l'agenda. Le vote passe par `share_token` (capacité du lien public) :
    un invité vote sans compte, un membre connecté voit son vote attribué."""

    __tablename__ = "availability_polls"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    location: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    # Calendrier cible pour la finalisation. SET NULL : supprimer le calendrier ne
    # détruit pas le sondage — on retombe sur le calendrier par défaut à la finalisation.
    calendar_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("calendars.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(
        Enum("open", "closed", name="poll_status"), nullable=False, default="open")
    final_slot_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    final_event_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    share_token: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, default=_uuid)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    slots: Mapped[list["PollSlot"]] = relationship(
        back_populates="poll", cascade="all, delete-orphan")
    votes: Mapped[list["PollVote"]] = relationship(
        back_populates="poll", cascade="all, delete-orphan")


class PollSlot(Base):
    __tablename__ = "poll_slots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    poll_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("availability_polls.id", ondelete="CASCADE"), nullable=False, index=True)
    start_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    poll: Mapped["AvailabilityPoll"] = relationship(back_populates="slots")


class PollVote(Base):
    """Vote d'une personne sur un créneau. Identité = `voter_id` (membre connecté) OU
    `guest_key` (invité anonyme). Un bulletin remplace tous les votes de l'identité pour
    le sondage (voir routers/polls.py) — pas de contrainte unique fragile côté anonyme."""

    __tablename__ = "poll_votes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    poll_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("availability_polls.id", ondelete="CASCADE"), nullable=False, index=True)
    slot_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("poll_slots.id", ondelete="CASCADE"), nullable=False, index=True)
    voter_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    voter_name: Mapped[str] = mapped_column(String(255), nullable=False)
    guest_key: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    value: Mapped[str] = mapped_column(
        Enum("oui", "si_besoin", "non", name="poll_vote_value"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    poll: Mapped["AvailabilityPoll"] = relationship(back_populates="votes")


# ── S179 : présence (position éphémère partagée) ──────────────────────────────

class LivePosition(Base):
    """Position éphémère partagée par une personne. UNE ligne max par personne
    (PK `user_id`) : repartager REMPLACE. `expires_at` borne la durée de vie ; au-delà,
    filtrée à la lecture puis purgée. Aucun historique conservé (ligne unique)."""

    __tablename__ = "live_positions"

    user_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    accuracy_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # famille = visible de tous les membres ; event = visible des seuls participants de
    # l'événement `event_id` (expiration = fin de l'event).
    scope: Mapped[str] = mapped_column(
        Enum("famille", "event", name="live_position_scope"), nullable=False, default="famille")
    event_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("events.id", ondelete="CASCADE"), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now())
