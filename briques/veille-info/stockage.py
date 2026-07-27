"""Persistance de la brique veille-info (SQLite). Cloisonné par `user_id` : une personne ne
voit jamais les sources, articles ni digests d'une autre — même motif que `briques/mail`.

Trois tables : `sources` (flux RSS suivis, taguées par `thematique`), `articles` (dédup par
`(user_id, url)`) et `digests` (un résumé par jour, par personne et par thématique —
`UNIQUE(user_id, thematique, date)` porte l'idempotence de la tâche horloge, cf. `digest.py`)."""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone

_DB = os.getenv("VEILLE_INFO_DB", "/data/veille_info.db")


def _maintenant() -> str:
    return datetime.now(timezone.utc).isoformat()


def _aujourdhui() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(_DB)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


_SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    nom TEXT NOT NULL,
    url TEXT NOT NULL,
    thematique TEXT NOT NULL DEFAULT '',
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    echecs_consecutifs INTEGER NOT NULL DEFAULT 0,
    dernier_echec TEXT
);
CREATE INDEX IF NOT EXISTS idx_sources_user ON sources(user_id);

CREATE TABLE IF NOT EXISTS articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    source_id INTEGER NOT NULL REFERENCES sources(id),
    titre TEXT NOT NULL,
    url TEXT NOT NULL,
    published_at TEXT,
    created_at TEXT NOT NULL,
    digested INTEGER NOT NULL DEFAULT 0,
    UNIQUE(user_id, url)
);
CREATE INDEX IF NOT EXISTS idx_articles_user ON articles(user_id);

CREATE TABLE IF NOT EXISTS digests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    thematique TEXT NOT NULL DEFAULT '',
    date TEXT NOT NULL,
    texte_resume TEXT NOT NULL,
    nb_articles INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(user_id, thematique, date)
);
CREATE INDEX IF NOT EXISTS idx_digests_user ON digests(user_id);

