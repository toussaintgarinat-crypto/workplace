"""Router relances — emails de recouvrement des impayés (S22).

- `GET  /relances/impayes/apercu`   → dry-run : qui serait relancé (rien envoyé).
- `POST /relances/impayes/executer` → envoie les relances dues + journalise (anti-doublon).
- `GET  /relances/journal`          → historique des relances envoyées.
- `POST /facturation/{id}/envoyer`  → envoie la facture au client par email + statut `envoyée`
  (démarre l'horloge des relances). Monté `/api` comme les autres routers.
"""

from __future__ import annotations

import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, select

from app import email as email_mod
from app import relances as relances_mod
from app.auth import UserContext, get_current_user
from app.db import SessionLocal
from app.models import FacturesDocs
from app.serde import facture_doc

router = APIRouter()


def _uuid(v: str):
    import uuid as _u
    try:
        return _u.UUID(v)
    except (ValueError, TypeError):
        return None


@router.get("/relances/impayes/apercu", dependencies=[Depends(get_current_user)])
async def apercu(user: UserContext = Depends(get_current_user)):
    return await relances_mod.apercu(user.sub)


@router.post("/relances/impayes/executer", dependencies=[Depends(get_current_user)])
async def executer(user: UserContext = Depends(get_current_user)):
    return await relances_mod.executer(user.sub)


@router.get("/relances/journal", dependencies=[Depends(get_current_user)])
async def journal():
    return {"relances": relances_mod.journal_lister()}


@router.post("/facturation/{did}/envoyer", dependencies=[Depends(get_current_user)])
async def envoyer_facture(did: str, user: UserContext = Depends(get_current_user)):
    """Envoie la facture au client par email et la passe `envoyée`.

    Renseigne l'émission (aujourd'hui) et, à défaut, l'échéance (+30 j) — pour que les
    relances aient une horloge. Idempotent côté email : renvoyable, mais re-notifie.
    """
    duid = _uuid(did)
    async with SessionLocal() as s:
        doc = (await s.execute(
            select(FacturesDocs).where(and_(FacturesDocs.id == duid, FacturesDocs.user_id == user.sub))
        )).scalar_one_or_none() if duid else None
        if doc is None:
            raise HTTPException(status_code=404, detail="Facture introuvable")
        if not (doc.client_email or "").strip():
            raise HTTPException(status_code=422, detail="La facture n'a pas d'email client.")
        today = datetime.date.today()
        if not (doc.date_emission or "").strip():
            doc.date_emission = today.isoformat()
        if not (doc.date_echeance or "").strip():
            doc.date_echeance = (today + datetime.timedelta(days=30)).isoformat()
        if doc.statut in ("brouillon", None):
            doc.statut = "envoyée"
        doc.updated_at = datetime.datetime.utcnow()
        client, numero, ttc, email, ech = (
            doc.client_nom, doc.numero, doc.total_ttc or 0.0, doc.client_email, doc.date_echeance)
        await s.commit()
        await s.refresh(doc)
        resultat = facture_doc(doc)

    sujet, html = email_mod.template_facture_emise(
        client=client, numero=numero, montant_ttc=ttc, echeance=ech)
    await email_mod.send(email, sujet, html)
    return {"ok": True, "envoye_a": email, **resultat}
