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

ETL_URL = os.getenv("ETL_URL", "http://host.docker.internal:5200")
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
        conn.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    _init_db()
    yield


app = FastAPI(title="Audit", version="0.1.0", lifespan=lifespan)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _audit_vers_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    for champ in ("docs_sources", "territoire", "flux", "problemes", "priorites"):
        if d.get(champ):
            try:
                d[champ] = json.loads(d[champ])
            except Exception:
                pass
    return d


async def _recuperer_textes(doc_ids: list[str]) -> tuple[list[str], str]:
    """Récupère le contenu textuel des documents depuis l'ETL. Retourne (textes, nom_entreprise)."""
    textes = []
    nom_entreprise = "Entreprise inconnue"
    async with httpx.AsyncClient(timeout=60) as client:
        for doc_id in doc_ids:
            try:
                r = await client.get(f"{ETL_URL}/documents/{doc_id}")
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
        r = await client.get(f"{ETL_URL}/documents")
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
        raise HTTPException(502, f"ETL inaccessible : {e}")
    if not doc_ids:
        raise HTTPException(404, "Aucun document dans l'ETL")
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
                problemes, priorites, statut)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                audit_id,
                audit.get("date_audit") or datetime.now(timezone.utc).isoformat(),
                audit.get("nom_entreprise"),
                _ser(audit.get("docs_sources")),
                _ser(audit.get("territoire")),
                _ser(audit.get("flux")),
                _ser(audit.get("problemes")),
                _ser(audit.get("priorites")),
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


@app.get("/audits/{audit_id}")
def lire_audit(audit_id: str):
    with _connexion() as conn:
        row = conn.execute("SELECT * FROM audits WHERE id=?", (audit_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Audit introuvable")
    return _audit_vers_dict(row)


@app.delete("/audits/{audit_id}", status_code=204)
def supprimer_audit(audit_id: str):
    with _connexion() as conn:
        conn.execute("DELETE FROM audits WHERE id=?", (audit_id,))
        conn.commit()


@app.get("/sante")
def sante():
    return {"statut": "ok", "service": "audit", "version": "0.1.0"}
