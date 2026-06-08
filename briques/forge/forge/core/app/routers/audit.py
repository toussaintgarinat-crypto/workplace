"""Router audit. Portage de routes/audit.ts (S130). Monté /api, protégé.

Missions d'audit + documents + génération de rapport IA (findings/recommandations
structurés en JSON par le LLM, via la gateway) + rendu markdown. Le LLM remplace
`generateText` du Vercel AI SDK par `app.llm.generate_text` (cf. S128/S129).
"""

from __future__ import annotations

import json
import re
import uuid as uuidlib
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import and_, desc, select, update
from sqlalchemy import delete as sa_delete

from app.auth import UserContext, get_current_user
from app.db import SessionLocal
from app.fmt import fr_date, fr_datetime
from app.llm import LlmContext, generate_text, resolve_llm_config
from app.models import (
    AuditDocuments, AuditFindings, AuditMissionPoles, AuditMissions,
    AuditRecommendations, Poles, Rapports,
)
from app.serde import audit_document, audit_finding, audit_mission, audit_recommendation, rapport

router = APIRouter()


def _uuid(v: str | None):
    try:
        return uuidlib.UUID(v)
    except (ValueError, TypeError):
        return None


async def _mission_with_poles(s, mission_id, user_id: str):
    u = _uuid(mission_id) if isinstance(mission_id, str) else mission_id
    m = (await s.execute(
        select(AuditMissions).where(and_(AuditMissions.id == u, AuditMissions.user_id == user_id))
    )).scalar_one_or_none()
    if m is None:
        return None
    rows = (await s.execute(
        select(Poles.id, Poles.nom, Poles.emoji, Poles.couleur, Poles.type)
        .select_from(AuditMissionPoles)
        .join(Poles, AuditMissionPoles.pole_id == Poles.id)
        .where(AuditMissionPoles.mission_id == u)
    )).all()
    poles = [{"id": str(r.id), "nom": r.nom, "emoji": r.emoji, "couleur": r.couleur, "type": r.type}
             for r in rows]
    return {**audit_mission(m), "poles": poles}


# ── Missions ──────────────────────────────────────────────────

@router.get("/poles/{pole_id}/audit", dependencies=[Depends(get_current_user)])
async def list_missions(pole_id: str, user: UserContext = Depends(get_current_user)):
    pu = _uuid(pole_id)
    async with SessionLocal() as s:
        rows = (await s.execute(
            select(AuditMissions).where(and_(AuditMissions.pole_id == pu, AuditMissions.user_id == user.sub))
            .order_by(desc(AuditMissions.created_at))
        )).scalars().all() if pu else []
        out = [await _mission_with_poles(s, m.id, user.sub) for m in rows]
    return [x for x in out if x]


class CreateMission(BaseModel):
    titre: str = Field(min_length=1, max_length=300)
    description: str | None = None


@router.post("/poles/{pole_id}/audit", dependencies=[Depends(get_current_user)])
async def create_mission(pole_id: str, body: CreateMission, response: Response,
                         user: UserContext = Depends(get_current_user)):
    pu = _uuid(pole_id)
    async with SessionLocal() as s:
        m = AuditMissions(pole_id=pu, user_id=user.sub, titre=body.titre, description=body.description or "")
        s.add(m)
        await s.flush()

        source_pole = (await s.execute(select(Poles).where(Poles.id == pu))).scalar_one_or_none() if pu else None
        if source_pole is not None and source_pole.venture_id:
            all_poles = (await s.execute(
                select(Poles).where(Poles.venture_id == source_pole.venture_id)
            )).scalars().all()
        else:
            all_poles = [source_pole] if source_pole is not None else []
        for p in all_poles:
            if p is not None:
                s.add(AuditMissionPoles(mission_id=m.id, pole_id=p.id))
        await s.commit()
        result = await _mission_with_poles(s, m.id, user.sub)
    response.status_code = 201
    return result


class UpdateMission(BaseModel):
    titre: str | None = None
    description: str | None = None
    statut: str | None = None  # brouillon|actif|termine


