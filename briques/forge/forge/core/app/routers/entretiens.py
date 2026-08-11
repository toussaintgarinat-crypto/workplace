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

import json
import logging
import uuid as uuidlib
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import and_, desc, select, update

from app.auth import UserContext, get_current_user
from app.config import settings
from app.db import SessionLocal
from app.llm import generate_text
from app.models import Entretiens, Ventures
from app.serde import entretien

logger = logging.getLogger(__name__)

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
            .limit(1)
        )).scalar_one_or_none()

        if existant:
            section = _section(existant.section_courante) or SECTIONS[0]
            return {
                **entretien(existant),
                "question": f"On reprend où on s'était arrêté : {section['premiere_question']}",
                "rappel": _rappel(existant),
            }

        premiere = SECTIONS[0]
        # `.replace(tzinfo=None)` OBLIGATOIRE (revue finale S228, Finding C2) :
        # `Entretiens.derniere_activite`/`created_at` sont des colonnes `DateTime` NAÏVES
        # (`timestamp without time zone`). asyncpg refuse d'y encoder un datetime aware
        # (« can't subtract offset-naive and offset-aware datetimes », remonté en
        # DataError) — invisible pour le filet de tests, qui n'a pas de vraie DB.
        # Convention du dépôt : cf. `agent_autonomy.py:148`.
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        row = Entretiens(
            venture_id=u, section_courante=premiere["id"], sections_couvertes=[],
            transcript="", statut="en_cours", derniere_activite=now, created_at=now,
        )
        s.add(row)
        await s.flush()
        await s.commit()
        await s.refresh(row)
        return {**entretien(row), "question": premiere["premiere_question"], "rappel": None}


def _fusionner_qualitatif(existant: dict | None, categorie: str, valeurs: list[str]) -> dict:
    """Fusion non destructive : ajoute les nouvelles valeurs à la liste existante de la
    catégorie, dé-doublonne, ne touche à AUCUNE autre catégorie."""
    base = dict(existant or {})
    deja = list(base.get(categorie) or [])
    for val in valeurs:
        if val and val not in deja:
            deja.append(val)
    base[categorie] = deja
    return base


_PROMPT_EXTRACTION = (
    "Tu extrais des informations d'entreprise depuis une réponse d'entretien.\n"
    "Catégorie : {categorie}\n"
    "Réponse de l'utilisateur : \"{message}\"\n\n"
    "Réponds UNIQUEMENT en JSON strict : {{\"valeurs\": [\"...\"]}} — une liste de faits "
    "courts et autonomes extraits de cette réponse. Liste vide si rien d'exploitable."
)

_PROMPT_DECISION_QUALITATIF = (
    "Tu mènes un entretien d'audit d'entreprise, catégorie « {categorie} ».\n"
    "Dernière réponse de l'utilisateur : \"{message}\"\n"
    "Ce qu'on sait déjà sur cette catégorie : {connu}\n\n"
    "Décide si cette catégorie est maintenant suffisamment couverte, ou s'il faut relancer "
    "avec une question de suivi CIBLÉE (une réponse courte appelle une relance précise).\n"
    "Réponds UNIQUEMENT en JSON strict : {{\"couverte\": true|false, \"question\": \"...\"|null}}."
)


class RepondreBody(BaseModel):
    message: str


