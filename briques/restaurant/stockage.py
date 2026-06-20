"""Stockage SQLite (stdlib) de la brique « restaurant », cloisonné par compte.

Hiérarchie des données :
    Compte (restaurateur)
      └─ Restaurant(s)            ← un restaurateur peut en gérer plusieurs
           ├─ Table(s)           ← chacune porte un code opaque → QR public
           ├─ Plat(s)            ← la carte (prix, dispo, plat du jour)
           ├─ Commande(s)        ← par convive (prénom/siège), envoyée en cuisine
           │     └─ Ligne(s)     ← plats commandés (snapshot du prix au moment T)
           └─ Paiement(s)        ← parts réglées (mock en ligne / espèces au comptoir)

ISOLATION (fail-closed) : toute lecture/écriture côté restaurateur exige le compte
propriétaire. Une fonction `_possede(compte_id, restaurant_id)` garde l'accès : un
restaurateur ne peut JAMAIS toucher au restaurant d'un autre. Les routes CLIENT (QR)
n'ont pas de compte : elles passent par le CODE de table (capability), qui ne donne
accès qu'à ce restaurant / cette table.
"""
from __future__ import annotations

import json
import os
import secrets
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = os.getenv("RESTAURANT_DB", "/data/restaurant.db")


def _maintenant() -> str:
    return datetime.now(timezone.utc).isoformat()


def _id() -> str:
    return uuid.uuid4().hex


def _code_table() -> str:
    """Code opaque d'une table (sert de capability dans l'URL du QR). Court mais non devinable."""
    return secrets.token_urlsafe(9)


