"""Sérialiseurs row → JSON camelCase, fidèles à la sortie Drizzle du Bun.

Drizzle renvoie les objets avec les NOMS DE CHAMPS du schéma (camelCase), pas les
colonnes SQL (snake_case), et encode les ``Date`` au format ``toISOString()``
(``...Z`` avec millisecondes). On réplique ça pour la parité.
"""

from __future__ import annotations

import datetime
import json
from typing import Any


def iso(dt: datetime.datetime | None) -> str | None:
    """Date → ISO 8601 UTC avec millisecondes et 'Z' (comme JS Date.toISOString())."""
    if dt is None:
        return None
    # Les colonnes Postgres `timestamp` sont stockées en UTC (naïf). On formate en Z.
    if dt.tzinfo is not None:
        dt = dt.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    return dt.isoformat(timespec="milliseconds") + "Z"


def _sid(v: Any) -> Any:
    """UUID → str ; None reste None ; reste inchangé."""
    return str(v) if v is not None else None


def real(x: float | None) -> float | None:
    """Colonne REAL (float4) → repr courte, comme le driver `pg` (texte) du Bun.

    asyncpg lit le float4 en binaire (ex: 99.9000015258789) ; le Bun le lit en
    texte Postgres (99.9). 7 chiffres significatifs ≈ précision d'un float4.
    """
    if x is None:
        return None
    return float(f"{x:.7g}")


def user_public(u) -> dict:
    return {"id": _sid(u.id), "nom": u.nom, "avatarEmoji": u.avatar_emoji}


def user_export(u) -> dict:
    return {
        "id": _sid(u.id),
        "email": u.email,
        "nom": u.nom,
        "avatarEmoji": u.avatar_emoji,
        "createdAt": iso(u.created_at),
    }


def audit_log(r) -> dict:
    return {
        "id": _sid(r.id),
        "orgId": _sid(r.org_id),
        "userId": r.user_id,
        "userNom": r.user_nom,
        "action": r.action,
        "entite": r.entite,
        "entiteId": r.entite_id,
        "pole": r.pole,
        "details": r.details,
        "createdAt": iso(r.created_at),
    }


def injection_log(r) -> dict:
    return {
        "id": _sid(r.id),
        "orgId": _sid(r.org_id),
        "userId": r.user_id,
        "input": r.input,
        "flagged": r.flagged,
        "raison": r.raison,
        "createdAt": iso(r.created_at),
    }


def managed_server(r) -> dict:
    """Row complète (POST returning). Le routeur écrase `sshKey` par le masque."""
    return {
        "id": _sid(r.id),
        "userId": r.user_id,
        "label": r.label,
        "ip": r.ip,
        "sshKey": r.ssh_key,
        "sshUser": r.ssh_user,
        "region": r.region,
        "status": r.status,
        "instanceId": _sid(r.instance_id),
        "createdAt": iso(r.created_at),
    }


def managed_server_public(r) -> dict:
    """GET /servers — sans la clé SSH (select de colonnes côté Bun)."""
    return {
        "id": _sid(r.id),
        "label": r.label,
        "ip": r.ip,
        "sshUser": r.ssh_user,
        "region": r.region,
        "status": r.status,
        "instanceId": _sid(r.instance_id),
        "createdAt": iso(r.created_at),
    }


def deployed_instance_public(r) -> dict:
    """GET /audit/:missionId/deployments — sans sshKey/passwordHash (select Bun)."""
    return {
        "id": _sid(r.id),
        "missionId": _sid(r.mission_id),
        "serverIp": r.server_ip,
        "domain": r.domain,
        "domainMode": r.domain_mode,
        "status": r.status,
        "adminEmail": r.admin_email,
        "notes": r.notes,
        "deployedAt": iso(r.deployed_at),
        "createdAt": iso(r.created_at),
    }