@router.patch("/audit/{mid}", dependencies=[Depends(get_current_user)])
async def update_mission(mid: str, body: UpdateMission, user: UserContext = Depends(get_current_user)):
    u = _uuid(mid)
    updates: dict = {"updated_at": datetime.utcnow()}
    if body.titre:
        updates["titre"] = body.titre
    if body.description is not None:
        updates["description"] = body.description
    if body.statut:
        updates["statut"] = body.statut
    async with SessionLocal() as s:
        m = (await s.execute(
            select(AuditMissions).where(and_(AuditMissions.id == u, AuditMissions.user_id == user.sub))
        )).scalar_one_or_none() if u else None
        if m is None:
            raise HTTPException(status_code=404, detail="Not found")
        await s.execute(update(AuditMissions)
                        .where(and_(AuditMissions.id == u, AuditMissions.user_id == user.sub))
                        .values(**updates))
        await s.commit()
        result = await _mission_with_poles(s, mid, user.sub)
    return result


@router.delete("/audit/{mid}", dependencies=[Depends(get_current_user)])
async def delete_mission(mid: str, user: UserContext = Depends(get_current_user)):
    u = _uuid(mid)
    async with SessionLocal() as s:
        if u:
            await s.execute(sa_delete(AuditMissions)
                            .where(and_(AuditMissions.id == u, AuditMissions.user_id == user.sub)))
            await s.commit()
    return {"ok": True}


# ── Pôles d'une mission ───────────────────────────────────────

@router.delete("/audit/{mission_id}/poles/{pole_id}", dependencies=[Depends(get_current_user)])
async def remove_mission_pole(mission_id: str, pole_id: str, user: UserContext = Depends(get_current_user)):
    mu, pu = _uuid(mission_id), _uuid(pole_id)
    async with SessionLocal() as s:
        m = (await s.execute(
            select(AuditMissions).where(and_(AuditMissions.id == mu, AuditMissions.user_id == user.sub))
        )).scalar_one_or_none() if mu else None
        if m is None:
            raise HTTPException(status_code=404, detail="Not found")
        await s.execute(sa_delete(AuditMissionPoles).where(and_(
            AuditMissionPoles.mission_id == mu, AuditMissionPoles.pole_id == pu)))
        await s.commit()
    return {"ok": True}


# ── Documents ─────────────────────────────────────────────────

@router.get("/audit/{mission_id}/documents", dependencies=[Depends(get_current_user)])
async def list_documents(mission_id: str, user: UserContext = Depends(get_current_user)):
    mu = _uuid(mission_id)
    async with SessionLocal() as s:
        rows = (await s.execute(
            select(AuditDocuments).where(and_(
                AuditDocuments.mission_id == mu, AuditDocuments.user_id == user.sub))
            .order_by(desc(AuditDocuments.created_at))
        )).scalars().all() if mu else []
    return [audit_document(d) for d in rows]


class CreateDocument(BaseModel):
    nom: str = Field(min_length=1)
    type: str | None = None
    contenu: str
    analyse: str | None = None


@router.post("/audit/{mission_id}/documents", dependencies=[Depends(get_current_user)])
async def create_document(mission_id: str, body: CreateDocument, response: Response,
                          user: UserContext = Depends(get_current_user)):
    mu = _uuid(mission_id)
    async with SessionLocal() as s:
        d = AuditDocuments(mission_id=mu, user_id=user.sub, nom=body.nom,
                           type=body.type or "pdf", contenu=body.contenu, analyse=body.analyse or "")
        s.add(d)
        await s.commit()
        await s.refresh(d)
    response.status_code = 201
    return audit_document(d)


@router.delete("/audit/documents/{did}", dependencies=[Depends(get_current_user)])
async def delete_document(did: str, user: UserContext = Depends(get_current_user)):
    u = _uuid(did)
    async with SessionLocal() as s:
        if u:
            await s.execute(sa_delete(AuditDocuments)
                            .where(and_(AuditDocuments.id == u, AuditDocuments.user_id == user.sub)))
            await s.commit()
    return {"ok": True}


# ── Génération rapport IA ─────────────────────────────────────

