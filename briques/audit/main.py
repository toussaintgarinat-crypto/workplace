import asyncio
import json
import os
import sqlite3
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import httpx
from fastapi import BackgroundTasks, FastAPI, HTTPException
from pydantic import BaseModel

from analyse import auditer
from chiffrage import chiffrer
from shared.schemas.audit import Audit

INGESTION_URL = os.getenv("INGESTION_URL", "http://host.docker.internal:5200")
# La brique `ingestion` est fermée par API_KEYS depuis S211 : `audit` déclare
# `besoin: ingestion`, elle doit donc porter la clé. Absente → dict vide, et une brique
# en mode ouvert répond
# comme avant (on ne casse pas un déploiement non configuré).
_INGESTION_CLE = os.getenv("INGESTION_KEY")
INGESTION_ENTETES = {"X-API-Key": _INGESTION_CLE} if _INGESTION_CLE else {}
DB_PATH = os.getenv("DB_PATH", "/data/audits.db")


# ── Base de données ────────────────────────────────────────────────────────────

def _connexion() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _init_db():
    with _connexion() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS audits (
                id             TEXT PRIMARY KEY,
                date_audit     TEXT NOT NULL,
                nom_entreprise TEXT,
                docs_sources   TEXT,
                territoire     TEXT,
                flux           TEXT,
                problemes      TEXT,
                priorites      TEXT,
                statut         TEXT DEFAULT 'en_cours'
            )
        """)
        # Migration S229 : colonne roi (5e couche, calculée à la demande via /chiffrer).
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(audits)").fetchall()}
        if "roi" not in cols:
            conn.execute("ALTER TABLE audits ADD COLUMN roi TEXT")
        conn.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    _init_db()
    yield


app = FastAPI(title="Audit", version="0.1.0", lifespan=lifespan)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _audit_vers_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    for champ in ("docs_sources", "territoire", "flux", "problemes", "priorites", "roi"):
        if d.get(champ):
            try:
                d[champ] = json.loads(d[champ])
            except Exception:
                pass
    return d


async def _recuperer_textes(doc_ids: list[str]) -> tuple[list[str], str]:
    """Récupère le contenu textuel des documents depuis la brique `ingestion`. Retourne (textes, nom_entreprise)."""
    textes = []
    nom_entreprise = "Entreprise inconnue"
    async with httpx.AsyncClient(timeout=60) as client:
        for doc_id in doc_ids:
            try:
                r = await client.get(f"{INGESTION_URL}/documents/{doc_id}", headers=INGESTION_ENTETES)
                r.raise_for_status()
                doc = r.json()
                texte = doc.get("texte_extrait") or doc.get("contenu") or ""
                if texte:
                    textes.append(texte)
                nom_doc = doc.get("nom") or doc.get("nom_fichier") or ""
                if nom_entreprise == "Entreprise inconnue" and nom_doc:
                    nom_entreprise = nom_doc.rsplit(".", 1)[0]
            except Exception:
                pass
    return textes, nom_entreprise


async def _recuperer_tous_ids() -> list[str]:
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(f"{INGESTION_URL}/documents", headers=INGESTION_ENTETES)
        r.raise_for_status()
        return [d["id"] for d in r.json().get("documents", r.json())]


# ── Tâche de fond ──────────────────────────────────────────────────────────────

async def _lancer_audit(audit_id: str, doc_ids: list[str]):
    textes, nom_entreprise = await _recuperer_textes(doc_ids)
    if not textes:
        with _connexion() as conn:
            conn.execute(
                "UPDATE audits SET statut='erreur' WHERE id=?", (audit_id,)
            )
            conn.commit()
        return

    try:
        resultat = await auditer(textes, nom_entreprise)
        with _connexion() as conn:
            conn.execute(
                """UPDATE audits SET
                    nom_entreprise=?, territoire=?, flux=?, problemes=?, priorites=?, statut='termine'
                   WHERE id=?""",
                (
                    nom_entreprise,
                    json.dumps(resultat["territoire"], ensure_ascii=False),
                    json.dumps(resultat["flux"], ensure_ascii=False),
                    json.dumps(resultat["problemes"], ensure_ascii=False),
                    json.dumps(resultat["priorites"], ensure_ascii=False),
                    audit_id,
                ),
            )
            conn.commit()
    except Exception as e:
        with _connexion() as conn:
            conn.execute(
                "UPDATE audits SET statut='erreur' WHERE id=?", (audit_id,)
            )
            conn.commit()


# ── Modèles Pydantic ───────────────────────────────────────────────────────────

class RequeteAudit(BaseModel):
    doc_ids: list[str]


class RequeteChiffrer(BaseModel):
    cout_horaire: dict[str, float] | None = None


# ── Endpoints ──────────────────────────────────────────────────────────────────

@app.post("/auditer", status_code=202)
async def auditer_docs(req: RequeteAudit, background_tasks: BackgroundTasks):
    audit_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    with _connexion() as conn:
        conn.execute(
            "INSERT INTO audits (id, date_audit, docs_sources, statut) VALUES (?,?,?,?)",
            (audit_id, now, json.dumps(req.doc_ids), "en_cours"),
        )
        conn.commit()
    background_tasks.add_task(_lancer_audit, audit_id, req.doc_ids)
    return {"id": audit_id, "statut": "en_cours"}


@app.post("/auditer/tout", status_code=202)
async def auditer_tout(background_tasks: BackgroundTasks):
    try:
        doc_ids = await _recuperer_tous_ids()
    except Exception as e:
        raise HTTPException(502, f"Brique ingestion inaccessible : {e}")
    if not doc_ids:
        raise HTTPException(404, "Aucun document ingéré")
    audit_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    with _connexion() as conn:
        conn.execute(
            "INSERT INTO audits (id, date_audit, docs_sources, statut) VALUES (?,?,?,?)",
            (audit_id, now, json.dumps(doc_ids), "en_cours"),
        )
        conn.commit()
    background_tasks.add_task(_lancer_audit, audit_id, doc_ids)
    return {"id": audit_id, "statut": "en_cours", "docs_count": len(doc_ids)}


@app.post("/audits/import")
def importer_audit(audit: dict):
    """Réinsère un audit complet (id préservé) — reprise d'un dossier décroché (S6)."""
    def _ser(v):
        if v is None or isinstance(v, str):
            return v
        return json.dumps(v, ensure_ascii=False)

    audit_id = audit.get("id") or str(uuid.uuid4())
    with _connexion() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO audits
               (id, date_audit, nom_entreprise, docs_sources, territoire, flux,
                problemes, priorites, roi, statut)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                audit_id,
                audit.get("date_audit") or datetime.now(timezone.utc).isoformat(),
                audit.get("nom_entreprise"),
                _ser(audit.get("docs_sources")),
                _ser(audit.get("territoire")),
                _ser(audit.get("flux")),
                _ser(audit.get("problemes")),
                _ser(audit.get("priorites")),
                _ser(audit.get("roi")),
                audit.get("statut") or "termine",
            ),
        )
        conn.commit()
    return {"id": audit_id, "statut": "termine"}


