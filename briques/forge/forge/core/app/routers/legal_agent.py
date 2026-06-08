"""Router legal-agent. Portage de routes/legal-agent.ts (S129). Monté /api, protégé.

Génère/analyse des documents juridiques (droit français) via la gateway.
"""

from __future__ import annotations

import datetime
import json
from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.auth import get_current_user
from app.llm import generate_text

router = APIRouter()

TEMPLATES = {
    "nda": "Accord de Non-Divulgation (NDA)",
    "cgv": "Conditions Générales de Vente (CGV)",
    "cgu": "Conditions Générales d'Utilisation (CGU)",
    "contrat_prestation": "Contrat de Prestation de Services",
    "contrat_travail": "Contrat de Travail",
    "politique_confidentialite": "Politique de Confidentialité RGPD",
}


@router.get("/legal-agent/templates", dependencies=[Depends(get_current_user)])
async def templates():
    return [{"key": k, "label": v} for k, v in TEMPLATES.items()]


class GenerateBody(BaseModel):
    type: Literal["nda", "cgv", "cgu", "contrat_prestation", "contrat_travail", "politique_confidentialite"]
    parties: dict[str, str]
    options: dict[str, Any] | None = None


@router.post("/legal-agent/generate", dependencies=[Depends(get_current_user)])
async def generate(body: GenerateBody):
    template = TEMPLATES[body.type]
    parties_str = "\n".join(f"{k}: {v}" for k, v in body.parties.items())
    prompt = (
        f"Tu es un juriste expert en droit français. Génère un document juridique : {template}\n\n"
        f"Parties impliquées :\n{parties_str}\n\n"
        f"Options : {json.dumps(body.options or {})}\n\n"
        "Le document doit :\n"
        "- Être conforme au droit français en vigueur\n"
        "- Inclure toutes les clauses essentielles\n"
        "- Être rédigé en français juridique clair\n"
        "- Inclure les sections : préambule, définitions, obligations, durée, résiliation, loi applicable\n"
        "- Avoir des espaces pour les signatures\n\n"
        "IMPORTANT : Ceci est un modèle à adapter par un professionnel du droit."
    )
    text = await generate_text(prompt=prompt)
    return {"type": body.type, "template": template, "document": text,
            "generatedAt": datetime.datetime.utcnow().isoformat() + "Z"}


class AnalyzeBody(BaseModel):
    contenu: str = Field(min_length=50)
    question: str | None = None


@router.post("/legal-agent/analyze", dependencies=[Depends(get_current_user)])
async def analyze(body: AnalyzeBody):
    q = (f"Question spécifique : {body.question}" if body.question
         else "Identifie les points clés, les risques potentiels et les clauses manquantes.")
    prompt = (
        "Tu es un juriste expert. Analyse ce document juridique :\n\n"
        f"{body.contenu[:3000]}\n\n"
        f"{q}\n\n"
        "Réponds en français de manière structurée."
    )
    text = await generate_text(prompt=prompt)
    return {"analyse": text}