@router.post("/ventures/{vid}/entretien/repondre", dependencies=[Depends(get_current_user)])
async def repondre_entretien(vid: str, body: RepondreBody, user: UserContext = Depends(get_current_user)):
    u = _uuid(vid)
    async with SessionLocal() as s:
        # Ownership vérifiée AVANT toute lecture d'Entretiens (Entretiens n'a pas de
        # owner_id) — même ordre que demarrer_entretien ci-dessus. Une venture
        # inexistante, une venture d'autrui, et une venture à soi sans entretien en
        # cours doivent tous porter le même detail générique : ne jamais laisser le
        # contenu de la réponse révéler à un appelant non autorisé si une venture
        # qu'il ne possède pas a une activité d'entretien en cours (revue post-Task 4).
        v = (await s.execute(
            select(Ventures).where(and_(Ventures.id == u, Ventures.owner_id == user.sub))
        )).scalar_one_or_none() if u else None
        if v is None:
            raise HTTPException(status_code=404, detail="Not found")

        row = (await s.execute(
            select(Entretiens).where(and_(Entretiens.venture_id == u, Entretiens.statut == "en_cours"))
            # `order_by` indispensable (revue finale S228, Finding I5) : c'était le seul
            # des 4 SELECT d'entretien de ce fichier à en manquer. Sans lui, si deux
            # lignes `en_cours` coexistent pour une venture, Postgres en choisit une
            # arbitrairement — `demarrer` pourrait reprendre l'une et `repondre` écrire
            # dans l'autre. Même classe de bug que le fix 7ed26b8, sur le 4e site oublié.
            .order_by(desc(Entretiens.derniere_activite))
            .limit(1)
        )).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="Not found")
        profil_courant = v.profil_entreprise

    # ── Fin de la session de LECTURE (revue finale S228, Finding I2) ─────────────
    # Tout ce qui suit fait des appels RÉSEAU longs : 2 appels LLM, puis jusqu'à 3 appels
    # HTTP dans `_cloturer` (30 s de timeout chacun, ~90 s au pire). Les tenir à
    # l'intérieur d'un `async with SessionLocal()` immobilisait une connexion et une
    # transaction ouvertes pendant toute cette durée. Motif déjà tranché en S227 :
    # `ventures.get_venture_dossier` ferme sa session AVANT de faire son fan-out HTTP.
    # Les écritures repartent plus bas dans une transaction courte et unique.
    section = _section(row.section_courante) or SECTIONS[0]
    # Naïf : colonnes `timestamp without time zone` (cf. Finding C2 dans demarrer_entretien).
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    extraction_echouee = False
    nouveau_profil = None

    if section["famille"] == "qualitatif":
        categorie = section["categorie"]
        connu = (profil_courant or {}).get(categorie) or []
        try:
            try:
                brut = await generate_text(
                    _PROMPT_EXTRACTION.format(categorie=categorie, message=body.message))
            except Exception as exc:  # réseau/timeout/quota/fournisseur — jamais un 500 ici
                logger.warning(
                    "[entretien:generate_text_echoue] venture=%s categorie=%s: %s",
                    vid, categorie, exc)
                brut = ""
            data = json.loads(brut)
            if not isinstance(data, dict):
                # JSON syntaxiquement valide mais pas un objet (ex. ["Lyon"], null,
                # 42) — même repli honnête qu'un JSONDecodeError, pas un .get() qui
                # planterait en AttributeError (revue post-Task 4).
                raise ValueError("réponse LLM n'est pas un objet JSON")
            valeurs = data.get("valeurs") or []
            if not isinstance(valeurs, list):
                raise ValueError("valeurs doit être une liste")
        except (json.JSONDecodeError, ValueError, TypeError):
            extraction_echouee = True
            valeurs = []
            logger.warning(
                "[entretien:extraction_echouee] venture=%s categorie=%s — tour conservé, "
                "fusion sautée pour ce tour", vid, categorie)

        if valeurs:
            # Calculé ici, PERSISTÉ plus bas dans la transaction d'écriture unique.
            nouveau_profil = _fusionner_qualitatif(profil_courant, categorie, valeurs)
            connu = nouveau_profil[categorie]

        try:
            decision_brut = await generate_text(
                _PROMPT_DECISION_QUALITATIF.format(categorie=categorie, message=body.message, connu=connu))
        except Exception as exc:
            logger.warning(
                "[entretien:generate_text_echoue] venture=%s section=%s: %s",
                vid, section["id"], exc)
            decision_brut = ""
    else:
        zone = section["zone"]
        row.transcript = (row.transcript or "") + f"\n\n## {zone}\n{body.message}"
        try:
            decision_brut = await generate_text(
                _PROMPT_DECISION_PROCESSUS.format(zone=zone, message=body.message))
        except Exception as exc:
            logger.warning(
                "[entretien:generate_text_echoue] venture=%s section=%s: %s",
                vid, section["id"], exc)
            decision_brut = ""

    try:
        decision = json.loads(decision_brut)
        if not isinstance(decision, dict):
            raise ValueError("réponse LLM n'est pas un objet JSON")
        couverte = bool(decision.get("couverte"))
        question_suivante = decision.get("question")
    except (json.JSONDecodeError, ValueError, TypeError):
        couverte = False
        question_suivante = "Peux-tu préciser ?"
        logger.warning(
            "[entretien:decision_echouee] venture=%s section=%s — repli question générique",
            vid, section["id"])

    audit_id = None
    if couverte:
        couvertes = list(row.sections_couvertes or []) + [row.section_courante]
        suivante = _prochaine_section(couvertes)
        if suivante is None:
            # `_cloturer` fait ses 3 appels HTTP ICI, hors de toute session ouverte.
            statut, sync_erreur, audit_id = await _cloturer(v, transcript=row.transcript)
            row.sections_couvertes = couvertes
            row.statut = statut
            row.sync_erreur = sync_erreur
            question_suivante = None
        else:
            row.section_courante = suivante["id"]
            row.sections_couvertes = couvertes
            question_suivante = suivante["premiere_question"]

    row.derniere_activite = now
    sync_erreur_finale = getattr(row, "sync_erreur", None)

    # ── Transaction d'ÉCRITURE, courte : plus aucun appel réseau au-delà d'ici ───
    async with SessionLocal() as s:
        if nouveau_profil is not None:
            await s.execute(update(Ventures).where(Ventures.id == u)
                            .values(profil_entreprise=nouveau_profil, updated_at=now))
        if audit_id:
            await s.execute(update(Ventures).where(Ventures.id == u)
                            .values(audit_id=audit_id, updated_at=now))
        await s.execute(update(Entretiens).where(Entretiens.id == row.id).values(
            section_courante=row.section_courante, sections_couvertes=row.sections_couvertes,
            transcript=row.transcript, statut=row.statut, sync_erreur=sync_erreur_finale,
            derniere_activite=now,
        ))
        await s.commit()

    return {
        "sectionCourante": row.section_courante,
        "sectionsCouvertes": row.sections_couvertes,
        "question": question_suivante,
        "statut": row.statut,
        "extractionEchouee": extraction_echouee,
        # Exposé (revue finale S228, Finding I4) : la clôture est best-effort — `statut`
        # vaut "termine" même si le push d'ingestion ou le rappel /auditer a échoué.
        # Sans ce champ, le Cœur annonçait « l'analyse est relancée » dans tous les cas.
        "syncErreur": sync_erreur_finale,
    }


