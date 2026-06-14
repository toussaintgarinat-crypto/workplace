# ──────────────────────────────────────────────────────────────────────────
# AUTO-GÉNÉRÉ par sqlacodegen — NE PAS ÉDITER À LA MAIN.
#
# Sprint S126 (socle migration forge/core TS→Python). Reflète les tables
# Postgres existantes (source de vérité = Drizzle forge/core/src/db/schema.ts).
# La DB ne bouge pas pendant la migration strangler → ces modèles mappent le
# schéma tel quel, zéro migration de données.
#
# Régénérer :  make -C forge/core models   (cf. scripts/gen_models.sh)
#
# Tables couvertes : 77 / 87 (Drizzle). Manquantes dans l'instance courante
# (features jamais activées, tables non encore créées) — à régénérer une fois
# présentes :
#   audit_mission_poles, hitl_requests, mcp_servers, metrics_snapshots,
#   pole_dev_requests, repetition_configs, repetition_events,
#   repetition_silences, skills, venture_delete_tokens
# ──────────────────────────────────────────────────────────────────────────
from typing import Optional
import datetime
import uuid

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKeyConstraint, Index, Integer, PrimaryKeyConstraint, REAL, Text, UniqueConstraint, Uuid, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

class Base(DeclarativeBase):
    pass


class AgentExecutions(Base):
    __tablename__ = 'agent_executions'
    __table_args__ = (
        PrimaryKeyConstraint('id', name='agent_executions_pkey'),
        Index('idx_agent_executions_parent', 'parent_id'),
        Index('idx_agent_executions_session', 'session_id')
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text('gen_random_uuid()'))
    agent_name: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'Forge'::text"))
    session_id: Mapped[str] = mapped_column(Text, nullable=False)
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    depth: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text('0'))
    input: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    parent_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid)
    agent_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid)
    output: Mapped[Optional[str]] = mapped_column(Text, server_default=text("''::text"))
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer)
    status: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'running'::text"))


class ForgePersonalities(Base):
    __tablename__ = 'forge_personalities'
    __table_args__ = (
        PrimaryKeyConstraint('id', name='forge_personalities_pkey'),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text('gen_random_uuid()'))
    label: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    position: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text('0'))
    emoji: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'🤖'::text"))
    description: Mapped[Optional[str]] = mapped_column(Text, server_default=text("''::text"))
    system_prompt: Mapped[Optional[str]] = mapped_column(Text, server_default=text("''::text"))
    is_builtin: Mapped[Optional[int]] = mapped_column(Integer, server_default=text('0'))

    agent_definitions: Mapped[list['AgentDefinitions']] = relationship('AgentDefinitions', back_populates='personality')


class GoogleOauthTokens(Base):
    __tablename__ = 'google_oauth_tokens'
    __table_args__ = (
        PrimaryKeyConstraint('id', name='google_oauth_tokens_pkey'),
        UniqueConstraint('user_id', name='google_oauth_tokens_user_id_unique')
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text('gen_random_uuid()'))
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    access_token: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    refresh_token: Mapped[Optional[str]] = mapped_column(Text)
    expires_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)


class ImapConfigs(Base):
    __tablename__ = 'imap_configs'
    __table_args__ = (
        PrimaryKeyConstraint('id', name='imap_configs_pkey'),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text('gen_random_uuid()'))
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    host: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    password_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    port: Mapped[Optional[int]] = mapped_column(Integer, server_default=text('993'))
    actif: Mapped[Optional[bool]] = mapped_column(Boolean, server_default=text('true'))

    imap_emails: Mapped[list['ImapEmails']] = relationship('ImapEmails', back_populates='config')


class Keybindings(Base):
    __tablename__ = 'keybindings'
    __table_args__ = (
        PrimaryKeyConstraint('id', name='keybindings_pkey'),
        UniqueConstraint('user_id', 'touche', name='keybindings_user_id_touche_unique')
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text('gen_random_uuid()'))
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    touche: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))


class ManagedServers(Base):
    __tablename__ = 'managed_servers'
    __table_args__ = (
        PrimaryKeyConstraint('id', name='managed_servers_pkey'),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text('gen_random_uuid()'))
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    ip: Mapped[str] = mapped_column(Text, nullable=False)
    ssh_key: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    ssh_user: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'root'::text"))
    region: Mapped[Optional[str]] = mapped_column(Text, server_default=text("''::text"))
    status: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'libre'::text"))
    instance_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid)


class Organizations(Base):
    __tablename__ = 'organizations'
    __table_args__ = (
        PrimaryKeyConstraint('id', name='organizations_pkey'),
        UniqueConstraint('slug', name='organizations_slug_unique')
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text('gen_random_uuid()'))
    nom: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    owner_id: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    emoji: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'🏢'::text"))
    plan: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'personal'::text"))

    abonnements: Mapped[list['Abonnements']] = relationship('Abonnements', back_populates='org')
    agenda_events: Mapped[list['AgendaEvents']] = relationship('AgendaEvents', back_populates='org')
    audit_logs: Mapped[list['AuditLogs']] = relationship('AuditLogs', back_populates='org')
    automation_rules: Mapped[list['AutomationRules']] = relationship('AutomationRules', back_populates='org')
    brief_configs: Mapped[list['BriefConfigs']] = relationship('BriefConfigs', back_populates='org')
    briefs: Mapped[list['Briefs']] = relationship('Briefs', back_populates='org')
    degradation_modes: Mapped[list['DegradationModes']] = relationship('DegradationModes', back_populates='org')
    gitpack_jobs: Mapped[list['GitpackJobs']] = relationship('GitpackJobs', back_populates='org')
    governor_configs: Mapped[list['GovernorConfigs']] = relationship('GovernorConfigs', back_populates='org')
    injection_logs: Mapped[list['InjectionLogs']] = relationship('InjectionLogs', back_populates='org')
    kb_articles: Mapped[list['KbArticles']] = relationship('KbArticles', back_populates='org')
    organization_members: Mapped[list['OrganizationMembers']] = relationship('OrganizationMembers', back_populates='org')
    poles: Mapped[list['Poles']] = relationship('Poles', back_populates='org')
    provider_api_keys: Mapped[list['ProviderApiKeys']] = relationship('ProviderApiKeys', back_populates='org')
    saved_filters: Mapped[list['SavedFilters']] = relationship('SavedFilters', back_populates='org')
    slo_entries: Mapped[list['SloEntries']] = relationship('SloEntries', back_populates='org')
    staging_proposals: Mapped[list['StagingProposals']] = relationship('StagingProposals', back_populates='org')
    stripe_payments: Mapped[list['StripePayments']] = relationship('StripePayments', back_populates='org')
    team_members: Mapped[list['TeamMembers']] = relationship('TeamMembers', back_populates='org')
    templates: Mapped[list['Templates']] = relationship('Templates', back_populates='org')
    tool_llm_configs: Mapped[list['ToolLlmConfigs']] = relationship('ToolLlmConfigs', back_populates='org')
    veille_sources: Mapped[list['VeilleSources']] = relationship('VeilleSources', back_populates='org')
    ventures: Mapped[list['Ventures']] = relationship('Ventures', back_populates='org')
    webhooks: Mapped[list['Webhooks']] = relationship('Webhooks', back_populates='org')
    dev_tasks: Mapped[list['DevTasks']] = relationship('DevTasks', back_populates='org')
    governor_usage: Mapped[list['GovernorUsage']] = relationship('GovernorUsage', back_populates='org')
    risk_logs: Mapped[list['RiskLogs']] = relationship('RiskLogs', back_populates='org')
    sessions: Mapped[list['Sessions']] = relationship('Sessions', back_populates='org')
    rapports: Mapped[list['Rapports']] = relationship('Rapports', back_populates='org')


class PipelineTemplates(Base):
    __tablename__ = 'pipeline_templates'
    __table_args__ = (
        PrimaryKeyConstraint('id', name='pipeline_templates_pkey'),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text('gen_random_uuid()'))
    nom: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    user_id: Mapped[Optional[str]] = mapped_column(Text)
    description: Mapped[Optional[str]] = mapped_column(Text, server_default=text("''::text"))
    icon: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'🔄'::text"))
    categorie: Mapped[Optional[str]] = mapped_column(Text, server_default=text("''::text"))
    nodes: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'[]'::text"))
    edges: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'[]'::text"))
    is_public: Mapped[Optional[bool]] = mapped_column(Boolean, server_default=text('false'))


class PushSubscriptions(Base):
    __tablename__ = 'push_subscriptions'
    __table_args__ = (
        PrimaryKeyConstraint('id', name='push_subscriptions_pkey'),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text('gen_random_uuid()'))
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    endpoint: Mapped[str] = mapped_column(Text, nullable=False)
    p256dh: Mapped[str] = mapped_column(Text, nullable=False)
    auth: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))