_SEVERITE = {"faible", "moyen", "critique"}
_PRIORITE = {"haute", "moyenne", "faible"}
_STATUT = {"ouvert", "en_cours", "resolu"}

_SEV_ICON = {"critique": "🔴", "moyen": "🟠", "faible": "🟡"}
_PRIO_ICON = {"haute": "🔴", "moyenne": "🟠", "faible": "🟢"}


def _build_report_markdown(titre: str, parsed: dict, findings: list, recos: list) -> str:
    by_cat: dict[str, list] = {}
    for f in findings:
        by_cat.setdefault(f.categorie, []).append(f)
    findings_section = "\n\n".join(
        f"### {cat}\n" + "\n".join(
            f"- {_SEV_ICON.get(f.severite, '⚪')} **[{(f.severite or '').upper()}]** {f.description}"
            + (f" *({f.source})*" if f.source else "")
            for f in items
        )
        for cat, items in by_cat.items()
    )
    recos_section = "\n".join(
        f"{i + 1}. {_PRIO_ICON.get(r.priorite, '⚪')} **[{(r.priorite or '').upper()}]** {r.action}"
        for i, r in enumerate(recos)
    )
    return (
        f"# Rapport d'audit — {titre}\n\n"
        f"*Généré le {fr_datetime(datetime.utcnow())}*\n\n"
        "## 📋 Résumé exécutif\n\n"
        f"{parsed.get('resume_executif', '')}\n\n"
        f"## 🔍 Constats ({len(findings)})\n\n"
        f"{findings_section or '*Aucun constat*'}\n\n"
        f"## ✅ Recommandations ({len(recos)})\n\n"
        f"{recos_section or '*Aucune recommandation*'}\n"
    )