def _conn() -> sqlite3.Connection:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    c.executescript(
        """
        CREATE TABLE IF NOT EXISTS comptes (
            id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE,
            mot_de_passe TEXT NOT NULL, nom TEXT, jeton_version INTEGER NOT NULL DEFAULT 1,
            cree_le TEXT);

        CREATE TABLE IF NOT EXISTS restaurants (
            id TEXT PRIMARY KEY, compte_id TEXT NOT NULL, nom TEXT,
            devise TEXT DEFAULT 'EUR', tva_taux REAL NOT NULL DEFAULT 10.0, cree_le TEXT);
        CREATE INDEX IF NOT EXISTS idx_resto_compte ON restaurants(compte_id);

        CREATE TABLE IF NOT EXISTS tables (
            id TEXT PRIMARY KEY, restaurant_id TEXT NOT NULL, numero TEXT,
            code TEXT NOT NULL UNIQUE, session_courante INTEGER NOT NULL DEFAULT 1, cree_le TEXT);
        CREATE INDEX IF NOT EXISTS idx_table_resto ON tables(restaurant_id);

        CREATE TABLE IF NOT EXISTS plats (
            id TEXT PRIMARY KEY, restaurant_id TEXT NOT NULL, nom TEXT,
            description TEXT, prix_cents INTEGER NOT NULL DEFAULT 0, photo TEXT,
            categorie TEXT DEFAULT '',
            formats TEXT DEFAULT '[]',
            disponible INTEGER NOT NULL DEFAULT 1, plat_du_jour INTEGER NOT NULL DEFAULT 0,
            ordre INTEGER NOT NULL DEFAULT 0, cree_le TEXT);
        CREATE INDEX IF NOT EXISTS idx_plat_resto ON plats(restaurant_id);

        CREATE TABLE IF NOT EXISTS commandes (
            id TEXT PRIMARY KEY, restaurant_id TEXT NOT NULL, table_id TEXT NOT NULL,
            session_id INTEGER NOT NULL DEFAULT 1,
            convive TEXT, statut TEXT NOT NULL DEFAULT 'en_cuisine', cree_le TEXT);
        CREATE INDEX IF NOT EXISTS idx_cmd_resto ON commandes(restaurant_id);
        CREATE INDEX IF NOT EXISTS idx_cmd_table ON commandes(table_id);

        CREATE TABLE IF NOT EXISTS lignes (
            id TEXT PRIMARY KEY, commande_id TEXT NOT NULL, plat_id TEXT,
            nom_plat TEXT, prix_cents INTEGER NOT NULL DEFAULT 0, quantite INTEGER NOT NULL DEFAULT 1);
        CREATE INDEX IF NOT EXISTS idx_ligne_cmd ON lignes(commande_id);

        CREATE TABLE IF NOT EXISTS paiements (
            id TEXT PRIMARY KEY, restaurant_id TEXT NOT NULL, table_id TEXT NOT NULL,
            session_id INTEGER NOT NULL DEFAULT 1,
            convive TEXT, montant_cents INTEGER NOT NULL, pourboire_cents INTEGER NOT NULL DEFAULT 0,
            moyen TEXT NOT NULL, regle_le TEXT);
        CREATE INDEX IF NOT EXISTS idx_paie_table ON paiements(table_id);

        -- Tickets archivés à la clôture d'une table (justificatif + historique).
        CREATE TABLE IF NOT EXISTS tickets (
            id TEXT PRIMARY KEY, restaurant_id TEXT NOT NULL, table_id TEXT NOT NULL,
            session_id INTEGER NOT NULL, numero TEXT, donnees TEXT NOT NULL, cloture_le TEXT);
        CREATE INDEX IF NOT EXISTS idx_ticket_resto ON tickets(restaurant_id);
        """
    )
    # Migrations douces (bases d'avant v0.2.0) : ajoute les colonnes manquantes.
    def _colonnes(table):
        return {r[1] for r in c.execute(f"PRAGMA table_info({table})")}
    if "jeton_version" not in _colonnes("comptes"):
        c.execute("ALTER TABLE comptes ADD COLUMN jeton_version INTEGER NOT NULL DEFAULT 1")
    if "tva_taux" not in _colonnes("restaurants"):
        c.execute("ALTER TABLE restaurants ADD COLUMN tva_taux REAL NOT NULL DEFAULT 10.0")
    if "session_courante" not in _colonnes("tables"):
        c.execute("ALTER TABLE tables ADD COLUMN session_courante INTEGER NOT NULL DEFAULT 1")
    pcol = _colonnes("plats")
    if "categorie" not in pcol:
        c.execute("ALTER TABLE plats ADD COLUMN categorie TEXT DEFAULT ''")
    if "formats" not in pcol:
        # Formats/tailles d'un plat (ex. bière 25cl/50cl/1L/girafe) : JSON
        # [{"taille": "...", "prix_cents": n}]. Vide = plat à prix unique (prix_cents).
        c.execute("ALTER TABLE plats ADD COLUMN formats TEXT DEFAULT '[]'")
    if "session_id" not in _colonnes("commandes"):
        c.execute("ALTER TABLE commandes ADD COLUMN session_id INTEGER NOT NULL DEFAULT 1")
    pc = _colonnes("paiements")
    if "session_id" not in pc:
        c.execute("ALTER TABLE paiements ADD COLUMN session_id INTEGER NOT NULL DEFAULT 1")
    if "pourboire_cents" not in pc:
        c.execute("ALTER TABLE paiements ADD COLUMN pourboire_cents INTEGER NOT NULL DEFAULT 0")
    return c


# ── Comptes (restaurateurs) ──────────────────────────────────────
def creer_compte(email: str, mot_de_passe_hache: str, nom: str = "") -> dict:
    """Crée un compte restaurateur. Lève sqlite3.IntegrityError si l'email existe déjà."""
    cid = _id()
    with _conn() as c:
        c.execute("INSERT INTO comptes (id, email, mot_de_passe, nom, cree_le) VALUES (?,?,?,?,?)",
                  (cid, email.strip().lower(), mot_de_passe_hache, nom.strip(), _maintenant()))
    return {"id": cid, "email": email.strip().lower(), "nom": nom.strip()}


def compte_par_email(email: str) -> dict | None:
    with _conn() as c:
        r = c.execute("SELECT * FROM comptes WHERE email=?", (email.strip().lower(),)).fetchone()
    return dict(r) if r else None


def compte_par_id(compte_id: str) -> dict | None:
    with _conn() as c:
        r = c.execute("SELECT id, email, nom, jeton_version, cree_le FROM comptes WHERE id=?",
                      (compte_id,)).fetchone()
    return dict(r) if r else None


def version_compte(compte_id: str) -> int | None:
    """Version de révocation courante d'un compte (None si le compte n'existe pas)."""
    with _conn() as c:
        r = c.execute("SELECT jeton_version FROM comptes WHERE id=?", (compte_id,)).fetchone()
    return r["jeton_version"] if r else None


