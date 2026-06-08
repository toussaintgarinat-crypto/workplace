"""Orchestrateur de l'usine à applications (Sprint S5).

Le Cœur pilote toute la chaîne de l'objectif 1 — ETL → Audit → Génération
(→ Packaging) — en une seule commande, en appelant les briques par HTTP et en
suivant l'avancement étape par étape. Chaque livraison d'entreprise est
persistée (SQLite) pour alimenter le « tableau des entreprises livrées ».

Le Cœur ne réimplémente AUCUNE logique métier : il se contente d'enchaîner les
contrats des briques (modèle « noyau + briques »). Si une brique change son API
en gardant son contrat, l'orchestrateur n'a pas à bouger.
"""

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import httpx

# Hôte par lequel le Cœur (dans son conteneur) joint les autres briques.
# Les manifests exposent déjà des url_sante en host.docker.internal:<port>.
BRIQUE_HOST = os.environ.get("BRIQUE_HOST", "host.docker.internal")

LIVRAISONS_DB = os.environ.get("LIVRAISONS_DB", "/data/livraisons.db")

# Délais de polling des étapes asynchrones (audit, génération) — l'enchaînement
# LLM peut être long (≈1 min pour un audit 4 couches).
POLL_INTERVALLE = float(os.environ.get("POLL_INTERVALLE", "3"))
POLL_TIMEOUT = float(os.environ.get("POLL_TIMEOUT", "900"))

# Étapes du pipeline, dans l'ordre. Sert au suivi et au dashboard.
ETAPES = ["ingestion", "audit", "generation", "packaging"]


def _maintenant() -> str:
    return datetime.now(timezone.utc).isoformat()


def _brique_base(registre, nom: str) -> str:
    """URL de base d'une brique. Priorité à une variable d'env d'override
    (`ETL_URL`, `AUDIT_URL`, `GENERATEUR_URL`…), sinon dérivée du registre."""
    override = os.environ.get(f"{nom.upper()}_URL")
    if override:
        return override.rstrip("/")
    brique = registre.briques.get(nom) or {}
    port = brique.get("port")
    if not port:
        raise RuntimeError(
            f"Brique '{nom}' absente du registre ou sans port — usine non pilotable"
        )
    return f"http://{BRIQUE_HOST}:{port}"


# ── Persistance des livraisons ───────────────────────────────────────────────

def _connexion() -> sqlite3.Connection:
    Path(LIVRAISONS_DB).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(LIVRAISONS_DB)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _connexion() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS livraisons (
                id             TEXT PRIMARY KEY,
                date_creation  TEXT NOT NULL,
                date_maj       TEXT NOT NULL,
                nom_entreprise TEXT,
                statut         TEXT DEFAULT 'en_cours',   -- en_cours | livree | erreur | decrochee
                etape_courante TEXT,
                doc_ids        TEXT,                       -- json: liste
                audit_id       TEXT,
                app_id         TEXT,
                mode           TEXT,                       -- autonome | hebergee
                messagerie     INTEGER DEFAULT 0,
                packager       INTEGER DEFAULT 0,
                package        TEXT,                       -- json: récap packaging
                etapes         TEXT,                       -- json: journal d'étapes
                erreur         TEXT,
                dossier        TEXT,                       -- chemin du dossier portable (si décrochée)
                email_client   TEXT,                       -- email du client (compte auto, S23)
                contact_client TEXT                        -- nom du contact client (S23)
            )
            """
        )
        # Migration : ajoute les colonnes aux bases déjà créées sans elles.
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(livraisons)").fetchall()}
        if "dossier" not in cols:  # S6
            conn.execute("ALTER TABLE livraisons ADD COLUMN dossier TEXT")
        if "email_client" not in cols:  # S23
            conn.execute("ALTER TABLE livraisons ADD COLUMN email_client TEXT")
        if "contact_client" not in cols:  # S23
            conn.execute("ALTER TABLE livraisons ADD COLUMN contact_client TEXT")
        conn.commit()


def creer_livraison(livraison_id: str, nom: str, mode: str,
                    messagerie: bool, packager: bool,
                    email_client: str | None = None,
                    contact_client: str | None = None):
    journal = [{"etape": e, "statut": "en_attente"} for e in ETAPES]
    if not packager:
        journal = [e for e in journal if e["etape"] != "packaging"]
    with _connexion() as conn:
        conn.execute(
            """INSERT INTO livraisons
               (id, date_creation, date_maj, nom_entreprise, statut, etape_courante,
                mode, messagerie, packager, etapes, email_client, contact_client)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (livraison_id, _maintenant(), _maintenant(), nom, "en_cours", None,
             mode, int(messagerie), int(packager),
             json.dumps(journal, ensure_ascii=False),
             (email_client or None), (contact_client or None)),
        )
        conn.commit()


