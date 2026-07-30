"""Schéma SQLite complet de `jeu-factions` (source unique de vérité pour toutes les tables)
+ CRUD des joueurs et personnages. Cloisonné par `cle_api` — mais voir zones.py/archetypes.py :
zones/scores/étapes/compétences sont un monde PARTAGÉ, pas filtré par tenant (design assumé,
cf. spec)."""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = os.getenv("JEU_FACTIONS_DB", "/data/jeu_factions.db")


def _migrer_colonnes_effet_competences(c: sqlite3.Connection) -> None:
    """Ajoute les colonnes d'effet de compétence si absentes (brique déployée avant ce
    plan) — `ALTER TABLE` idempotent, vérifié via `PRAGMA table_info` (SQLite n'a pas
    d'`ADD COLUMN IF NOT EXISTS`)."""
    colonnes = {row["name"] for row in c.execute("PRAGMA table_info(competences)").fetchall()}
    for nom, type_sql in (("effet_type", "TEXT"), ("magnitude", "INTEGER"),
                          ("portee", "INTEGER"), ("cooldown_s", "REAL")):
        if nom not in colonnes:
            c.execute(f"ALTER TABLE competences ADD COLUMN {nom} {type_sql}")


def _migrer_colonne_presence(c: sqlite3.Connection) -> None:
    """Ajoute `derniere_presence` à `joueurs` si absente (même motif que
    `_migrer_colonnes_effet_competences` ci-dessus)."""
    colonnes = {row["name"] for row in c.execute("PRAGMA table_info(joueurs)").fetchall()}
    if "derniere_presence" not in colonnes:
        c.execute("ALTER TABLE joueurs ADD COLUMN derniere_presence TEXT")


def _conn() -> sqlite3.Connection:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS joueurs (
        cle_api TEXT PRIMARY KEY, pseudo TEXT NOT NULL)""")
    _migrer_colonne_presence(c)
    c.execute("""CREATE TABLE IF NOT EXISTS personnages_jeu (
        id TEXT PRIMARY KEY, cle_api TEXT NOT NULL, nom TEXT NOT NULL,
        donnees_naissance TEXT NOT NULL, snapshot_holistique TEXT NOT NULL,
        zone_actuelle TEXT, cree_le TEXT NOT NULL)""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_perso_cle ON personnages_jeu(cle_api)")
    c.execute("""CREATE TABLE IF NOT EXISTS zones (
        id TEXT PRIMARY KEY, nom TEXT NOT NULL, element_natif TEXT NOT NULL,
        signe_natif TEXT NOT NULL, difficulte_pve INTEGER NOT NULL,
        etat TEXT NOT NULL DEFAULT 'en_cours')""")
    c.execute("""CREATE TABLE IF NOT EXISTS mobs_zone (
        id TEXT PRIMARY KEY, zone_id TEXT NOT NULL, nom TEXT NOT NULL, role TEXT NOT NULL,
        pv_max INTEGER NOT NULL, degats_attaque INTEGER NOT NULL,
        cooldown_attaque_s REAL NOT NULL, portee_aggro INTEGER NOT NULL,
        portee_attaque INTEGER NOT NULL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS mobs_zone_archetype (
        id TEXT PRIMARY KEY, zone_archetype_id TEXT NOT NULL, nom TEXT NOT NULL,
        role TEXT NOT NULL, pv_max INTEGER NOT NULL, degats_attaque INTEGER NOT NULL,
        cooldown_attaque_s REAL NOT NULL, portee_aggro INTEGER NOT NULL,
        portee_attaque INTEGER NOT NULL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS scores_zone_guilde (
        zone_id TEXT NOT NULL, guilde TEXT NOT NULL, points_cumules INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (zone_id, guilde))""")
    c.execute("""CREATE TABLE IF NOT EXISTS resolutions (
        id TEXT PRIMARY KEY, zone_id TEXT, zone_archetype_id TEXT, horodatage TEXT NOT NULL,
        contributions TEXT NOT NULL, etat_resultant TEXT NOT NULL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS zones_archetype (
        id TEXT PRIMARY KEY, archetype TEXT NOT NULL, ordre INTEGER NOT NULL,
        nom TEXT NOT NULL, difficulte_pve INTEGER NOT NULL, texte_lore TEXT NOT NULL,
        UNIQUE (archetype, ordre))""")
    c.execute("""CREATE TABLE IF NOT EXISTS progression_archetype (
        personnage_id TEXT NOT NULL, zone_archetype_id TEXT NOT NULL,
        etat TEXT NOT NULL DEFAULT 'en_cours', date_completion TEXT,
        PRIMARY KEY (personnage_id, zone_archetype_id))""")
    c.execute("""CREATE TABLE IF NOT EXISTS groupes (
        id TEXT PRIMARY KEY, personnage_cible_id TEXT NOT NULL, zone_archetype_id TEXT NOT NULL,
        etat TEXT NOT NULL DEFAULT 'actif', cree_le TEXT NOT NULL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS membres_groupe (
        groupe_id TEXT NOT NULL, personnage_id TEXT NOT NULL,
        PRIMARY KEY (groupe_id, personnage_id))""")
    c.execute("""CREATE TABLE IF NOT EXISTS competences (
        id TEXT PRIMARY KEY, nom TEXT NOT NULL, texte TEXT NOT NULL,
        archetype TEXT NOT NULL, ordre_etape INTEGER NOT NULL)""")
    _migrer_colonnes_effet_competences(c)
    c.execute("""CREATE TABLE IF NOT EXISTS competences_debloquees (
        personnage_id TEXT NOT NULL, competence_id TEXT NOT NULL, date TEXT NOT NULL,
        PRIMARY KEY (personnage_id, competence_id))""")
    return c


