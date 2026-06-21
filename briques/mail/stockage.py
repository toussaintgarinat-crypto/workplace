"""Persistance de la brique mail (SQLite). Tout est cloisonné par `tenant` (empreinte de la
clé API) : un tenant ne voit JAMAIS le compte, le cache ni les brouillons d'un autre (fail-closed).

Trois tables : `comptes` (un compte IMAP par tenant — mot de passe **chiffré au repos**),
`messages` (cache de la dernière synchro, pour répondre vite sans rouvrir IMAP) et `brouillons`
(réponses préparées, **jamais envoyées** en v0.1.0).

Le mot de passe d'application est chiffré en **AES-GCM** (clé = SHA-256 de `MAIL_VAULT_SECRET`,
nonce de 12 octets préfixé), même motif que `briques/agenda/.../vault.py`. Sans `MAIL_VAULT_SECRET`,
toute écriture d'un compte lève : on ne stocke jamais un secret en clair par accident. Honnêteté :
c'est du chiffrement **au repos**, pas du bout-en-bout.
"""
from __future__ import annotations

import hashlib
import os
import sqlite3
import uuid
from datetime import datetime, timezone

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_DB = os.getenv("MAIL_DB", "/data/mail.db")


def _maintenant() -> str:
    return datetime.now(timezone.utc).isoformat()