def _maj(livraison_id: str, **champs):
    if not champs:
        return
    champs["date_maj"] = _maintenant()
    sets = ", ".join(f"{k}=?" for k in champs)
    with _connexion() as conn:
        conn.execute(
            f"UPDATE livraisons SET {sets} WHERE id=?",
            (*champs.values(), livraison_id),
        )
        conn.commit()


def _maj_etape(livraison_id: str, etape: str, statut: str, message: str = ""):
    """Met à jour le journal d'étapes + l'étape courante."""
    with _connexion() as conn:
        row = conn.execute(
            "SELECT etapes FROM livraisons WHERE id=?", (livraison_id,)
        ).fetchone()
        journal = json.loads(row["etapes"]) if row and row["etapes"] else []
        for e in journal:
            if e["etape"] == etape:
                e["statut"] = statut
                e["message"] = message
                e["horodatage"] = _maintenant()
                break
        conn.execute(
            "UPDATE livraisons SET etapes=?, etape_courante=?, date_maj=? WHERE id=?",
            (json.dumps(journal, ensure_ascii=False), etape, _maintenant(), livraison_id),
        )
        conn.commit()


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    for champ in ("doc_ids", "package", "etapes"):
        if d.get(champ):
            try:
                d[champ] = json.loads(d[champ])
            except Exception:
                pass
    d["messagerie"] = bool(d.get("messagerie"))
    d["packager"] = bool(d.get("packager"))
    return d


