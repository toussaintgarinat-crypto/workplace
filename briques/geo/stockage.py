"""Persistance de la brique geo (SQLite + index spatial R*Tree). Tout est cloisonné par
`tenant` : un tenant ne voit JAMAIS les objets d'un autre (fail-closed, 404 plutôt que
403 → on ne révèle pas l'existence). Le `tenant` est dérivé de la clé API (sha256
tronqué) côté `main.py` : la clé reste le secret, jamais stockée en clair.

Modèle GÉNÉRIQUE : `geo_objects` ne porte que le socle commun à tout point de la Terre
(type, lat/lon, date de référence métier) ; la spécificité vit dans `metadata` (JSON).
Ajouter un type d'objet (immobilier, événement, jeu) = zéro migration.

L'index spatial est une table virtuelle R*Tree (points = boîtes dégénérées lat/lat,
lon/lon) synchronisée par triggers — la recherche par bounding box reste rapide sans
PostGIS (cf. docs/decisions/2026-07-06-geo-sqlite-rtree.md pour les seuils de bascule).

Pur SQL + stdlib (sqlite3, uuid, json). Aucune logique métier ici : les calculs
(fraîcheur, validations) vivent dans `domaine.py`."""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone

_DB = os.getenv("GEO_DB", "/data/geo.db")


def _maintenant() -> str:
    return datetime.now(timezone.utc).isoformat()


def _id() -> str:
    return uuid.uuid4().hex


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(_DB)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def rtree_disponible() -> bool:
    """Vrai si le sqlite3 embarqué compile le module R*Tree (garde testée hors-ligne)."""
    try:
        c = sqlite3.connect(":memory:")
        c.execute("CREATE VIRTUAL TABLE _t USING rtree(id, a, b)")
        c.close()
        return True
    except sqlite3.OperationalError:
        return False


