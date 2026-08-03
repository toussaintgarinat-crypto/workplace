"""Schéma SQLite complet de `jeu-factions-public` — copie du schéma de `briques/jeu-factions/`
(zones/mobs/archetypes/groupes/competences inchangés, cf. spec) + table `comptes` propre à
cette brique (identité locale, pas de tenant Keycloak). `cle_api` référence désormais
`comptes.id`."""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = os.getenv("JEU_FACTIONS_PUBLIC_DB", "/data/jeu_factions_public.db")


def _migrer_colonnes_effet_competences(c: sqlite3.Connection) -> None:
    colonnes = {row["name"] for row in c.execute("PRAGMA table_info(competences)").fetchall()}
    for nom, type_sql in (("effet_type", "TEXT"), ("magnitude", "INTEGER"),
                          ("portee", "INTEGER"), ("cooldown_s", "REAL")):
        if nom not in colonnes:
            c.execute(f"ALTER TABLE competences ADD COLUMN {nom} {type_sql}")


def _migrer_colonne_presence(c: sqlite3.Connection) -> None:
    colonnes = {row["name"] for row in c.execute("PRAGMA table_info(joueurs)").fetchall()}
    if "derniere_presence" not in colonnes:
        c.execute("ALTER TABLE joueurs ADD COLUMN derniere_presence TEXT")


def _migrer_colonne_epoch_session(c: sqlite3.Connection) -> None:
    colonnes = {row["name"] for row in c.execute("PRAGMA table_info(comptes)").fetchall()}
    if "epoch_session" not in colonnes:
        c.execute("ALTER TABLE comptes ADD COLUMN epoch_session INTEGER NOT NULL DEFAULT 0")


def _conn() -> sqlite3.Connection:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS comptes (
        id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE,
        mot_de_passe_hash TEXT NOT NULL, pseudo TEXT NOT NULL, cree_le TEXT NOT NULL)""")
    _migrer_colonne_epoch_session(c)
    c.execute("""CREATE TABLE IF NOT EXISTS reinitialisations_utilisees (
        jeton_hash TEXT PRIMARY KEY, utilise_le TEXT NOT NULL)""")
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


def creer_compte(email: str, mot_de_passe_hash: str, pseudo: str) -> dict:
    compte_id = uuid.uuid4().hex
    cree_le = _maintenant()
    with _conn() as c:
        c.execute("""INSERT INTO comptes (id, email, mot_de_passe_hash, pseudo, cree_le)
                     VALUES (?,?,?,?,?)""", (compte_id, email, mot_de_passe_hash, pseudo, cree_le))
    return {"id": compte_id, "email": email, "pseudo": pseudo, "cree_le": cree_le}


def lire_compte_par_email(email: str) -> dict | None:
    with _conn() as c:
        r = c.execute("SELECT * FROM comptes WHERE email=?", (email,)).fetchone()
    return dict(r) if r else None


def lire_epoch_session(compte_id: str) -> int | None:
    """None si aucun compte réel à cet id (cas normal des identités fabriquées par les tests
    de logique de jeu, cf. jeton.py — le contrôle d'époque ne s'applique alors pas)."""
    with _conn() as c:
        r = c.execute("SELECT epoch_session FROM comptes WHERE id=?", (compte_id,)).fetchone()
    return r["epoch_session"] if r else None


def incrementer_epoch_session(compte_id: str) -> None:
    with _conn() as c:
        c.execute("UPDATE comptes SET epoch_session = epoch_session + 1 WHERE id=?", (compte_id,))


def marquer_reinitialisation_utilisee(jeton: str) -> bool:
    """Atomique : True si c'est la première fois que CE jeton précis est marqué utilisé
    (insertion réussie), False s'il l'était déjà (rejeu) — même motif que le TOCTOU corrigé
    en Task 5 (INSERT + catch IntegrityError, pas de check-then-insert séparé)."""
    import hashlib as _hashlib
    hash_jeton = _hashlib.sha256(jeton.encode()).hexdigest()
    with _conn() as c:
        try:
            c.execute("INSERT INTO reinitialisations_utilisees (jeton_hash, utilise_le) VALUES (?,?)",
                      (hash_jeton, _maintenant()))
            return True
        except sqlite3.IntegrityError:
            return False


def mettre_a_jour_mot_de_passe(compte_id: str, mot_de_passe_hash: str) -> None:
    with _conn() as c:
        c.execute("UPDATE comptes SET mot_de_passe_hash=? WHERE id=?", (mot_de_passe_hash, compte_id))


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