def lister_livraisons() -> list[dict]:
    with _connexion() as conn:
        rows = conn.execute(
            "SELECT * FROM livraisons ORDER BY date_creation DESC"
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def lire_livraison(livraison_id: str) -> dict | None:
    with _connexion() as conn:
        row = conn.execute(
            "SELECT * FROM livraisons WHERE id=?", (livraison_id,)
        ).fetchone()
    return _row_to_dict(row) if row else None


def supprimer_livraison(livraison_id: str):
    with _connexion() as conn:
        conn.execute("DELETE FROM livraisons WHERE id=?", (livraison_id,))
        conn.commit()


def marquer_decrochee(livraison_id: str, dossier: str):
    """L'entreprise est sortie des bases centrales ; son état vit dans `dossier`."""
    _maj(livraison_id, statut="decrochee", dossier=dossier, etape_courante=None, erreur=None)


def marquer_reprise(livraison_id: str):
    """L'entreprise est réinjectée dans la solution principale (de nouveau active)."""
    _maj(livraison_id, statut="livree", dossier=None)


# ── Pipeline ─────────────────────────────────────────────────────────────────

class EchecEtape(Exception):
    """Lève une erreur attribuée à une étape précise du pipeline."""

    def __init__(self, etape: str, message: str):
        self.etape = etape
        super().__init__(message)


async def _attendre_termine(client: httpx.AsyncClient, url: str, etape: str) -> dict:
    """Poll un endpoint async jusqu'à statut 'termine' (ou 'erreur')."""
    debut = datetime.now(timezone.utc)
    while True:
        r = await client.get(url)
        r.raise_for_status()
        data = r.json()
        statut = data.get("statut")
        if statut == "termine":
            return data
        if statut == "erreur":
            raise EchecEtape(etape, data.get("erreur") or "la brique a renvoyé une erreur")
        if (datetime.now(timezone.utc) - debut).total_seconds() > POLL_TIMEOUT:
            raise EchecEtape(etape, f"délai dépassé ({POLL_TIMEOUT:.0f}s) — statut={statut}")
        import anyio
        await anyio.sleep(POLL_INTERVALLE)


async def _etape_ingestion(client, etl_base, fichiers, livraison_id) -> list[str]:
    _maj_etape(livraison_id, "ingestion", "en_cours")
    doc_ids: list[str] = []
    if fichiers:
        for nom, contenu, mime in fichiers:
            r = await client.post(
                f"{etl_base}/ingerer",
                files={"fichier": (nom, contenu, mime or "application/octet-stream")},
            )
            if r.status_code >= 400:
                raise EchecEtape("ingestion", f"ETL a refusé {nom} : {r.text}")
            doc_ids.append(r.json()["id"])
    else:
        # Pas de fichiers fournis → on audite les documents déjà présents dans l'ETL.
        r = await client.get(f"{etl_base}/documents", params={"limite": 500})
        r.raise_for_status()
        doc_ids = [d["id"] for d in r.json().get("documents", [])]
        if not doc_ids:
            raise EchecEtape("ingestion", "aucun fichier fourni et aucun document dans l'ETL")
    _maj(livraison_id, doc_ids=json.dumps(doc_ids, ensure_ascii=False))
    _maj_etape(livraison_id, "ingestion", "termine", f"{len(doc_ids)} document(s)")
    return doc_ids


async def _etape_audit(client, audit_base, doc_ids, livraison_id) -> dict:
    _maj_etape(livraison_id, "audit", "en_cours")
    r = await client.post(f"{audit_base}/auditer", json={"doc_ids": doc_ids})
    if r.status_code >= 400:
        raise EchecEtape("audit", f"Audit a refusé la demande : {r.text}")
    audit_id = r.json()["id"]
    _maj(livraison_id, audit_id=audit_id)
    audit = await _attendre_termine(client, f"{audit_base}/audits/{audit_id}", "audit")
    # Le nom fourni par l'utilisateur prime ; on ne retient celui dérivé par l'audit
    # que si l'utilisateur a laissé le défaut.
    liv = lire_livraison(livraison_id) or {}
    nom_audit = audit.get("nom_entreprise")
    if nom_audit and (liv.get("nom_entreprise") or "Entreprise") == "Entreprise":
        _maj(livraison_id, nom_entreprise=nom_audit)
    _maj_etape(livraison_id, "audit", "termine", f"audit {audit_id[:8]}")
    return audit


async def _etape_generation(client, gen_base, audit_id, mode, messagerie, livraison_id,
                            email_client=None, contact_client=None) -> str:
    _maj_etape(livraison_id, "generation", "en_cours")
    r = await client.post(
        f"{gen_base}/generer",
        json={"audit_id": audit_id, "persistance": mode, "messagerie": messagerie,
              "email_client": email_client, "contact_client": contact_client},
    )
    if r.status_code >= 400:
        raise EchecEtape("generation", f"Générateur a refusé la demande : {r.text}")
    app_id = r.json()["id"]
    _maj(livraison_id, app_id=app_id)
    await _attendre_termine(client, f"{gen_base}/apps/{app_id}", "generation")
    _maj_etape(livraison_id, "generation", "termine", f"app {app_id[:8]}")
    return app_id


async def _etape_packaging(client, gen_base, app_id, livraison_id) -> dict:
    _maj_etape(livraison_id, "packaging", "en_cours")
    r = await client.post(f"{gen_base}/apps/{app_id}/packager")
    if r.status_code >= 400:
        raise EchecEtape("packaging", f"Packaging échoué : {r.text}")
    recap = r.json()
    _maj(livraison_id, package=json.dumps(recap, ensure_ascii=False))
    _maj_etape(livraison_id, "packaging", "termine", recap.get("url_app", "bundle prêt"))
    return recap


async def executer_pipeline(registre, livraison_id: str, fichiers: list[tuple],
                           mode: str, messagerie: bool, packager: bool,
                           email_client: str | None = None,
                           contact_client: str | None = None):
    """Enchaîne ETL → Audit → Génération (→ Packaging). Met à jour la livraison
    à chaque étape ; capture toute erreur en l'attribuant à son étape."""
    try:
        etl_base = _brique_base(registre, "etl")
        audit_base = _brique_base(registre, "audit")
        gen_base = _brique_base(registre, "generateur")
    except RuntimeError as e:
        _maj(livraison_id, statut="erreur", erreur=str(e))
        return

    async with httpx.AsyncClient(timeout=60) as client:
        try:
            doc_ids = await _etape_ingestion(client, etl_base, fichiers, livraison_id)
            audit = await _etape_audit(client, audit_base, doc_ids, livraison_id)
            app_id = await _etape_generation(
                client, gen_base, audit["id"], mode, messagerie, livraison_id,
                email_client, contact_client,
            )
            if packager:
                await _etape_packaging(client, gen_base, app_id, livraison_id)
            _maj(livraison_id, statut="livree", etape_courante=None)
        except EchecEtape as e:
            _maj_etape(livraison_id, e.etape, "erreur", str(e))
            _maj(livraison_id, statut="erreur", erreur=f"[{e.etape}] {e}")
        except Exception as e:
            _maj(livraison_id, statut="erreur", erreur=str(e))
