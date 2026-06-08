"""Router content-agent. Portage de routes/content-agent.ts (S129). Monté /api, protégé.

Génère du contenu marketing (article/post/tweet/email/landing/newsletter) via la gateway.
"""

from __future__ import annotations

import datetime
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.auth import get_current_user
from app.llm import generate_text

router = APIRouter()

_LONGUEUR_MAP = {"court": "300-500 mots", "moyen": "800-1200 mots", "long": "2000-3000 mots"}


class GenerateBody(BaseModel):
    sujet: str = Field(min_length=3)
    type: Literal["article", "post_linkedin", "tweet", "email", "landing_page", "newsletter"] | None = None
    ton: str | None = None
    longueur: Literal["court", "moyen", "long"] | None = None
    motsCles: list[str] | None = None


@router.post("/content-agent/generate", dependencies=[Depends(get_current_user)])
async def generate(body: GenerateBody):
    type_ = body.type or "article"
    ton = body.ton or "professionnel et engageant"
    longueur = body.longueur or "moyen"
    mots_cles = ", ".join(body.motsCles) if body.motsCles else ""

    extra = ""
    if type_ == "article":
        extra = "- Inclus un titre accrocheur, une introduction, des sous-titres H2, une conclusion et un CTA"
    elif type_ == "post_linkedin":
        extra = "- Commence par une phrase d'accroche, utilise des émojis avec modération, inclus des hashtags"
    elif type_ == "tweet":
        extra = "- Maximum 280 caractères, percutant, avec 2-3 hashtags"

    prompt = (
        f'Tu es un expert en création de contenu marketing. Génère un {type_} sur : "{body.sujet}".\n\n'
        "Contraintes :\n"
        f"- Ton : {ton}\n"
        f"- Longueur : {_LONGUEUR_MAP[longueur]}\n"
        f"- Mots-clés à intégrer : {mots_cles or 'à ta discrétion'}\n"
        "- Langue : français\n"
        f"{extra}\n\n"
        "Génère directement le contenu, sans préambule."
    )
    text = await generate_text(prompt=prompt)
    return {"sujet": body.sujet, "type": type_, "contenu": text,
            "generatedAt": datetime.datetime.utcnow().isoformat() + "Z"}