class ToolCatalog(Base):
    __tablename__ = 'tool_catalog'
    __table_args__ = (
        PrimaryKeyConstraint('id', name='tool_catalog_pkey'),
        UniqueConstraint('key', name='tool_catalog_key_unique')
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text('gen_random_uuid()'))
    key: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    icon: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'🔧'::text"))
    description: Mapped[Optional[str]] = mapped_column(Text, server_default=text("''::text"))
    commun: Mapped[Optional[bool]] = mapped_column(Boolean, server_default=text('true'))
    poles_dedies: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'[]'::text"))
    ordre: Mapped[Optional[int]] = mapped_column(Integer, server_default=text('0'))


class Users(Base):
    __tablename__ = 'users'
    __table_args__ = (
        PrimaryKeyConstraint('id', name='users_pkey'),
        UniqueConstraint('email', name='users_email_unique'),
        UniqueConstraint('keycloak_sub', name='users_keycloak_sub_unique')
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text('gen_random_uuid()'))
    email: Mapped[str] = mapped_column(Text, nullable=False)
    nom: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    avatar_emoji: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'👤'::text"))
    keycloak_sub: Mapped[Optional[str]] = mapped_column(Text)


class Abonnements(Base):
    __tablename__ = 'abonnements'
    __table_args__ = (
        ForeignKeyConstraint(['org_id'], ['organizations.id'], ondelete='CASCADE', name='abonnements_org_id_organizations_id_fk'),
        PrimaryKeyConstraint('id', name='abonnements_pkey')
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text('gen_random_uuid()'))
    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    plan: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'free'::text"))
    statut: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'trial'::text"))
    stripe_sub_id: Mapped[Optional[str]] = mapped_column(Text, server_default=text("''::text"))
    periode_fin: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)

    org: Mapped['Organizations'] = relationship('Organizations', back_populates='abonnements')


class AgendaEvents(Base):
    __tablename__ = 'agenda_events'
    __table_args__ = (
        ForeignKeyConstraint(['org_id'], ['organizations.id'], ondelete='CASCADE', name='agenda_events_org_id_organizations_id_fk'),
        PrimaryKeyConstraint('id', name='agenda_events_pkey')
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text('gen_random_uuid()'))
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    titre: Mapped[str] = mapped_column(Text, nullable=False)
    date_debut: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    org_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid)
    description: Mapped[Optional[str]] = mapped_column(Text, server_default=text("''::text"))
    date_fin: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)
    pole: Mapped[Optional[str]] = mapped_column(Text, server_default=text("''::text"))
    google_id: Mapped[Optional[str]] = mapped_column(Text, server_default=text("''::text"))

    org: Mapped[Optional['Organizations']] = relationship('Organizations', back_populates='agenda_events')


class AuditLogs(Base):
    __tablename__ = 'audit_logs'
    __table_args__ = (
        ForeignKeyConstraint(['org_id'], ['organizations.id'], ondelete='CASCADE', name='audit_logs_org_id_organizations_id_fk'),
        PrimaryKeyConstraint('id', name='audit_logs_pkey')
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text('gen_random_uuid()'))
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    entite: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    org_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid)
    user_nom: Mapped[Optional[str]] = mapped_column(Text, server_default=text("''::text"))
    entite_id: Mapped[Optional[str]] = mapped_column(Text, server_default=text("''::text"))
    pole: Mapped[Optional[str]] = mapped_column(Text, server_default=text("''::text"))
    details: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'{}'::text"))

    org: Mapped[Optional['Organizations']] = relationship('Organizations', back_populates='audit_logs')


class AutomationRules(Base):
    __tablename__ = 'automation_rules'
    __table_args__ = (
        ForeignKeyConstraint(['org_id'], ['organizations.id'], ondelete='CASCADE', name='automation_rules_org_id_organizations_id_fk'),
        PrimaryKeyConstraint('id', name='automation_rules_pkey')
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text('gen_random_uuid()'))
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    nom: Mapped[str] = mapped_column(Text, nullable=False)
    trigger: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    org_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid)
    description: Mapped[Optional[str]] = mapped_column(Text, server_default=text("''::text"))
    conditions: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'{}'::text"))
    actions: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'[]'::text"))
    actif: Mapped[Optional[bool]] = mapped_column(Boolean, server_default=text('true'))
    executions: Mapped[Optional[int]] = mapped_column(Integer, server_default=text('0'))

    org: Mapped[Optional['Organizations']] = relationship('Organizations', back_populates='automation_rules')


class BriefConfigs(Base):
    __tablename__ = 'brief_configs'
    __table_args__ = (
        ForeignKeyConstraint(['org_id'], ['organizations.id'], ondelete='CASCADE', name='brief_configs_org_id_organizations_id_fk'),
        PrimaryKeyConstraint('id', name='brief_configs_pkey'),
        UniqueConstraint('user_id', name='brief_configs_user_id_unique')
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text('gen_random_uuid()'))
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    org_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid)
    enabled: Mapped[Optional[bool]] = mapped_column(Boolean, server_default=text('true'))
    heure_utc: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'07:00'::text"))
    jours_semaine: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'[1,2,3,4,5]'::text"))

    org: Mapped[Optional['Organizations']] = relationship('Organizations', back_populates='brief_configs')


class Briefs(Base):
    __tablename__ = 'briefs'
    __table_args__ = (
        ForeignKeyConstraint(['org_id'], ['organizations.id'], ondelete='CASCADE', name='briefs_org_id_organizations_id_fk'),
        PrimaryKeyConstraint('id', name='briefs_pkey')
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text('gen_random_uuid()'))
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    titre: Mapped[str] = mapped_column(Text, nullable=False)
    contenu: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    org_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid)
    type: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'morning'::text"))
    lu: Mapped[Optional[bool]] = mapped_column(Boolean, server_default=text('false'))

    org: Mapped[Optional['Organizations']] = relationship('Organizations', back_populates='briefs')


class DegradationModes(Base):
    __tablename__ = 'degradation_modes'
    __table_args__ = (
        ForeignKeyConstraint(['org_id'], ['organizations.id'], ondelete='CASCADE', name='degradation_modes_org_id_organizations_id_fk'),
        PrimaryKeyConstraint('id', name='degradation_modes_pkey')
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text('gen_random_uuid()'))
    ressource: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    org_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid)
    actif: Mapped[Optional[bool]] = mapped_column(Boolean, server_default=text('false'))
    grace_mode: Mapped[Optional[bool]] = mapped_column(Boolean, server_default=text('false'))

    org: Mapped[Optional['Organizations']] = relationship('Organizations', back_populates='degradation_modes')
    degradation_episodes: Mapped[list['DegradationEpisodes']] = relationship('DegradationEpisodes', back_populates='mode')


class GitpackJobs(Base):
    __tablename__ = 'gitpack_jobs'
    __table_args__ = (
        ForeignKeyConstraint(['org_id'], ['organizations.id'], ondelete='CASCADE', name='gitpack_jobs_org_id_organizations_id_fk'),
        PrimaryKeyConstraint('id', name='gitpack_jobs_pkey')
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text('gen_random_uuid()'))
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    github_url: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    platform: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'macos'::text"))
    statut: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'pending'::text"))
    language: Mapped[Optional[str]] = mapped_column(Text)
    framework: Mapped[Optional[str]] = mapped_column(Text)
    logs: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'[]'::text"))
    error: Mapped[Optional[str]] = mapped_column(Text)
    org_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid)

    org: Mapped[Optional['Organizations']] = relationship('Organizations', back_populates='gitpack_jobs')


class GovernorConfigs(Base):
    __tablename__ = 'governor_configs'
    __table_args__ = (
        ForeignKeyConstraint(['org_id'], ['organizations.id'], ondelete='CASCADE', name='governor_configs_org_id_organizations_id_fk'),
        PrimaryKeyConstraint('id', name='governor_configs_pkey')
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text('gen_random_uuid()'))
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    org_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid)
    budget_journalier: Mapped[Optional[int]] = mapped_column(Integer, server_default=text('100000'))
    budget_mensuel: Mapped[Optional[int]] = mapped_column(Integer, server_default=text('2000000'))
    alerte_seuil: Mapped[Optional[int]] = mapped_column(Integer, server_default=text('80'))
    blocage_seuil: Mapped[Optional[int]] = mapped_column(Integer, server_default=text('95'))
    actif: Mapped[Optional[bool]] = mapped_column(Boolean, server_default=text('true'))

    org: Mapped[Optional['Organizations']] = relationship('Organizations', back_populates='governor_configs')