def _hash_compte(compte_id: str) -> str | None:
    with _conn() as c:
        r = c.execute("SELECT mot_de_passe FROM comptes WHERE id=?", (compte_id,)).fetchone()
    return r["mot_de_passe"] if r else None


def changer_mot_de_passe(compte_id: str, nouveau_hache: str) -> int | None:
    """Remplace le mot de passe ET incrémente la version → invalide toutes les sessions
    existantes (y compris celles d'un appareil volé). Renvoie la nouvelle version."""
    with _conn() as c:
        cur = c.execute("UPDATE comptes SET mot_de_passe=?, jeton_version=jeton_version+1 WHERE id=?",
                        (nouveau_hache, compte_id))
        if cur.rowcount == 0:
            return None
        return c.execute("SELECT jeton_version FROM comptes WHERE id=?", (compte_id,)).fetchone()[0]


def deconnecter_partout(compte_id: str) -> int | None:
    """Incrémente la version → invalide toutes les sessions. Renvoie la nouvelle version."""
    with _conn() as c:
        cur = c.execute("UPDATE comptes SET jeton_version=jeton_version+1 WHERE id=?", (compte_id,))
        if cur.rowcount == 0:
            return None
        return c.execute("SELECT jeton_version FROM comptes WHERE id=?", (compte_id,)).fetchone()[0]


# ── Garde d'appartenance (cœur de l'isolation) ───────────────────
def _possede(c: sqlite3.Connection, compte_id: str, restaurant_id: str) -> bool:
    r = c.execute("SELECT 1 FROM restaurants WHERE id=? AND compte_id=?",
                  (restaurant_id, compte_id)).fetchone()
    return r is not None


# ── Restaurants ──────────────────────────────────────────────────
def creer_restaurant(compte_id: str, nom: str, devise: str = "EUR", tva_taux: float = 10.0) -> dict:
    rid = _id()
    with _conn() as c:
        c.execute("INSERT INTO restaurants (id, compte_id, nom, devise, tva_taux, cree_le) "
                  "VALUES (?,?,?,?,?,?)",
                  (rid, compte_id, nom.strip() or "Mon restaurant", devise or "EUR",
                   max(0.0, float(tva_taux)), _maintenant()))
    return {"id": rid, "nom": nom.strip() or "Mon restaurant", "devise": devise or "EUR",
            "tva_taux": max(0.0, float(tva_taux))}


def lister_restaurants(compte_id: str) -> list:
    with _conn() as c:
        rows = c.execute("SELECT id, nom, devise, tva_taux, cree_le FROM restaurants WHERE compte_id=? "
                         "ORDER BY cree_le", (compte_id,)).fetchall()
    return [dict(r) for r in rows]


def lire_restaurant(compte_id: str, restaurant_id: str) -> dict | None:
    with _conn() as c:
        if not _possede(c, compte_id, restaurant_id):
            return None
        r = c.execute("SELECT id, nom, devise, tva_taux, cree_le FROM restaurants WHERE id=?",
                      (restaurant_id,)).fetchone()
    return dict(r) if r else None


def maj_restaurant(compte_id: str, restaurant_id: str, champs: dict) -> dict | None:
    r = lire_restaurant(compte_id, restaurant_id)
    if not r:
        return None
    nom = champs.get("nom")
    devise = champs.get("devise")
    tva = champs.get("tva_taux")
    with _conn() as c:
        c.execute("UPDATE restaurants SET nom=?, devise=?, tva_taux=? WHERE id=? AND compte_id=?",
                  (str(nom).strip() or r["nom"] if nom is not None else r["nom"],
                   (devise or r["devise"]) if devise is not None else r["devise"],
                   max(0.0, float(tva)) if tva is not None else r["tva_taux"],
                   restaurant_id, compte_id))
    return lire_restaurant(compte_id, restaurant_id)


def restaurant_public(restaurant_id: str) -> dict | None:
    """Infos publiques d'un resto (nom, devise, TVA) — sans compte, pour l'affichage client."""
    with _conn() as c:
        r = c.execute("SELECT id, nom, devise, tva_taux FROM restaurants WHERE id=?",
                      (restaurant_id,)).fetchone()
    return dict(r) if r else None


