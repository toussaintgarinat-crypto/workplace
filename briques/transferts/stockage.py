"""Persistance de la brique transferts (SQLite + fichiers ciphertext sur disque).

Le serveur ne stocke QUE du binaire opaque (ciphertext) + des métadonnées
(nom, taille, expiration) — jamais de clé, jamais de clair (v1 = toujours
confidentiel/E2E, cf. arbitrage du plan S196 : pas de mode "normal" où le
serveur détiendrait la clé).

Disposition sur disque : FICHIERS_DIR/<transfert_id>/<fichier_id>.partN pendant
l'upload (une partie = un fichier), concaténées en <fichier_id>.bin à la
finalisation (mêmes octets, dans l'ordre — mirrors le "contiguous concatenation
of N chunks" de suitenumerique/transfers, cf. docs/ENCRYPTION.md § What lands
in S3).
"""
from __future__ import annotations

import math
import os
import secrets
import shutil
import sqlite3
import time
import uuid
from pathlib import Path

DB = os.getenv("TRANSFERTS_DB", "/data/transferts.db")
DIR = Path(os.getenv("TRANSFERTS_DIR", "/data/fichiers"))
TAILLE_MAX_OCTETS = int(os.getenv("TAILLE_MAX_OCTETS", str(20 * 1024 ** 3)))

_SURCOUT_PAR_PARTIE = 28  # IV(12) + tag GCM(16) — même constante que encryption.ts


