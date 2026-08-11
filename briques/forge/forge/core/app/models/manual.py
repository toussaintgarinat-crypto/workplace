"""Modèles SQLAlchemy écrits À LA MAIN — tables absentes de `generated.py`.

`generated.py` est produit par sqlacodegen depuis l'instance Postgres courante.
Quatre tables du schéma Drizzle (forge/core/src/db/schema.ts) n'y figurent pas
car elles n'étaient pas encore créées dans l'instance ayant servi au codegen
(features récentes / jamais activées) :

    audit_mission_poles, pole_dev_requests, venture_delete_tokens, decisions_n0

Le S130 (ventures & audit) en a besoin → on les mappe à la main, fidèlement au
schéma Drizzle. À retirer d'ici et régénérer via ``make models`` une fois ces
tables présentes dans l'instance de référence.
"""

from __future__ import annotations

import datetime
import uuid

from sqlalchemy import Boolean, DateTime, Integer, Text, Uuid, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.generated import Base


class AuditMissionPoles(Base):
    __tablename__ = "audit_mission_poles"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text("gen_random_uuid()"))
    mission_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    pole_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)


class VentureDeleteTokens(Base):
    __tablename__ = "venture_delete_tokens"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text("gen_random_uuid()"))
    venture_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False)
    used_at: Mapped[datetime.datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text("now()"))


class PoleDevRequests(Base):
    __tablename__ = "pole_dev_requests"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text("gen_random_uuid()"))
    source_pole_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    source_pole_name: Mapped[str] = mapped_column(Text, nullable=False)
    source_pole_emoji: Mapped[str | None] = mapped_column(Text, server_default=text("'📌'::text"))
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    frequency: Mapped[str | None] = mapped_column(Text, server_default=text("'manual'::text"))
    priority: Mapped[str | None] = mapped_column(Text, server_default=text("'medium'::text"))
    status: Mapped[str | None] = mapped_column(Text, server_default=text("'pending'::text"))
    analysis: Mapped[str | None] = mapped_column(Text)
    proposed_solution: Mapped[str | None] = mapped_column(Text)
    automation_rule_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text("now()"))
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text("now()"))


class DecisionsN0(Base):
    __tablename__ = "decisions_n0"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text("gen_random_uuid()"))
    pole_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    pole_nom: Mapped[str] = mapped_column(Text, nullable=False)
    agent_nom: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    niveau: Mapped[str | None] = mapped_column(Text, server_default=text("'N0'::text"))
    statut: Mapped[str | None] = mapped_column(Text, server_default=text("'en_attente'::text"))
    urgence: Mapped[str | None] = mapped_column(Text, server_default=text("'normale'::text"))
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text("now()"))
    resolved_at: Mapped[datetime.datetime | None] = mapped_column(DateTime)
    resolved_by: Mapped[str | None] = mapped_column(Text)


# ── S133 — Automation & pipelines : tables hors codegen ─────────────────
# hitl_requests + détection de répétition (repetition_*) ne figurent pas dans
# l'instance ayant servi au codegen. Mappées à la main, fidèles à schema.ts.


class HitlRequests(Base):
    __tablename__ = "hitl_requests"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text("gen_random_uuid()"))
    session_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    niveau: Mapped[int | None] = mapped_column(Integer, server_default=text("1"))
    action: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[str | None] = mapped_column(Text, server_default=text("'{}'::text"))
    statut: Mapped[str | None] = mapped_column(Text, server_default=text("'pending'::text"))
    decide_par: Mapped[str | None] = mapped_column(Text)
    decide_at: Mapped[datetime.datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text("now()"))


class RepetitionConfigs(Base):
    __tablename__ = "repetition_configs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text("gen_random_uuid()"))
    pole_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, unique=True)
    seuil_occurrences: Mapped[int | None] = mapped_column(Integer, server_default=text("3"))
    periode_jours: Mapped[int | None] = mapped_column(Integer, server_default=text("7"))
    silence_days: Mapped[int | None] = mapped_column(Integer, server_default=text("30"))
    actif: Mapped[bool | None] = mapped_column(Boolean, server_default=text("true"))
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text("now()"))


class RepetitionEvents(Base):
    __tablename__ = "repetition_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text("gen_random_uuid()"))
    pole_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    action_key: Mapped[str] = mapped_column(Text, nullable=False)
    action_label: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text("now()"))


class RepetitionSilences(Base):
    __tablename__ = "repetition_silences"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text("gen_random_uuid()"))
    pole_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    action_key: Mapped[str] = mapped_column(Text, nullable=False)
    silence_until: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text("now()"))


# ── S135 — Comms & intégrations : table hors codegen ────────────────────
# mcp_servers ne figure pas dans l'instance ayant servi au codegen. Mappée à
# la main, fidèle à schema.ts (forge/core/src/db/schema.ts:1005).


class McpServers(Base):
    __tablename__ = "mcp_servers"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text("gen_random_uuid()"))
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    org_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    venture_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    pole_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    nom: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    auth_type: Mapped[str | None] = mapped_column(Text, server_default=text("'none'::text"))
    auth_token: Mapped[str | None] = mapped_column(Text, server_default=text("''::text"))
    actif: Mapped[bool | None] = mapped_column(Boolean, server_default=text("true"))
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text("now()"))


# ── S137 — Skills (re-porté après S136) : table hors codegen ─────────────
# `skills` ne figure pas dans l'instance ayant servi au codegen. Mappée à la
# main, fidèle à schema.ts. Re-portée car le frontend l'appelle (régression
# détectée au cutover S136 : la route Bun avait été droppée à tort).
# NB : `global` est un mot-clé Python → attribut `is_global`, colonne "global".


class Skills(Base):
    __tablename__ = "skills"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text("gen_random_uuid()"))
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    org_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    venture_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    pole_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    nom: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, server_default=text("''::text"))
    tags: Mapped[str | None] = mapped_column(Text, server_default=text("'[]'::text"))
    skill_md: Mapped[str] = mapped_column(Text, nullable=False)
    actif: Mapped[bool | None] = mapped_column(Boolean, server_default=text("true"))
    is_global: Mapped[bool | None] = mapped_column("global", Boolean, server_default=text("false"))
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text("now()"))
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text("now()"))


# ── S228 — Entretien guidé IA : table hors codegen ───────────────────────
# entretiens ne figure pas dans l'instance ayant servi au codegen. Mappée à la
# main, fidèle à schema.ts. Table neuve : aucune entrée dans MIGRATIONS_S227/S228
# nécessaire, `create_all` (scripts/init_db.py) la crée seule.


class Entretiens(Base):
    """S228 — état de l'entretien guidé IA (une ligne par entretien en cours/terminé).

    Table neuve : aucune entrée dans MIGRATIONS_S227/S228 nécessaire, `create_all`
    (scripts/init_db.py) la crée seule (même motif que VentureDeleteTokens ci-dessus).
    """
    __tablename__ = "entretiens"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text("gen_random_uuid()"))
    venture_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    section_courante: Mapped[str] = mapped_column(Text, nullable=False)
    sections_couvertes: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    transcript: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    statut: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'en_cours'"))
    # Renseigné best-effort si ingestion/audit injoignables à la clôture (jamais bloquant).
    sync_erreur: Mapped[str | None] = mapped_column(Text)
    derniere_activite: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text("now()"))
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text("now()"))