def compte_du_restaurant(restaurant_id: str) -> str | None:
    """Le compte PROPRIÉTAIRE d'un restaurant (ou None s'il n'existe pas).

    Sert le chemin de SERVICE (capacités du Cœur, clé de service) : on dérive le compte
    depuis le seul restaurant_id pour réutiliser les fonctions cloisonnées par compte
    sans que l'appelant ait à connaître le propriétaire. Le cloisonnement reste réel :
    chaque écriture passe ensuite par `compte_id` exact via `_possede`."""
    with _conn() as c:
        r = c.execute("SELECT compte_id FROM restaurants WHERE id=?", (restaurant_id,)).fetchone()
    return r["compte_id"] if r else None


# ── Tables (+ QR) ────────────────────────────────────────────────
def creer_table(compte_id: str, restaurant_id: str, numero: str) -> dict | None:
    with _conn() as c:
        if not _possede(c, compte_id, restaurant_id):
            return None
        tid, code = _id(), _code_table()
        c.execute("INSERT INTO tables (id, restaurant_id, numero, code, cree_le) VALUES (?,?,?,?,?)",
                  (tid, restaurant_id, str(numero).strip() or "?", code, _maintenant()))
    return {"id": tid, "restaurant_id": restaurant_id, "numero": str(numero).strip() or "?", "code": code}


def lister_tables(compte_id: str, restaurant_id: str) -> list | None:
    with _conn() as c:
        if not _possede(c, compte_id, restaurant_id):
            return None
        rows = c.execute("SELECT id, numero, code, cree_le FROM tables WHERE restaurant_id=? "
                         "ORDER BY cree_le", (restaurant_id,)).fetchall()
    return [dict(r) for r in rows]


def table_par_code(code: str) -> dict | None:
    """Résout une table via son CODE (capability du QR). Sert les routes client publiques."""
    with _conn() as c:
        r = c.execute("SELECT id, restaurant_id, numero, code, session_courante FROM tables "
                      "WHERE code=?", (code,)).fetchone()
    return dict(r) if r else None


def _session_table(c: sqlite3.Connection, table_id: str) -> int:
    r = c.execute("SELECT session_courante FROM tables WHERE id=?", (table_id,)).fetchone()
    return r["session_courante"] if r else 1


def supprimer_table(compte_id: str, restaurant_id: str, table_id: str) -> bool:
    with _conn() as c:
        if not _possede(c, compte_id, restaurant_id):
            return False
        cur = c.execute("DELETE FROM tables WHERE id=? AND restaurant_id=?", (table_id, restaurant_id))
    return cur.rowcount > 0


# ── Plats (la carte) ─────────────────────────────────────────────
def _normaliser_formats(formats) -> list:
    """Nettoie une liste de formats → [{taille:str, prix_cents:int>=0}], sans doublon de taille.

    Tolère prix en euros (float) via la clé `prix` ; ignore les entrées sans taille. Vide = []
    (= plat à prix unique). C'est la source de vérité du prix quand la liste est non vide."""
    out, vues = [], set()
    for f in formats or []:
        if not isinstance(f, dict):
            continue
        taille = str(f.get("taille") or "").strip()
        if not taille or taille.lower() in vues:
            continue
        if f.get("prix_cents") is not None:
            try:
                prix = max(0, int(f["prix_cents"]))
            except (TypeError, ValueError):
                continue
        elif f.get("prix") is not None:
            try:
                prix = max(0, round(float(str(f["prix"]).replace(",", ".")) * 100))
            except (TypeError, ValueError):
                continue
        else:
            continue
        vues.add(taille.lower())
        out.append({"taille": taille[:40], "prix_cents": prix})
    return out


def _formats_de(r: sqlite3.Row) -> list:
    if "formats" not in r.keys():
        return []
    try:
        return _normaliser_formats(json.loads(r["formats"] or "[]"))
    except (ValueError, TypeError):
        return []


def _plat_dict(r: sqlite3.Row) -> dict:
    return {"id": r["id"], "nom": r["nom"], "description": r["description"],
            "prix_cents": r["prix_cents"], "photo": r["photo"],
            "categorie": (r["categorie"] or "") if "categorie" in r.keys() else "",
            "formats": _formats_de(r),
            "disponible": bool(r["disponible"]), "plat_du_jour": bool(r["plat_du_jour"]),
            "ordre": r["ordre"]}