def _id() -> str:
    return uuid.uuid4().hex


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(_DB)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def init() -> None:
    """Crée le schéma si besoin (idempotent)."""
    os.makedirs(os.path.dirname(_DB) or ".", exist_ok=True)
    with _conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS comptes (
                tenant TEXT PRIMARY KEY, host TEXT NOT NULL, port INTEGER DEFAULT 993,
                utilisateur TEXT NOT NULL, mdp_chiffre BLOB NOT NULL,
                dossier TEXT DEFAULT 'INBOX', cree_le TEXT);

            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY, tenant TEXT NOT NULL, uid TEXT,
                de TEXT, de_nom TEXT, sujet TEXT, date TEXT, extrait TEXT, corps TEXT,
                lu INTEGER DEFAULT 0, dossier TEXT DEFAULT 'INBOX',
                categorie TEXT, score INTEGER DEFAULT 0, source TEXT, recu_le TEXT);
            CREATE INDEX IF NOT EXISTS idx_msg_tenant ON messages(tenant);

            CREATE TABLE IF NOT EXISTS brouillons (
                id TEXT PRIMARY KEY, tenant TEXT NOT NULL, en_reponse_a TEXT,
                a TEXT, sujet TEXT, corps TEXT, cree_le TEXT);
            CREATE INDEX IF NOT EXISTS idx_br_tenant ON brouillons(tenant);
            """
        )


init()  # schéma prêt dès l'import (robuste même sous TestClient)


# ── Chiffrement du mot de passe (AES-GCM au repos) ───────────────────────────
def _cle() -> bytes:
    secret = os.getenv("MAIL_VAULT_SECRET")
    if not secret:
        raise RuntimeError("MAIL_VAULT_SECRET absent — impossible de chiffrer le mot de passe IMAP.")
    return hashlib.sha256(secret.encode()).digest()


def _chiffrer(clair: str) -> bytes:
    aes = AESGCM(_cle())
    nonce = os.urandom(12)
    return nonce + aes.encrypt(nonce, clair.encode(), None)


def _dechiffrer(blob: bytes) -> str:
    aes = AESGCM(_cle())
    blob = bytes(blob)
    return aes.decrypt(blob[:12], blob[12:], None).decode()


# ── Comptes IMAP (un par tenant) ─────────────────────────────────────────────
def enregistrer_compte(tenant: str, host: str, utilisateur: str, mot_de_passe: str,
                       *, port: int = 993, dossier: str = "INBOX") -> dict:
    """Crée/remplace le compte IMAP du tenant (mot de passe chiffré)."""
    with _conn() as c:
        c.execute(
            "INSERT INTO comptes (tenant, host, port, utilisateur, mdp_chiffre, dossier, cree_le) "
            "VALUES (?,?,?,?,?,?,?) ON CONFLICT(tenant) DO UPDATE SET "
            "host=excluded.host, port=excluded.port, utilisateur=excluded.utilisateur, "
            "mdp_chiffre=excluded.mdp_chiffre, dossier=excluded.dossier",
            (tenant, host, port, utilisateur, _chiffrer(mot_de_passe), dossier, _maintenant()))
    return lire_compte(tenant) or {}


def lire_compte(tenant: str, *, avec_secret: bool = False) -> dict | None:
    """Compte du tenant. Par défaut SANS le mot de passe (pour /config, l'UI). Avec
    `avec_secret=True` (usage interne : connexion IMAP), le mot de passe est déchiffré."""
    with _conn() as c:
        r = c.execute("SELECT * FROM comptes WHERE tenant=?", (tenant,)).fetchone()
    if not r:
        return None
    compte = {"host": r["host"], "port": r["port"], "utilisateur": r["utilisateur"],
              "dossier": r["dossier"], "cree_le": r["cree_le"]}
    if avec_secret:
        compte["mot_de_passe"] = _dechiffrer(r["mdp_chiffre"])
    return compte


def supprimer_compte(tenant: str) -> None:
    with _conn() as c:
        c.execute("DELETE FROM comptes WHERE tenant=?", (tenant,))


# ── Cache des messages (dernière synchro) ────────────────────────────────────
def remplacer_messages(tenant: str, messages: list[dict]) -> int:
    """Remplace le cache du tenant par la liste fournie (déjà enrichie : categorie+score)."""
    now = _maintenant()
    with _conn() as c:
        c.execute("DELETE FROM messages WHERE tenant=?", (tenant,))
        for m in messages:
            c.execute(
                "INSERT INTO messages (id, tenant, uid, de, de_nom, sujet, date, extrait, corps, "
                "lu, dossier, categorie, score, source, recu_le) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (_id(), tenant, str(m.get("id", "")), m.get("de", ""), m.get("de_nom", ""),
                 m.get("sujet", ""), m.get("date", ""), m.get("extrait", ""), m.get("corps", ""),
                 1 if m.get("lu") else 0, m.get("dossier", "INBOX"), m.get("categorie", ""),
                 int(m.get("score", 0)), m.get("source", ""), now))
    return len(messages)


def _msg_dict(r: sqlite3.Row, *, avec_corps: bool = False) -> dict:
    d = {"id": r["id"], "uid": r["uid"], "de": r["de"], "de_nom": r["de_nom"],
         "sujet": r["sujet"], "date": r["date"], "extrait": r["extrait"], "lu": bool(r["lu"]),
         "dossier": r["dossier"], "categorie": r["categorie"], "score": r["score"],
         "source": r["source"]}
    if avec_corps:
        d["corps"] = r["corps"]
    return d


def lister_messages(tenant: str, *, non_lus: bool = False, categorie: str = "",
                    limite: int = 50) -> list[dict]:
    """Cache du tenant, trié par score (importance) puis date décroissante.

    Filtres optionnels : `non_lus` (cumulable) et `categorie` (facture, rendez_vous, personnel,
    notification, newsletter, autre) pour ne montrer qu'un type de mails."""
    sql = "SELECT * FROM messages WHERE tenant=?"
    args: list = [tenant]
    if non_lus:
        sql += " AND lu=0"
    if categorie:
        sql += " AND categorie=?"
        args.append(categorie)
    sql += " ORDER BY score DESC, date DESC LIMIT ?"
    args.append(limite)
    with _conn() as c:
        rows = c.execute(sql, args).fetchall()
    return [_msg_dict(r) for r in rows]


def lire_message(tenant: str, message_id: str) -> dict | None:
    """Un message complet (avec corps). Cloisonné : autre tenant → None (invisible)."""
    with _conn() as c:
        r = c.execute("SELECT * FROM messages WHERE id=? AND tenant=?",
                      (message_id, tenant)).fetchone()
    return _msg_dict(r, avec_corps=True) if r else None


def expediteurs_connus(tenant: str) -> set[str]:
    """Adresses déjà vues pour ce tenant (sert le score : on connaît l'expéditeur)."""
    with _conn() as c:
        rows = c.execute("SELECT DISTINCT de FROM messages WHERE tenant=? AND de<>''",
                         (tenant,)).fetchall()
    return {r["de"] for r in rows}


# ── Brouillons (préparés, jamais envoyés en v0.1.0) ──────────────────────────
def enregistrer_brouillon(tenant: str, *, en_reponse_a: str, a: str, sujet: str,
                          corps: str) -> dict:
    bid = _id()
    with _conn() as c:
        c.execute("INSERT INTO brouillons (id, tenant, en_reponse_a, a, sujet, corps, cree_le) "
                  "VALUES (?,?,?,?,?,?,?)",
                  (bid, tenant, en_reponse_a, a, sujet, corps, _maintenant()))
        r = c.execute("SELECT * FROM brouillons WHERE id=?", (bid,)).fetchone()
    return _brouillon_dict(r)


def _brouillon_dict(r: sqlite3.Row) -> dict:
    return {"id": r["id"], "en_reponse_a": r["en_reponse_a"], "a": r["a"],
            "sujet": r["sujet"], "corps": r["corps"], "cree_le": r["cree_le"]}


def lister_brouillons(tenant: str) -> list[dict]:
    with _conn() as c:
        rows = c.execute("SELECT * FROM brouillons WHERE tenant=? ORDER BY cree_le DESC",
                         (tenant,)).fetchall()
    return [_brouillon_dict(r) for r in rows]