@router.post("/audit/{mission_id}/generate-report", dependencies=[Depends(get_current_user)])
async def generate_report(mission_id: str, response: Response, user: UserContext = Depends(get_current_user)):
    async with SessionLocal() as s:
        mission = await _mission_with_poles(s, mission_id, user.sub)
        if mission is None:
            raise HTTPException(status_code=404, detail="Mission introuvable")
        mu = _uuid(mission_id)
        docs = (await s.execute(
            select(AuditDocuments).where(and_(
                AuditDocuments.mission_id == mu, AuditDocuments.user_id == user.sub))
        )).scalars().all()
        if not docs:
            raise HTTPException(status_code=422, detail="Aucun document à analyser")

        preset = await resolve_llm_config(LlmContext(pole_id=mission["poleId"]))

        docs_context = "\n\n".join(
            f"=== {d.nom} ({d.type}) ===\n{d.contenu or '(contenu vide)'}" for d in docs
        )
        desc = f" ({mission['description']})" if mission.get("description") else ""
        prompt = f"""Tu es un expert en audit. Analyse les documents suivants issus de la mission d'audit "{mission['titre']}"{desc}.

DOCUMENTS :
{docs_context}

Retourne UNIQUEMENT du JSON valide avec cette structure exacte :
{{
  "resume_executif": "Résumé exécutif de 2-3 paragraphes en français couvrant les points clés, risques principaux et état général.",
  "findings": [
    {{ "categorie": "Sécurité|Conformité|Performance|Processus|Finance|Autre", "severite": "faible|moyen|critique", "description": "Description précise du constat", "source": "Nom du document source" }}
  ],
  "recommandations": [
    {{ "priorite": "haute|moyenne|faible", "action": "Action concrète à mener", "statut": "ouvert" }}
  ]
}}

Règles :
- findings : minimum 3, maximum 20
- recommandations : minimum 2, maximum 15
- severite doit être exactement "faible", "moyen" ou "critique"
- priorite doit être exactement "haute", "moyenne" ou "faible"
- Réponds uniquement en JSON, sans texte avant ou après"""

        try:
            text = await generate_text(
                prompt=prompt,
                provider=preset.provider if preset else None,
                model=preset.model if preset else None,
                max_tokens=3000,
            )
            match = re.search(r"\{[\s\S]*\}", text)
            if not match:
                raise ValueError("Pas de JSON dans la réponse LLM")
            parsed = json.loads(match.group(0))
        except Exception as err:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"Erreur LLM : {err}")

        # Supprimer anciens findings/recommandations de cette mission
        await s.execute(sa_delete(AuditFindings).where(and_(
            AuditFindings.mission_id == mu, AuditFindings.user_id == user.sub)))
        await s.execute(sa_delete(AuditRecommendations).where(and_(
            AuditRecommendations.mission_id == mu, AuditRecommendations.user_id == user.sub)))

        saved_findings = []
        for f in (parsed.get("findings") or []):
            sev = f.get("severite")
            obj = AuditFindings(
                mission_id=mu, user_id=user.sub,
                categorie=str(f.get("categorie") or "Autre")[:100],
                severite=sev if sev in _SEVERITE else "faible",
                description=str(f.get("description") or ""),
                source=str(f.get("source") or ""),
            )
            s.add(obj)
            saved_findings.append(obj)

        saved_recos = []
        for r in (parsed.get("recommandations") or []):
            prio, stat = r.get("priorite"), r.get("statut")
            obj = AuditRecommendations(
                mission_id=mu, user_id=user.sub,
                priorite=prio if prio in _PRIORITE else "moyenne",
                action=str(r.get("action") or ""),
                statut=stat if stat in _STATUT else "ouvert",
            )
            s.add(obj)
            saved_recos.append(obj)
        await s.flush()

        titre = f"Rapport d'audit — {mission['titre']} — {fr_date(datetime.utcnow())}"
        contenu = _build_report_markdown(mission["titre"], parsed, saved_findings, saved_recos)
        rap = Rapports(user_id=user.sub, mission_id=mu, titre=titre, contenu=contenu,
                       type="audit", periode=fr_date(datetime.utcnow()))
        s.add(rap)
        await s.commit()
        await s.refresh(rap)
        # Re-sélection ordonnée pour des createdAt peuplés (parité .returning() du Bun).
        fresh_findings = (await s.execute(
            select(AuditFindings).where(and_(
                AuditFindings.mission_id == mu, AuditFindings.user_id == user.sub))
            .order_by(AuditFindings.created_at)
        )).scalars().all()
        fresh_recos = (await s.execute(
            select(AuditRecommendations).where(and_(
                AuditRecommendations.mission_id == mu, AuditRecommendations.user_id == user.sub))
            .order_by(AuditRecommendations.created_at)
        )).scalars().all()
        result = {
            "rapport": rapport(rap),
            "findings": [audit_finding(f) for f in fresh_findings],
            "recommandations": [audit_recommendation(r) for r in fresh_recos],
        }
    response.status_code = 201
    return result


@router.get("/audit/{mission_id}/rapport", dependencies=[Depends(get_current_user)])
async def get_rapport(mission_id: str, user: UserContext = Depends(get_current_user)):
    mu = _uuid(mission_id)
    async with SessionLocal() as s:
        mission = (await s.execute(
            select(AuditMissions).where(and_(AuditMissions.id == mu, AuditMissions.user_id == user.sub))
        )).scalar_one_or_none() if mu else None
        if mission is None:
            raise HTTPException(status_code=404, detail="Mission introuvable")
        rap = (await s.execute(
            select(Rapports).where(and_(Rapports.mission_id == mu, Rapports.user_id == user.sub))
            .order_by(desc(Rapports.created_at)).limit(1)
        )).scalar_one_or_none()
        if rap is None:
            return None
        findings = (await s.execute(
            select(AuditFindings).where(and_(
                AuditFindings.mission_id == mu, AuditFindings.user_id == user.sub))
            .order_by(AuditFindings.created_at)
        )).scalars().all()
        recos = (await s.execute(
            select(AuditRecommendations).where(and_(
                AuditRecommendations.mission_id == mu, AuditRecommendations.user_id == user.sub))
            .order_by(AuditRecommendations.created_at)
        )).scalars().all()
    return {
        "rapport": rapport(rap),
        "findings": [audit_finding(f) for f in findings],
        "recommandations": [audit_recommendation(r) for r in recos],
    }