def creer_plat(compte_id: str, restaurant_id: str, nom: str, description: str = "",
               prix_cents: int = 0, photo: str = "", plat_du_jour: bool = False,
               categorie: str = "", formats=None) -> dict | None:
    formats = _normaliser_formats(formats)
    # Avec des formats, le prix de carte = « à partir de » (le moins cher).
    if formats:
        prix_cents = min(f["prix_cents"] for f in formats)
    with _conn() as c:
        if not _possede(c, compte_id, restaurant_id):
            return None
        pid = _id()
        ordre = (c.execute("SELECT COALESCE(MAX(ordre), 0) + 1 FROM plats WHERE restaurant_id=?",
                           (restaurant_id,)).fetchone()[0])
        c.execute("""INSERT INTO plats (id, restaurant_id, nom, description, prix_cents, photo,
                     categorie, formats, disponible, plat_du_jour, ordre, cree_le)
                     VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                  (pid, restaurant_id, nom.strip() or "Plat", description.strip(),
                   max(0, int(prix_cents)), photo.strip(), (categorie or "").strip(),
                   json.dumps(formats, ensure_ascii=False),
                   1, 1 if plat_du_jour else 0, ordre, _maintenant()))
        r = c.execute("SELECT * FROM plats WHERE id=?", (pid,)).fetchone()
    return _plat_dict(r)


def lister_plats(compte_id: str, restaurant_id: str) -> list | None:
    """Carte COMPLÈTE (vue restaurateur) — y compris les plats indisponibles."""
    with _conn() as c:
        if not _possede(c, compte_id, restaurant_id):
            return None
        rows = c.execute("SELECT * FROM plats WHERE restaurant_id=? ORDER BY ordre, cree_le",
                         (restaurant_id,)).fetchall()
    return [_plat_dict(r) for r in rows]


def carte_publique(restaurant_id: str) -> list:
    """Carte vue par le CLIENT : uniquement les plats DISPONIBLES (rupture = invisible)."""
    with _conn() as c:
        rows = c.execute("SELECT * FROM plats WHERE restaurant_id=? AND disponible=1 "
                         "ORDER BY categorie, plat_du_jour DESC, ordre, cree_le",
                         (restaurant_id,)).fetchall()
    return [_plat_dict(r) for r in rows]


def maj_plat(compte_id: str, restaurant_id: str, plat_id: str, champs: dict) -> dict | None:
    with _conn() as c:
        if not _possede(c, compte_id, restaurant_id):
            return None
        r = c.execute("SELECT * FROM plats WHERE id=? AND restaurant_id=?",
                      (plat_id, restaurant_id)).fetchone()
        if not r:
            return None
        d = _plat_dict(r)
        if "nom" in champs and champs["nom"] is not None:
            d["nom"] = str(champs["nom"]).strip() or d["nom"]
        if "description" in champs and champs["description"] is not None:
            d["description"] = str(champs["description"]).strip()
        if "prix_cents" in champs and champs["prix_cents"] is not None:
            d["prix_cents"] = max(0, int(champs["prix_cents"]))
        if "photo" in champs and champs["photo"] is not None:
            d["photo"] = str(champs["photo"]).strip()
        if "categorie" in champs and champs["categorie"] is not None:
            d["categorie"] = str(champs["categorie"]).strip()
        if "disponible" in champs and champs["disponible"] is not None:
            d["disponible"] = bool(champs["disponible"])
        if "plat_du_jour" in champs and champs["plat_du_jour"] is not None:
            d["plat_du_jour"] = bool(champs["plat_du_jour"])
        if "formats" in champs and champs["formats"] is not None:
            d["formats"] = _normaliser_formats(champs["formats"])
            if d["formats"]:                       # prix de carte = « à partir de »
                d["prix_cents"] = min(f["prix_cents"] for f in d["formats"])
        c.execute("""UPDATE plats SET nom=?, description=?, prix_cents=?, photo=?,
                     categorie=?, formats=?, disponible=?, plat_du_jour=? WHERE id=? AND restaurant_id=?""",
                  (d["nom"], d["description"], d["prix_cents"], d["photo"], d["categorie"],
                   json.dumps(d["formats"], ensure_ascii=False),
                   1 if d["disponible"] else 0, 1 if d["plat_du_jour"] else 0,
                   plat_id, restaurant_id))
    return d


def supprimer_plat(compte_id: str, restaurant_id: str, plat_id: str) -> bool:
    with _conn() as c:
        if not _possede(c, compte_id, restaurant_id):
            return False
        cur = c.execute("DELETE FROM plats WHERE id=? AND restaurant_id=?", (plat_id, restaurant_id))
    return cur.rowcount > 0


# ── Commandes (côté client : créées via le code de table) ────────
def creer_commande(restaurant_id: str, table_id: str, convive: str, plats: list) -> dict | None:
    """Crée une commande pour un convive. `plats` = [{plat_id, quantite, format?}].

    Le prix de chaque ligne est un SNAPSHOT pris au moment de la commande : si le
    restaurateur change le prix après coup, l'addition du convive ne bouge pas. Si le plat a
    des FORMATS (taille), `format` choisit lequel (défaut : le 1er) → le prix et le nom de la
    ligne reflètent la taille (ex. « Carlsberg (50cl) »).
    Refuse les plats indisponibles / hors de ce restaurant (fail-closed)."""
    convive = (convive or "").strip() or "Convive"
    with _conn() as c:
        cmd_id = _id()
        session_id = _session_table(c, table_id)
        lignes = []
        for item in plats or []:
            r = c.execute("SELECT * FROM plats WHERE id=? AND restaurant_id=? AND disponible=1",
                          (item.get("plat_id"), restaurant_id)).fetchone()
            if not r:
                continue
            q = max(1, int(item.get("quantite", 1)))
            nom_plat, prix = r["nom"], r["prix_cents"]
            formats = _formats_de(r)
            if formats:                            # plat à formats → résoudre la taille choisie
                voulu = str(item.get("format") or "").strip().lower()
                choisi = next((f for f in formats if f["taille"].lower() == voulu), formats[0])
                nom_plat = f'{r["nom"]} ({choisi["taille"]})'
                prix = choisi["prix_cents"]
            lignes.append({"id": _id(), "plat_id": r["id"], "nom_plat": nom_plat,
                           "prix_cents": prix, "quantite": q})
        if not lignes:
            return None
        c.execute("INSERT INTO commandes (id, restaurant_id, table_id, session_id, convive, statut, cree_le) "
                  "VALUES (?,?,?,?,?,?,?)",
                  (cmd_id, restaurant_id, table_id, session_id, convive, "en_cuisine", _maintenant()))
        for l in lignes:
            c.execute("INSERT INTO lignes (id, commande_id, plat_id, nom_plat, prix_cents, quantite) "
                      "VALUES (?,?,?,?,?,?)",
                      (l["id"], cmd_id, l["plat_id"], l["nom_plat"], l["prix_cents"], l["quantite"]))
    return {"id": cmd_id, "convive": convive, "statut": "en_cuisine",
            "lignes": lignes, "total_cents": sum(l["prix_cents"] * l["quantite"] for l in lignes)}


def _lignes_de(c: sqlite3.Connection, cmd_id: str) -> list:
    rows = c.execute("SELECT id, plat_id, nom_plat, prix_cents, quantite FROM lignes WHERE commande_id=?",
                     (cmd_id,)).fetchall()
    return [dict(r) for r in rows]


def lister_commandes_cuisine(compte_id: str, restaurant_id: str, actives_seulement: bool = True) -> list | None:
    """File cuisine (vue restaurateur). Par défaut, masque les commandes déjà servies."""
    with _conn() as c:
        if not _possede(c, compte_id, restaurant_id):
            return None
        sql = "SELECT * FROM commandes WHERE restaurant_id=?"
        params = [restaurant_id]
        if actives_seulement:
            sql += " AND statut != 'servie'"
        sql += " ORDER BY cree_le"
        rows = c.execute(sql, params).fetchall()
        out = []
        for r in rows:
            t = c.execute("SELECT numero FROM tables WHERE id=?", (r["table_id"],)).fetchone()
            out.append({"id": r["id"], "table_id": r["table_id"],
                        "table_numero": t["numero"] if t else "?", "convive": r["convive"],
                        "statut": r["statut"], "cree_le": r["cree_le"],
                        "lignes": _lignes_de(c, r["id"])})
    return out


def maj_statut_commande(compte_id: str, restaurant_id: str, commande_id: str, statut: str) -> dict | None:
    if statut not in ("en_cuisine", "prete", "servie"):
        return None
    with _conn() as c:
        if not _possede(c, compte_id, restaurant_id):
            return None
        cur = c.execute("UPDATE commandes SET statut=? WHERE id=? AND restaurant_id=?",
                        (statut, commande_id, restaurant_id))
        if cur.rowcount == 0:
            return None
        r = c.execute("SELECT * FROM commandes WHERE id=?", (commande_id,)).fetchone()
    return {"id": r["id"], "statut": r["statut"], "convive": r["convive"], "table_id": r["table_id"]}


# ── Addition partagée (état d'une table) ─────────────────────────
def _ventilation_tva(ttc_cents: int, taux: float) -> dict:
    """Décompose un montant TTC en HT + TVA (les prix de carte sont TTC, usage resto FR)."""
    if taux <= 0:
        return {"ht_cents": ttc_cents, "tva_cents": 0, "tva_taux": taux}
    ht = round(ttc_cents / (1 + taux / 100.0))
    return {"ht_cents": ht, "tva_cents": ttc_cents - ht, "tva_taux": taux}


def etat_table(restaurant_id: str, table_id: str) -> dict:
    """État d'addition de la table pour sa SESSION COURANTE : par convive (dû/payé/reste),
    total table, ventilation TVA et pourboires. Une clôture ouvre une nouvelle session →
    la table repart vierge pour le groupe suivant (les anciennes sessions sont archivées).

    « dû » = somme des lignes du convive ; « payé » = somme de ses paiements (mock/espèces) ;
    « reste » = dû − payé borné à 0. Sert le client ET la tablette resto, en temps réel."""
    with _conn() as c:
        session_id = _session_table(c, table_id)
        tva_taux = (c.execute("SELECT tva_taux FROM restaurants WHERE id=?",
                              (restaurant_id,)).fetchone() or [10.0])[0]
        cmds = c.execute("SELECT id, convive FROM commandes WHERE table_id=? AND restaurant_id=? "
                         "AND session_id=?", (table_id, restaurant_id, session_id)).fetchall()
        du: dict[str, int] = {}
        details: dict[str, list] = {}
        for cmd in cmds:
            conv = cmd["convive"]
            for l in _lignes_de(c, cmd["id"]):
                du[conv] = du.get(conv, 0) + l["prix_cents"] * l["quantite"]
                details.setdefault(conv, []).append(
                    {"nom_plat": l["nom_plat"], "prix_cents": l["prix_cents"], "quantite": l["quantite"]})
        paye: dict[str, int] = {}
        pourb: dict[str, int] = {}
        moyens: dict[str, str] = {}
        for p in c.execute("SELECT convive, montant_cents, pourboire_cents, moyen FROM paiements "
                           "WHERE table_id=? AND session_id=?", (table_id, session_id)).fetchall():
            paye[p["convive"]] = paye.get(p["convive"], 0) + p["montant_cents"]
            pourb[p["convive"]] = pourb.get(p["convive"], 0) + p["pourboire_cents"]
            moyens[p["convive"]] = p["moyen"]

    convives = []
    for nom in sorted(set(du) | set(paye)):
        d, p = du.get(nom, 0), paye.get(nom, 0)
        convives.append({"convive": nom, "du_cents": d, "paye_cents": p,
                         "reste_cents": max(0, d - p), "regle": p >= d and d > 0,
                         "pourboire_cents": pourb.get(nom, 0),
                         "moyen": moyens.get(nom, ""), "details": details.get(nom, [])})
    total = sum(c2["du_cents"] for c2 in convives)
    regle = sum(c2["paye_cents"] for c2 in convives)
    pourboire = sum(c2["pourboire_cents"] for c2 in convives)
    return {"table_id": table_id, "session_id": session_id, "convives": convives,
            "total_cents": total, "paye_cents": regle, "reste_cents": max(0, total - regle),
            "pourboire_cents": pourboire, "tva": _ventilation_tva(total, tva_taux)}


def enregistrer_paiement(restaurant_id: str, table_id: str, convive: str, moyen: str,
                         pourboire_cents: int = 0) -> dict | None:
    """Règle la PART d'un convive (son reste dû) par `moyen` (« mock » en ligne / « especes »),
    avec un pourboire optionnel.

    Idempotent par construction : on ne paie que le reste dû ; si tout est déjà réglé,
    renvoie None (rien à encaisser). Le montant est recalculé serveur (jamais soumis
    par le client) → un client ne peut pas « payer 0 » ni se sur-créditer. Le pourboire
    est borné à >= 0 et n'entre pas dans le « reste dû » (c'est un extra)."""
    if moyen not in ("mock", "especes"):
        return None
    pourboire_cents = max(0, int(pourboire_cents or 0))
    etat = etat_table(restaurant_id, table_id)
    part = next((c for c in etat["convives"] if c["convive"] == convive), None)
    if not part or part["reste_cents"] <= 0:
        return None
    with _conn() as c:
        session_id = _session_table(c, table_id)
        c.execute("INSERT INTO paiements (id, restaurant_id, table_id, session_id, convive, "
                  "montant_cents, pourboire_cents, moyen, regle_le) VALUES (?,?,?,?,?,?,?,?,?)",
                  (_id(), restaurant_id, table_id, session_id, convive, part["reste_cents"],
                   pourboire_cents, moyen, _maintenant()))
    return {"convive": convive, "montant_cents": part["reste_cents"],
            "pourboire_cents": pourboire_cents, "moyen": moyen}


def lister_tickets(compte_id: str, restaurant_id: str, limite: int = 50) -> list | None:
    """Historique des tickets archivés (clôtures), récents d'abord. Pour la compta du resto."""
    import json as _json
    with _conn() as c:
        if not _possede(c, compte_id, restaurant_id):
            return None
        rows = c.execute("SELECT id, table_id, numero, session_id, donnees, cloture_le FROM tickets "
                         "WHERE restaurant_id=? ORDER BY cloture_le DESC LIMIT ?",
                         (restaurant_id, max(1, int(limite)))).fetchall()
    return [{"id": r["id"], "table_id": r["table_id"], "table_numero": r["numero"],
             "session_id": r["session_id"], "etat": _json.loads(r["donnees"]),
             "cloture_le": r["cloture_le"]} for r in rows]


