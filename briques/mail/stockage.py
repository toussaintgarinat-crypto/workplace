"""Persistance de la brique mail (SQLite). Tout est cloisonné par `tenant` (empreinte de la
clé API) : un tenant ne voit JAMAIS les comptes, le cache ni les brouillons d'un autre (fail-closed).

Depuis la v0.1.1, un tenant peut connecter **plusieurs boîtes** (perso, pro…). Chaque message du
cache porte son `compte_id` (+ le libellé `compte` = l'adresse), ce qui donne une **boîte unifiée**
filtrable par compte.

Trois tables : `comptes` (N comptes IMAP par tenant — mot de passe **chiffré au repos**),
`messages` (cache de la dernière synchro, tagué par compte) et `brouillons` (réponses préparées,
**jamais envoyées** en v0.1.x).

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


def _colonnes(c: sqlite3.Connection, table: str) -> set[str]:
    return {r["name"] for r in c.execute(f"PRAGMA table_info({table})").fetchall()}


def _table_existe(c: sqlite3.Connection, table: str) -> bool:
    return c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                     (table,)).fetchone() is not None


_SCHEMA = """
CREATE TABLE IF NOT EXISTS comptes (
    id TEXT PRIMARY KEY, tenant TEXT NOT NULL, host TEXT NOT NULL, port INTEGER DEFAULT 993,
    utilisateur TEXT NOT NULL, mdp_chiffre BLOB NOT NULL, dossier TEXT DEFAULT 'INBOX',
    smtp_host TEXT, smtp_port INTEGER, cree_le TEXT, UNIQUE(tenant, utilisateur));
CREATE INDEX IF NOT EXISTS idx_comptes_tenant ON comptes(tenant);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY, tenant TEXT NOT NULL, compte_id TEXT, compte TEXT, uid TEXT,
    de TEXT, de_nom TEXT, sujet TEXT, date TEXT, extrait TEXT, corps TEXT,
    lu INTEGER DEFAULT 0, dossier TEXT DEFAULT 'INBOX',
    categorie TEXT, score INTEGER DEFAULT 0, source TEXT, recu_le TEXT);
CREATE INDEX IF NOT EXISTS idx_msg_tenant ON messages(tenant);

CREATE TABLE IF NOT EXISTS brouillons (
    id TEXT PRIMARY KEY, tenant TEXT NOT NULL, en_reponse_a TEXT, compte_id TEXT, compte TEXT,
    a TEXT, sujet TEXT, corps TEXT, statut TEXT DEFAULT 'brouillon', cree_le TEXT, envoye_le TEXT);
CREATE INDEX IF NOT EXISTS idx_br_tenant ON brouillons(tenant);

CREATE TABLE IF NOT EXISTS filtres (
    id TEXT PRIMARY KEY, tenant TEXT NOT NULL, nom TEXT NOT NULL,
    mots TEXT, expediteur TEXT, cree_le TEXT);
CREATE INDEX IF NOT EXISTS idx_filtres_tenant ON filtres(tenant);
"""


def init() -> None:
    """Crée le schéma si besoin (idempotent) + migre l'ancien schéma mono-compte (v0.1.0)."""
    os.makedirs(os.path.dirname(_DB) or ".", exist_ok=True)
    with _conn() as c:
        # Migration v0.1.0 → v0.1.1 : `comptes` avait `tenant` en clé primaire (un seul compte).
        # On le renomme pour le recréer au nouveau schéma puis recopier les lignes avec un id.
        legacy = _table_existe(c, "comptes") and "id" not in _colonnes(c, "comptes")
        if legacy:
            c.execute("ALTER TABLE comptes RENAME TO comptes_legacy")

        c.executescript(_SCHEMA)

        if legacy:
            for r in c.execute("SELECT * FROM comptes_legacy").fetchall():
                c.execute("INSERT OR IGNORE INTO comptes (id, tenant, host, port, utilisateur, "
                          "mdp_chiffre, dossier, cree_le) VALUES (?,?,?,?,?,?,?,?)",
                          (_id(), r["tenant"], r["host"], r["port"], r["utilisateur"],
                           r["mdp_chiffre"], r["dossier"], r["cree_le"]))
            c.execute("DROP TABLE comptes_legacy")

        # Messages : ajoute les colonnes de tag par compte si elles manquent (DB v0.1.0).
        cols_msg = _colonnes(c, "messages")
        for col in ("compte_id", "compte"):
            if col not in cols_msg:
                c.execute(f"ALTER TABLE messages ADD COLUMN {col} TEXT")

        # Comptes : colonnes SMTP (envoi, v0.2.0) si elles manquent.
        cols_cpt = _colonnes(c, "comptes")
        for col, typ in (("smtp_host", "TEXT"), ("smtp_port", "INTEGER")):
            if col not in cols_cpt:
                c.execute(f"ALTER TABLE comptes ADD COLUMN {col} {typ}")

        # Brouillons : provenance (compte) + cycle de vie d'envoi (v0.2.0) si elles manquent.
        cols_br = _colonnes(c, "brouillons")
        for col, typ in (("compte_id", "TEXT"), ("compte", "TEXT"),
                         ("statut", "TEXT"), ("envoye_le", "TEXT")):
            if col not in cols_br:
                c.execute(f"ALTER TABLE brouillons ADD COLUMN {col} {typ}")


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