class ImapEmails(Base):
    __tablename__ = 'imap_emails'
    __table_args__ = (
        ForeignKeyConstraint(['config_id'], ['imap_configs.id'], ondelete='CASCADE', name='imap_emails_config_id_imap_configs_id_fk'),
        PrimaryKeyConstraint('id', name='imap_emails_pkey')
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text('gen_random_uuid()'))
    config_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    message_id: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    sujet: Mapped[Optional[str]] = mapped_column(Text, server_default=text("''::text"))
    expediteur: Mapped[Optional[str]] = mapped_column(Text, server_default=text("''::text"))
    corps: Mapped[Optional[str]] = mapped_column(Text, server_default=text("''::text"))
    lu: Mapped[Optional[bool]] = mapped_column(Boolean, server_default=text('false'))

    config: Mapped['ImapConfigs'] = relationship('ImapConfigs', back_populates='imap_emails')


class InjectionLogs(Base):
    __tablename__ = 'injection_logs'
    __table_args__ = (
        ForeignKeyConstraint(['org_id'], ['organizations.id'], ondelete='CASCADE', name='injection_logs_org_id_organizations_id_fk'),
        PrimaryKeyConstraint('id', name='injection_logs_pkey')
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text('gen_random_uuid()'))
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    input: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    org_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid)
    flagged: Mapped[Optional[bool]] = mapped_column(Boolean, server_default=text('false'))
    raison: Mapped[Optional[str]] = mapped_column(Text, server_default=text("''::text"))

    org: Mapped[Optional['Organizations']] = relationship('Organizations', back_populates='injection_logs')


class KbArticles(Base):
    __tablename__ = 'kb_articles'
    __table_args__ = (
        ForeignKeyConstraint(['org_id'], ['organizations.id'], ondelete='CASCADE', name='kb_articles_org_id_organizations_id_fk'),
        PrimaryKeyConstraint('id', name='kb_articles_pkey'),
        Index('idx_kb_articles_user', 'user_id')
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text('gen_random_uuid()'))
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    titre: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    contenu: Mapped[Optional[str]] = mapped_column(Text, server_default=text("''::text"))
    tags: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'[]'::text"))
    is_pinned: Mapped[Optional[bool]] = mapped_column(Boolean, server_default=text('false'))
    is_public: Mapped[Optional[bool]] = mapped_column(Boolean, server_default=text('false'))
    org_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid)

    org: Mapped[Optional['Organizations']] = relationship('Organizations', back_populates='kb_articles')


class OrganizationMembers(Base):
    __tablename__ = 'organization_members'
    __table_args__ = (
        ForeignKeyConstraint(['org_id'], ['organizations.id'], ondelete='CASCADE', name='organization_members_org_id_organizations_id_fk'),
        PrimaryKeyConstraint('id', name='organization_members_pkey'),
        UniqueConstraint('org_id', 'user_id', name='organization_members_org_id_user_id_unique')
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text('gen_random_uuid()'))
    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    joined_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    role: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'member'::text"))

    org: Mapped['Organizations'] = relationship('Organizations', back_populates='organization_members')


class Poles(Base):
    __tablename__ = 'poles'
    __table_args__ = (
        ForeignKeyConstraint(['org_id'], ['organizations.id'], ondelete='CASCADE', name='poles_org_id_organizations_id_fk'),
        PrimaryKeyConstraint('id', name='poles_pkey'),
        Index('idx_poles_org', 'org_id'),
        Index('idx_poles_venture', 'venture_id')
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text('gen_random_uuid()'))
    nom: Mapped[str] = mapped_column(Text, nullable=False)
    owner_id: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    description: Mapped[Optional[str]] = mapped_column(Text, server_default=text("''::text"))
    emoji: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'🌍'::text"))
    couleur: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'#6366f1'::text"))
    venture_id: Mapped[Optional[str]] = mapped_column(Text)
    type: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'custom'::text"))
    org_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid)

    org: Mapped[Optional['Organizations']] = relationship('Organizations', back_populates='poles')
    agent_definitions: Mapped[list['AgentDefinitions']] = relationship('AgentDefinitions', back_populates='pole')
    audit_missions: Mapped[list['AuditMissions']] = relationship('AuditMissions', back_populates='pole')
    blackboard_events: Mapped[list['BlackboardEvents']] = relationship('BlackboardEvents', back_populates='pole')
    budget_entries: Mapped[list['BudgetEntries']] = relationship('BudgetEntries', back_populates='pole')
    contrats: Mapped[list['Contrats']] = relationship('Contrats', back_populates='pole')
    crm_leads: Mapped[list['CrmLeads']] = relationship('CrmLeads', back_populates='pole')
    dev_tasks: Mapped[list['DevTasks']] = relationship('DevTasks', back_populates='pole')
    factures_docs: Mapped[list['FacturesDocs']] = relationship('FacturesDocs', back_populates='pole')
    forecast_entries: Mapped[list['ForecastEntries']] = relationship('ForecastEntries', back_populates='pole')
    governor_usage: Mapped[list['GovernorUsage']] = relationship('GovernorUsage', back_populates='pole')
    incidents: Mapped[list['Incidents']] = relationship('Incidents', back_populates='pole')
    llm_configs: Mapped['LlmConfigs'] = relationship('LlmConfigs', uselist=False, back_populates='pole')
    okrs: Mapped[list['Okrs']] = relationship('Okrs', back_populates='pole')
    orchestrator_sessions: Mapped[list['OrchestratorSessions']] = relationship('OrchestratorSessions', back_populates='pole')
    pole_members: Mapped[list['PoleMembers']] = relationship('PoleMembers', back_populates='pole')
    pole_tools: Mapped[list['PoleTools']] = relationship('PoleTools', back_populates='pole')
    risk_logs: Mapped[list['RiskLogs']] = relationship('RiskLogs', back_populates='pole')
    sessions: Mapped[list['Sessions']] = relationship('Sessions', back_populates='pole')
    social_accounts: Mapped[list['SocialAccounts']] = relationship('SocialAccounts', back_populates='pole')
    sprints: Mapped[list['Sprints']] = relationship('Sprints', back_populates='pole')
    task_dag_items: Mapped[list['TaskDagItems']] = relationship('TaskDagItems', back_populates='pole')
    agent_runs: Mapped[list['AgentRuns']] = relationship('AgentRuns', back_populates='pole')
    documents: Mapped[list['Documents']] = relationship('Documents', back_populates='pole')
    tasks: Mapped[list['Tasks']] = relationship('Tasks', back_populates='pole')


class ProviderApiKeys(Base):
    __tablename__ = 'provider_api_keys'
    __table_args__ = (
        ForeignKeyConstraint(['org_id'], ['organizations.id'], ondelete='CASCADE', name='provider_api_keys_org_id_organizations_id_fk'),
        PrimaryKeyConstraint('id', name='provider_api_keys_pkey'),
        UniqueConstraint('user_id', 'provider', name='provider_api_keys_user_id_provider_unique')
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text('gen_random_uuid()'))
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    encrypted_key: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    org_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid)
    hint: Mapped[Optional[str]] = mapped_column(Text, server_default=text("''::text"))

    org: Mapped[Optional['Organizations']] = relationship('Organizations', back_populates='provider_api_keys')


class SavedFilters(Base):
    __tablename__ = 'saved_filters'
    __table_args__ = (
        ForeignKeyConstraint(['org_id'], ['organizations.id'], ondelete='CASCADE', name='saved_filters_org_id_organizations_id_fk'),
        PrimaryKeyConstraint('id', name='saved_filters_pkey')
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text('gen_random_uuid()'))
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    nom: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    org_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid)
    contexte: Mapped[Optional[str]] = mapped_column(Text, server_default=text("''::text"))
    filtre: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'{}'::text"))

    org: Mapped[Optional['Organizations']] = relationship('Organizations', back_populates='saved_filters')


class SloEntries(Base):
    __tablename__ = 'slo_entries'
    __table_args__ = (
        ForeignKeyConstraint(['org_id'], ['organizations.id'], ondelete='CASCADE', name='slo_entries_org_id_organizations_id_fk'),
        PrimaryKeyConstraint('id', name='slo_entries_pkey')
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text('gen_random_uuid()'))
    module: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    org_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid)
    health_score: Mapped[Optional[int]] = mapped_column(Integer, server_default=text('100'))
    slo_target: Mapped[Optional[float]] = mapped_column(REAL, server_default=text('99.9'))
    slo_current: Mapped[Optional[float]] = mapped_column(REAL, server_default=text('100'))
    erreurs_24h: Mapped[Optional[int]] = mapped_column(Integer, server_default=text('0'))

    org: Mapped[Optional['Organizations']] = relationship('Organizations', back_populates='slo_entries')