_PROMPT_DECISION_PROCESSUS = (
    "Tu mènes un entretien d'audit d'entreprise sur le processus « {zone} ».\n"
    "Dernière réponse de l'utilisateur : \"{message}\"\n\n"
    "Décide si ce processus est maintenant suffisamment décrit (de bout en bout), ou s'il "
    "faut relancer avec une question de suivi CIBLÉE (une réponse courte appelle une "
    "relance précise, motif : « comment arrive une demande » → « qui répond » → « combien "
    "de temps » → ...).\n"
    "Réponds UNIQUEMENT en JSON strict : {{\"couverte\": true|false, \"question\": \"...\"|null}}."
)


async def _cloturer(v, transcript: str) -> tuple[str, str | None, str | None]:
    """Pousse le transcript vers ingestion (POST /ingerer, JAMAIS /documents/import qui ne
    propage pas venture_id) puis rappelle POST {AUDIT_URL}/auditer avec tous les doc_ids de
    la venture. Best-effort : une panne à N'IMPORTE QUELLE étape ne bloque JAMAIS la clôture
    (`statut` devient toujours "termine"), seul `sync_erreur` signale un défaut de synchro,
    rejouable en rappelant /entretien/terminer.

    Rend ``(statut, sync_erreur, audit_id)`` et NE TOUCHE AUCUNE SESSION (revue finale
    S228, Finding I2). Les 3 appels HTTP ci-dessous durent jusqu'à 30 s chacun : les
    exécuter dans une session ouverte immobilisait une connexion/transaction ~90 s.
    L'appelant fait tourner cette fonction hors session, puis persiste `audit_id` dans
    une transaction courte — même découpage que `ventures.get_venture_dossier` (S227).
    """
    if not settings.INGESTION_URL or not settings.AUDIT_URL:
        return "termine", "ingestion/audit non configurés", None

    ingestion_headers = {"X-API-Key": settings.INGESTION_KEY} if settings.INGESTION_KEY else {}
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            fichier = transcript.encode("utf-8")
            r_push = await c.post(
                f"{settings.INGESTION_URL.rstrip('/')}/ingerer",
                files={"fichier": (f"entretien-{v.id}.txt", fichier, "text/plain")},
                data={"venture_id": str(v.id)},
                headers=ingestion_headers,
            )
            if r_push.status_code >= 400:
                return "termine", f"push ingestion échoué ({r_push.status_code})", None

            r_docs = await c.get(
                f"{settings.INGESTION_URL.rstrip('/')}/documents",
                params={"venture_id": str(v.id)}, headers=ingestion_headers,
            )
            if r_docs.status_code >= 400:
                return "termine", f"lecture documents échouée ({r_docs.status_code})", None
            docs_data = r_docs.json()
            # Corps 200 mais pas un objet (ex. liste brute) : repli honnête plutôt que
            # planter sur .get()/d["id"] — même garde que _lister_documents/
            # _lire_audit_business dans ventures.py (revue post-fusion, Fix 3/5).
            if not isinstance(docs_data, dict):
                return "termine", "lecture documents : réponse invalide", None
            doc_ids = [d["id"] for d in docs_data.get("documents", []) if isinstance(d, dict) and "id" in d]
            if not doc_ids:
                return "termine", "aucun doc_id disponible après push", None

            r_audit = await c.post(f"{settings.AUDIT_URL.rstrip('/')}/auditer",
                                   json={"doc_ids": doc_ids})
            if r_audit.status_code >= 400:
                return "termine", f"rappel /auditer échoué ({r_audit.status_code})", None
            audit_data = r_audit.json()
            if not isinstance(audit_data, dict):
                return "termine", "rappel /auditer : réponse invalide", None
            audit_id = audit_data.get("id")
            if not audit_id:
                return "termine", "rappel /auditer : id manquant dans la réponse", None
    except (httpx.HTTPError, httpx.InvalidURL, ValueError, TypeError, KeyError) as e:
        # httpx.InvalidURL n'hérite pas de httpx.HTTPError (vérifié httpx 0.28) — même
        # garde que _lister_documents/_lire_audit_business dans ventures.py. ValueError
        # couvre json.JSONDecodeError (corps non-JSON) ; TypeError/KeyError couvrent un
        # accès malformé résiduel sur un corps de réponse inattendu.
        return "termine", f"panne réseau : {e}", None

    # Reflet en mémoire uniquement (l'objet est détaché : sa session est fermée). La
    # persistance de `audit_id` est faite par l'appelant, dans sa transaction courte.
    v.audit_id = audit_id
    return "termine", None, audit_id