# ── Comptes IMAP (plusieurs par tenant) ──────────────────────────────────────
def _compte_dict(r: sqlite3.Row, *, avec_secret: bool = False) -> dict:
    d = {"id": r["id"], "host": r["host"], "port": r["port"], "utilisateur": r["utilisateur"],
         "dossier": r["dossier"], "smtp_host": r["smtp_host"], "smtp_port": r["smtp_port"],
         "cree_le": r["cree_le"]}
    if avec_secret:
        d["mot_de_passe"] = _dechiffrer(r["mdp_chiffre"])
    return d


def enregistrer_compte(tenant: str, host: str, utilisateur: str, mot_de_passe: str,
                       *, port: int = 993, dossier: str = "INBOX",
                       smtp_host: str = "", smtp_port: int = 0) -> dict:
    """Ajoute une boîte au tenant. Réenregistrer la MÊME adresse met à jour ses identifiants
    (contrainte UNIQUE(tenant, utilisateur)) au lieu de créer un doublon. `smtp_host`/`smtp_port`
    (optionnels) servent à l'envoi (v0.2.0) ; vides = devinés depuis l'hôte IMAP au moment d'envoyer."""
    with _conn() as c:
        c.execute(
            "INSERT INTO comptes (id, tenant, host, port, utilisateur, mdp_chiffre, dossier, "
            "smtp_host, smtp_port, cree_le) VALUES (?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(tenant, utilisateur) DO UPDATE SET host=excluded.host, port=excluded.port, "
            "mdp_chiffre=excluded.mdp_chiffre, dossier=excluded.dossier, "
            "smtp_host=excluded.smtp_host, smtp_port=excluded.smtp_port",
            (_id(), tenant, host, port, utilisateur, _chiffrer(mot_de_passe), dossier,
             smtp_host or None, smtp_port or None, _maintenant()))
        r = c.execute("SELECT * FROM comptes WHERE tenant=? AND utilisateur=?",
                      (tenant, utilisateur)).fetchone()
    return _compte_dict(r)


def lister_comptes(tenant: str, *, avec_secret: bool = False) -> list[dict]:
    """Comptes du tenant. Sans secret par défaut (UI/config) ; avec secret pour la synchro."""
    with _conn() as c:
        rows = c.execute("SELECT * FROM comptes WHERE tenant=? ORDER BY cree_le", (tenant,)).fetchall()
    return [_compte_dict(r, avec_secret=avec_secret) for r in rows]


def lire_compte(tenant: str, compte_id: str, *, avec_secret: bool = False) -> dict | None:
    """Un compte précis du tenant (cloisonné : autre tenant → None)."""
    with _conn() as c:
        r = c.execute("SELECT * FROM comptes WHERE tenant=? AND id=?",
                      (tenant, compte_id)).fetchone()
    return _compte_dict(r, avec_secret=avec_secret) if r else None


def supprimer_compte(tenant: str, compte_id: str) -> bool:
    """Déconnecte une boîte (et purge ses messages cachés). Renvoie True si un compte a été retiré."""
    with _conn() as c:
        cur = c.execute("DELETE FROM comptes WHERE tenant=? AND id=?", (tenant, compte_id))
        c.execute("DELETE FROM messages WHERE tenant=? AND compte_id=?", (tenant, compte_id))
        return cur.rowcount > 0