class StagingProposals(Base):
    __tablename__ = 'staging_proposals'
    __table_args__ = (
        ForeignKeyConstraint(['org_id'], ['organizations.id'], ondelete='CASCADE', name='staging_proposals_org_id_organizations_id_fk'),
        PrimaryKeyConstraint('id', name='staging_proposals_pkey')
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text('gen_random_uuid()'))
    contenu: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    org_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid)
    score_mea: Mapped[Optional[float]] = mapped_column(REAL, server_default=text('0'))
    statut: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'pending'::text"))

    org: Mapped[Optional['Organizations']] = relationship('Organizations', back_populates='staging_proposals')


class StripePayments(Base):
    __tablename__ = 'stripe_payments'
    __table_args__ = (
        ForeignKeyConstraint(['org_id'], ['organizations.id'], ondelete='CASCADE', name='stripe_payments_org_id_organizations_id_fk'),
        PrimaryKeyConstraint('id', name='stripe_payments_pkey')
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text('gen_random_uuid()'))
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    stripe_session_id: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    org_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid)
    montant: Mapped[Optional[int]] = mapped_column(Integer, server_default=text('0'))
    devise: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'eur'::text"))
    statut: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'pending'::text"))
    completed_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)

    org: Mapped[Optional['Organizations']] = relationship('Organizations', back_populates='stripe_payments')


class TeamMembers(Base):
    __tablename__ = 'team_members'
    __table_args__ = (
        ForeignKeyConstraint(['org_id'], ['organizations.id'], ondelete='CASCADE', name='team_members_org_id_organizations_id_fk'),
        PrimaryKeyConstraint('id', name='team_members_pkey')
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text('gen_random_uuid()'))
    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    nom: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    email: Mapped[Optional[str]] = mapped_column(Text, server_default=text("''::text"))
    role: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'viewer'::text"))
    poles: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'[]'::text"))
    statut: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'actif'::text"))

    org: Mapped['Organizations'] = relationship('Organizations', back_populates='team_members')


class Templates(Base):
    __tablename__ = 'templates'
    __table_args__ = (
        ForeignKeyConstraint(['org_id'], ['organizations.id'], ondelete='CASCADE', name='templates_org_id_organizations_id_fk'),
        PrimaryKeyConstraint('id', name='templates_pkey')
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text('gen_random_uuid()'))
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    nom: Mapped[str] = mapped_column(Text, nullable=False)
    contenu: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    org_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid)
    description: Mapped[Optional[str]] = mapped_column(Text, server_default=text("''::text"))
    type: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'autre'::text"))
    variables: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'[]'::text"))
    public: Mapped[Optional[bool]] = mapped_column(Boolean, server_default=text('false'))

    org: Mapped[Optional['Organizations']] = relationship('Organizations', back_populates='templates')


class ToolLlmConfigs(Base):
    __tablename__ = 'tool_llm_configs'
    __table_args__ = (
        ForeignKeyConstraint(['org_id'], ['organizations.id'], ondelete='CASCADE', name='tool_llm_configs_org_id_organizations_id_fk'),
        PrimaryKeyConstraint('id', name='tool_llm_configs_pkey'),
        UniqueConstraint('org_id', 'tool_id', name='tool_llm_configs_org_id_tool_id_unique')
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text('gen_random_uuid()'))
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    tool_id: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    org_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid)

    org: Mapped[Optional['Organizations']] = relationship('Organizations', back_populates='tool_llm_configs')


class VeilleSources(Base):
    __tablename__ = 'veille_sources'
    __table_args__ = (
        ForeignKeyConstraint(['org_id'], ['organizations.id'], ondelete='CASCADE', name='veille_sources_org_id_organizations_id_fk'),
        PrimaryKeyConstraint('id', name='veille_sources_pkey'),
        Index('idx_veille_sources_user', 'user_id')
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text('gen_random_uuid()'))
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    nom: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    type: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'rss'::text"))
    enabled: Mapped[Optional[bool]] = mapped_column(Boolean, server_default=text('true'))
    org_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid)

    org: Mapped[Optional['Organizations']] = relationship('Organizations', back_populates='veille_sources')
    veille_articles: Mapped[list['VeilleArticles']] = relationship('VeilleArticles', back_populates='source')


class Ventures(Base):
    __tablename__ = 'ventures'
    __table_args__ = (
        ForeignKeyConstraint(['org_id'], ['organizations.id'], ondelete='CASCADE', name='ventures_org_id_organizations_id_fk'),
        PrimaryKeyConstraint('id', name='ventures_pkey')
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text('gen_random_uuid()'))
    owner_id: Mapped[str] = mapped_column(Text, nullable=False)
    nom: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    org_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid)
    description: Mapped[Optional[str]] = mapped_column(Text, server_default=text("''::text"))
    emoji: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'🚀'::text"))
    couleur: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'#6366f1'::text"))
    type: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'own'::text"))
    statut: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'actif'::text"))

    org: Mapped[Optional['Organizations']] = relationship('Organizations', back_populates='ventures')
    governor_usage: Mapped[list['GovernorUsage']] = relationship('GovernorUsage', back_populates='venture')
    llm_presets: Mapped[list['LlmPresets']] = relationship('LlmPresets', back_populates='venture')
    sessions: Mapped[list['Sessions']] = relationship('Sessions', back_populates='venture')
    venture_members: Mapped[list['VentureMembers']] = relationship('VentureMembers', back_populates='venture')


class Webhooks(Base):
    __tablename__ = 'webhooks'
    __table_args__ = (
        ForeignKeyConstraint(['org_id'], ['organizations.id'], ondelete='CASCADE', name='webhooks_org_id_organizations_id_fk'),
        PrimaryKeyConstraint('id', name='webhooks_pkey'),
        Index('idx_webhooks_user', 'user_id')
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text('gen_random_uuid()'))
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    nom: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    events: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'[]'::text"))
    enabled: Mapped[Optional[bool]] = mapped_column(Boolean, server_default=text('true'))
    secret: Mapped[Optional[str]] = mapped_column(Text, server_default=text("''::text"))
    org_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid)

    org: Mapped[Optional['Organizations']] = relationship('Organizations', back_populates='webhooks')


class AgentDefinitions(Base):
    __tablename__ = 'agent_definitions'
    __table_args__ = (
        ForeignKeyConstraint(['personality_id'], ['forge_personalities.id'], ondelete='SET NULL', name='agent_definitions_personality_id_fkey'),
        ForeignKeyConstraint(['pole_id'], ['poles.id'], ondelete='SET NULL', name='agent_definitions_pole_id_poles_id_fk'),
        PrimaryKeyConstraint('id', name='agent_definitions_pkey')
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text('gen_random_uuid()'))
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    nom: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    pole_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid)
    description: Mapped[Optional[str]] = mapped_column(Text, server_default=text("''::text"))
    instructions: Mapped[Optional[str]] = mapped_column(Text, server_default=text("''::text"))
    niveau: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'medium'::text"))
    statut: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'draft'::text"))
    llm_preset: Mapped[Optional[str]] = mapped_column(Text, server_default=text("''::text"))
    personality_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid)

    personality: Mapped[Optional['ForgePersonalities']] = relationship('ForgePersonalities', back_populates='agent_definitions')
    pole: Mapped[Optional['Poles']] = relationship('Poles', back_populates='agent_definitions')
    agent_autonomy_rules: Mapped[list['AgentAutonomyRules']] = relationship('AgentAutonomyRules', back_populates='agent')
    agent_feedback: Mapped[list['AgentFeedback']] = relationship('AgentFeedback', back_populates='agent')
    agent_runs: Mapped[list['AgentRuns']] = relationship('AgentRuns', back_populates='agent')
    agent_scores: Mapped[list['AgentScores']] = relationship('AgentScores', back_populates='agent')


class AuditMissions(Base):
    __tablename__ = 'audit_missions'
    __table_args__ = (
        ForeignKeyConstraint(['pole_id'], ['poles.id'], ondelete='CASCADE', name='audit_missions_pole_id_poles_id_fk'),
        PrimaryKeyConstraint('id', name='audit_missions_pkey')
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text('gen_random_uuid()'))
    pole_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    titre: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    description: Mapped[Optional[str]] = mapped_column(Text, server_default=text("''::text"))
    statut: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'brouillon'::text"))

    pole: Mapped['Poles'] = relationship('Poles', back_populates='audit_missions')
    audit_documents: Mapped[list['AuditDocuments']] = relationship('AuditDocuments', back_populates='mission')
    audit_findings: Mapped[list['AuditFindings']] = relationship('AuditFindings', back_populates='mission')
    audit_recommendations: Mapped[list['AuditRecommendations']] = relationship('AuditRecommendations', back_populates='mission')
    deployed_instances: Mapped[list['DeployedInstances']] = relationship('DeployedInstances', back_populates='mission')
    rapports: Mapped[list['Rapports']] = relationship('Rapports', back_populates='mission')


