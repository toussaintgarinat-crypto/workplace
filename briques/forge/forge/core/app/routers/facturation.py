"""Router facturation. Portage de routes/facturation.ts (S131). Monté /api, protégé.

Factures & devis : numérotation auto (FACT/DEVIS-AAAA-NNNN), calcul des totaux
HT/TVA/TTC, transformation devis→facture. Les lignes sont stockées en JSON-string
(parité Drizzle) ; la création renvoie les lignes désérialisées comme le Bun.
"""

from __future__ import annotations

import datetime
import json
import math
import uuid as uuidlib

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import and_, desc, func, select, update
from sqlalchemy import delete as sa_delete

from app.auth import UserContext, get_current_user
from app.db import SessionLocal
from app.models import FacturesDocs
from app.serde import facture_doc

router = APIRouter()


def _uuid(v: str | None):
    try:
        return uuidlib.UUID(v)
    except (ValueError, TypeError):
        return None


def _round2(x: float) -> float:
    """Math.round(x*100)/100 — arrondi half-up à 2 décimales (parité JS)."""
    return math.floor(x * 100 + 0.5) / 100


def _calc_totaux(lignes: list[dict], tva_taux: float) -> tuple[float, float, float]:
    total_ht = sum(l.get("quantite", 1) * l.get("prixUnitaire", 0) for l in lignes)
    total_tva = sum(
        l.get("quantite", 1) * l.get("prixUnitaire", 0) * ((l.get("tva", tva_taux)) / 100)
        for l in lignes
    )
    return _round2(total_ht), _round2(total_tva), _round2(total_ht + total_tva)


async def _next_numero(s, type_: str, user_id: str) -> str:
    year = datetime.datetime.utcnow().year
    prefix = "DEVIS" if type_ == "devis" else "FACT"
    count = (await s.execute(
        select(func.count()).select_from(FacturesDocs)
        .where(and_(FacturesDocs.user_id == user_id, FacturesDocs.type == type_))
    )).scalar_one()
    n = (count or 0) + 1
    return f"{prefix}-{year}-{n:04d}"


class Ligne(BaseModel):
    description: str
    quantite: float = 1
    prixUnitaire: float = 0
    tva: float = 20


class DocBody(BaseModel):
    type: str = "facture"
    clientNom: str = Field(min_length=1)
    clientEmail: str | None = None
    clientAdresse: str | None = None
    lignes: list[Ligne] = Field(default_factory=list)
    tvaTaux: float = 20
    notes: str | None = None
    conditions: str | None = None
    dateEmission: str | None = None
    dateEcheance: str | None = None
    poleId: str | None = None


@router.get("/facturation", dependencies=[Depends(get_current_user)])
async def list_docs(type: str | None = None, user: UserContext = Depends(get_current_user)):
    conds = [FacturesDocs.user_id == user.sub]
    if type:
        conds.append(FacturesDocs.type == type)
    async with SessionLocal() as s:
        docs = (await s.execute(
            select(FacturesDocs).where(and_(*conds)).order_by(desc(FacturesDocs.created_at))
        )).scalars().all()
    stats = {"caTotal": 0.0, "caEnAttente": 0.0, "nbFactures": 0, "nbDevis": 0}
    for d in docs:
        ttc = d.total_ttc or 0
        if d.statut == "payée":
            stats["caTotal"] += ttc
        if d.statut in ("envoyée", "envoyé"):
            stats["caEnAttente"] += ttc
        if d.type == "facture":
            stats["nbFactures"] += 1
        if d.type == "devis":
            stats["nbDevis"] += 1
    return {"items": [facture_doc(d) for d in docs], "stats": stats}


@router.get("/facturation/{did}", dependencies=[Depends(get_current_user)])
async def get_doc(did: str, user: UserContext = Depends(get_current_user)):
    duid = _uuid(did)
    async with SessionLocal() as s:
        doc = (await s.execute(
            select(FacturesDocs).where(and_(FacturesDocs.id == duid, FacturesDocs.user_id == user.sub))
        )).scalar_one_or_none() if duid else None
    if doc is None:
        raise HTTPException(status_code=404, detail="Not found")
    return facture_doc(doc)