@router.post("/ventures/{vid}/entretien/terminer", dependencies=[Depends(get_current_user)])
async def terminer_entretien(vid: str, user: UserContext = Depends(get_current_user)):
    """Clôture explicite (avant squelette complet) ou retry d'une clôture qui avait
    échoué (sync_erreur non nul) : rappelle le même `_cloturer` que la clôture
    automatique de fin de squelette (Task 5), jamais une réimplémentation."""
    u = _uuid(vid)
    async with SessionLocal() as s:
        # Ownership d'abord — même ordre que demarrer_entretien/repondre_entretien/
        # etat_entretien ci-dessous, pour cohérence (Entretiens n'a pas d'owner_id).
        v = (await s.execute(
            select(Ventures).where(and_(Ventures.id == u, Ventures.owner_id == user.sub))
        )).scalar_one_or_none() if u else None
        row = (await s.execute(
            select(Entretiens).where(Entretiens.venture_id == u)
            .order_by(desc(Entretiens.derniere_activite)).limit(1)
        )).scalar_one_or_none() if u and v is not None else None
        if row is None or v is None:
            raise HTTPException(status_code=404, detail="Aucun entretien pour cette venture")

        # Idempotence (revue finale S228, Finding I3) : sans ce court-circuit, rappeler
        # /terminer sur un entretien déjà clôturé PROPREMENT rejouait `_cloturer` en
        # entier — un 2e transcript poussé vers l'ingestion et un NOUVEL audit qui
        # écrasait `Ventures.audit_id`. La docstring annonçait « retry d'une clôture qui
        # avait échoué » mais rien ne l'imposait ; c'est `sync_erreur is not None` qui
        # définit une clôture rejouable.
        if row.statut == "termine" and row.sync_erreur is None:
            return entretien(row)

    # `_cloturer` hors session (Finding I2), puis transaction d'écriture courte.
    statut, sync_erreur, audit_id = await _cloturer(v, transcript=row.transcript)
    # Naïf : colonnes `timestamp without time zone` (cf. Finding C2).
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    async with SessionLocal() as s:
        await s.execute(update(Entretiens).where(Entretiens.id == row.id).values(
            statut=statut, sync_erreur=sync_erreur, derniere_activite=now))
        if audit_id:
            await s.execute(update(Ventures).where(Ventures.id == u)
                            .values(audit_id=audit_id, updated_at=now))
        await s.commit()
    row.statut, row.sync_erreur = statut, sync_erreur
    row.derniere_activite = now

    return entretien(row)


@router.get("/ventures/{vid}/entretien/etat", dependencies=[Depends(get_current_user)])
async def etat_entretien(vid: str, user: UserContext = Depends(get_current_user)):
    u = _uuid(vid)
    async with SessionLocal() as s:
        # Ownership d'abord : sans ce filtre, n'importe quel utilisateur authentifié pourrait
        # lire l'état d'entretien de n'importe quelle venture en devinant son id — même
        # classe de bug que les fixes Critical S227 sur les scopes client_lecture.
        v = (await s.execute(
            select(Ventures).where(and_(Ventures.id == u, Ventures.owner_id == user.sub))
        )).scalar_one_or_none() if u else None
        row = (await s.execute(
            select(Entretiens).where(Entretiens.venture_id == u)
            .order_by(desc(Entretiens.derniere_activite)).limit(1)
        )).scalar_one_or_none() if u and v is not None else None
        if v is None or row is None:
            raise HTTPException(status_code=404, detail="Aucun entretien pour cette venture")
    return entretien(row)