def dev_task(r) -> dict:
    return {
        "id": _sid(r.id),
        "poleId": _sid(r.pole_id),
        "userId": r.user_id,
        "orgId": _sid(r.org_id),
        "titre": r.titre,
        "description": r.description,
        "type": r.type,
        "statut": r.statut,
        "priorite": r.priorite,
        "agentIA": r.agent_ia,
        "analyseLLM": r.analyse_llm,
        "tempsEstime": r.temps_estime,
        "assigneA": r.assigne_a,
        "deadline": iso(r.deadline),
        "createdAt": iso(r.created_at),
        "updatedAt": iso(r.updated_at),
    }


def sprint(r) -> dict:
    return {
        "id": _sid(r.id),
        "poleId": _sid(r.pole_id),
        "userId": r.user_id,
        "nom": r.nom,
        "objectif": r.objectif,
        "statut": r.statut,
        "dateDebut": iso(r.date_debut),
        "dateFin": iso(r.date_fin),
        "createdAt": iso(r.created_at),
    }


def task(r) -> dict:
    return {
        "id": _sid(r.id),
        "sprintId": _sid(r.sprint_id),
        "poleId": _sid(r.pole_id),
        "userId": r.user_id,
        "titre": r.titre,
        "description": r.description,
        "statut": r.statut,
        "priorite": r.priorite,
        "assigneA": r.assigne_a,
        "createdAt": iso(r.created_at),
        "updatedAt": iso(r.updated_at),
    }


def staging_proposal(r) -> dict:
    return {
        "id": _sid(r.id),
        "orgId": _sid(r.org_id),
        "contenu": r.contenu,
        "scoreMea": real(r.score_mea),
        "statut": r.statut,
        "createdAt": iso(r.created_at),
    }


def gitpack_job(r) -> dict:
    # `logs` est du TEXT contenant du JSON — renvoyé brut (parité Drizzle).
    return {
        "id": _sid(r.id),
        "userId": r.user_id,
        "orgId": _sid(r.org_id),
        "githubUrl": r.github_url,
        "platform": r.platform,
        "statut": r.statut,
        "language": r.language,
        "framework": r.framework,
        "logs": r.logs,
        "error": r.error,
        "createdAt": iso(r.created_at),
        "updatedAt": iso(r.updated_at),
    }


def task_dag_item(r) -> dict:
    # `dependances` est du TEXT JSON — renvoyé brut (parité Drizzle).
    return {
        "id": _sid(r.id),
        "poleId": _sid(r.pole_id),
        "userId": r.user_id,
        "nom": r.nom,
        "description": r.description,
        "agentOwner": r.agent_owner,
        "dependances": r.dependances,
        "statut": r.statut,
        "criticite": r.criticite,
        "nodeType": r.node_type,
        "posX": real(r.pos_x),
        "posY": real(r.pos_y),
        "promptText": r.prompt_text,
        "createdAt": iso(r.created_at),
        "updatedAt": iso(r.updated_at),
    }


def llm_preset(r) -> dict:
    return {
        "id": _sid(r.id),
        "scopeType": r.scope_type,
        "scopeId": r.scope_id,
        "ventureId": _sid(r.venture_id),
        "provider": r.provider,
        "baseUrl": r.base_url,
        "apiKey": r.api_key,
        "model": r.model,
        "maxTokens": r.max_tokens,
        "budgetDaily": real(r.budget_daily),
        "budgetMonthly": real(r.budget_monthly),
        "updatedAt": iso(r.updated_at),
        "updatedBy": r.updated_by,
    }


def agent_definition(r) -> dict:
    return {
        "id": _sid(r.id),
        "userId": r.user_id,
        "poleId": _sid(r.pole_id),
        "personalityId": _sid(r.personality_id),
        "nom": r.nom,
        "description": r.description,
        "instructions": r.instructions,
        "niveau": r.niveau,
        "statut": r.statut,
        "llmPreset": r.llm_preset,
        "createdAt": iso(r.created_at),
        "updatedAt": iso(r.updated_at),
    }


def personality(r) -> dict:
    return {
        "id": _sid(r.id),
        "label": r.label,
        "emoji": r.emoji,
        "description": r.description,
        "systemPrompt": r.system_prompt,
        "isBuiltin": r.is_builtin,
        "position": r.position,
        "createdAt": iso(r.created_at),
    }