class BlackboardEvents(Base):
    __tablename__ = 'blackboard_events'
    __table_args__ = (
        ForeignKeyConstraint(['pole_id'], ['poles.id'], ondelete='SET NULL', name='blackboard_events_pole_id_poles_id_fk'),
        PrimaryKeyConstraint('id', name='blackboard_events_pkey'),
        Index('idx_blackboard_created', 'created_at'),
        Index('idx_blackboard_pole', 'pole_id')
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text('gen_random_uuid()'))
    pole_nom: Mapped[str] = mapped_column(Text, nullable=False)
    agent_nom: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    pole_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid)
    pole_emoji: Mapped[Optional[str]] = mapped_column(Text, server_default=text("''::text"))
    niveau: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'N1'::text"))

    pole: Mapped[Optional['Poles']] = relationship('Poles', back_populates='blackboard_events')


class BudgetEntries(Base):
    __tablename__ = 'budget_entries'
    __table_args__ = (
        ForeignKeyConstraint(['pole_id'], ['poles.id'], ondelete='CASCADE', name='budget_entries_pole_id_poles_id_fk'),
        PrimaryKeyConstraint('id', name='budget_entries_pkey')
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text('gen_random_uuid()'))
    pole_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    montant: Mapped[int] = mapped_column(Integer, nullable=False)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    date: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    categorie: Mapped[Optional[str]] = mapped_column(Text, server_default=text("''::text"))

    pole: Mapped['Poles'] = relationship('Poles', back_populates='budget_entries')


class Contrats(Base):
    __tablename__ = 'contrats'
    __table_args__ = (
        ForeignKeyConstraint(['pole_id'], ['poles.id'], ondelete='CASCADE', name='contrats_pole_id_poles_id_fk'),
        PrimaryKeyConstraint('id', name='contrats_pkey'),
        Index('idx_contrats_pole', 'pole_id'),
        Index('idx_contrats_user', 'user_id')
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text('gen_random_uuid()'))
    pole_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    titre: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    type: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'Autre'::text"))
    parties: Mapped[Optional[str]] = mapped_column(Text, server_default=text("''::text"))
    contenu: Mapped[Optional[str]] = mapped_column(Text, server_default=text("''::text"))
    valeur: Mapped[Optional[int]] = mapped_column(Integer, server_default=text('0'))
    statut: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'brouillon'::text"))
    date_debut: Mapped[Optional[str]] = mapped_column(Text, server_default=text("''::text"))
    date_fin: Mapped[Optional[str]] = mapped_column(Text, server_default=text("''::text"))
    notes: Mapped[Optional[str]] = mapped_column(Text, server_default=text("''::text"))
    signe_par: Mapped[Optional[str]] = mapped_column(Text)
    signe_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)

    pole: Mapped['Poles'] = relationship('Poles', back_populates='contrats')


class CrmLeads(Base):
    __tablename__ = 'crm_leads'
    __table_args__ = (
        ForeignKeyConstraint(['pole_id'], ['poles.id'], ondelete='CASCADE', name='crm_leads_pole_id_poles_id_fk'),
        PrimaryKeyConstraint('id', name='crm_leads_pkey'),
        Index('idx_crm_leads_pole', 'pole_id'),
        Index('idx_crm_leads_user', 'user_id')
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text('gen_random_uuid()'))
    pole_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    nom: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    email: Mapped[Optional[str]] = mapped_column(Text, server_default=text("''::text"))
    telephone: Mapped[Optional[str]] = mapped_column(Text, server_default=text("''::text"))
    entreprise: Mapped[Optional[str]] = mapped_column(Text, server_default=text("''::text"))
    statut: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'prospect'::text"))
    valeur: Mapped[Optional[int]] = mapped_column(Integer, server_default=text('0'))
    notes: Mapped[Optional[str]] = mapped_column(Text, server_default=text("''::text"))

    pole: Mapped['Poles'] = relationship('Poles', back_populates='crm_leads')


class DegradationEpisodes(Base):
    __tablename__ = 'degradation_episodes'
    __table_args__ = (
        ForeignKeyConstraint(['mode_id'], ['degradation_modes.id'], ondelete='CASCADE', name='degradation_episodes_mode_id_degradation_modes_id_fk'),
        PrimaryKeyConstraint('id', name='degradation_episodes_pkey')
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text('gen_random_uuid()'))
    mode_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    duree_minutes: Mapped[Optional[int]] = mapped_column(Integer, server_default=text('0'))
    raison: Mapped[Optional[str]] = mapped_column(Text, server_default=text("''::text"))

    mode: Mapped['DegradationModes'] = relationship('DegradationModes', back_populates='degradation_episodes')


class DevTasks(Base):
    __tablename__ = 'dev_tasks'
    __table_args__ = (
        ForeignKeyConstraint(['org_id'], ['organizations.id'], ondelete='CASCADE', name='dev_tasks_org_id_organizations_id_fk'),
        ForeignKeyConstraint(['pole_id'], ['poles.id'], ondelete='SET NULL', name='dev_tasks_pole_id_poles_id_fk'),
        PrimaryKeyConstraint('id', name='dev_tasks_pkey')
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text('gen_random_uuid()'))
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    titre: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    pole_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid)
    org_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid)
    description: Mapped[Optional[str]] = mapped_column(Text, server_default=text("''::text"))
    type: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'feature'::text"))
    statut: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'backlog'::text"))
    priorite: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'normale'::text"))
    agent_ia: Mapped[Optional[str]] = mapped_column(Text, server_default=text("''::text"))
    analyse_llm: Mapped[Optional[str]] = mapped_column(Text, server_default=text("''::text"))
    temps_estime: Mapped[Optional[int]] = mapped_column(Integer, server_default=text('0'))
    assigne_a: Mapped[Optional[str]] = mapped_column(Text, server_default=text("''::text"))
    deadline: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)

    org: Mapped[Optional['Organizations']] = relationship('Organizations', back_populates='dev_tasks')
    pole: Mapped[Optional['Poles']] = relationship('Poles', back_populates='dev_tasks')


class FacturesDocs(Base):
    __tablename__ = 'factures_docs'
    __table_args__ = (
        ForeignKeyConstraint(['pole_id'], ['poles.id'], ondelete='SET NULL', name='factures_docs_pole_id_poles_id_fk'),
        PrimaryKeyConstraint('id', name='factures_docs_pkey')
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text('gen_random_uuid()'))
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    numero: Mapped[str] = mapped_column(Text, nullable=False)
    client_nom: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    pole_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid)
    type: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'facture'::text"))
    client_email: Mapped[Optional[str]] = mapped_column(Text, server_default=text("''::text"))
    client_adresse: Mapped[Optional[str]] = mapped_column(Text, server_default=text("''::text"))
    lignes: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'[]'::text"))
    total_ht: Mapped[Optional[float]] = mapped_column(REAL, server_default=text('0'))
    total_tva: Mapped[Optional[float]] = mapped_column(REAL, server_default=text('0'))
    total_ttc: Mapped[Optional[float]] = mapped_column(REAL, server_default=text('0'))
    tva_taux: Mapped[Optional[float]] = mapped_column(REAL, server_default=text('20'))
    statut: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'brouillon'::text"))
    notes: Mapped[Optional[str]] = mapped_column(Text, server_default=text("''::text"))
    conditions: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'Paiement à 30 jours'::text"))
    date_emission: Mapped[Optional[str]] = mapped_column(Text, server_default=text("''::text"))
    date_echeance: Mapped[Optional[str]] = mapped_column(Text, server_default=text("''::text"))
    date_paiement: Mapped[Optional[str]] = mapped_column(Text, server_default=text("''::text"))

    pole: Mapped[Optional['Poles']] = relationship('Poles', back_populates='factures_docs')


class ForecastEntries(Base):
    __tablename__ = 'forecast_entries'
    __table_args__ = (
        ForeignKeyConstraint(['pole_id'], ['poles.id'], ondelete='CASCADE', name='forecast_entries_pole_id_poles_id_fk'),
        PrimaryKeyConstraint('id', name='forecast_entries_pkey')
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text('gen_random_uuid()'))
    pole_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    annee_mois: Mapped[str] = mapped_column(Text, nullable=False)
    montant: Mapped[float] = mapped_column(REAL, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    categorie: Mapped[Optional[str]] = mapped_column(Text, server_default=text("''::text"))
    type: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'recette'::text"))
    source: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'manuel'::text"))

    pole: Mapped['Poles'] = relationship('Poles', back_populates='forecast_entries')


class GovernorUsage(Base):
    __tablename__ = 'governor_usage'
    __table_args__ = (
        ForeignKeyConstraint(['org_id'], ['organizations.id'], ondelete='CASCADE', name='governor_usage_org_id_organizations_id_fk'),
        ForeignKeyConstraint(['pole_id'], ['poles.id'], ondelete='SET NULL', name='governor_usage_pole_id_poles_id_fk'),
        ForeignKeyConstraint(['venture_id'], ['ventures.id'], ondelete='SET NULL', name='governor_usage_venture_id_fkey'),
        PrimaryKeyConstraint('id', name='governor_usage_pkey'),
        Index('idx_governor_usage_venture', 'venture_id')
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text('gen_random_uuid()'))
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    org_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid)
    pole_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid)
    tokens_in: Mapped[Optional[int]] = mapped_column(Integer, server_default=text('0'))
    tokens_out: Mapped[Optional[int]] = mapped_column(Integer, server_default=text('0'))
    cout_usd: Mapped[Optional[float]] = mapped_column(REAL, server_default=text('0'))
    venture_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid)

    org: Mapped[Optional['Organizations']] = relationship('Organizations', back_populates='governor_usage')
    pole: Mapped[Optional['Poles']] = relationship('Poles', back_populates='governor_usage')
    venture: Mapped[Optional['Ventures']] = relationship('Ventures', back_populates='governor_usage')