@app.get("/audits")
def lister_audits():
    with _connexion() as conn:
        rows = conn.execute(
            "SELECT id, date_audit, nom_entreprise, statut FROM audits ORDER BY date_audit DESC"
        ).fetchall()
    return [dict(r) for r in rows]


@app.get("/audits/{audit_id}", response_model=Audit)
def lire_audit(audit_id: str):
    with _connexion() as conn:
        row = conn.execute("SELECT * FROM audits WHERE id=?", (audit_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Audit introuvable")
    return _audit_vers_dict(row)


@app.post("/audits/{audit_id}/chiffrer")
async def chiffrer_audit(audit_id: str, req: RequeteChiffrer | None = None):
    req = req or RequeteChiffrer()
    with _connexion() as conn:
        row = conn.execute(
            "SELECT territoire, flux, problemes, priorites, statut FROM audits WHERE id=?",
            (audit_id,),
        ).fetchone()
    if not row:
        raise HTTPException(404, "Audit introuvable")
    if row["statut"] != "termine":
        raise HTTPException(400, f"L'audit n'est pas terminé (statut : {row['statut']})")

    territoire = json.loads(row["territoire"]) if row["territoire"] else {}
    problemes = json.loads(row["problemes"]) if row["problemes"] else {}
    priorites = json.loads(row["priorites"]) if row["priorites"] else {}

    resultat = await chiffrer(territoire, problemes, priorites, req.cout_horaire)
    with _connexion() as conn:
        conn.execute(
            "UPDATE audits SET roi=? WHERE id=?",
            (json.dumps(resultat, ensure_ascii=False) if resultat else None, audit_id),
        )
        conn.commit()
    return {"id": audit_id, "roi": resultat,
            "statut_roi": "termine" if resultat else "roi_indisponible"}


@app.delete("/audits/{audit_id}", status_code=204)
def supprimer_audit(audit_id: str):
    with _connexion() as conn:
        conn.execute("DELETE FROM audits WHERE id=?", (audit_id,))
        conn.commit()


@app.get("/sante")
def sante():
    return {"statut": "ok", "service": "audit", "version": "0.1.0"}