def autonomy_rule(r) -> dict:
    return {
        "id": _sid(r.id),
        "agentId": _sid(r.agent_id),
        "userId": r.user_id,
        "niveau": r.niveau,
        "horaires": r.horaires,
        "overrideOk": r.override_ok,
        "updatedAt": iso(r.updated_at),
    }


def agent_feedback(r) -> dict:
    return {
        "id": _sid(r.id),
        "agentId": _sid(r.agent_id),
        "userId": r.user_id,
        "rating": r.rating,
        "commentaire": r.commentaire,
        "createdAt": iso(r.created_at),
    }


def agent_run(r) -> dict:
    return {
        "id": _sid(r.id),
        "agentId": _sid(r.agent_id),
        "userId": r.user_id,
        "poleId": _sid(r.pole_id),
        "statut": r.statut,
        "input": r.input,
        "output": r.output,
        "tokensIn": r.tokens_in,
        "tokensOut": r.tokens_out,
        "dureeMs": r.duree_ms,
        "createdAt": iso(r.created_at),
        "completedAt": iso(r.completed_at),
    }


def agent_score(r) -> dict:
    return {
        "id": _sid(r.id),
        "agentId": _sid(r.agent_id),
        "confianceScore": real(r.confiance_score),
        "riskLevel": r.risk_level,
        "retroFeedback": r.retro_feedback,
        "updatedAt": iso(r.updated_at),
    }


def orchestrator_session(r) -> dict:
    return {
        "id": _sid(r.id),
        "userId": r.user_id,
        "poleId": _sid(r.pole_id),
        "titre": r.titre,
        "agents": r.agents,
        "statut": r.statut,
        "output": r.output,
        "createdAt": iso(r.created_at),
        "updatedAt": iso(r.updated_at),
    }


def kb_article(r) -> dict:
    """Article KB — parité ligne Drizzle brute (tags = STRING JSON stockée)."""
    return {
        "id": _sid(r.id),
        "userId": r.user_id,
        "orgId": _sid(r.org_id),
        "titre": r.titre,
        "contenu": r.contenu,
        "tags": r.tags,
        "isPinned": r.is_pinned,
        "isPublic": r.is_public,
        "createdAt": iso(r.created_at),
        "updatedAt": iso(r.updated_at),
    }


# ── S130 — Ventures & Audit ─────────────────────────────────────────────


def venture(r) -> dict:
    return {
        "id": _sid(r.id),
        "ownerId": r.owner_id,
        "orgId": _sid(r.org_id),
        "nom": r.nom,
        "description": r.description,
        "emoji": r.emoji,
        "couleur": r.couleur,
        "type": r.type,
        "statut": r.statut,
        "createdAt": iso(r.created_at),
        "updatedAt": iso(r.updated_at),
    }


def venture_member(r) -> dict:
    return {
        "id": _sid(r.id),
        "ventureId": _sid(r.venture_id),
        "userId": r.user_id,
        "role": r.role,
        "joinedAt": iso(r.joined_at),
    }


def pole(r) -> dict:
    return {
        "id": _sid(r.id),
        "nom": r.nom,
        "description": r.description,
        "emoji": r.emoji,
        "couleur": r.couleur,
        "type": r.type,
        "ownerId": r.owner_id,
        "orgId": _sid(r.org_id),
        "ventureId": r.venture_id,  # colonne TEXT (pas Uuid) côté Drizzle
        "createdAt": iso(r.created_at),
    }


def pole_member(r) -> dict:
    return {
        "id": _sid(r.id),
        "poleId": _sid(r.pole_id),
        "userId": r.user_id,
        "nom": r.nom,
        "avatarEmoji": r.avatar_emoji,
        "role": r.role,
        "joinedAt": iso(r.joined_at),
    }


def audit_mission(r) -> dict:
    return {
        "id": _sid(r.id),
        "poleId": _sid(r.pole_id),
        "userId": r.user_id,
        "titre": r.titre,
        "description": r.description,
        "statut": r.statut,
        "createdAt": iso(r.created_at),
        "updatedAt": iso(r.updated_at),
    }