def init() -> None:
    """Crée le schéma si besoin (idempotent)."""
    os.makedirs(os.path.dirname(_DB) or ".", exist_ok=True)
    with _conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS geo_objects (
                id TEXT PRIMARY KEY, tenant TEXT NOT NULL,
                type TEXT NOT NULL DEFAULT 'entreprise',
                latitude REAL NOT NULL, longitude REAL NOT NULL,
                date_reference TEXT,
                source TEXT NOT NULL DEFAULT 'simule',
                ref_externe TEXT,
                metadata TEXT NOT NULL DEFAULT '{}',
                cree_le TEXT NOT NULL, maj_le TEXT NOT NULL);
            -- Clé d'upsert (ex. SIREN) : unique par tenant+type quand elle existe.
            CREATE UNIQUE INDEX IF NOT EXISTS idx_geo_ref
                ON geo_objects(tenant, type, ref_externe) WHERE ref_externe IS NOT NULL;
            CREATE INDEX IF NOT EXISTS idx_geo_tenant_type ON geo_objects(tenant, type);
            CREATE INDEX IF NOT EXISTS idx_geo_cree ON geo_objects(tenant, cree_le);

            -- Index spatial : un point = une boîte dégénérée. id = rowid de geo_objects.
            CREATE VIRTUAL TABLE IF NOT EXISTS geo_rtree
                USING rtree(id, lat_min, lat_max, lon_min, lon_max);

            CREATE TRIGGER IF NOT EXISTS geo_ai AFTER INSERT ON geo_objects BEGIN
                INSERT INTO geo_rtree VALUES
                    (new.rowid, new.latitude, new.latitude, new.longitude, new.longitude);
            END;
            CREATE TRIGGER IF NOT EXISTS geo_au
                AFTER UPDATE OF latitude, longitude ON geo_objects BEGIN
                UPDATE geo_rtree SET lat_min = new.latitude, lat_max = new.latitude,
                                     lon_min = new.longitude, lon_max = new.longitude
                WHERE id = old.rowid;
            END;
            CREATE TRIGGER IF NOT EXISTS geo_ad AFTER DELETE ON geo_objects BEGIN
                DELETE FROM geo_rtree WHERE id = old.rowid;
            END;

            -- Zones de VEILLE : les bbox que l'ingestion nocturne surveille, par tenant.
            CREATE TABLE IF NOT EXISTS geo_zones (
                id TEXT PRIMARY KEY, tenant TEXT NOT NULL, nom TEXT NOT NULL,
                lat_min REAL NOT NULL, lon_min REAL NOT NULL,
                lat_max REAL NOT NULL, lon_max REAL NOT NULL,
                type TEXT NOT NULL DEFAULT 'entreprise',
                naf TEXT,
                active INTEGER NOT NULL DEFAULT 1,
                cree_le TEXT NOT NULL, derniere_ingestion TEXT);
            CREATE INDEX IF NOT EXISTS idx_zones_tenant ON geo_zones(tenant);
            """
        )
        c.executescript(
            """
            -- Journal RGPD des enrichissements (S161) : chaque tentative, réussie ou
            -- non, laisse une trace consultable — opt-in prouvable, jamais de masse.
            CREATE TABLE IF NOT EXISTS geo_enrichissements (
                id TEXT PRIMARY KEY, tenant TEXT NOT NULL, objet_id TEXT NOT NULL,
                quand TEXT NOT NULL, statut TEXT NOT NULL,
                requete TEXT, source_url TEXT, resultat TEXT NOT NULL DEFAULT '{}');
            CREATE INDEX IF NOT EXISTS idx_enrich_tenant
                ON geo_enrichissements(tenant, quand);
            """
        )
        # Migration douce (bases créées avant la colonne `naf`) — idempotent.
        try:
            c.execute("ALTER TABLE geo_zones ADD COLUMN naf TEXT")
        except sqlite3.OperationalError:
            pass  # colonne déjà présente


# Schéma prêt dès l'import (idempotent) : robuste même sans événement de démarrage (TestClient).
init()


def _objet_dict(r: sqlite3.Row) -> dict:
    return {"id": r["id"], "type": r["type"], "latitude": r["latitude"],
            "longitude": r["longitude"], "date_reference": r["date_reference"],
            "source": r["source"], "ref_externe": r["ref_externe"],
            "metadata": json.loads(r["metadata"] or "{}"),
            "cree_le": r["cree_le"], "maj_le": r["maj_le"]}


# ── Objets géolocalisés ──────────────────────────────────────────
def creer_objet(tenant: str, *, type_: str, latitude: float, longitude: float,
                date_reference: str | None = None, source: str = "simule",
                ref_externe: str | None = None, metadata: dict | None = None) -> dict:
    oid = _id()
    now = _maintenant()
    with _conn() as c:
        c.execute(
            "INSERT INTO geo_objects (id, tenant, type, latitude, longitude, date_reference,"
            " source, ref_externe, metadata, cree_le, maj_le) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (oid, tenant, type_, latitude, longitude, date_reference,
             source, ref_externe, json.dumps(metadata or {}, ensure_ascii=False), now, now))
        r = c.execute("SELECT * FROM geo_objects WHERE id = ?", (oid,)).fetchone()
    return _objet_dict(r)


def upsert_objet(tenant: str, *, type_: str, latitude: float, longitude: float,
                 date_reference: str | None = None, source: str = "simule",
                 ref_externe: str | None = None,
                 metadata: dict | None = None) -> tuple[dict, bool]:
    """Insère l'objet, ou le met à jour s'il existe déjà pour (tenant, type, ref_externe).
    Renvoie (objet, nouveau) — `nouveau` sert au décompte des découvertes d'ingestion.
    Sans `ref_externe`, pas de clé d'unicité : c'est une création simple."""
    if not ref_externe:
        return creer_objet(tenant, type_=type_, latitude=latitude, longitude=longitude,
                           date_reference=date_reference, source=source,
                           metadata=metadata), True
    with _conn() as c:
        r = c.execute(
            "SELECT id FROM geo_objects WHERE tenant = ? AND type = ? AND ref_externe = ?",
            (tenant, type_, ref_externe)).fetchone()
        if r:
            c.execute(
                "UPDATE geo_objects SET latitude = ?, longitude = ?, date_reference = ?,"
                " source = ?, metadata = ?, maj_le = ? WHERE id = ?",
                (latitude, longitude, date_reference, source,
                 json.dumps(metadata or {}, ensure_ascii=False), _maintenant(), r["id"]))
            maj = c.execute("SELECT * FROM geo_objects WHERE id = ?", (r["id"],)).fetchone()
            return _objet_dict(maj), False
    return creer_objet(tenant, type_=type_, latitude=latitude, longitude=longitude,
                       date_reference=date_reference, source=source,
                       ref_externe=ref_externe, metadata=metadata), True


def chercher_bbox(tenant: str, bbox: tuple[float, float, float, float], *,
                  type_: str | None = None, date_min: str | None = None,
                  naf: str | None = None, q: str | None = None,
                  limite: int = 2000) -> dict:
    """Objets du tenant dans la bounding box (lat_min, lon_min, lat_max, lon_max), via
    l'index R*Tree. Filtres optionnels : type, date_reference minimale (fraîcheur),
    préfixe NAF et texte sur le nom (json_extract sur metadata). Renvoie
    {objets, nb_total, tronque} — `tronque` prévient le front qu'il faut zoomer."""
    lat_min, lon_min, lat_max, lon_max = bbox
    where = ["o.tenant = ?", "r.lat_min >= ?", "r.lat_max <= ?",
             "r.lon_min >= ?", "r.lon_max <= ?"]
    params: list = [tenant, lat_min, lat_max, lon_min, lon_max]
    if type_:
        where.append("o.type = ?")
        params.append(type_)
    if date_min:
        where.append("o.date_reference >= ?")
        params.append(date_min)
    if naf:
        where.append("json_extract(o.metadata, '$.naf') LIKE ?")
        params.append(f"{naf}%")
    if q:
        where.append("json_extract(o.metadata, '$.nom') LIKE ?")
        params.append(f"%{q}%")
    base = ("FROM geo_objects o JOIN geo_rtree r ON r.id = o.rowid WHERE "
            + " AND ".join(where))
    with _conn() as c:
        nb_total = c.execute(f"SELECT COUNT(*) {base}", params).fetchone()[0]
        lignes = c.execute(
            f"SELECT o.* {base} ORDER BY o.date_reference DESC LIMIT ?",
            params + [limite]).fetchall()
    return {"objets": [_objet_dict(r) for r in lignes],
            "nb_total": nb_total, "tronque": nb_total > limite}