# ── Cache des messages (dernière synchro, boîte unifiée) ─────────────────────
def _inserer(c: sqlite3.Connection, tenant: str, messages: list[dict], now: str) -> None:
    for m in messages:
        c.execute(
            "INSERT INTO messages (id, tenant, compte_id, compte, uid, de, de_nom, sujet, date, "
            "extrait, corps, lu, dossier, categorie, score, source, recu_le) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (_id(), tenant, m.get("compte_id"), m.get("compte", ""), str(m.get("id", "")),
             m.get("de", ""), m.get("de_nom", ""), m.get("sujet", ""), m.get("date", ""),
             m.get("extrait", ""), m.get("corps", ""), 1 if m.get("lu") else 0,
             m.get("dossier", "INBOX"), m.get("categorie", ""), int(m.get("score", 0)),
             m.get("source", ""), now))


def remplacer_messages(tenant: str, messages: list[dict]) -> int:
    """Remplace TOUT le cache du tenant (toutes boîtes). Utilisé en mode mock / après purge."""
    now = _maintenant()
    with _conn() as c:
        c.execute("DELETE FROM messages WHERE tenant=?", (tenant,))
        _inserer(c, tenant, messages, now)
    return len(messages)


def remplacer_messages_compte(tenant: str, compte_id: str | None, messages: list[dict]) -> int:
    """Remplace seulement la part de cache d'UNE boîte (les autres boîtes ne sont pas touchées :
    si une boîte échoue à se synchroniser, son ancien cache est conservé)."""
    now = _maintenant()
    with _conn() as c:
        if compte_id is None:
            c.execute("DELETE FROM messages WHERE tenant=? AND compte_id IS NULL", (tenant,))
        else:
            c.execute("DELETE FROM messages WHERE tenant=? AND compte_id=?", (tenant, compte_id))
        _inserer(c, tenant, messages, now)
    return len(messages)


def _msg_dict(r: sqlite3.Row, *, avec_corps: bool = False) -> dict:
    d = {"id": r["id"], "compte": r["compte"] or "", "uid": r["uid"], "de": r["de"],
         "de_nom": r["de_nom"], "sujet": r["sujet"], "date": r["date"], "extrait": r["extrait"],
         "lu": bool(r["lu"]), "dossier": r["dossier"], "categorie": r["categorie"],
         "score": r["score"], "source": r["source"]}
    if avec_corps:
        d["corps"] = r["corps"]
    return d


def lister_messages(tenant: str, *, non_lus: bool = False, categorie: str = "", compte: str = "",
                    limite: int = 50) -> list[dict]:
    """Boîte unifiée du tenant, triée par score (importance) puis date décroissante.

    Filtres optionnels cumulables : `non_lus`, `categorie` (facture, rendez_vous, personnel,
    notification, newsletter, autre) et `compte` (adresse exacte, ex. « perso@gmail.com »)."""
    sql = "SELECT * FROM messages WHERE tenant=?"
    args: list = [tenant]
    if non_lus:
        sql += " AND lu=0"
    if categorie:
        sql += " AND categorie=?"
        args.append(categorie)
    if compte:
        sql += " AND compte=?"
        args.append(compte)
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


# ── Brouillons (préparés ; envoyés sur validation en v0.2.0) ─────────────────
def enregistrer_brouillon(tenant: str, *, en_reponse_a: str, a: str, sujet: str, corps: str,
                          compte_id: str | None = None, compte: str = "") -> dict:
    """Range un brouillon (statut « brouillon »). `compte`/`compte_id` = la boîte d'où il PARTIRA
    (celle qui a reçu le message d'origine), pour envoyer depuis la bonne adresse."""
    bid = _id()
    with _conn() as c:
        c.execute("INSERT INTO brouillons (id, tenant, en_reponse_a, compte_id, compte, a, sujet, "
                  "corps, statut, cree_le) VALUES (?,?,?,?,?,?,?,?,'brouillon',?)",
                  (bid, tenant, en_reponse_a, compte_id, compte, a, sujet, corps, _maintenant()))
        r = c.execute("SELECT * FROM brouillons WHERE id=?", (bid,)).fetchone()
    return _brouillon_dict(r)