def audit_document(r) -> dict:
    return {
        "id": _sid(r.id),
        "missionId": _sid(r.mission_id),
        "userId": r.user_id,
        "nom": r.nom,
        "type": r.type,
        "contenu": r.contenu,
        "analyse": r.analyse,
        "createdAt": iso(r.created_at),
    }


def audit_finding(r) -> dict:
    return {
        "id": _sid(r.id),
        "missionId": _sid(r.mission_id),
        "userId": r.user_id,
        "categorie": r.categorie,
        "severite": r.severite,
        "description": r.description,
        "source": r.source,
        "createdAt": iso(r.created_at),
    }


def audit_recommendation(r) -> dict:
    return {
        "id": _sid(r.id),
        "missionId": _sid(r.mission_id),
        "userId": r.user_id,
        "priorite": r.priorite,
        "action": r.action,
        "statut": r.statut,
        "createdAt": iso(r.created_at),
    }


def rapport(r) -> dict:
    return {
        "id": _sid(r.id),
        "userId": r.user_id,
        "orgId": _sid(r.org_id),
        "missionId": _sid(r.mission_id),
        "titre": r.titre,
        "contenu": r.contenu,
        "type": r.type,
        "periode": r.periode,
        "createdAt": iso(r.created_at),
    }


def brief(r) -> dict:
    return {
        "id": _sid(r.id),
        "userId": r.user_id,
        "orgId": _sid(r.org_id),
        "titre": r.titre,
        "contenu": r.contenu,
        "type": r.type,
        "lu": r.lu,
        "createdAt": iso(r.created_at),
    }


def brief_config(r) -> dict:
    return {
        "id": _sid(r.id),
        "userId": r.user_id,
        "orgId": _sid(r.org_id),
        "enabled": r.enabled,
        "heureUtc": r.heure_utc,
        "joursSemaine": r.jours_semaine,
        "updatedAt": iso(r.updated_at),
    }


def veille_source(r) -> dict:
    return {
        "id": _sid(r.id),
        "userId": r.user_id,
        "orgId": _sid(r.org_id),
        "nom": r.nom,
        "url": r.url,
        "type": r.type,
        "enabled": r.enabled,
        "createdAt": iso(r.created_at),
    }


def veille_article(r) -> dict:
    return {
        "id": _sid(r.id),
        "userId": r.user_id,
        "sourceId": _sid(r.source_id),
        "titre": r.titre,
        "url": r.url,
        "resume": r.resume,
        "lu": r.lu,
        "publishedAt": r.published_at,
        "createdAt": iso(r.created_at),
    }


def pole_dev_request(r) -> dict:
    return {
        "id": _sid(r.id),
        "sourcePoleId": _sid(r.source_pole_id),
        "sourcePoleName": r.source_pole_name,
        "sourcePoleEmoji": r.source_pole_emoji,
        "title": r.title,
        "description": r.description,
        "frequency": r.frequency,
        "priority": r.priority,
        "status": r.status,
        "analysis": r.analysis,
        "proposedSolution": r.proposed_solution,
        "automationRuleId": _sid(r.automation_rule_id),
        "rejectionReason": r.rejection_reason,
        "userId": r.user_id,
        "createdAt": iso(r.created_at),
        "updatedAt": iso(r.updated_at),
    }


# ── S131 — Business & finance ───────────────────────────────────────────


def organization(r) -> dict:
    return {
        "id": _sid(r.id),
        "nom": r.nom,
        "slug": r.slug,
        "emoji": r.emoji,
        "ownerId": r.owner_id,
        "plan": r.plan,
        "createdAt": iso(r.created_at),
    }


def team_member(r) -> dict:
    return {
        "id": _sid(r.id),
        "orgId": _sid(r.org_id),
        "userId": r.user_id,
        "nom": r.nom,
        "email": r.email,
        "role": r.role,
        "poles": r.poles,  # colonne TEXT (JSON stocké) → renvoyée brute, comme Drizzle
        "statut": r.statut,
        "createdAt": iso(r.created_at),
    }


def crm_lead(r) -> dict:
    return {
        "id": _sid(r.id),
        "poleId": _sid(r.pole_id),
        "userId": r.user_id,
        "nom": r.nom,
        "email": r.email,
        "telephone": r.telephone,
        "entreprise": r.entreprise,
        "statut": r.statut,
        "valeur": r.valeur,
        "notes": r.notes,
        "createdAt": iso(r.created_at),
        "updatedAt": iso(r.updated_at),
    }


