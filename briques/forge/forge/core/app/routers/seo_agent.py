"""Router seo-agent. Portage de routes/seo-agent.ts (S129). Monté /api, protégé.

Analyse SEO d'une URL + génération de mots-clés, via la gateway.
"""

from __future__ import annotations

import datetime
import json

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.auth import get_current_user
from app.llm import generate_text

router = APIRouter()


class AnalyzeBody(BaseModel):
    url: str
    poleId: str | None = None


@router.post("/seo-agent/analyze", dependencies=[Depends(get_current_user)])
async def analyze(body: AnalyzeBody):
    prompt = (
        f"Tu es un expert SEO. Effectue une analyse SEO complète de ce site : {body.url}\n\n"
        "Analyse les points suivants et donne des recommandations concrètes :\n"
        "1. **Title et méta-description** — pertinence, longueur, mots-clés\n"
        "2. **Structure du contenu** — H1/H2/H3, lisibilité\n"
        "3. **Mots-clés** — densité, placement, opportunités\n"
        "4. **Performance** — Core Web Vitals, vitesse de chargement estimée\n"
        "5. **Mobile** — compatibilité mobile\n"
        "6. **Backlinks** — profil de liens supposé\n"
        "7. **Score global** — note sur 100 avec justification\n\n"
        "Réponds en français avec des émojis pour chaque section. Sois précis et actionnable."
    )
    text = await generate_text(prompt=prompt)
    return {"url": body.url, "analyse": text,
            "generatedAt": datetime.datetime.utcnow().isoformat() + "Z"}


class KeywordsBody(BaseModel):
    sujet: str = Field(min_length=3)
    langue: str | None = None


@router.post("/seo-agent/keywords", dependencies=[Depends(get_current_user)])
async def keywords(body: KeywordsBody):
    langue = body.langue or "fr"
    prompt = (
        f'Génère une liste de 20 mots-clés SEO pertinents pour le sujet : "{body.sujet}" en langue {langue}.\n'
        "Pour chaque mot-clé, indique : volume estimé (faible/moyen/élevé), intention "
        "(info/transactionnel/navigational), difficulté (1-10).\n"
        "Format : JSON array avec { keyword, volume, intention, difficulte }"
    )
    text = await generate_text(prompt=prompt)
    try:
        kw = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        kw = [{"keyword": body.sujet, "volume": "moyen", "intention": "info", "difficulte": 5}]
    return {"sujet": body.sujet, "keywords": kw}