def _conn() -> sqlite3.Connection:
    Path(DB).parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def init_db() -> None:
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS transferts (
                id TEXT PRIMARY KEY, proprietaire TEXT NOT NULL,
                jeton_upload TEXT NOT NULL, jeton_public TEXT UNIQUE,
                statut TEXT NOT NULL DEFAULT 'brouillon',
                cree_le REAL NOT NULL, expire_le REAL NOT NULL,
                telecharge_fois INTEGER NOT NULL DEFAULT 0)
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_transferts_proprietaire ON transferts(proprietaire)")
        c.execute("""
            CREATE TABLE IF NOT EXISTS fichiers (
                id TEXT PRIMARY KEY, transfert_id TEXT NOT NULL,
                nom TEXT NOT NULL, type_mime TEXT NOT NULL,
                taille_clair INTEGER NOT NULL, taille_partie INTEGER NOT NULL,
                nb_parties INTEGER NOT NULL,
                FOREIGN KEY (transfert_id) REFERENCES transferts(id))
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_fichiers_transfert ON fichiers(transfert_id)")
        c.execute("""
            CREATE TABLE IF NOT EXISTS parties (
                fichier_id TEXT NOT NULL, numero INTEGER NOT NULL, taille INTEGER NOT NULL,
                PRIMARY KEY (fichier_id, numero))
        """)


def _repertoire_transfert(transfert_id: str) -> Path:
    d = DIR / transfert_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _chemin_partie(transfert_id: str, fichier_id: str, numero: int) -> Path:
    return _repertoire_transfert(transfert_id) / f"{fichier_id}.part{numero}"


def chemin_ciphertext(transfert_id: str, fichier_id: str) -> Path:
    return _repertoire_transfert(transfert_id) / f"{fichier_id}.bin"


def creer_transfert(proprietaire: str, expiration_heures: float) -> dict:
    tid = uuid.uuid4().hex
    jeton_upload = secrets.token_urlsafe(32)
    maintenant = time.time()
    expire_le = maintenant + expiration_heures * 3600
    with _conn() as c:
        c.execute(
            "INSERT INTO transferts (id, proprietaire, jeton_upload, statut, cree_le, expire_le) "
            "VALUES (?, ?, ?, 'brouillon', ?, ?)",
            (tid, proprietaire, jeton_upload, maintenant, expire_le),
        )
    return {"id": tid, "jeton_upload": jeton_upload, "expire_le": expire_le}


def _transfert_brouillon(c: sqlite3.Connection, transfert_id: str, jeton_upload: str) -> sqlite3.Row:
    row = c.execute("SELECT * FROM transferts WHERE id = ?", (transfert_id,)).fetchone()
    if not row:
        raise ValueError("Transfert introuvable.")
    if row["jeton_upload"] != jeton_upload:
        raise ValueError("jeton d'upload invalide.")
    if row["statut"] != "brouillon":
        raise ValueError(f"Transfert déjà {row['statut']} (plus modifiable).")
    return row


def ajouter_fichier(transfert_id: str, jeton_upload: str, nom: str, type_mime: str,
                     taille_clair: int, taille_partie: int) -> dict:
    if taille_clair > TAILLE_MAX_OCTETS:
        raise ValueError(f"Fichier trop volumineux ({taille_clair} > {TAILLE_MAX_OCTETS} octets).")
    if taille_clair < 0 or taille_partie <= 0:
        raise ValueError("Taille de fichier ou de partie invalide.")
    nb_parties = 1 if taille_clair == 0 else math.ceil(taille_clair / taille_partie)
    with _conn() as c:
        _transfert_brouillon(c, transfert_id, jeton_upload)
        fid = uuid.uuid4().hex
        c.execute(
            "INSERT INTO fichiers (id, transfert_id, nom, type_mime, taille_clair, taille_partie, nb_parties) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (fid, transfert_id, nom, type_mime, taille_clair, taille_partie, nb_parties),
        )
    return {"id": fid, "nb_parties": nb_parties}


def ecrire_partie(transfert_id: str, fichier_id: str, jeton_upload: str,
                   numero: int, donnees: bytes) -> dict:
    with _conn() as c:
        _transfert_brouillon(c, transfert_id, jeton_upload)
        f = c.execute("SELECT * FROM fichiers WHERE id = ? AND transfert_id = ?",
                       (fichier_id, transfert_id)).fetchone()
        if not f:
            raise ValueError("Fichier introuvable dans ce transfert.")
        if not (0 <= numero < f["nb_parties"]):
            raise ValueError(f"Numéro de partie hors bornes (0..{f['nb_parties'] - 1}).")
        _chemin_partie(transfert_id, fichier_id, numero).write_bytes(donnees)
        c.execute(
            "INSERT INTO parties (fichier_id, numero, taille) VALUES (?, ?, ?) "
            "ON CONFLICT(fichier_id, numero) DO UPDATE SET taille = excluded.taille",
            (fichier_id, numero, len(donnees)),
        )
        recues = c.execute("SELECT COUNT(*) AS n FROM parties WHERE fichier_id = ?",
                            (fichier_id,)).fetchone()["n"]
    return {"parties_recues": recues, "nb_parties": f["nb_parties"], "complet": recues == f["nb_parties"]}


def finaliser_transfert(transfert_id: str, jeton_upload: str) -> dict:
    with _conn() as c:
        _transfert_brouillon(c, transfert_id, jeton_upload)
        fichiers = c.execute("SELECT * FROM fichiers WHERE transfert_id = ?",
                              (transfert_id,)).fetchall()
        if not fichiers:
            raise ValueError("Aucun fichier ajouté à ce transfert.")
        for f in fichiers:
            recues = c.execute("SELECT COUNT(*) AS n FROM parties WHERE fichier_id = ?",
                                (f["id"],)).fetchone()["n"]
            if recues != f["nb_parties"]:
                raise ValueError(f"Fichier '{f['nom']}' pas complet ({recues}/{f['nb_parties']} parties).")

        for f in fichiers:
            cible = chemin_ciphertext(transfert_id, f["id"])
            with open(cible, "wb") as out:
                for n in range(f["nb_parties"]):
                    partie = _chemin_partie(transfert_id, f["id"], n)
                    out.write(partie.read_bytes())
                    partie.unlink()

        jeton_public = secrets.token_urlsafe(24)
        c.execute("UPDATE transferts SET statut = 'actif', jeton_public = ? WHERE id = ?",
                  (jeton_public, transfert_id))
    return {"jeton_public": jeton_public}


def lire_transfert_public(jeton_public: str) -> dict | None:
    with _conn() as c:
        t = c.execute("SELECT * FROM transferts WHERE jeton_public = ?", (jeton_public,)).fetchone()
        if not t:
            return None
        fichiers = c.execute(
            "SELECT id, nom, type_mime, taille_clair, taille_partie FROM fichiers WHERE transfert_id = ?",
            (t["id"],)).fetchall()
    statut = t["statut"]
    if statut == "actif" and t["expire_le"] <= time.time():
        statut = "expire"
    return {
        "id": t["id"], "statut": statut, "expire_le": t["expire_le"],
        "fichiers": [dict(f) for f in fichiers],
    }


def enregistrer_telechargement(transfert_id: str) -> None:
    with _conn() as c:
        c.execute("UPDATE transferts SET telecharge_fois = telecharge_fois + 1 WHERE id = ?",
                  (transfert_id,))


def lister_transferts(proprietaire: str) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT id, statut, cree_le, expire_le, telecharge_fois FROM transferts "
            "WHERE proprietaire = ? AND statut != 'revoque' ORDER BY cree_le DESC",
            (proprietaire,)).fetchall()
    return [dict(r) for r in rows]


def _supprimer_disque(transfert_id: str) -> None:
    d = DIR / transfert_id
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)


def revoquer(transfert_id: str, proprietaire: str) -> bool:
    with _conn() as c:
        t = c.execute("SELECT * FROM transferts WHERE id = ? AND proprietaire = ?",
                       (transfert_id, proprietaire)).fetchone()
        if not t:
            return False
        c.execute("DELETE FROM parties WHERE fichier_id IN "
                  "(SELECT id FROM fichiers WHERE transfert_id = ?)", (transfert_id,))
        c.execute("DELETE FROM fichiers WHERE transfert_id = ?", (transfert_id,))
        c.execute("DELETE FROM transferts WHERE id = ?", (transfert_id,))
    _supprimer_disque(transfert_id)
    return True


def purger_expires() -> int:
    maintenant = time.time()
    with _conn() as c:
        expires = c.execute(
            "SELECT id FROM transferts WHERE expire_le <= ? OR statut = 'revoque'",
            (maintenant,)).fetchall()
        ids = [r["id"] for r in expires]
        if ids:
            marks = ",".join("?" * len(ids))
            c.execute(f"DELETE FROM parties WHERE fichier_id IN "
                      f"(SELECT id FROM fichiers WHERE transfert_id IN ({marks}))", ids)
            c.execute(f"DELETE FROM fichiers WHERE transfert_id IN ({marks})", ids)
            c.execute(f"DELETE FROM transferts WHERE id IN ({marks})", ids)
    for tid in ids:
        _supprimer_disque(tid)
    return len(ids)