def contrat(r) -> dict:
    return {
        "id": _sid(r.id),
        "poleId": _sid(r.pole_id),
        "userId": r.user_id,
        "titre": r.titre,
        "type": r.type,
        "parties": r.parties,
        "contenu": r.contenu,
        "valeur": r.valeur,
        "statut": r.statut,
        "dateDebut": r.date_debut,
        "dateFin": r.date_fin,
        "notes": r.notes,
        "signePar": r.signe_par,
        "signeAt": iso(r.signe_at),
        "createdAt": iso(r.created_at),
        "updatedAt": iso(r.updated_at),
    }


def facture_doc(r) -> dict:
    return {
        "id": _sid(r.id),
        "userId": r.user_id,
        "poleId": _sid(r.pole_id),
        "numero": r.numero,
        "type": r.type,
        "clientNom": r.client_nom,
        "clientEmail": r.client_email,
        "clientAdresse": r.client_adresse,
        "lignes": r.lignes,  # colonne TEXT (JSON stocké) → renvoyée brute
        "totalHt": real(r.total_ht),
        "totalTva": real(r.total_tva),
        "totalTtc": real(r.total_ttc),
        "tvaRaux": real(r.tva_taux),  # nom de champ Drizzle (typo conservée pour parité)
        "statut": r.statut,
        "notes": r.notes,
        "conditions": r.conditions,
        "dateEmission": r.date_emission,
        "dateEcheance": r.date_echeance,
        "datePaiement": r.date_paiement,
        "createdAt": iso(r.created_at),
        "updatedAt": iso(r.updated_at),
    }


def budget_entry(r) -> dict:
    return {
        "id": _sid(r.id),
        "poleId": _sid(r.pole_id),
        "userId": r.user_id,
        "label": r.label,
        "montant": r.montant,
        "type": r.type,
        "categorie": r.categorie,
        "date": iso(r.date),
        "createdAt": iso(r.created_at),
    }


def forecast_entry(r) -> dict:
    return {
        "id": _sid(r.id),
        "poleId": _sid(r.pole_id),
        "userId": r.user_id,
        "anneeMois": r.annee_mois,
        "montant": real(r.montant),
        "categorie": r.categorie,
        "type": r.type,
        "source": r.source,
        "createdAt": iso(r.created_at),
    }


def okr(r) -> dict:
    return {
        "id": _sid(r.id),
        "userId": r.user_id,
        "poleId": _sid(r.pole_id),
        "titre": r.titre,
        "description": r.description,
        "statut": r.statut,
        "periode": r.periode,
        "createdAt": iso(r.created_at),
        "updatedAt": iso(r.updated_at),
    }


def key_result(r) -> dict:
    return {
        "id": _sid(r.id),
        "okrId": _sid(r.okr_id),
        "titre": r.titre,
        "valeurCible": real(r.valeur_cible),
        "valeurActuelle": real(r.valeur_actuelle),
        "unite": r.unite,
        "createdAt": iso(r.created_at),
    }


def abonnement(r) -> dict:
    return {
        "id": _sid(r.id),
        "orgId": _sid(r.org_id),
        "plan": r.plan,
        "statut": r.statut,
        "stripeSubId": r.stripe_sub_id,
        "periodeFin": iso(r.periode_fin),
        "createdAt": iso(r.created_at),
        "updatedAt": iso(r.updated_at),
    }


def stripe_payment(r) -> dict:
    return {
        "id": _sid(r.id),
        "orgId": _sid(r.org_id),
        "userId": r.user_id,
        "stripeSessionId": r.stripe_session_id,
        "montant": r.montant,
        "devise": r.devise,
        "statut": r.statut,
        "createdAt": iso(r.created_at),
        "completedAt": iso(r.completed_at),
    }


