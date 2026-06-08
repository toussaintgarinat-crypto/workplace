"""Stockage SQLite des documents ingérés."""

import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

DB_CHEMIN = Path("/data/etl.db")


def _conn() -> sqlite3.Connection:
    DB_CHEMIN.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_CHEMIN)
    con.row_factory = sqlite3.Row
    return con


def initialiser():
    with _conn() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                id            TEXT PRIMARY KEY,
                nom           TEXT NOT NULL,
                source        TEXT NOT NULL,
                type_mime     TEXT,
                taille        INTEGER,
                texte_extrait TEXT,
                metadonnees   TEXT DEFAULT '{}',
                date_ingestion TEXT NOT NULL
            )
        """)


def sauvegarder(
    nom: str,
    source: str,
    type_mime: str | None,
    taille: int,
    texte: str,
    metadonnees: dict | None = None,
) -> str:
    doc_id = str(uuid.uuid4())
    with _conn() as con:
        con.execute(
            """INSERT INTO documents
               (id, nom, source, type_mime, taille, texte_extrait, metadonnees, date_ingestion)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                doc_id,
                nom,
                source,
                type_mime,
                taille,
                texte,
                json.dumps(metadonnees or {}, ensure_ascii=False),
                datetime.utcnow().isoformat(),
            ),
        )
    return doc_id


def importer(doc: dict) -> str:
    """Réinsère un document tel quel (id préservé), SANS ré-extraction.

    Sert à la « reprise » d'un dossier d'entreprise décroché (Sprint S6) : on
    réécrit le texte déjà extrait au lieu de relancer OCR/MarkItDown.
    """
    doc_id = doc.get("id") or str(uuid.uuid4())
    with _conn() as con:
        con.execute(
            """INSERT OR REPLACE INTO documents
               (id, nom, source, type_mime, taille, texte_extrait, metadonnees, date_ingestion)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                doc_id,
                doc.get("nom") or "inconnu",
                doc.get("source") or "import",
                doc.get("type_mime"),
                doc.get("taille") or 0,
                doc.get("texte_extrait") or "",
                json.dumps(doc.get("metadonnees") or {}, ensure_ascii=False),
                doc.get("date_ingestion") or datetime.utcnow().isoformat(),
            ),
        )
    return doc_id


def lister(
    limite: int = 100,
    offset: int = 0,
    categorie: str | None = None,
    projet: str | None = None,
    entreprise_id: str | None = None,
) -> list[dict]:
    """Liste les documents (du plus récent au plus ancien), avec leur `classement`.

    Le classement vit dans `metadonnees.classement` (posé par le Cœur). On le
    remonte tel quel dans chaque ligne et on filtre éventuellement dessus —
    filtrage en Python car SQLite ne sait pas indexer ce JSON ici (volumes faibles).
    """
    with _conn() as con:
        rows = con.execute(
            "SELECT id, nom, source, type_mime, taille, date_ingestion, metadonnees, "
            "LENGTH(texte_extrait) as nb_caracteres "
            "FROM documents ORDER BY date_ingestion DESC",
        ).fetchall()

    docs: list[dict] = []
    for r in rows:
        d = dict(r)
        meta = json.loads(d.pop("metadonnees") or "{}")
        classement = meta.get("classement") or {}
        if categorie and classement.get("categorie") != categorie:
            continue
        if projet and classement.get("projet") != projet:
            continue
        if entreprise_id and classement.get("entreprise_id") != entreprise_id:
            continue
        d["classement"] = classement
        docs.append(d)
    return docs[offset:offset + limite]


def classer(doc_id: str, classement: dict) -> bool:
    """Fusionne `classement` (catégorie, tags, entreprise, projet, résumé) dans les
    métadonnées du document. Renvoie False si le document n'existe pas."""
    with _conn() as con:
        row = con.execute(
            "SELECT metadonnees FROM documents WHERE id = ?", (doc_id,)
        ).fetchone()
        if not row:
            return False
        meta = json.loads(row["metadonnees"] or "{}")
        ancien = meta.get("classement") or {}
        # On ne garde que les champs réellement fournis (None = ne pas écraser).
        ancien.update({k: v for k, v in classement.items() if v is not None})
        meta["classement"] = ancien
        con.execute(
            "UPDATE documents SET metadonnees = ? WHERE id = ?",
            (json.dumps(meta, ensure_ascii=False), doc_id),
        )
    return True


def dossiers() -> dict:
    """Regroupe les documents classés par `projet` et par `categorie` (compteurs)."""
    par_projet: dict[str, int] = {}
    par_categorie: dict[str, int] = {}
    for d in lister(limite=10000):
        c = d.get("classement") or {}
        if c.get("projet"):
            par_projet[c["projet"]] = par_projet.get(c["projet"], 0) + 1
        if c.get("categorie"):
            par_categorie[c["categorie"]] = par_categorie.get(c["categorie"], 0) + 1
    return {"projets": par_projet, "categories": par_categorie}


def lire(doc_id: str) -> dict | None:
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM documents WHERE id = ?", (doc_id,)
        ).fetchone()
    if not row:
        return None
    d = dict(row)
    d["metadonnees"] = json.loads(d["metadonnees"] or "{}")
    return d


def supprimer(doc_id: str) -> bool:
    with _conn() as con:
        nb = con.execute("DELETE FROM documents WHERE id = ?", (doc_id,)).rowcount
    return nb > 0


def compter() -> int:
    with _conn() as con:
        return con.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