class Incidents(Base):
    __tablename__ = 'incidents'
    __table_args__ = (
        ForeignKeyConstraint(['pole_id'], ['poles.id'], ondelete='CASCADE', name='incidents_pole_id_poles_id_fk'),
        PrimaryKeyConstraint('id', name='incidents_pkey'),
        Index('idx_incidents_pole', 'pole_id'),
        Index('idx_incidents_user', 'user_id')
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text('gen_random_uuid()'))
    pole_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    titre: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    description: Mapped[Optional[str]] = mapped_column(Text, server_default=text("''::text"))
    severite: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'moyenne'::text"))
    statut: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'ouvert'::text"))
    resolved_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)

    pole: Mapped['Poles'] = relationship('Poles', back_populates='incidents')


class KillSwitches(Poles):
    __tablename__ = 'kill_switches'
    __table_args__ = (
        ForeignKeyConstraint(['pole_id'], ['poles.id'], ondelete='CASCADE', name='kill_switches_pole_id_poles_id_fk'),
        PrimaryKeyConstraint('pole_id', name='kill_switches_pkey')
    )

    pole_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    en_pause: Mapped[Optional[bool]] = mapped_column(Boolean, server_default=text('false'))
    updated_by: Mapped[Optional[str]] = mapped_column(Text)


class LlmConfigs(Base):
    __tablename__ = 'llm_configs'
    __table_args__ = (
        ForeignKeyConstraint(['pole_id'], ['poles.id'], ondelete='CASCADE', name='llm_configs_pole_id_poles_id_fk'),
        PrimaryKeyConstraint('id', name='llm_configs_pkey'),
        UniqueConstraint('pole_id', name='llm_configs_pole_id_unique')
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text('gen_random_uuid()'))
    pole_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    provider: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'ollama'::text"))
    base_url: Mapped[Optional[str]] = mapped_column(Text, server_default=text("''::text"))
    api_key: Mapped[Optional[str]] = mapped_column(Text, server_default=text("''::text"))
    model: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'llama3.2'::text"))
    max_tokens: Mapped[Optional[int]] = mapped_column(Integer, server_default=text('2048'))
    updated_by: Mapped[Optional[str]] = mapped_column(Text)

    pole: Mapped['Poles'] = relationship('Poles', back_populates='llm_configs')


class LlmPresets(Base):
    __tablename__ = 'llm_presets'
    __table_args__ = (
        CheckConstraint("scope_type = ANY (ARRAY['venture'::text, 'pole'::text, 'tool'::text, 'agent'::text, 'global'::text])", name='llm_presets_scope_type_check'),
        ForeignKeyConstraint(['venture_id'], ['ventures.id'], ondelete='CASCADE', name='llm_presets_venture_id_fkey'),
        PrimaryKeyConstraint('id', name='llm_presets_pkey'),
        UniqueConstraint('scope_type', 'scope_id', name='llm_presets_scope_type_scope_id_key'),
        Index('idx_llm_presets_venture', 'venture_id')
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text('gen_random_uuid()'))
    scope_type: Mapped[str] = mapped_column(Text, nullable=False)
    scope_id: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'ollama'::text"))
    model: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'llama3.2'::text"))
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    venture_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid)
    base_url: Mapped[Optional[str]] = mapped_column(Text, server_default=text("''::text"))
    api_key: Mapped[Optional[str]] = mapped_column(Text, server_default=text("''::text"))
    max_tokens: Mapped[Optional[int]] = mapped_column(Integer, server_default=text('2048'))
    budget_daily: Mapped[Optional[float]] = mapped_column(REAL)
    budget_monthly: Mapped[Optional[float]] = mapped_column(REAL)
    updated_by: Mapped[Optional[str]] = mapped_column(Text)

    venture: Mapped[Optional['Ventures']] = relationship('Ventures', back_populates='llm_presets')


class Okrs(Base):
    __tablename__ = 'okrs'
    __table_args__ = (
        ForeignKeyConstraint(['pole_id'], ['poles.id'], ondelete='CASCADE', name='okrs_pole_id_poles_id_fk'),
        PrimaryKeyConstraint('id', name='okrs_pkey')
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text('gen_random_uuid()'))
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    titre: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    pole_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid)
    description: Mapped[Optional[str]] = mapped_column(Text, server_default=text("''::text"))
    statut: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'actif'::text"))
    periode: Mapped[Optional[str]] = mapped_column(Text, server_default=text("''::text"))

    pole: Mapped[Optional['Poles']] = relationship('Poles', back_populates='okrs')
    key_results: Mapped[list['KeyResults']] = relationship('KeyResults', back_populates='okr')


class OrchestratorSessions(Base):
    __tablename__ = 'orchestrator_sessions'
    __table_args__ = (
        ForeignKeyConstraint(['pole_id'], ['poles.id'], ondelete='SET NULL', name='orchestrator_sessions_pole_id_poles_id_fk'),
        PrimaryKeyConstraint('id', name='orchestrator_sessions_pkey')
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text('gen_random_uuid()'))
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    titre: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    pole_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid)
    agents: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'[]'::text"))
    statut: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'actif'::text"))
    output: Mapped[Optional[str]] = mapped_column(Text, server_default=text("''::text"))

    pole: Mapped[Optional['Poles']] = relationship('Poles', back_populates='orchestrator_sessions')


class PoleMembers(Base):
    __tablename__ = 'pole_members'
    __table_args__ = (
        ForeignKeyConstraint(['pole_id'], ['poles.id'], ondelete='CASCADE', name='pole_members_pole_id_poles_id_fk'),
        PrimaryKeyConstraint('id', name='pole_members_pkey'),
        UniqueConstraint('pole_id', 'user_id', name='pole_members_pole_id_user_id_unique')
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text('gen_random_uuid()'))
    pole_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    nom: Mapped[str] = mapped_column(Text, nullable=False)
    joined_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    avatar_emoji: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'👤'::text"))
    role: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'member'::text"))

    pole: Mapped['Poles'] = relationship('Poles', back_populates='pole_members')


class PoleTools(Base):
    __tablename__ = 'pole_tools'
    __table_args__ = (
        ForeignKeyConstraint(['pole_id'], ['poles.id'], ondelete='CASCADE', name='pole_tools_pole_id_poles_id_fk'),
        PrimaryKeyConstraint('id', name='pole_tools_pkey'),
        UniqueConstraint('pole_id', 'tool_key', name='pole_tools_pole_id_tool_key_unique')
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text('gen_random_uuid()'))
    pole_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    tool_key: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    enabled: Mapped[Optional[bool]] = mapped_column(Boolean, server_default=text('true'))
    ordre: Mapped[Optional[int]] = mapped_column(Integer, server_default=text('0'))

    pole: Mapped['Poles'] = relationship('Poles', back_populates='pole_tools')


class RiskLogs(Base):
    __tablename__ = 'risk_logs'
    __table_args__ = (
        ForeignKeyConstraint(['org_id'], ['organizations.id'], ondelete='CASCADE', name='risk_logs_org_id_organizations_id_fk'),
        ForeignKeyConstraint(['pole_id'], ['poles.id'], ondelete='SET NULL', name='risk_logs_pole_id_poles_id_fk'),
        PrimaryKeyConstraint('id', name='risk_logs_pkey')
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text('gen_random_uuid()'))
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    org_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid)
    pole_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid)
    score: Mapped[Optional[int]] = mapped_column(Integer, server_default=text('0'))
    niveau: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'faible'::text"))
    fast_path: Mapped[Optional[bool]] = mapped_column(Boolean, server_default=text('false'))
    approuve: Mapped[Optional[bool]] = mapped_column(Boolean, server_default=text('false'))
    raison: Mapped[Optional[str]] = mapped_column(Text, server_default=text("''::text"))

    org: Mapped[Optional['Organizations']] = relationship('Organizations', back_populates='risk_logs')
    pole: Mapped[Optional['Poles']] = relationship('Poles', back_populates='risk_logs')