def cloturer_table(compte_id: str, restaurant_id: str, table_id: str, force: bool = False) -> dict | None:
    """Clôt la session courante d'une table → archive un TICKET et ouvre une session vierge.

    Refuse si le reste à payer n'est pas nul, SAUF `force` (ex. départ sans payer assumé
    par le resto). Marque les commandes de la session comme servies (sortent de la cuisine).
    Renvoie le ticket archivé, ou None si table absente / reste dû sans force."""
    with _conn() as c:
        if not _possede(c, compte_id, restaurant_id):
            return None
        t = c.execute("SELECT id, numero, session_courante FROM tables WHERE id=? AND restaurant_id=?",
                      (table_id, restaurant_id)).fetchone()
        if not t:
            return None
    etat = etat_table(restaurant_id, table_id)
    if etat["reste_cents"] > 0 and not force:
        return None
    if not etat["convives"]:
        return None      # rien à clôturer (table vide)
    import json as _json
    ticket = {"id": _id(), "table_numero": t["numero"], "session_id": t["session_courante"],
              "etat": etat, "cloture_le": _maintenant()}
    with _conn() as c:
        c.execute("INSERT INTO tickets (id, restaurant_id, table_id, session_id, numero, donnees, cloture_le) "
                  "VALUES (?,?,?,?,?,?,?)",
                  (ticket["id"], restaurant_id, table_id, t["session_courante"], t["numero"],
                   _json.dumps(ticket["etat"], ensure_ascii=False), ticket["cloture_le"]))
        # Les commandes de la session quittent la file cuisine, et la table repart vierge.
        c.execute("UPDATE commandes SET statut='servie' WHERE table_id=? AND session_id=?",
                  (table_id, t["session_courante"]))
        c.execute("UPDATE tables SET session_courante=session_courante+1 WHERE id=?", (table_id,))
    return ticket
