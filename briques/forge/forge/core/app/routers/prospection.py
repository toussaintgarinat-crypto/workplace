"""Router prospection. Portage de routes/prospection.ts (S131). Monté /api, protégé.

Analyse de cible B2B + génération d'email de prospection via la gateway LLM
(remplace `generateText` du Vercel AI SDK, cohérent décision S128).
"""

from __future__ import annotations

import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.auth import get_current_user
from app.llm import generate_text

router = APIRouter()


class AnalyzeBody(BaseModel):
    entreprise: str = Field(min_length=2)
    secteur: str | None = None
    url: str | None = None
    contact: str | None = None


@router.post("/prospection/analyze", dependencies=[Depends(get_current_user)])
async def analyze(body: AnalyzeBody):
    prompt = (
        "Tu es un expert en prospection B2B. Analyse cette cible de prospection :\n\n"
        f"Entreprise : {body.entreprise}\n"
        f"Secteur : {body.secteur or 'non précisé'}\n"
        f"URL : {body.url or 'non précisée'}\n"
        f"Contact : {body.contact or 'non précisé'}\n\n"
        "Génère :\n"
        "1. **Profil de la cible** — description, besoins supposés, taille estimée\n"
        "2. **Angle d'approche** — comment adresser cette entreprise\n"
        "3. **Email de prospection** — objet + corps personnalisé\n"
        "4. **Points de douleur** — 3 problèmes que tu peux résoudre\n"
        "5. **Score d'intérêt** — note /10 avec justification\n\n"
        "Réponds en français."
    )
    text = await generate_text(prompt=prompt)
    return {"entreprise": body.entreprise, "analyse": text,
            "generatedAt": datetime.datetime.utcnow().isoformat() + "Z"}


class EmailBody(BaseModel):
    entreprise: str
    contact: str | None = None
    contexte: str | None = None
    produit: str | None = None


@router.post("/prospection/email", dependencies=[Depends(get_current_user)])
async def email(body: EmailBody):
    a_lattention = f", à l'attention de {body.contact}" if body.contact else ""
    offre = f"Notre offre : {body.produit}" if body.produit else ""
    contexte = f"Contexte : {body.contexte}" if body.contexte else ""
    prompt = (
        f"Rédige un email de prospection B2B pour {body.entreprise}{a_lattention}.\n"
        f"{offre}\n"
        f"{contexte}\n\n"
        "L'email doit être :\n"
        "- Personnalisé et non générique\n"
        "- Court (150-200 mots max)\n"
        "- Avec un objet percutant\n"
        "- Avec un CTA clair\n"
        "- En français\n\n"
        "Format : OBJET: ...\n\n[corps de l'email]"
    )
    text = await generate_text(prompt=prompt)
    return {"entreprise": body.entreprise, "email": text}