class Sessions(Base):
    __tablename__ = 'sessions'
    __table_args__ = (
        CheckConstraint("scope = ANY (ARRAY['user'::text, 'pole'::text, 'venture'::text])", name='sessions_scope_check'),
        ForeignKeyConstraint(['org_id'], ['organizations.id'], ondelete='CASCADE', name='sessions_org_id_organizations_id_fk'),
        ForeignKeyConstraint(['pole_id'], ['poles.id'], ondelete='SET NULL', name='sessions_pole_id_poles_id_fk'),
        ForeignKeyConstraint(['venture_id'], ['ventures.id'], ondelete='SET NULL', name='sessions_venture_id_fkey'),
        PrimaryKeyConstraint('id', name='sessions_pkey'),
        Index('idx_sessions_org', 'org_id'),
        Index('idx_sessions_pole', 'pole_id'),
        Index('idx_sessions_user', 'user_id'),
        Index('idx_sessions_venture', 'venture_id')
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text('gen_random_uuid()'))
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'New conversation'::text"))
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    scope: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'user'::text"))
    pole_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid)
    org_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid)
    venture_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid)

    org: Mapped[Optional['Organizations']] = relationship('Organizations', back_populates='sessions')
    pole: Mapped[Optional['Poles']] = relationship('Poles', back_populates='sessions')
    venture: Mapped[Optional['Ventures']] = relationship('Ventures', back_populates='sessions')
    artifacts: Mapped[list['Artifacts']] = relationship('Artifacts', back_populates='session')
    documents: Mapped[list['Documents']] = relationship('Documents', back_populates='session')
    messages: Mapped[list['Messages']] = relationship('Messages', back_populates='session')


class SocialAccounts(Base):
    __tablename__ = 'social_accounts'
    __table_args__ = (
        ForeignKeyConstraint(['pole_id'], ['poles.id'], ondelete='CASCADE', name='social_accounts_pole_id_poles_id_fk'),
        PrimaryKeyConstraint('id', name='social_accounts_pkey')
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text('gen_random_uuid()'))
    pole_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    platform: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    nom: Mapped[Optional[str]] = mapped_column(Text, server_default=text("''::text"))
    config: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'{}'::text"))
    actif: Mapped[Optional[bool]] = mapped_column(Boolean, server_default=text('true'))

    pole: Mapped['Poles'] = relationship('Poles', back_populates='social_accounts')


class Sprints(Base):
    __tablename__ = 'sprints'
    __table_args__ = (
        ForeignKeyConstraint(['pole_id'], ['poles.id'], ondelete='CASCADE', name='sprints_pole_id_poles_id_fk'),
        PrimaryKeyConstraint('id', name='sprints_pkey'),
        Index('idx_sprints_pole', 'pole_id')
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text('gen_random_uuid()'))
    pole_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    nom: Mapped[str] = mapped_column(Text, nullable=False)
    date_debut: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    objectif: Mapped[Optional[str]] = mapped_column(Text, server_default=text("''::text"))
    statut: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'actif'::text"))
    date_fin: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)

    pole: Mapped['Poles'] = relationship('Poles', back_populates='sprints')
    tasks: Mapped[list['Tasks']] = relationship('Tasks', back_populates='sprint')


class TaskDagItems(Base):
    __tablename__ = 'task_dag_items'
    __table_args__ = (
        ForeignKeyConstraint(['pole_id'], ['poles.id'], ondelete='CASCADE', name='task_dag_items_pole_id_poles_id_fk'),
        PrimaryKeyConstraint('id', name='task_dag_items_pkey')
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text('gen_random_uuid()'))
    pole_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    nom: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    description: Mapped[Optional[str]] = mapped_column(Text, server_default=text("''::text"))
    agent_owner: Mapped[Optional[str]] = mapped_column(Text, server_default=text("''::text"))
    dependances: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'[]'::text"))
    statut: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'pending'::text"))
    criticite: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'normale'::text"))
    node_type: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'agent'::text"))
    pos_x: Mapped[Optional[float]] = mapped_column(REAL, server_default=text('0'))
    pos_y: Mapped[Optional[float]] = mapped_column(REAL, server_default=text('0'))
    prompt_text: Mapped[Optional[str]] = mapped_column(Text, server_default=text("''::text"))

    pole: Mapped['Poles'] = relationship('Poles', back_populates='task_dag_items')


class VeilleArticles(Base):
    __tablename__ = 'veille_articles'
    __table_args__ = (
        ForeignKeyConstraint(['source_id'], ['veille_sources.id'], ondelete='CASCADE', name='veille_articles_source_id_veille_sources_id_fk'),
        PrimaryKeyConstraint('id', name='veille_articles_pkey'),
        Index('idx_veille_articles_source', 'source_id'),
        Index('idx_veille_articles_user', 'user_id')
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text('gen_random_uuid()'))
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    titre: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    source_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid)
    resume: Mapped[Optional[str]] = mapped_column(Text, server_default=text("''::text"))
    lu: Mapped[Optional[bool]] = mapped_column(Boolean, server_default=text('false'))
    published_at: Mapped[Optional[str]] = mapped_column(Text, server_default=text("''::text"))

    source: Mapped[Optional['VeilleSources']] = relationship('VeilleSources', back_populates='veille_articles')


class VentureMembers(Base):
    __tablename__ = 'venture_members'
    __table_args__ = (
        ForeignKeyConstraint(['venture_id'], ['ventures.id'], ondelete='CASCADE', name='venture_members_venture_id_ventures_id_fk'),
        PrimaryKeyConstraint('id', name='venture_members_pkey'),
        UniqueConstraint('venture_id', 'user_id', name='venture_members_venture_id_user_id_unique')
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text('gen_random_uuid()'))
    venture_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    joined_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    role: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'member'::text"))

    venture: Mapped['Ventures'] = relationship('Ventures', back_populates='venture_members')


class AgentAutonomyRules(Base):
    __tablename__ = 'agent_autonomy_rules'
    __table_args__ = (
        ForeignKeyConstraint(['agent_id'], ['agent_definitions.id'], ondelete='CASCADE', name='agent_autonomy_rules_agent_id_agent_definitions_id_fk'),
        PrimaryKeyConstraint('id', name='agent_autonomy_rules_pkey')
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text('gen_random_uuid()'))
    agent_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    niveau: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'N1'::text"))
    horaires: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'{}'::text"))
    override_ok: Mapped[Optional[bool]] = mapped_column(Boolean, server_default=text('false'))

    agent: Mapped['AgentDefinitions'] = relationship('AgentDefinitions', back_populates='agent_autonomy_rules')


class AgentFeedback(Base):
    __tablename__ = 'agent_feedback'
    __table_args__ = (
        ForeignKeyConstraint(['agent_id'], ['agent_definitions.id'], ondelete='CASCADE', name='agent_feedback_agent_id_agent_definitions_id_fk'),
        PrimaryKeyConstraint('id', name='agent_feedback_pkey')
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text('gen_random_uuid()'))
    agent_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    rating: Mapped[Optional[int]] = mapped_column(Integer, server_default=text('3'))
    commentaire: Mapped[Optional[str]] = mapped_column(Text, server_default=text("''::text"))

    agent: Mapped['AgentDefinitions'] = relationship('AgentDefinitions', back_populates='agent_feedback')


class AgentRuns(Base):
    __tablename__ = 'agent_runs'
    __table_args__ = (
        ForeignKeyConstraint(['agent_id'], ['agent_definitions.id'], ondelete='SET NULL', name='agent_runs_agent_id_agent_definitions_id_fk'),
        ForeignKeyConstraint(['pole_id'], ['poles.id'], ondelete='SET NULL', name='agent_runs_pole_id_poles_id_fk'),
        PrimaryKeyConstraint('id', name='agent_runs_pkey')
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text('gen_random_uuid()'))
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    agent_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid)
    pole_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid)
    statut: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'running'::text"))
    input: Mapped[Optional[str]] = mapped_column(Text, server_default=text("''::text"))
    output: Mapped[Optional[str]] = mapped_column(Text, server_default=text("''::text"))
    tokens_in: Mapped[Optional[int]] = mapped_column(Integer, server_default=text('0'))
    tokens_out: Mapped[Optional[int]] = mapped_column(Integer, server_default=text('0'))
    duree_ms: Mapped[Optional[int]] = mapped_column(Integer, server_default=text('0'))
    completed_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)

    agent: Mapped[Optional['AgentDefinitions']] = relationship('AgentDefinitions', back_populates='agent_runs')
    pole: Mapped[Optional['Poles']] = relationship('Poles', back_populates='agent_runs')


