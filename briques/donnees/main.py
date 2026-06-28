"""Brique Persistance (« donnees ») — magasin CRUD générique multi-tenant.

Remplace le localStorage des apps générées par une vraie persistance serveur.
Les données sont rangées par (app_id, entite_id), chaque enregistrement reçoit
un identifiant serveur stable (uuid) → édition/suppression fiables, multi-utilisateur.

C'est une brique « socle » : elle ne connaît pas le métier des entreprises, elle
stocke des objets JSON quelconques. Le schéma des champs reste défini côté app générée.
"""
import json
import os
import sqlite3
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from auth import config_valide, garde_auth, tenant_actuel

DB_PATH = os.getenv("DB_PATH", "/data/donnees.db")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Base de données ────────────────────────────────────────────────────────────

def _connexion() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _init_db():
    with _connexion() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS enregistrements (
                id            TEXT PRIMARY KEY,
                app_id        TEXT NOT NULL,
                entite_id     TEXT NOT NULL,
                org_id        TEXT NOT NULL DEFAULT 'defaut',
                donnees       TEXT NOT NULL,
                date_creation TEXT NOT NULL,
                date_maj      TEXT NOT NULL
            )
        """)
        # Migration S121 (prépa multi-tenant) : les bases d'avant S121 n'ont pas la
        # colonne org_id. On l'ajoute si absente ; les lignes existantes héritent du
        # DEFAULT 'defaut' (rétro-remplissage → aucune donnée orpheline). Idempotent.
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(enregistrements)")}
        if "org_id" not in cols:
            conn.execute(
                "ALTER TABLE enregistrements ADD COLUMN org_id TEXT NOT NULL DEFAULT 'defaut'"
            )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_org_app_entite "
            "ON enregistrements(org_id, app_id, entite_id)"
        )
        conn.commit()


def _amorcer_depuis_fichier():
    """Seed initial depuis un fichier JSON monté (déploiement reproductible — S4).

    Format attendu : {app_id: {entite_id: [enregistrements...]}}. Idempotent :
    n'insère que dans les entités encore vides (on ne réécrase pas des saisies réelles).
    Permet à un bundle livré de démarrer pré-rempli au simple `docker compose up`.
    """
    chemin = os.getenv("SEED_FILE")
    if not chemin or not os.path.exists(chemin):
        return
    try:
        with open(chemin, encoding="utf-8") as f:
            graine = json.load(f)
    except Exception as e:
        print(f"[donnees] SEED_FILE illisible ({chemin}) : {e}")
        return
    # Le seed appartient à l'organisation du bundle (SEED_ORG ; défaut 'defaut' = instance
    # ouverte). Permet à un bundle authentifié de pré-remplir la bonne org.
    seed_org = os.getenv("SEED_ORG", "defaut")
    total = 0
    with _connexion() as conn:
        for app_id, entites in (graine or {}).items():
            for entite_id, recs in (entites or {}).items():
                deja = conn.execute(
                    "SELECT COUNT(*) AS n FROM enregistrements "
                    "WHERE org_id=? AND app_id=? AND entite_id=?",
                    (seed_org, app_id, entite_id),
                ).fetchone()["n"]
                if deja:
                    continue
                now = _now()
                for d in (recs or []):
                    if not isinstance(d, dict):
                        continue
                    propre = {k: v for k, v in d.items() if not str(k).startswith("_")}
                    conn.execute(
                        "INSERT INTO enregistrements (id, app_id, entite_id, org_id, donnees, date_creation, date_maj) "
                        "VALUES (?,?,?,?,?,?,?)",
                        (str(uuid.uuid4()), app_id, entite_id, seed_org,
                         json.dumps(propre, ensure_ascii=False), now, now),
                    )
                    total += 1
        conn.commit()
    if total:
        print(f"[donnees] seed initial : {total} enregistrement(s) depuis {chemin}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    _init_db()
    _amorcer_depuis_fichier()
    yield


_init_db()  # garantit le schéma dès l'import (volume vierge, reconnexions)
app = FastAPI(title="Persistance Workplace", version="0.1.0", lifespan=lifespan)

# CORS : ouvert par défaut (apps exportées / aperçu / hébergement libre — brique socle).
# Dans un bundle authentifié, le packager pose CORS_ORIGINS sur l'origine de l'app
# (défense en profondeur ; l'enforcement réel reste le JWT via garde_auth).
_cors = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()] or ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors,
    allow_methods=["*"],
    allow_headers=["*"],
)

from auth import AUTH_ENABLED  # noqa: E402  (lecture du flag pour le diagnostic de démarrage)
if config_valide():
    print("[donnees] authentification ACTIVE — Bearer Keycloak exigé sur toutes les routes de données")
elif AUTH_ENABLED:
    print("[donnees] ⚠ AUTH_ENABLED=true mais KEYCLOAK_URL/REALM manquant → brique OUVERTE (corrigez la config)")
else:
    print("[donnees] authentification désactivée (brique ouverte) — AUTH_ENABLED non posé")

# Garde JWT posée sur toutes les routes de données (no-op si AUTH_ENABLED absent).
# /sante reste publique (sondes Docker / supervision).
_protege = [Depends(garde_auth)]


# ── Sérialisation ──────────────────────────────────────────────────────────────

def _ligne_vers_dict(row: sqlite3.Row) -> dict:
    """Aplati l'enregistrement : champs métier + métadonnées préfixées par _."""
    try:
        donnees = json.loads(row["donnees"])
    except Exception:
        donnees = {}
    if not isinstance(donnees, dict):
        donnees = {}
    return {
        **donnees,
        "_id": row["id"],
        "_cree": row["date_creation"],
        "_maj": row["date_maj"],
    }


