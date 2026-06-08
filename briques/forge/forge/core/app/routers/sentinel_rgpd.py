"""Router sentinel-rgpd (audit conformité RGPD). Portage de routes/sentinel-rgpd.ts (S135).

Monté /api, protégé. Checklist RGPD figée (10 points / articles) + audit LLM : à
partir d'une checklist cochée, calcule un score de conformité et génère une analyse
(risques, actions correctives, délais) via la gateway.
"""

from __future__ import annotations

import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.auth import get_current_user
from app.llm import generate_text
from app.serde import iso

router = APIRouter()

RGPD_CHECKLIST: list[dict] = [
    {"id": "registre", "label": "Registre des traitements", "articles": ["Art. 30"]},
    {"id": "consentement", "label": "Gestion du consentement", "articles": ["Art. 6", "Art. 7"]},
    {"id": "droit_acces", "label": "Droit d'accès et portabilité", "articles": ["Art. 15", "Art. 20"]},
    {"id": "droit_effacement", "label": "Droit à l'effacement", "articles": ["Art. 17"]},
    {"id": "notification_violation", "label": "Procédure de notification de violation", "articles": ["Art. 33"]},
    {"id": "dpia", "label": "Analyse d'impact (DPIA)", "articles": ["Art. 35"]},
    {"id": "dpo", "label": "Désignation DPO si requis", "articles": ["Art. 37"]},
    {"id": "transferts", "label": "Transferts hors UE encadrés", "articles": ["Art. 44-49"]},
    {"id": "minimisation", "label": "Minimisation des données", "articles": ["Art. 5"]},
    {"id": "duree_conservation", "label": "Durées de conservation définies", "articles": ["Art. 5"]},
]


# Capacités RGPD **réellement appliquées par Forge** (S18-8) — adossées à des routes
# qui agissent sur les données, pas à une case cochée. Sépare la conformité *prouvée
# par le système* de la conformité *organisationnelle* (déclarative).
CAPACITES_FORGE: dict[str, dict] = {
    "droit_acces": {"prouve": True, "preuve": "GET /api/rgpd/export", "depuis": "S18-6"},
    "droit_effacement": {"prouve": True, "preuve": "POST /api/rgpd/effacer (Postgres+Qdrant+Mémoire)", "depuis": "S18-5"},
    "duree_conservation": {"prouve": True, "preuve": "docs/sprints S18 — table de rétention", "depuis": "S18-7"},
    "minimisation": {"prouve": True, "preuve": "scoping org imposé par require_org (Chantier 1)", "depuis": "S18-3"},
    # Organisationnels (non automatisables côté code) → restent déclaratifs.
    "registre": {"prouve": False, "preuve": "organisationnel"},
    "consentement": {"prouve": False, "preuve": "organisationnel"},
    "notification_violation": {"prouve": False, "preuve": "organisationnel / procédure"},
    "dpia": {"prouve": False, "preuve": "organisationnel"},
    "dpo": {"prouve": False, "preuve": "organisationnel"},
    "transferts": {"prouve": False, "preuve": "organisationnel / infra"},
}


@router.get("/sentinel-rgpd/checklist", dependencies=[Depends(get_current_user)])
async def get_checklist():
    return RGPD_CHECKLIST


@router.get("/sentinel-rgpd/capacites-forge", dependencies=[Depends(get_current_user)])
async def capacites_forge():
    """Posture RGPD **prouvée** de Forge (S18-8) : ce que le système applique vraiment.

    Le score ici ne reflète pas une déclaration mais une capacité adossée à une route /
    un mécanisme réel. Les points organisationnels (registre, DPO…) restent hors code.
    """
    points = [
        {**item, **CAPACITES_FORGE.get(item["id"], {"prouve": False})}
        for item in RGPD_CHECKLIST
    ]
    prouves = sum(1 for p in points if p.get("prouve"))
    return {
        "points": points,
        "scoreSysteme": round((prouves / len(RGPD_CHECKLIST)) * 100),
        "prouves": prouves,
        "total": len(RGPD_CHECKLIST),
        "note": "Conformité prouvée par le système (routes réelles). Les points "
                "organisationnels (registre, consentement, DPO, transferts) restent déclaratifs.",
    }


class AuditBody(BaseModel):
    entreprise: str = Field(min_length=2)
    secteur: str | None = None
    description: str | None = None
    checklist: dict[str, bool] | None = None


@router.post("/sentinel-rgpd/audit", dependencies=[Depends(get_current_user)])
async def run_audit(body: AuditBody):
    checklist_status = [
        {**item, "conforme": (body.checklist or {}).get(item["id"], False)}
        for item in RGPD_CHECKLIST
    ]
    non_conformes = [i["label"] for i in checklist_status if not i["conforme"]]

    prompt = (
        "Tu es un expert RGPD/DPO. Effectue un audit de conformité RGPD pour :\n\n"
        f"Entreprise : {body.entreprise}\n"
        f"Secteur : {body.secteur or 'non précisé'}\n"
        f"Description : {body.description or 'non précisée'}\n\n"
        "Points de non-conformité identifiés :\n"
        + "\n".join(f"- {nc}" for nc in non_conformes)
        + "\n\nPour chaque point non conforme, fournis :\n"
        "1. Le risque associé\n"
        "2. Les actions correctives prioritaires\n"
        "3. Un délai recommandé pour mise en conformité\n\n"
        "Calcule aussi un score de conformité sur 100 et donne les 3 actions les plus urgentes.\n\n"
        "Réponds en français de manière structurée."
    )
    text = await generate_text(prompt=prompt)

    conformes = sum(1 for i in checklist_status if i["conforme"])
    score = round((conformes / len(RGPD_CHECKLIST)) * 100)

    return {
        "entreprise": body.entreprise,
        "score": score,
        "checklist": checklist_status,
        "analyse": text,
        "generatedAt": iso(datetime.datetime.utcnow()),
    }