def slo_entry(r) -> dict:
    return {
        "id": _sid(r.id),
        "orgId": _sid(r.org_id),
        "module": r.module,
        "healthScore": r.health_score,
        "sloTarget": real(r.slo_target),
        "sloCurrent": real(r.slo_current),
        "erreurs24h": r.erreurs_24h,
        "updatedAt": iso(r.updated_at),
    }


# ── S133 — Automation & pipelines ───────────────────────────────────────
# Les colonnes TEXT contenant du JSON (nodes/edges/conditions/actions/variables/
# payload) sont renvoyées BRUTES, comme Drizzle (parité avec le Bun).


def pipeline_template(r) -> dict:
    return {
        "id": _sid(r.id),
        "userId": r.user_id,
        "nom": r.nom,
        "description": r.description,
        "icon": r.icon,
        "categorie": r.categorie,
        "isPublic": r.is_public,
        "nodes": r.nodes,
        "edges": r.edges,
        "createdAt": iso(r.created_at),
        "updatedAt": iso(r.updated_at),
    }


def automation_rule(r) -> dict:
    return {
        "id": _sid(r.id),
        "userId": r.user_id,
        "orgId": _sid(r.org_id),
        "nom": r.nom,
        "description": r.description,
        "trigger": r.trigger,
        "conditions": r.conditions,
        "actions": r.actions,
        "actif": r.actif,
        "executions": r.executions,
        "createdAt": iso(r.created_at),
        "updatedAt": iso(r.updated_at),
    }


def template(r) -> dict:
    return {
        "id": _sid(r.id),
        "userId": r.user_id,
        "orgId": _sid(r.org_id),
        "nom": r.nom,
        "description": r.description,
        "type": r.type,
        "contenu": r.contenu,
        "variables": r.variables,
        "public": r.public,
        "createdAt": iso(r.created_at),
        "updatedAt": iso(r.updated_at),
    }


def repetition_config(r) -> dict:
    return {
        "id": _sid(r.id),
        "poleId": _sid(r.pole_id),
        "seuilOccurrences": r.seuil_occurrences,
        "periodeJours": r.periode_jours,
        "silenceDays": r.silence_days,
        "actif": r.actif,
        "updatedAt": iso(r.updated_at),
    }


def hitl_request(r) -> dict:
    return {
        "id": _sid(r.id),
        "sessionId": _sid(r.session_id),
        "userId": r.user_id,
        "niveau": r.niveau,
        "action": r.action,
        "payload": r.payload,  # TEXT JSON brut
        "statut": r.statut,
        "decidePar": r.decide_par,
        "decideAt": iso(r.decide_at),
        "createdAt": iso(r.created_at),
    }


def decision_n0(r) -> dict:
    return {
        "id": _sid(r.id),
        "poleId": _sid(r.pole_id),
        "poleNom": r.pole_nom,
        "agentNom": r.agent_nom,
        "action": r.action,
        "niveau": r.niveau,
        "statut": r.statut,
        "urgence": r.urgence,
        "createdAt": iso(r.created_at),
        "resolvedAt": iso(r.resolved_at),
        "resolvedBy": r.resolved_by,
    }


def blackboard_event(r) -> dict:
    return {
        "id": _sid(r.id),
        "poleId": _sid(r.pole_id),
        "poleNom": r.pole_nom,
        "poleEmoji": r.pole_emoji,
        "agentNom": r.agent_nom,
        "type": r.type,
        "payload": r.payload,
        "niveau": r.niveau,
        "createdAt": iso(r.created_at),
    }


def session(r) -> dict:
    return {
        "id": _sid(r.id),
        "userId": r.user_id,
        "orgId": _sid(r.org_id),
        "name": r.name,
        "poleId": _sid(r.pole_id),
        "ventureId": _sid(r.venture_id),
        "scope": r.scope,
        "createdAt": iso(r.created_at),
        "updatedAt": iso(r.updated_at),
    }


def message(r) -> dict:
    return {
        "id": _sid(r.id),
        "sessionId": _sid(r.session_id),
        "role": r.role,
        "content": r.content,
        "createdAt": iso(r.created_at),
    }