def _brouillon_dict(r: sqlite3.Row) -> dict:
    return {"id": r["id"], "en_reponse_a": r["en_reponse_a"], "compte_id": r["compte_id"],
            "compte": r["compte"] or "", "a": r["a"], "sujet": r["sujet"], "corps": r["corps"],
            "statut": r["statut"] or "brouillon", "cree_le": r["cree_le"], "envoye_le": r["envoye_le"]}


def lire_brouillon(tenant: str, brouillon_id: str) -> dict | None:
    """Un brouillon précis du tenant (cloisonné : autre tenant → None)."""
    with _conn() as c:
        r = c.execute("SELECT * FROM brouillons WHERE id=? AND tenant=?",
                      (brouillon_id, tenant)).fetchone()
    return _brouillon_dict(r) if r else None


def maj_brouillon(tenant: str, brouillon_id: str, *, sujet: str | None = None,
                  corps: str | None = None) -> dict | None:
    """Modifie un brouillon AVANT envoi (la « validation » : l'utilisateur ajuste le texte)."""
    champs, args = [], []
    if sujet is not None:
        champs.append("sujet=?"); args.append(sujet)
    if corps is not None:
        champs.append("corps=?"); args.append(corps)
    if champs:
        with _conn() as c:
            args += [brouillon_id, tenant]
            c.execute(f"UPDATE brouillons SET {', '.join(champs)} WHERE id=? AND tenant=? "
                      "AND statut='brouillon'", args)
    return lire_brouillon(tenant, brouillon_id)


def marquer_brouillon_envoye(tenant: str, brouillon_id: str) -> None:
    with _conn() as c:
        c.execute("UPDATE brouillons SET statut='envoye', envoye_le=? WHERE id=? AND tenant=?",
                  (_maintenant(), brouillon_id, tenant))


def lister_brouillons(tenant: str) -> list[dict]:
    with _conn() as c:
        rows = c.execute("SELECT * FROM brouillons WHERE tenant=? ORDER BY cree_le DESC",
                         (tenant,)).fetchall()
    return [_brouillon_dict(r) for r in rows]


# ── Filtres personnalisés (ex. un filtre par entreprise) ─────────────────────
def _filtre_dict(r: sqlite3.Row) -> dict:
    return {"id": r["id"], "nom": r["nom"],
            "mots": [m for m in (r["mots"] or "").split(",") if m],
            "expediteur": r["expediteur"] or "", "cree_le": r["cree_le"]}


def enregistrer_filtre(tenant: str, *, nom: str, mots: list[str], expediteur: str = "") -> dict:
    """Crée un filtre personnalisé (nom + mots-clés et/ou expéditeur). Pour « les mails par
    entreprise » : un filtre par société, par domaine d'expéditeur (ex. « @acme.com »)."""
    fid = _id()
    with _conn() as c:
        c.execute("INSERT INTO filtres (id, tenant, nom, mots, expediteur, cree_le) "
                  "VALUES (?,?,?,?,?,?)",
                  (fid, tenant, nom.strip(), ",".join(m.strip() for m in mots if m.strip()),
                   expediteur.strip(), _maintenant()))
        r = c.execute("SELECT * FROM filtres WHERE id=?", (fid,)).fetchone()
    return _filtre_dict(r)


def lister_filtres(tenant: str) -> list[dict]:
    with _conn() as c:
        rows = c.execute("SELECT * FROM filtres WHERE tenant=? ORDER BY cree_le", (tenant,)).fetchall()
    return [_filtre_dict(r) for r in rows]


def lire_filtre(tenant: str, filtre_id: str) -> dict | None:
    with _conn() as c:
        r = c.execute("SELECT * FROM filtres WHERE id=? AND tenant=?",
                      (filtre_id, tenant)).fetchone()
    return _filtre_dict(r) if r else None


def resoudre_filtre(tenant: str, ref: str) -> dict | None:
    """Retrouve un filtre par son ID ou, à défaut, par son NOM (insensible à la casse).
    Permet à l'assistant de dire « le filtre Acme » sans connaître l'id technique."""
    f = lire_filtre(tenant, ref)
    if f:
        return f
    cible = (ref or "").strip().lower()
    for f in lister_filtres(tenant):
        if f["nom"].lower() == cible:
            return f
    return None


def supprimer_filtre(tenant: str, filtre_id: str) -> bool:
    with _conn() as c:
        cur = c.execute("DELETE FROM filtres WHERE id=? AND tenant=?", (filtre_id, tenant))
        return cur.rowcount > 0