class AgentScores(Base):
    __tablename__ = 'agent_scores'
    __table_args__ = (
        ForeignKeyConstraint(['agent_id'], ['agent_definitions.id'], ondelete='CASCADE', name='agent_scores_agent_id_agent_definitions_id_fk'),
        PrimaryKeyConstraint('id', name='agent_scores_pkey')
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text('gen_random_uuid()'))
    agent_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    confiance_score: Mapped[Optional[float]] = mapped_column(REAL, server_default=text('0'))
    risk_level: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'faible'::text"))
    retro_feedback: Mapped[Optional[str]] = mapped_column(Text, server_default=text("''::text"))

    agent: Mapped['AgentDefinitions'] = relationship('AgentDefinitions', back_populates='agent_scores')


class Artifacts(Base):
    __tablename__ = 'artifacts'
    __table_args__ = (
        ForeignKeyConstraint(['session_id'], ['sessions.id'], ondelete='CASCADE', name='artifacts_session_id_sessions_id_fk'),
        PrimaryKeyConstraint('id', name='artifacts_pkey')
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text('gen_random_uuid()'))
    session_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    status: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'pending'::text"))

    session: Mapped['Sessions'] = relationship('Sessions', back_populates='artifacts')


class AuditDocuments(Base):
    __tablename__ = 'audit_documents'
    __table_args__ = (
        ForeignKeyConstraint(['mission_id'], ['audit_missions.id'], ondelete='CASCADE', name='audit_documents_mission_id_audit_missions_id_fk'),
        PrimaryKeyConstraint('id', name='audit_documents_pkey')
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text('gen_random_uuid()'))
    mission_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    nom: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    type: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'pdf'::text"))
    contenu: Mapped[Optional[str]] = mapped_column(Text, server_default=text("''::text"))
    analyse: Mapped[Optional[str]] = mapped_column(Text, server_default=text("''::text"))

    mission: Mapped['AuditMissions'] = relationship('AuditMissions', back_populates='audit_documents')


class AuditFindings(Base):
    __tablename__ = 'audit_findings'
    __table_args__ = (
        ForeignKeyConstraint(['mission_id'], ['audit_missions.id'], ondelete='CASCADE', name='audit_findings_mission_id_fkey'),
        PrimaryKeyConstraint('id', name='audit_findings_pkey')
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text('gen_random_uuid()'))
    mission_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    categorie: Mapped[Optional[str]] = mapped_column(Text, server_default=text("''::text"))
    severite: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'faible'::text"))
    source: Mapped[Optional[str]] = mapped_column(Text, server_default=text("''::text"))

    mission: Mapped['AuditMissions'] = relationship('AuditMissions', back_populates='audit_findings')


class AuditRecommendations(Base):
    __tablename__ = 'audit_recommendations'
    __table_args__ = (
        ForeignKeyConstraint(['mission_id'], ['audit_missions.id'], ondelete='CASCADE', name='audit_recommendations_mission_id_fkey'),
        PrimaryKeyConstraint('id', name='audit_recommendations_pkey')
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text('gen_random_uuid()'))
    mission_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    priorite: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'moyenne'::text"))
    statut: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'ouvert'::text"))

    mission: Mapped['AuditMissions'] = relationship('AuditMissions', back_populates='audit_recommendations')


class DeployedInstances(Base):
    __tablename__ = 'deployed_instances'
    __table_args__ = (
        ForeignKeyConstraint(['mission_id'], ['audit_missions.id'], ondelete='CASCADE', name='deployed_instances_mission_id_fkey'),
        PrimaryKeyConstraint('id', name='deployed_instances_pkey')
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text('gen_random_uuid()'))
    mission_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    server_ip: Mapped[str] = mapped_column(Text, nullable=False)
    ssh_key: Mapped[str] = mapped_column(Text, nullable=False)
    admin_email: Mapped[str] = mapped_column(Text, nullable=False)
    admin_password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    ssh_user: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'root'::text"))
    domain: Mapped[Optional[str]] = mapped_column(Text, server_default=text("''::text"))
    domain_mode: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'manual'::text"))
    status: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'deploying'::text"))
    notes: Mapped[Optional[str]] = mapped_column(Text, server_default=text("''::text"))
    deployed_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)
    progress_step: Mapped[Optional[int]] = mapped_column(Integer, server_default=text('0'))
    progress_total: Mapped[Optional[int]] = mapped_column(Integer, server_default=text('6'))
    progress_msg: Mapped[Optional[str]] = mapped_column(Text, server_default=text("''::text"))
    progress_updated_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)

    mission: Mapped['AuditMissions'] = relationship('AuditMissions', back_populates='deployed_instances')


class Documents(Base):
    __tablename__ = 'documents'
    __table_args__ = (
        ForeignKeyConstraint(['pole_id'], ['poles.id'], ondelete='SET NULL', name='documents_pole_id_poles_id_fk'),
        ForeignKeyConstraint(['session_id'], ['sessions.id'], ondelete='SET NULL', name='documents_session_id_sessions_id_fk'),
        PrimaryKeyConstraint('id', name='documents_pkey'),
        Index('idx_documents_pole', 'pole_id'),
        Index('idx_documents_user', 'user_id')
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text('gen_random_uuid()'))
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    nom: Mapped[str] = mapped_column(Text, nullable=False)
    contenu: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    pole_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid)
    session_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid)
    type: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'pdf'::text"))
    analyse: Mapped[Optional[str]] = mapped_column(Text, server_default=text("''::text"))
    taille: Mapped[Optional[int]] = mapped_column(Integer, server_default=text('0'))

    pole: Mapped[Optional['Poles']] = relationship('Poles', back_populates='documents')
    session: Mapped[Optional['Sessions']] = relationship('Sessions', back_populates='documents')


class KeyResults(Base):
    __tablename__ = 'key_results'
    __table_args__ = (
        ForeignKeyConstraint(['okr_id'], ['okrs.id'], ondelete='CASCADE', name='key_results_okr_id_okrs_id_fk'),
        PrimaryKeyConstraint('id', name='key_results_pkey')
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text('gen_random_uuid()'))
    okr_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    titre: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    valeur_cible: Mapped[Optional[float]] = mapped_column(REAL, server_default=text('100'))
    valeur_actuelle: Mapped[Optional[float]] = mapped_column(REAL, server_default=text('0'))
    unite: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'%'::text"))

    okr: Mapped['Okrs'] = relationship('Okrs', back_populates='key_results')


class Messages(Base):
    __tablename__ = 'messages'
    __table_args__ = (
        ForeignKeyConstraint(['session_id'], ['sessions.id'], ondelete='CASCADE', name='messages_session_id_sessions_id_fk'),
        PrimaryKeyConstraint('id', name='messages_pkey'),
        Index('idx_messages_session', 'session_id')
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text('gen_random_uuid()'))
    session_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))

    session: Mapped['Sessions'] = relationship('Sessions', back_populates='messages')


class Rapports(Base):
    __tablename__ = 'rapports'
    __table_args__ = (
        ForeignKeyConstraint(['mission_id'], ['audit_missions.id'], ondelete='SET NULL', name='rapports_mission_id_fkey'),
        ForeignKeyConstraint(['org_id'], ['organizations.id'], ondelete='CASCADE', name='rapports_org_id_organizations_id_fk'),
        PrimaryKeyConstraint('id', name='rapports_pkey')
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text('gen_random_uuid()'))
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    titre: Mapped[str] = mapped_column(Text, nullable=False)
    contenu: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    org_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid)
    type: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'weekly'::text"))
    periode: Mapped[Optional[str]] = mapped_column(Text, server_default=text("''::text"))
    mission_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid)

    mission: Mapped[Optional['AuditMissions']] = relationship('AuditMissions', back_populates='rapports')
    org: Mapped[Optional['Organizations']] = relationship('Organizations', back_populates='rapports')


class Tasks(Base):
    __tablename__ = 'tasks'
    __table_args__ = (
        ForeignKeyConstraint(['pole_id'], ['poles.id'], ondelete='CASCADE', name='tasks_pole_id_poles_id_fk'),
        ForeignKeyConstraint(['sprint_id'], ['sprints.id'], ondelete='SET NULL', name='tasks_sprint_id_sprints_id_fk'),
        PrimaryKeyConstraint('id', name='tasks_pkey'),
        Index('idx_tasks_pole', 'pole_id'),
        Index('idx_tasks_user', 'user_id')
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text('gen_random_uuid()'))
    pole_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    titre: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('now()'))
    sprint_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid)
    description: Mapped[Optional[str]] = mapped_column(Text, server_default=text("''::text"))
    statut: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'todo'::text"))
    priorite: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'normale'::text"))
    assigne_a: Mapped[Optional[str]] = mapped_column(Text)

    pole: Mapped['Poles'] = relationship('Poles', back_populates='tasks')
    sprint: Mapped[Optional['Sprints']] = relationship('Sprints', back_populates='tasks')