CREATE TABLE IF NOT EXISTS digest_audio (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    digest_id INTEGER NOT NULL REFERENCES digests(id),
    url TEXT NOT NULL,
    duree REAL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_digest_audio_digest ON digest_audio(digest_id);

CREATE TABLE IF NOT EXISTS veille_audio_global (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    jeton TEXT NOT NULL UNIQUE,
    ordre_thematiques TEXT NOT NULL,
    fichier_path TEXT NOT NULL,
    duree_secondes REAL,
    expire_le TEXT NOT NULL,
    cree_le TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audio_global_user ON veille_audio_global(user_id);
CREATE INDEX IF NOT EXISTS idx_audio_global_jeton ON veille_audio_global(jeton);

CREATE TABLE IF NOT EXISTS veille_audio_global_envois (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    audio_global_id INTEGER NOT NULL REFERENCES veille_audio_global(id),
    destinataire TEXT NOT NULL,
    statut TEXT NOT NULL,
    detail TEXT,
    envoye_le TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_envois_audio_global ON veille_audio_global_envois(audio_global_id);
"""


def _migrer_thematiques(c: sqlite3.Connection) -> None:
    """Met à niveau une base créée AVANT l'ajout de `thematique` (S199). `sources` : simple
    ALTER TABLE ADD COLUMN. `digests` : nécessite de recréer la table, SQLite ne permet pas
    de modifier une contrainte UNIQUE existante via ALTER TABLE. No-op sur une base déjà à
    jour (CREATE TABLE IF NOT EXISTS de `_SCHEMA` l'a créée directement dans sa forme finale)."""
    cols_sources = {r[1] for r in c.execute("PRAGMA table_info(sources)").fetchall()}
    if "thematique" not in cols_sources:
        c.execute("ALTER TABLE sources ADD COLUMN thematique TEXT NOT NULL DEFAULT ''")

    cols_digests = {r[1] for r in c.execute("PRAGMA table_info(digests)").fetchall()}
    if "thematique" not in cols_digests:
        # legacy_alter_table=ON le temps du RENAME : sinon SQLite réécrit silencieusement les
        # clauses REFERENCES des AUTRES tables (ex. digest_audio) vers "digests_old", table
        # droppée deux lignes plus bas — laissant digest_audio pointer dans le vide.
        c.execute("PRAGMA legacy_alter_table = ON")
        c.executescript("""
            ALTER TABLE digests RENAME TO digests_old;
            CREATE TABLE digests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                thematique TEXT NOT NULL DEFAULT '',
                date TEXT NOT NULL,
                texte_resume TEXT NOT NULL,
                nb_articles INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(user_id, thematique, date)
            );
            INSERT INTO digests (id, user_id, thematique, date, texte_resume, nb_articles, created_at)
                SELECT id, user_id, '', date, texte_resume, nb_articles, created_at FROM digests_old;
            DROP TABLE digests_old;
            CREATE INDEX IF NOT EXISTS idx_digests_user ON digests(user_id);
        """)
        c.execute("PRAGMA legacy_alter_table = OFF")


def _migrer_echecs(c: sqlite3.Connection) -> None:
    """Met à niveau une base créée AVANT le suivi des sources en panne. No-op sur une base
    déjà à jour (`_SCHEMA` crée les colonnes directement)."""
    cols = {r[1] for r in c.execute("PRAGMA table_info(sources)").fetchall()}
    if "echecs_consecutifs" not in cols:
        c.execute("ALTER TABLE sources ADD COLUMN echecs_consecutifs INTEGER NOT NULL DEFAULT 0")
    if "dernier_echec" not in cols:
        c.execute("ALTER TABLE sources ADD COLUMN dernier_echec TEXT")


def init() -> None:
    os.makedirs(os.path.dirname(_DB) or ".", exist_ok=True)
    with _conn() as c:
        c.executescript(_SCHEMA)
        _migrer_thematiques(c)
        _migrer_echecs(c)


init()  # schéma prêt dès l'import (robuste même sous TestClient)


# ── Sources ───────────────────────────────────────────────────
def _source_dict(r: sqlite3.Row) -> dict:
    return {"id": r["id"], "nom": r["nom"], "url": r["url"], "thematique": r["thematique"],
            "enabled": bool(r["enabled"]), "created_at": r["created_at"],
            "echecs_consecutifs": r["echecs_consecutifs"], "dernier_echec": r["dernier_echec"]}


def creer_source(user_id: str, nom: str, url: str, thematique: str = "") -> dict:
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO sources (user_id, nom, url, thematique, enabled, created_at) "
            "VALUES (?,?,?,?,1,?)",
            (user_id, nom, url, thematique, _maintenant()))
        row = c.execute("SELECT * FROM sources WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _source_dict(row)


def lister_sources(user_id: str, *, actives_seulement: bool = False) -> list[dict]:
    q = "SELECT * FROM sources WHERE user_id = ?"
    if actives_seulement:
        q += " AND enabled = 1"
    q += " ORDER BY created_at DESC"
    with _conn() as c:
        rows = c.execute(q, (user_id,)).fetchall()
    return [_source_dict(r) for r in rows]


def supprimer_source(user_id: str, source_id: int) -> bool:
    with _conn() as c:
        cur = c.execute("DELETE FROM sources WHERE id = ? AND user_id = ?", (source_id, user_id))
    return cur.rowcount > 0


def enregistrer_echec_source(source_id: int, message: str) -> int:
    """Incrémente le compteur d'échecs CONSÉCUTIFS de la source et renvoie sa nouvelle valeur.

    Sert à rendre visibles les flux morts : un feed qui répond 404 depuis des semaines était
    jusqu'ici retenté à chaque digest, ne remontait jamais rien, et n'existait que sous forme
    d'un `logger.warning` que personne ne lit. On ne désactive PAS la source pour autant :
    `enabled` est piloté par la pause/reprise d'une THÉMATIQUE ENTIÈRE
    (`basculer_pause_thematique`), qui écraserait la décision — et aucune route ne permet de
    réactiver une source seule. C'est donc à l'humain de trancher, depuis l'atelier."""
    with _conn() as c:
        c.execute("UPDATE sources SET echecs_consecutifs = echecs_consecutifs + 1, "
                  "dernier_echec = ? WHERE id = ?", (message[:300], source_id))
        row = c.execute("SELECT echecs_consecutifs FROM sources WHERE id = ?",
                        (source_id,)).fetchone()
    return row["echecs_consecutifs"] if row else 0


def reinitialiser_echecs_source(source_id: int) -> None:
    """Un fetch réussi efface l'ardoise : le compteur mesure les échecs CONSÉCUTIFS."""
    with _conn() as c:
        c.execute("UPDATE sources SET echecs_consecutifs = 0, dernier_echec = NULL "
                  "WHERE id = ? AND echecs_consecutifs > 0", (source_id,))


def lister_user_ids_actifs() -> list[str]:
    with _conn() as c:
        rows = c.execute("SELECT DISTINCT user_id FROM sources WHERE enabled = 1").fetchall()
    return [r["user_id"] for r in rows]


def thematiques_actives(user_id: str) -> list[str]:
    with _conn() as c:
        rows = c.execute(
            "SELECT DISTINCT thematique FROM sources WHERE user_id = ? AND enabled = 1",
            (user_id,)).fetchall()
    return [r["thematique"] for r in rows]


def modifier_url_source(user_id: str, source_id: int, url: str) -> bool:
    """Corrige l'URL d'une source SANS perdre son historique (S203).

    Les flux bougent tout le temps — sur les 5 sources « Cosmétique », 3 avaient simplement
    déménagé (mauvais TLD, chemin changé, site migré). Sans cette route, corriger une URL
    imposait de supprimer puis recréer la source, donc de casser le lien `articles.source_id`
    et de perdre l'antériorité. Remet aussi le compteur d'échecs à zéro : une nouvelle URL
    mérite une nouvelle chance."""
    with _conn() as c:
        cur = c.execute(
            "UPDATE sources SET url = ?, echecs_consecutifs = 0, dernier_echec = NULL "
            "WHERE id = ? AND user_id = ?", (url, source_id, user_id))
    return cur.rowcount > 0


def basculer_source_active(user_id: str, source_id: int, active: bool) -> bool:
    """Allume ou éteint UNE source (S203).

    Jusqu'ici `enabled` ne se pilotait qu'au niveau d'une thématique entière
    (`basculer_pause_thematique`) : impossible d'éteindre le seul flux mort d'un groupe
    sain, et impossible de rallumer quoi que ce soit individuellement. C'est ce qui
    interdisait de désactiver automatiquement une source en panne — on aurait laissé
    l'utilisateur devant un interrupteur qui n'existe pas.

    Attention, la contrainte demeure : « Reprendre » sur la thématique rallume TOUTES ses
    sources, y compris celles éteintes ici. C'est cohérent (un geste explicite sur le groupe
    l'emporte sur un geste sur l'élément), mais ça reste le point à trancher avant toute
    extinction automatique."""
    with _conn() as c:
        cur = c.execute("UPDATE sources SET enabled = ? WHERE id = ? AND user_id = ?",
                        (1 if active else 0, source_id, user_id))
    return cur.rowcount > 0


def retagger_source(user_id: str, source_id: int, thematique: str) -> bool:
    with _conn() as c:
        cur = c.execute("UPDATE sources SET thematique = ? WHERE id = ? AND user_id = ?",
                        (thematique, source_id, user_id))
    return cur.rowcount > 0


def lister_thematiques(user_id: str) -> list[dict]:
    """Regroupe les sources de `user_id` par thématique. `en_pause` vaut True quand AUCUNE
    source du groupe n'est active — cohérent avec `thematiques_actives()` (S199), qui
    inclut une thématique dès qu'UNE seule de ses sources est active."""
    with _conn() as c:
        rows = c.execute(
            "SELECT thematique, COUNT(*) AS nb_sources, SUM(enabled) AS nb_actives "
            "FROM sources WHERE user_id = ? GROUP BY thematique", (user_id,)).fetchall()
    return [{"thematique": r["thematique"], "nb_sources": r["nb_sources"],
            "en_pause": (r["nb_actives"] or 0) == 0} for r in rows]


def basculer_pause_thematique(user_id: str, thematique: str, en_pause: bool) -> int:
    """Met en pause (enabled=0) ou reprend (enabled=1) TOUTES les sources de cette
    thématique pour cet utilisateur. Renvoie le nombre de sources affectées (0 = thématique
    inconnue pour cet utilisateur)."""
    with _conn() as c:
        cur = c.execute(
            "UPDATE sources SET enabled = ? WHERE user_id = ? AND thematique = ?",
            (0 if en_pause else 1, user_id, thematique))
    return cur.rowcount


def lister_sources_thematique(user_id: str, thematique: str) -> list[dict]:
    """Sources d'une thématique donnée pour cet utilisateur, actives OU en pause — utilisé
    pour forcer le fetch d'une thématique explicitement choisie (génération ponctuelle,
    S200), contrairement à lister_sources(actives_seulement=True) qui ne verrait rien si
    toutes les sources de la thématique sont en pause."""
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM sources WHERE user_id = ? AND thematique = ?",
            (user_id, thematique)).fetchall()
    return [_source_dict(r) for r in rows]


def lister_user_ids_thematique(thematique: str) -> list[str]:
    """Utilisateurs ayant au moins une source (active ou en pause) dans cette thématique.
    Contrairement à lister_user_ids_actifs(), n'exclut pas quelqu'un dont la seule
    thématique concernée est en pause (S200 — génération ponctuelle forcée)."""
    with _conn() as c:
        rows = c.execute(
            "SELECT DISTINCT user_id FROM sources WHERE thematique = ?",
            (thematique,)).fetchall()
    return [r["user_id"] for r in rows]


# ── Articles ──────────────────────────────────────────────────
def inserer_article(user_id: str, source_id: int, titre: str, url: str,
                    published_at: str) -> bool:
    """Insère un article. Renvoie False si déjà présent pour cet utilisateur (dédup par URL)."""
    with _conn() as c:
        cur = c.execute(
            "INSERT OR IGNORE INTO articles (user_id, source_id, titre, url, published_at, "
            "created_at) VALUES (?,?,?,?,?,?)",
            (user_id, source_id, titre, url, published_at, _maintenant()))
    return cur.rowcount > 0


def articles_non_digestes(user_id: str, thematique: str | None = None) -> list[dict]:
    """`thematique=None` (défaut) : tous les articles non digérés, toutes thématiques
    confondues (comportement historique). Une valeur précise (y compris `""`) filtre sur
    cette thématique via jointure `sources` — c'est ce qu'utilise digest.py, qui traite
    thématique par thématique."""
    if thematique is None:
        with _conn() as c:
            rows = c.execute(
                "SELECT * FROM articles WHERE user_id = ? AND digested = 0 ORDER BY created_at ASC",
                (user_id,)).fetchall()
    else:
        with _conn() as c:
            rows = c.execute(
                "SELECT a.* FROM articles a JOIN sources s ON s.id = a.source_id "
                "WHERE a.user_id = ? AND a.digested = 0 AND s.thematique = ? "
                "ORDER BY a.created_at ASC",
                (user_id, thematique)).fetchall()
    return [{"id": r["id"], "titre": r["titre"], "url": r["url"],
            "published_at": r["published_at"]} for r in rows]


def marquer_articles_digestes(article_ids: list[int]) -> None:
    if not article_ids:
        return
    placeholders = ",".join("?" * len(article_ids))
    with _conn() as c:
        c.execute(f"UPDATE articles SET digested = 1 WHERE id IN ({placeholders})", article_ids)


# ── Digests ───────────────────────────────────────────────────
def _digest_dict(r: sqlite3.Row) -> dict:
    cols = r.keys()
    return {"id": r["id"], "date": r["date"], "thematique": r["thematique"] if "thematique" in cols else "",
            "texte_resume": r["texte_resume"], "nb_articles": r["nb_articles"],
            "created_at": r["created_at"],
            "audio_url": r["audio_url"] if "audio_url" in cols else None,
            "audio_duree": r["audio_duree"] if "audio_duree" in cols else None}


_DIGEST_AVEC_AUDIO = """
    SELECT d.*, da.url AS audio_url, da.duree AS audio_duree
    FROM digests d
    LEFT JOIN digest_audio da ON da.id = (
        SELECT id FROM digest_audio WHERE digest_id = d.id ORDER BY id DESC LIMIT 1
    )
"""


def digest_existe(user_id: str, date: str | None = None, thematique: str = "") -> bool:
    date = date or _aujourdhui()
    with _conn() as c:
        row = c.execute(
            "SELECT 1 FROM digests WHERE user_id = ? AND date = ? AND thematique = ?",
            (user_id, date, thematique)).fetchone()
    return row is not None


def inserer_digest(user_id: str, texte_resume: str, nb_articles: int,
                   date: str | None = None, thematique: str = "") -> dict:
    date = date or _aujourdhui()
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO digests (user_id, thematique, date, texte_resume, nb_articles, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (user_id, thematique, date, texte_resume, nb_articles, _maintenant()))
        row = c.execute("SELECT * FROM digests WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _digest_dict(row)


def lister_digests(user_id: str) -> list[dict]:
    with _conn() as c:
        rows = c.execute(_DIGEST_AVEC_AUDIO + " WHERE d.user_id = ? ORDER BY d.date DESC",
                         (user_id,)).fetchall()
    return [_digest_dict(r) for r in rows]


def digest_get(user_id: str, digest_id: int) -> dict | None:
    with _conn() as c:
        row = c.execute(_DIGEST_AVEC_AUDIO + " WHERE d.id = ? AND d.user_id = ?",
                        (digest_id, user_id)).fetchone()
    return _digest_dict(row) if row else None


# ── Audio ─────────────────────────────────────────────────────
def inserer_audio_digest(digest_id: int, url: str, duree: float | None) -> dict:
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO digest_audio (digest_id, url, duree, created_at) VALUES (?,?,?,?)",
            (digest_id, url, duree, _maintenant()))
        row = c.execute("SELECT * FROM digest_audio WHERE id = ?", (cur.lastrowid,)).fetchone()
    return {"id": row["id"], "digest_id": row["digest_id"], "url": row["url"],
            "duree": row["duree"], "created_at": row["created_at"]}


# ── Audio global (S199) ──────────────────────────────────────────
def _audio_global_dict(r: sqlite3.Row) -> dict:
    return {"id": r["id"], "user_id": r["user_id"], "jeton": r["jeton"],
            "ordre_thematiques": json.loads(r["ordre_thematiques"]),
            "fichier_path": r["fichier_path"], "duree_secondes": r["duree_secondes"],
            "expire_le": r["expire_le"], "cree_le": r["cree_le"]}


def inserer_audio_global(user_id: str, jeton: str, ordre_digest_ids: list[int],
                         fichier_path: str, duree: float | None, expire_le: str) -> dict:
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO veille_audio_global (user_id, jeton, ordre_thematiques, fichier_path, "
            "duree_secondes, expire_le, cree_le) VALUES (?,?,?,?,?,?,?)",
            (user_id, jeton, json.dumps(ordre_digest_ids), fichier_path, duree, expire_le,
             _maintenant()))
        row = c.execute("SELECT * FROM veille_audio_global WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _audio_global_dict(row)


def audio_global_par_jeton(jeton: str) -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM veille_audio_global WHERE jeton = ?", (jeton,)).fetchone()
    return _audio_global_dict(row) if row else None


def audio_global_get(user_id: str, audio_id: int) -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM veille_audio_global WHERE id = ? AND user_id = ?",
                        (audio_id, user_id)).fetchone()
    return _audio_global_dict(row) if row else None


def lister_audio_global(user_id: str) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM veille_audio_global WHERE user_id = ? ORDER BY cree_le DESC",
            (user_id,)).fetchall()
    return [_audio_global_dict(r) for r in rows]


def inserer_envoi_audio_global(audio_global_id: int, destinataire: str, statut: str,
                               detail: str | None) -> dict:
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO veille_audio_global_envois (audio_global_id, destinataire, statut, "
            "detail, envoye_le) VALUES (?,?,?,?,?)",
            (audio_global_id, destinataire, statut, detail, _maintenant()))
        row = c.execute("SELECT * FROM veille_audio_global_envois WHERE id = ?",
                        (cur.lastrowid,)).fetchone()
    return dict(row)


def lister_envois_audio_global(audio_global_id: int) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM veille_audio_global_envois WHERE audio_global_id = ? "
            "ORDER BY envoye_le DESC", (audio_global_id,)).fetchall()
    return [dict(r) for r in rows]