def _maintenant() -> str:
    return datetime.now(timezone.utc).isoformat()


def assurer_joueur(cle_api: str, pseudo: str = "") -> None:
    with _conn() as c:
        c.execute("INSERT OR IGNORE INTO joueurs (cle_api, pseudo) VALUES (?,?)",
                  (cle_api, pseudo or cle_api))


def _ligne_personnage(r: sqlite3.Row) -> dict:
    return {"id": r["id"], "nom": r["nom"],
            "donnees_naissance": json.loads(r["donnees_naissance"]),
            "snapshot_holistique": json.loads(r["snapshot_holistique"]),
            "zone_actuelle": r["zone_actuelle"], "cree_le": r["cree_le"]}


def creer_personnage(cle_api: str, nom: str, donnees_naissance: dict, snapshot: dict) -> dict:
    pid = uuid.uuid4().hex
    cree_le = _maintenant()
    with _conn() as c:
        c.execute("""INSERT INTO personnages_jeu
                     (id, cle_api, nom, donnees_naissance, snapshot_holistique, zone_actuelle, cree_le)
                     VALUES (?,?,?,?,?,NULL,?)""",
                  (pid, cle_api, nom, json.dumps(donnees_naissance, ensure_ascii=False),
                   json.dumps(snapshot, ensure_ascii=False), cree_le))
    return {"id": pid, "nom": nom, "donnees_naissance": donnees_naissance,
            "snapshot_holistique": snapshot, "zone_actuelle": None, "cree_le": cree_le}


def lister_personnages(cle_api: str) -> list[dict]:
    with _conn() as c:
        rows = c.execute("SELECT * FROM personnages_jeu WHERE cle_api=? ORDER BY cree_le",
                         (cle_api,)).fetchall()
    return [_ligne_personnage(r) for r in rows]


def lire_personnage(cle_api: str, pid: str) -> dict | None:
    with _conn() as c:
        r = c.execute("SELECT * FROM personnages_jeu WHERE id=? AND cle_api=?",
                      (pid, cle_api)).fetchone()
    return _ligne_personnage(r) if r else None


def assigner_zone(cle_api: str, pid: str, zone_id: str) -> dict | None:
    with _conn() as c:
        cur = c.execute("UPDATE personnages_jeu SET zone_actuelle=? WHERE id=? AND cle_api=?",
                        (zone_id, pid, cle_api))
        if cur.rowcount == 0:
            return None
    return lire_personnage(cle_api, pid)


def log_resolution(zone_id: str | None, zone_archetype_id: str | None,
                   contributions: dict, etat_resultant: str) -> None:
    with _conn() as c:
        c.execute("""INSERT INTO resolutions (id, zone_id, zone_archetype_id, horodatage,
                     contributions, etat_resultant) VALUES (?,?,?,?,?,?)""",
                  (uuid.uuid4().hex, zone_id, zone_archetype_id, _maintenant(),
                   json.dumps(contributions, ensure_ascii=False), etat_resultant))


def enregistrer_presence(cle_api: str) -> None:
    assurer_joueur(cle_api)
    with _conn() as c:
        c.execute("UPDATE joueurs SET derniere_presence=? WHERE cle_api=?",
                  (_maintenant(), cle_api))


def lire_derniere_presence(cle_api: str) -> str | None:
    with _conn() as c:
        row = c.execute("SELECT derniere_presence FROM joueurs WHERE cle_api=?",
                        (cle_api,)).fetchone()
    return row["derniere_presence"] if row else None


def lire_derniere_presence_personnage(personnage_id: str) -> str | None:
    with _conn() as c:
        row = c.execute("""SELECT j.derniere_presence FROM personnages_jeu p
                            JOIN joueurs j ON j.cle_api = p.cle_api
                            WHERE p.id=?""", (personnage_id,)).fetchone()
    return row["derniere_presence"] if row else None


def migrer_public_si_premiere_connexion(cle_api_reelle: str) -> None:
    """Idempotent : no-op dès que `cle_api_reelle` a déjà une ligne dans `joueurs` (le cas
    courant, à partir de la 2e requête). Sinon, réattribue les données historiques sous le
    tenant partagé "public" à cette première identité réelle vue — `groupes`/`membres_groupe`
    n'ont pas de colonne `cle_api`, ils suivent `personnages_jeu` sans migration propre
    (spec S217)."""
    with _conn() as c:
        existe = c.execute("SELECT 1 FROM joueurs WHERE cle_api=?", (cle_api_reelle,)).fetchone()
        if existe:
            return
        public = c.execute("SELECT 1 FROM joueurs WHERE cle_api='public'").fetchone()
        if not public:
            return
        c.execute("UPDATE joueurs SET cle_api=?, pseudo=? WHERE cle_api='public'",
                  (cle_api_reelle, cle_api_reelle))
        c.execute("UPDATE personnages_jeu SET cle_api=? WHERE cle_api='public'", (cle_api_reelle,))
