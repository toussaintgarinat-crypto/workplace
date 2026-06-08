"""Router conseil. Portage de routes/conseil.ts (S129). Monté /api/conseil, protégé.

Soumet un même prompt à plusieurs modèles EN PARALLÈLE (mode « Conseil LLM » d'IPCRA).
Chaque voix passe par la gateway ; un échec est avalé par voix (parité Promise.allSettled).
"""

from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth import get_current_user
from app.llm import generate_text

router = APIRouter()


class Voix(BaseModel):
    provider: str
    model: str


class ConseilBody(BaseModel):
    prompt: str
    system: str | None = None
    providers: list[Voix] = []


async def _ask(v: Voix, prompt: str, system: str | None) -> dict:
    t0 = time.time()
    try:
        text = await generate_text(
            prompt=prompt,
            system=system or "Réponds de façon concise et structurée.",
            provider=v.provider,
            model=v.model,
            max_tokens=800,
        )
        return {"provider": v.provider, "model": v.model, "answer": text,
                "duree_ms": int((time.time() - t0) * 1000), "error": None}
    except Exception as e:  # noqa: BLE001 — parité : échec par voix capturé
        return {"provider": v.provider, "model": v.model, "answer": "",
                "duree_ms": int((time.time() - t0) * 1000), "error": str(e) or "Erreur"}


@router.post("", dependencies=[Depends(get_current_user)])
async def conseil(body: ConseilBody):
    if not body.prompt or not body.providers:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="prompt et providers requis")
    voix = body.providers[:5]  # cap à 5 modèles
    responses = await asyncio.gather(*[_ask(v, body.prompt, body.system) for v in voix])
    return {"responses": responses}