def _nettoyer(donnees: Any) -> dict:
    """Garde uniquement un objet plat ; retire d'éventuelles métadonnées entrantes."""
    if not isinstance(donnees, dict):
        raise HTTPException(422, "Le corps doit être un objet JSON (champs de l'enregistrement).")
    return {k: v for k, v in donnees.items() if not str(k).startswith("_")}


# ── Modèles ────────────────────────────────────────────────────────────────────

class Graine(BaseModel):
    enregistrements: list[dict] = []


class ImportDonnees(BaseModel):
    # {entite_id: [enregistrements avec _id/_cree/_maj]}
    entites: dict[str, list[dict]] = {}


# ── Endpoints CRUD ─────────────────────────────────────────────────────────────

_BASE = "/apps/{app_id}/entites/{entite_id}/enregistrements"


@app.get(_BASE, dependencies=_protege)
def lister(app_id: str, entite_id: str, org: str = Depends(tenant_actuel)):
    with _connexion() as conn:
        rows = conn.execute(
            "SELECT * FROM enregistrements WHERE org_id=? AND app_id=? AND entite_id=? "
            "ORDER BY date_creation ASC",
            (org, app_id, entite_id),
        ).fetchall()
    return [_ligne_vers_dict(r) for r in rows]


@app.post(_BASE, status_code=201, dependencies=_protege)
def creer(app_id: str, entite_id: str, donnees: dict, org: str = Depends(tenant_actuel)):
    donnees = _nettoyer(donnees)
    rec_id = str(uuid.uuid4())
    now = _now()
    with _connexion() as conn:
        conn.execute(
            "INSERT INTO enregistrements (id, app_id, entite_id, org_id, donnees, date_creation, date_maj) "
            "VALUES (?,?,?,?,?,?,?)",
            (rec_id, app_id, entite_id, org, json.dumps(donnees, ensure_ascii=False), now, now),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM enregistrements WHERE id=?", (rec_id,)).fetchone()
    return _ligne_vers_dict(row)


@app.put(_BASE + "/{rec_id}", dependencies=_protege)
def modifier(app_id: str, entite_id: str, rec_id: str, donnees: dict,
             org: str = Depends(tenant_actuel)):
    donnees = _nettoyer(donnees)
    now = _now()
    with _connexion() as conn:
        cur = conn.execute(
            "UPDATE enregistrements SET donnees=?, date_maj=? "
            "WHERE id=? AND org_id=? AND app_id=? AND entite_id=?",
            (json.dumps(donnees, ensure_ascii=False), now, rec_id, org, app_id, entite_id),
        )
        conn.commit()
        if cur.rowcount == 0:
            raise HTTPException(404, "Enregistrement introuvable")
        row = conn.execute("SELECT * FROM enregistrements WHERE id=?", (rec_id,)).fetchone()
    return _ligne_vers_dict(row)


@app.delete(_BASE + "/{rec_id}", status_code=204, dependencies=_protege)
def supprimer(app_id: str, entite_id: str, rec_id: str, org: str = Depends(tenant_actuel)):
    with _connexion() as conn:
        cur = conn.execute(
            "DELETE FROM enregistrements WHERE id=? AND org_id=? AND app_id=? AND entite_id=?",
            (rec_id, org, app_id, entite_id),
        )
        conn.commit()
        if cur.rowcount == 0:
            raise HTTPException(404, "Enregistrement introuvable")


@app.post("/apps/{app_id}/entites/{entite_id}/seed", dependencies=_protege)
def semer(app_id: str, entite_id: str, graine: Graine, org: str = Depends(tenant_actuel)):
    """Insère des données d'exemple — seulement si l'entité est vide (idempotent).

    Permet au générateur de pré-remplir une app à sa création sans réécraser les
    saisies réelles si la fonction est rappelée.
    """
    with _connexion() as conn:
        existant = conn.execute(
            "SELECT COUNT(*) AS n FROM enregistrements WHERE org_id=? AND app_id=? AND entite_id=?",
            (org, app_id, entite_id),
        ).fetchone()["n"]
        if existant:
            return {"seme": False, "raison": "entité déjà peuplée", "nombre": existant}
        now = _now()
        for d in graine.enregistrements:
            conn.execute(
                "INSERT INTO enregistrements (id, app_id, entite_id, org_id, donnees, date_creation, date_maj) "
                "VALUES (?,?,?,?,?,?,?)",
                (str(uuid.uuid4()), app_id, entite_id, org,
                 json.dumps(_nettoyer(d), ensure_ascii=False), now, now),
            )
        conn.commit()
    return {"seme": True, "nombre": len(graine.enregistrements)}


@app.get("/apps/{app_id}/export", dependencies=_protege)
def exporter_app(app_id: str, org: str = Depends(tenant_actuel)):
    """Tous les enregistrements d'une app, groupés par entité (décrochage S6).

    Conserve les métadonnées (_id, _cree, _maj) pour une réinjection à l'identique.
    """
    with _connexion() as conn:
        rows = conn.execute(
            "SELECT * FROM enregistrements WHERE org_id=? AND app_id=? "
            "ORDER BY entite_id, date_creation ASC",
            (org, app_id),
        ).fetchall()
    par_entite: dict[str, list] = {}
    for r in rows:
        par_entite.setdefault(r["entite_id"], []).append(_ligne_vers_dict(r))
    return {"app_id": app_id, "entites": par_entite}


@app.post("/apps/{app_id}/import", dependencies=_protege)
def importer_app(app_id: str, payload: ImportDonnees, org: str = Depends(tenant_actuel)):
    """Réinjecte les enregistrements d'une app (ids et horodatages préservés) — reprise S6."""
    total = 0
    with _connexion() as conn:
        for entite_id, recs in payload.entites.items():
            for d in recs:
                if not isinstance(d, dict):
                    continue
                rec_id = d.get("_id") or str(uuid.uuid4())
                cree = d.get("_cree") or _now()
                maj = d.get("_maj") or cree
                donnees = {k: v for k, v in d.items() if not str(k).startswith("_")}
                conn.execute(
                    "INSERT OR REPLACE INTO enregistrements "
                    "(id, app_id, entite_id, org_id, donnees, date_creation, date_maj) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (rec_id, app_id, entite_id, org,
                     json.dumps(donnees, ensure_ascii=False), cree, maj),
                )
                total += 1
        conn.commit()
    return {"importe": True, "nombre": total}


@app.get("/apps/{app_id}/resume", dependencies=_protege)
def resume(app_id: str, org: str = Depends(tenant_actuel)):
    """Compte les enregistrements par entité pour une app (utile au tableau de bord)."""
    with _connexion() as conn:
        rows = conn.execute(
            "SELECT entite_id, COUNT(*) AS n FROM enregistrements WHERE org_id=? AND app_id=? "
            "GROUP BY entite_id",
            (org, app_id),
        ).fetchall()
    return {"app_id": app_id, "entites": {r["entite_id"]: r["n"] for r in rows}}


@app.delete("/apps/{app_id}", status_code=204, dependencies=_protege)
def purger_app(app_id: str, org: str = Depends(tenant_actuel)):
    """Efface toutes les données d'une app (désinstallation / remise à zéro)."""
    with _connexion() as conn:
        conn.execute("DELETE FROM enregistrements WHERE org_id=? AND app_id=?", (org, app_id))
        conn.commit()


@app.get("/sante")
def sante():
    return {"statut": "ok", "service": "donnees", "version": "0.1.0"}