def lire_objet(tenant: str, objet_id: str) -> dict | None:
    with _conn() as c:
        r = c.execute("SELECT * FROM geo_objects WHERE tenant = ? AND id = ?",
                      (tenant, objet_id)).fetchone()
    return _objet_dict(r) if r else None


def maj_metadata(tenant: str, objet_id: str, metadata: dict) -> dict | None:
    with _conn() as c:
        c.execute("UPDATE geo_objects SET metadata = ?, maj_le = ?"
                  " WHERE tenant = ? AND id = ?",
                  (json.dumps(metadata, ensure_ascii=False), _maintenant(),
                   tenant, objet_id))
    return lire_objet(tenant, objet_id)


# ── Journal des enrichissements (transparence RGPD) ──────────────
def journaliser_enrichissement(tenant: str, objet_id: str, *, statut: str,
                               requete: str = "", source_url: str = "",
                               resultat: dict | None = None) -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO geo_enrichissements (id, tenant, objet_id, quand, statut,"
            " requete, source_url, resultat) VALUES (?,?,?,?,?,?,?,?)",
            (_id(), tenant, objet_id, _maintenant(), statut, requete, source_url,
             json.dumps(resultat or {}, ensure_ascii=False)))


def lister_enrichissements(tenant: str, limite: int = 50) -> list[dict]:
    with _conn() as c:
        lignes = c.execute(
            "SELECT * FROM geo_enrichissements WHERE tenant = ?"
            " ORDER BY quand DESC LIMIT ?", (tenant, limite)).fetchall()
    return [{"id": r["id"], "objet_id": r["objet_id"], "quand": r["quand"],
             "statut": r["statut"], "requete": r["requete"],
             "source_url": r["source_url"],
             "resultat": json.loads(r["resultat"] or "{}")} for r in lignes]


# ── Zones de veille ──────────────────────────────────────────────
def _zone_dict(r: sqlite3.Row) -> dict:
    return {"id": r["id"], "nom": r["nom"], "lat_min": r["lat_min"], "lon_min": r["lon_min"],
            "lat_max": r["lat_max"], "lon_max": r["lon_max"], "type": r["type"],
            "naf": r["naf"], "active": bool(r["active"]), "cree_le": r["cree_le"],
            "derniere_ingestion": r["derniere_ingestion"]}


def creer_zone(tenant: str, nom: str, bbox: tuple[float, float, float, float],
               type_: str = "entreprise", naf: str | None = None) -> dict:
    zid = _id()
    with _conn() as c:
        c.execute(
            "INSERT INTO geo_zones (id, tenant, nom, lat_min, lon_min, lat_max, lon_max,"
            " type, naf, cree_le) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (zid, tenant, nom, bbox[0], bbox[1], bbox[2], bbox[3], type_, naf,
             _maintenant()))
        r = c.execute("SELECT * FROM geo_zones WHERE id = ?", (zid,)).fetchone()
    return _zone_dict(r)


def lister_zones(tenant: str, seulement_actives: bool = False) -> list[dict]:
    sql = "SELECT * FROM geo_zones WHERE tenant = ?"
    if seulement_actives:
        sql += " AND active = 1"
    with _conn() as c:
        return [_zone_dict(r) for r in c.execute(sql + " ORDER BY cree_le", (tenant,))]


def supprimer_zone(tenant: str, zone_id: str) -> bool:
    with _conn() as c:
        cur = c.execute("DELETE FROM geo_zones WHERE tenant = ? AND id = ?",
                        (tenant, zone_id))
        return cur.rowcount > 0


def maj_derniere_ingestion(zone_id: str) -> None:
    with _conn() as c:
        c.execute("UPDATE geo_zones SET derniere_ingestion = ? WHERE id = ?",
                  (_maintenant(), zone_id))


def nouveaux_depuis(tenant: str, depuis_iso: str, limite: int = 50) -> list[dict]:
    """Objets DÉCOUVERTS (cree_le, pas date métier) depuis un instant — sert /nouveautes."""
    with _conn() as c:
        lignes = c.execute(
            "SELECT * FROM geo_objects WHERE tenant = ? AND cree_le >= ?"
            " ORDER BY cree_le DESC LIMIT ?",
            (tenant, depuis_iso, limite)).fetchall()
    return [_objet_dict(r) for r in lignes]