def governor_config(r) -> dict:
    return {
        "id": _sid(r.id),
        "userId": r.user_id,
        "orgId": _sid(r.org_id),
        "budgetJournalier": r.budget_journalier,
        "budgetMensuel": r.budget_mensuel,
        "alerteSeuil": r.alerte_seuil,
        "blocageSeuil": r.blocage_seuil,
        "actif": r.actif,
        "updatedAt": iso(r.updated_at),
    }


def governor_usage(r) -> dict:
    return {
        "id": _sid(r.id),
        "userId": r.user_id,
        "orgId": _sid(r.org_id),
        "provider": r.provider,
        "model": r.model,
        "tokensIn": r.tokens_in,
        "tokensOut": r.tokens_out,
        "coutUsd": real(r.cout_usd),
        "poleId": _sid(r.pole_id),
        "ventureId": _sid(r.venture_id),
        "createdAt": iso(r.created_at),
    }


def risk_log(r) -> dict:
    return {
        "id": _sid(r.id),
        "userId": r.user_id,
        "orgId": _sid(r.org_id),
        "poleId": _sid(r.pole_id),
        "action": r.action,
        "score": r.score,
        "niveau": r.niveau,
        "fastPath": r.fast_path,
        "approuve": r.approuve,
        "raison": r.raison,
        "createdAt": iso(r.created_at),
    }


def degradation_mode(r) -> dict:
    return {
        "id": _sid(r.id),
        "orgId": _sid(r.org_id),
        "ressource": r.ressource,
        "actif": r.actif,
        "graceMode": r.grace_mode,
        "createdAt": iso(r.created_at),
    }


def degradation_episode(r) -> dict:
    return {
        "id": _sid(r.id),
        "modeId": _sid(r.mode_id),
        "dureeMinutes": r.duree_minutes,
        "raison": r.raison,
        "createdAt": iso(r.created_at),
    }


# ── S134 — temps réel (push, webhooks) ──────────────────────────────────
def push_subscription_min(r) -> dict:
    """GET /push/subscriptions : le Bun ne sélectionne que ces 3 colonnes."""
    return {
        "id": _sid(r.id),
        "endpoint": r.endpoint,
        "createdAt": iso(r.created_at),
    }


def push_subscription(r) -> dict:
    """POST /push/subscribe : ``.returning()`` renvoie la ligne complète."""
    return {
        "id": _sid(r.id),
        "userId": r.user_id,
        "endpoint": r.endpoint,
        "p256dh": r.p256dh,
        "auth": r.auth,
        "createdAt": iso(r.created_at),
    }


def webhook(r, parse_events: bool = True) -> dict:
    """Webhook complet camelCase.

    Quirk Bun préservé : GET et POST renvoient ``events`` parsé en tableau, mais
    PATCH renvoie la ligne brute de ``.returning()`` → ``events`` reste la chaîne
    JSON TEXT. On expose ``parse_events`` pour répliquer les deux comportements.
    """
    events_raw = r.events if r.events is not None else "[]"
    if parse_events:
        try:
            events: Any = json.loads(events_raw)
        except (ValueError, TypeError):
            events = []
    else:
        events = events_raw
    return {
        "id": _sid(r.id),
        "userId": r.user_id,
        "nom": r.nom,
        "url": r.url,
        "events": events,
        "enabled": r.enabled,
        "secret": r.secret,
        "orgId": _sid(r.org_id),
        "createdAt": iso(r.created_at),
    }


# ── S135 — Comms & intégrations ─────────────────────────────────────────
# Les colonnes TEXT contenant du JSON (config/filtre) sont renvoyées BRUTES,
# comme Drizzle (parité avec le Bun).


def keybinding(r) -> dict:
    return {
        "id": _sid(r.id),
        "userId": r.user_id,
        "touche": r.touche,
        "action": r.action,
        "createdAt": iso(r.created_at),
    }


def saved_filter(r) -> dict:
    return {
        "id": _sid(r.id),
        "userId": r.user_id,
        "orgId": _sid(r.org_id),
        "nom": r.nom,
        "contexte": r.contexte,
        "filtre": r.filtre,  # TEXT JSON brut (parité Drizzle)
        "createdAt": iso(r.created_at),
    }


