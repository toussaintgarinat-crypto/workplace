"""Router entretiens (S228) — entretien guidé IA, greffé sur Forge à côté de Ventures.

Squelette de sections FIXE (garde-fou) : deux familles jamais mélangées dans le
traitement d'une réponse.
- « qualitatif » : les 9 catégories du profil_entreprise (S227) — extraction LLM
  ciblée, patch direct (fusion non destructive, jamais d'écrasement).
- « processus » : les 4 zones de la vision (Commercial/Production/Administratif/
  Communication) — accumulées en transcript brut, analysées par briques/audit
  (aucune écriture incrémentale là-bas, décision actée S228).

Dans chaque section, le LLM décide de la relance (réponse courte → question de
suivi ciblée) ; il ne quitte une section que si elle est jugée suffisamment
couverte. Pause/reprise obligatoire : l'état est persisté à chaque tour.
"""

from __future__ import annotations

import uuid as uuidlib
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, desc, select

from app.auth import UserContext, get_current_user
from app.db import SessionLocal
from app.models import Entretiens, Ventures
from app.serde import entretien

SECTIONS: list[dict] = [
    {"id": "qualitatif.organisation", "famille": "qualitatif", "categorie": "organisation",
     "premiere_question": "Comment votre entreprise est-elle organisée (statut juridique, effectif, structure) ?"},
    {"id": "qualitatif.activites", "famille": "qualitatif", "categorie": "activites",
     "premiere_question": "Quelles sont vos activités principales ?"},
    {"id": "qualitatif.clients", "famille": "qualitatif", "categorie": "clients",
     "premiere_question": "Qui sont vos clients types ?"},
    {"id": "qualitatif.fournisseurs", "famille": "qualitatif", "categorie": "fournisseurs",
     "premiere_question": "Quels sont vos principaux fournisseurs ou partenaires ?"},
    {"id": "qualitatif.outils_utilises", "famille": "qualitatif", "categorie": "outils_utilises",
     "premiere_question": "Quels outils ou logiciels utilisez-vous au quotidien ?"},
    {"id": "qualitatif.personnel", "famille": "qualitatif", "categorie": "personnel",
     "premiere_question": "Parlez-moi de votre équipe : effectif, rôles clés."},
    {"id": "qualitatif.contraintes", "famille": "qualitatif", "categorie": "contraintes",
     "premiere_question": "Quelles contraintes fortes pèsent sur votre activité (réglementaires, saisonnières...) ?"},
    {"id": "qualitatif.objectifs", "famille": "qualitatif", "categorie": "objectifs",
     "premiere_question": "Quels sont vos objectifs pour les 12 prochains mois ?"},
    {"id": "qualitatif.problemes_connus", "famille": "qualitatif", "categorie": "problemes_connus",
     "premiere_question": "Quels problèmes avez-vous déjà identifiés dans votre organisation ?"},
    {"id": "processus.commercial", "famille": "processus", "zone": "commercial",
     "premiere_question": "Comment arrive une demande client, de la prospection jusqu'au devis ?"},
    {"id": "processus.production", "famille": "processus", "zone": "production",
     "premiere_question": "Comment se déroule une intervention, du planning au compte rendu ?"},
    {"id": "processus.administratif", "famille": "processus", "zone": "administratif",
     "premiere_question": "Comment gérez-vous la facturation et les documents administratifs ?"},
    {"id": "processus.communication", "famille": "processus", "zone": "communication",
     "premiere_question": "Quels canaux utilisez-vous pour communiquer (email, téléphone, SMS, réseaux sociaux) ?"},
]

_PAR_ID = {s["id"]: s for s in SECTIONS}


def _section(section_id: str) -> dict | None:
    return _PAR_ID.get(section_id)


def _prochaine_section(couvertes: list[str]) -> dict | None:
    """Première section du squelette pas encore dans `couvertes`, ou None si complet."""
    deja = set(couvertes or ())
    for s in SECTIONS:
        if s["id"] not in deja:
            return s
    return None


router = APIRouter()


def _uuid(v: str | None):
    try:
        return uuidlib.UUID(v)
    except (ValueError, TypeError):
        return None


def _rappel(row) -> str | None:
    """Les 50 derniers caractères pertinents du transcript, ou None — jamais inventé."""
    if row.transcript:
        return row.transcript[-50:]
    return None


@router.post("/ventures/{vid}/entretien/demarrer", dependencies=[Depends(get_current_user)])
async def demarrer_entretien(vid: str, user: UserContext = Depends(get_current_user)):
    u = _uuid(vid)
    async with SessionLocal() as s:
        v = (await s.execute(
            select(Ventures).where(and_(Ventures.id == u, Ventures.owner_id == user.sub))
        )).scalar_one_or_none() if u else None
        if v is None:
            raise HTTPException(status_code=404, detail="Not found")

        existant = (await s.execute(
            select(Entretiens)
            .where(and_(Entretiens.venture_id == u, Entretiens.statut == "en_cours"))
            .order_by(desc(Entretiens.derniere_activite))
        )).scalar_one_or_none()

        if existant:
            section = _section(existant.section_courante) or SECTIONS[0]
            return {
                **entretien(existant),
                "question": f"On reprend où on s'était arrêté : {section['premiere_question']}",
                "rappel": _rappel(existant),
            }

        premiere = SECTIONS[0]
        now = datetime.now(timezone.utc)
        row = Entretiens(
            venture_id=u, section_courante=premiere["id"], sections_couvertes=[],
            transcript="", statut="en_cours", derniere_activite=now, created_at=now,
        )
        s.add(row)
        await s.flush()
        await s.commit()
        await s.refresh(row)
        return {**entretien(row), "question": premiere["premiere_question"], "rappel": None}