@router.post("/facturation", dependencies=[Depends(get_current_user)])
async def create_doc(body: DocBody, user: UserContext = Depends(get_current_user)):
    lignes_arr = [l.model_dump() for l in body.lignes]
    total_ht, total_tva, total_ttc = _calc_totaux(lignes_arr, body.tvaTaux)
    async with SessionLocal() as s:
        numero = await _next_numero(s, body.type, user.sub)
        doc = FacturesDocs(
            user_id=user.sub, pole_id=_uuid(body.poleId), numero=numero, type=body.type,
            client_nom=body.clientNom, client_email=body.clientEmail or "",
            client_adresse=body.clientAdresse or "", lignes=json.dumps(lignes_arr),
            total_ht=total_ht, total_tva=total_tva, total_ttc=total_ttc, tva_taux=body.tvaTaux,
            notes=body.notes or "", conditions=body.conditions or "Paiement à 30 jours",
            date_emission=body.dateEmission or "", date_echeance=body.dateEcheance or "",
            statut="brouillon",
        )
        s.add(doc)
        await s.commit()
        await s.refresh(doc)
    return JSONResponse(status_code=201, content={**facture_doc(doc), "lignes": lignes_arr})


# Mapping champ Drizzle (camelCase) → colonne SQL pour le PATCH "libre".
_PATCH_COLMAP = {
    "type": "type", "clientNom": "client_nom", "clientEmail": "client_email",
    "clientAdresse": "client_adresse", "lignes": "lignes", "totalHt": "total_ht",
    "totalTva": "total_tva", "totalTtc": "total_ttc", "tvaRaux": "tva_taux",
    "statut": "statut", "notes": "notes", "conditions": "conditions",
    "dateEmission": "date_emission", "dateEcheance": "date_echeance",
    "datePaiement": "date_paiement",
}


@router.patch("/facturation/{did}", dependencies=[Depends(get_current_user)])
async def update_doc(did: str, request: Request, user: UserContext = Depends(get_current_user)):
    duid = _uuid(did)
    body = await request.json()
    if body.get("lignes"):
        total_ht, total_tva, total_ttc = _calc_totaux(body["lignes"], body.get("tvaTaux", 20))
        body["totalHt"], body["totalTva"], body["totalTtc"] = total_ht, total_tva, total_ttc
        body["lignes"] = json.dumps(body["lignes"])
    cols = {_PATCH_COLMAP[k]: v for k, v in body.items() if k in _PATCH_COLMAP}
    cols["updated_at"] = datetime.datetime.utcnow()
    async with SessionLocal() as s:
        doc = None
        if duid:
            await s.execute(
                update(FacturesDocs).where(and_(
                    FacturesDocs.id == duid, FacturesDocs.user_id == user.sub)).values(**cols)
            )
            await s.commit()
            doc = (await s.execute(
                select(FacturesDocs).where(and_(FacturesDocs.id == duid, FacturesDocs.user_id == user.sub))
            )).scalar_one_or_none()
    return facture_doc(doc) if doc else None


@router.delete("/facturation/{did}", dependencies=[Depends(get_current_user)])
async def delete_doc(did: str, user: UserContext = Depends(get_current_user)):
    duid = _uuid(did)
    async with SessionLocal() as s:
        if duid:
            await s.execute(sa_delete(FacturesDocs).where(and_(
                FacturesDocs.id == duid, FacturesDocs.user_id == user.sub)))
            await s.commit()
    return {"ok": True}


@router.post("/facturation/{did}/transformer", dependencies=[Depends(get_current_user)])
async def transformer(did: str, user: UserContext = Depends(get_current_user)):
    duid = _uuid(did)
    async with SessionLocal() as s:
        devis = (await s.execute(
            select(FacturesDocs).where(and_(FacturesDocs.id == duid, FacturesDocs.user_id == user.sub))
        )).scalar_one_or_none() if duid else None
        if devis is None or devis.type != "devis":
            raise HTTPException(status_code=400, detail="Not a devis")
        lignes = json.loads(devis.lignes or "[]")
        total_ht, total_tva, total_ttc = _calc_totaux(lignes, devis.tva_taux or 20)
        numero = await _next_numero(s, "facture", user.sub)
        facture = FacturesDocs(
            user_id=devis.user_id, pole_id=devis.pole_id, numero=numero, type="facture",
            client_nom=devis.client_nom, client_email=devis.client_email,
            client_adresse=devis.client_adresse, lignes=devis.lignes,
            total_ht=total_ht, total_tva=total_tva, total_ttc=total_ttc, tva_taux=devis.tva_taux,
            statut="brouillon", notes=devis.notes, conditions=devis.conditions,
            date_emission=devis.date_emission, date_echeance=devis.date_echeance,
            date_paiement=devis.date_paiement,
        )
        s.add(facture)
        await s.execute(
            update(FacturesDocs).where(FacturesDocs.id == duid)
            .values(statut="transformé", updated_at=datetime.datetime.utcnow())
        )
        await s.commit()
        await s.refresh(facture)
    return JSONResponse(status_code=201, content=facture_doc(facture))