def imap_config_public(r) -> dict:
    """GET /imap/configs — le Bun sélectionne ces 6 colonnes (pas le mot de passe)."""
    return {
        "id": _sid(r.id),
        "host": r.host,
        "port": r.port,
        "email": r.email,
        "actif": r.actif,
        "createdAt": iso(r.created_at),
    }


def imap_config_min(r) -> dict:
    """POST /imap/configs — le Bun ne renvoie que ces 4 champs de la ligne créée."""
    return {
        "id": _sid(r.id),
        "host": r.host,
        "email": r.email,
        "actif": r.actif,
    }


def imap_email(r) -> dict:
    return {
        "id": _sid(r.id),
        "configId": _sid(r.config_id),
        "messageId": r.message_id,
        "sujet": r.sujet,
        "expediteur": r.expediteur,
        "corps": r.corps,
        "lu": r.lu,
        "createdAt": iso(r.created_at),
    }


def incident(r) -> dict:
    return {
        "id": _sid(r.id),
        "poleId": _sid(r.pole_id),
        "userId": r.user_id,
        "titre": r.titre,
        "description": r.description,
        "severite": r.severite,
        "statut": r.statut,
        "resolvedAt": iso(r.resolved_at),
        "createdAt": iso(r.created_at),
        "updatedAt": iso(r.updated_at),
    }


def agenda_event(r) -> dict:
    return {
        "id": _sid(r.id),
        "userId": r.user_id,
        "orgId": _sid(r.org_id),
        "titre": r.titre,
        "description": r.description,
        "dateDebut": iso(r.date_debut),
        "dateFin": iso(r.date_fin),
        "pole": r.pole,
        "googleId": r.google_id,
        "createdAt": iso(r.created_at),
    }


def social_account(r) -> dict:
    """Compte social — sans ``meta`` (le routeur l'ajoute via PLATFORMS)."""
    return {
        "id": _sid(r.id),
        "poleId": _sid(r.pole_id),
        "userId": r.user_id,
        "platform": r.platform,
        "nom": r.nom,
        "config": r.config,  # TEXT JSON brut (parité Drizzle)
        "actif": r.actif,
        "createdAt": iso(r.created_at),
    }


def mcp_server(r) -> dict:
    """Serveur MCP — le routeur masque ``authToken`` (jamais exposé en clair)."""
    return {
        "id": _sid(r.id),
        "userId": r.user_id,
        "orgId": _sid(r.org_id),
        "ventureId": _sid(r.venture_id),
        "poleId": _sid(r.pole_id),
        "nom": r.nom,
        "url": r.url,
        "authType": r.auth_type,
        "authToken": r.auth_token,
        "actif": r.actif,
        "createdAt": iso(r.created_at),
    }


def document_full(r) -> dict:
    return {
        "id": _sid(r.id),
        "userId": r.user_id,
        "poleId": _sid(r.pole_id),
        "sessionId": _sid(r.session_id),
        "nom": r.nom,
        "type": r.type,
        "contenu": r.contenu,
        "analyse": r.analyse,
        "taille": r.taille,
        "createdAt": iso(r.created_at),
    }


def document_list(r) -> dict:
    """GET /documents — le Bun sélectionne ce sous-ensemble (sans ``contenu``)."""
    return {
        "id": _sid(r.id),
        "nom": r.nom,
        "type": r.type,
        "analyse": r.analyse,
        "taille": r.taille,
        "poleId": _sid(r.pole_id),
        "createdAt": iso(r.created_at),
    }


def skill(r) -> dict:
    """Skill → dict (parité Bun). tags = STRING JSON brute (quirk Drizzle).

    `global` (mot-clé Python) est mappé sur l'attribut `is_global` → exposé `global`.
    """
    return {
        "id": _sid(r.id),
        "userId": r.user_id,
        "orgId": _sid(r.org_id),
        "ventureId": _sid(r.venture_id),
        "poleId": _sid(r.pole_id),
        "nom": r.nom,
        "description": r.description,
        "tags": r.tags,
        "skillMd": r.skill_md,
        "actif": r.actif,
        "global": r.is_global,
        "createdAt": iso(r.created_at),
        "updatedAt": iso(r.updated_at),
    }
