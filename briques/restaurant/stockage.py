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
            mot_de_passe TEXT NOT NULL, nom TEXT, cree_le TEXT);

        CREATE TABLE IF NOT EXISTS restaurants (
            id TEXT PRIMARY KEY, compte_id TEXT NOT NULL, nom TEXT,
            devise TEXT DEFAULT 'EUR', cree_le TEXT);
        CREATE INDEX IF NOT EXISTS idx_resto_compte ON restaurants(compte_id);

        CREATE TABLE IF NOT EXISTS tables (
            id TEXT PRIMARY KEY, restaurant_id TEXT NOT NULL, numero TEXT,
            code TEXT NOT NULL UNIQUE, cree_le TEXT);
        CREATE INDEX IF NOT EXISTS idx_table_resto ON tables(restaurant_id);

        CREATE TABLE IF NOT EXISTS plats (
            id TEXT PRIMARY KEY, restaurant_id TEXT NOT NULL, nom TEXT,
            description TEXT, prix_cents INTEGER NOT NULL DEFAULT 0, photo TEXT,
            disponible INTEGER NOT NULL DEFAULT 1, plat_du_jour INTEGER NOT NULL DEFAULT 0,
            ordre INTEGER NOT NULL DEFAULT 0, cree_le TEXT);
        CREATE INDEX IF NOT EXISTS idx_plat_resto ON plats(restaurant_id);

        CREATE TABLE IF NOT EXISTS commandes (
            id TEXT PRIMARY KEY, restaurant_id TEXT NOT NULL, table_id TEXT NOT NULL,
            convive TEXT, statut TEXT NOT NULL DEFAULT 'en_cuisine', cree_le TEXT);
        CREATE INDEX IF NOT EXISTS idx_cmd_resto ON commandes(restaurant_id);
        CREATE INDEX IF NOT EXISTS idx_cmd_table ON commandes(table_id);

        CREATE TABLE IF NOT EXISTS lignes (
            id TEXT PRIMARY KEY, commande_id TEXT NOT NULL, plat_id TEXT,
            nom_plat TEXT, prix_cents INTEGER NOT NULL DEFAULT 0, quantite INTEGER NOT NULL DEFAULT 1);
        CREATE INDEX IF NOT EXISTS idx_ligne_cmd ON lignes(commande_id);

        CREATE TABLE IF NOT EXISTS paiements (
            id TEXT PRIMARY KEY, restaurant_id TEXT NOT NULL, table_id TEXT NOT NULL,
            convive TEXT, montant_cents INTEGER NOT NULL, moyen TEXT NOT NULL,
            regle_le TEXT);
        CREATE INDEX IF NOT EXISTS idx_paie_table ON paiements(table_id);
        """
    )
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
        r = c.execute("SELECT id, email, nom, cree_le FROM comptes WHERE id=?", (compte_id,)).fetchone()
    return dict(r) if r else None


# ── Garde d'appartenance (cœur de l'isolation) ───────────────────
def _possede(c: sqlite3.Connection, compte_id: str, restaurant_id: str) -> bool:
    r = c.execute("SELECT 1 FROM restaurants WHERE id=? AND compte_id=?",
                  (restaurant_id, compte_id)).fetchone()
    return r is not None


# ── Restaurants ──────────────────────────────────────────────────
def creer_restaurant(compte_id: str, nom: str, devise: str = "EUR") -> dict:
    rid = _id()
    with _conn() as c:
        c.execute("INSERT INTO restaurants (id, compte_id, nom, devise, cree_le) VALUES (?,?,?,?,?)",
                  (rid, compte_id, nom.strip() or "Mon restaurant", devise or "EUR", _maintenant()))
    return {"id": rid, "nom": nom.strip() or "Mon restaurant", "devise": devise or "EUR"}


def lister_restaurants(compte_id: str) -> list:
    with _conn() as c:
        rows = c.execute("SELECT id, nom, devise, cree_le FROM restaurants WHERE compte_id=? "
                         "ORDER BY cree_le", (compte_id,)).fetchall()
    return [dict(r) for r in rows]


def lire_restaurant(compte_id: str, restaurant_id: str) -> dict | None:
    with _conn() as c:
        if not _possede(c, compte_id, restaurant_id):
            return None
        r = c.execute("SELECT id, nom, devise, cree_le FROM restaurants WHERE id=?",
                      (restaurant_id,)).fetchone()
    return dict(r) if r else None


def restaurant_public(restaurant_id: str) -> dict | None:
    """Infos publiques d'un resto (nom, devise) — sans compte, pour l'affichage client."""
    with _conn() as c:
        r = c.execute("SELECT id, nom, devise FROM restaurants WHERE id=?", (restaurant_id,)).fetchone()
    return dict(r) if r else None


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
        r = c.execute("SELECT id, restaurant_id, numero, code FROM tables WHERE code=?", (code,)).fetchone()
    return dict(r) if r else None


def supprimer_table(compte_id: str, restaurant_id: str, table_id: str) -> bool:
    with _conn() as c:
        if not _possede(c, compte_id, restaurant_id):
            return False
        cur = c.execute("DELETE FROM tables WHERE id=? AND restaurant_id=?", (table_id, restaurant_id))
    return cur.rowcount > 0


# ── Plats (la carte) ─────────────────────────────────────────────
def _plat_dict(r: sqlite3.Row) -> dict:
    return {"id": r["id"], "nom": r["nom"], "description": r["description"],
            "prix_cents": r["prix_cents"], "photo": r["photo"],
            "disponible": bool(r["disponible"]), "plat_du_jour": bool(r["plat_du_jour"]),
            "ordre": r["ordre"]}


def creer_plat(compte_id: str, restaurant_id: str, nom: str, description: str = "",
               prix_cents: int = 0, photo: str = "", plat_du_jour: bool = False) -> dict | None:
    with _conn() as c:
        if not _possede(c, compte_id, restaurant_id):
            return None
        pid = _id()
        ordre = (c.execute("SELECT COALESCE(MAX(ordre), 0) + 1 FROM plats WHERE restaurant_id=?",
                           (restaurant_id,)).fetchone()[0])
        c.execute("""INSERT INTO plats (id, restaurant_id, nom, description, prix_cents, photo,
                     disponible, plat_du_jour, ordre, cree_le) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                  (pid, restaurant_id, nom.strip() or "Plat", description.strip(),
                   max(0, int(prix_cents)), photo.strip(), 1, 1 if plat_du_jour else 0,
                   ordre, _maintenant()))
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
                         "ORDER BY plat_du_jour DESC, ordre, cree_le", (restaurant_id,)).fetchall()
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
        if "disponible" in champs and champs["disponible"] is not None:
            d["disponible"] = bool(champs["disponible"])
        if "plat_du_jour" in champs and champs["plat_du_jour"] is not None:
            d["plat_du_jour"] = bool(champs["plat_du_jour"])
        c.execute("""UPDATE plats SET nom=?, description=?, prix_cents=?, photo=?,
                     disponible=?, plat_du_jour=? WHERE id=? AND restaurant_id=?""",
                  (d["nom"], d["description"], d["prix_cents"], d["photo"],
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
    """Crée une commande pour un convive. `plats` = [{plat_id, quantite}].

    Le prix de chaque ligne est un SNAPSHOT pris au moment de la commande : si le
    restaurateur change le prix après coup, l'addition du convive ne bouge pas.
    Refuse les plats indisponibles / hors de ce restaurant (fail-closed)."""
    convive = (convive or "").strip() or "Convive"
    with _conn() as c:
        cmd_id = _id()
        lignes = []
        for item in plats or []:
            r = c.execute("SELECT * FROM plats WHERE id=? AND restaurant_id=? AND disponible=1",
                          (item.get("plat_id"), restaurant_id)).fetchone()
            if not r:
                continue
            q = max(1, int(item.get("quantite", 1)))
            lignes.append({"id": _id(), "plat_id": r["id"], "nom_plat": r["nom"],
                           "prix_cents": r["prix_cents"], "quantite": q})
        if not lignes:
            return None
        c.execute("INSERT INTO commandes (id, restaurant_id, table_id, convive, statut, cree_le) "
                  "VALUES (?,?,?,?,?,?)",
                  (cmd_id, restaurant_id, table_id, convive, "en_cuisine", _maintenant()))
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
def etat_table(restaurant_id: str, table_id: str) -> dict:
    """État d'addition d'une table : par convive (dû / payé / reste) + total table.

    « dû » d'un convive = somme de ses lignes ; « payé » = somme de ses paiements
    (mock en ligne OU espèces validées par le resto). « reste » = dû − payé, borné à 0.
    Sert le client (sa part) ET la tablette resto (vue d'ensemble), en temps réel."""
    with _conn() as c:
        cmds = c.execute("SELECT id, convive FROM commandes WHERE table_id=? AND restaurant_id=?",
                         (table_id, restaurant_id)).fetchall()
        du: dict[str, int] = {}
        details: dict[str, list] = {}
        for cmd in cmds:
            conv = cmd["convive"]
            for l in _lignes_de(c, cmd["id"]):
                du[conv] = du.get(conv, 0) + l["prix_cents"] * l["quantite"]
                details.setdefault(conv, []).append(
                    {"nom_plat": l["nom_plat"], "prix_cents": l["prix_cents"], "quantite": l["quantite"]})
        paye: dict[str, int] = {}
        moyens: dict[str, str] = {}
        for p in c.execute("SELECT convive, montant_cents, moyen FROM paiements WHERE table_id=?",
                           (table_id,)).fetchall():
            paye[p["convive"]] = paye.get(p["convive"], 0) + p["montant_cents"]
            moyens[p["convive"]] = p["moyen"]

    convives = []
    for nom in sorted(set(du) | set(paye)):
        d, p = du.get(nom, 0), paye.get(nom, 0)
        convives.append({"convive": nom, "du_cents": d, "paye_cents": p,
                         "reste_cents": max(0, d - p), "regle": p >= d and d > 0,
                         "moyen": moyens.get(nom, ""), "details": details.get(nom, [])})
    total = sum(c2["du_cents"] for c2 in convives)
    regle = sum(c2["paye_cents"] for c2 in convives)
    return {"table_id": table_id, "convives": convives, "total_cents": total,
            "paye_cents": regle, "reste_cents": max(0, total - regle)}


def enregistrer_paiement(restaurant_id: str, table_id: str, convive: str, moyen: str) -> dict | None:
    """Règle la PART d'un convive (son reste dû) par `moyen` (« mock » en ligne / « especes »).

    Idempotent par construction : on ne paie que le reste dû ; si tout est déjà réglé,
    renvoie None (rien à encaisser). Le montant est recalculé serveur (jamais soumis
    par le client) → un client ne peut pas « payer 0 » ni se sur-créditer."""
    if moyen not in ("mock", "especes"):
        return None
    etat = etat_table(restaurant_id, table_id)
    part = next((c for c in etat["convives"] if c["convive"] == convive), None)
    if not part or part["reste_cents"] <= 0:
        return None
    with _conn() as c:
        c.execute("INSERT INTO paiements (id, restaurant_id, table_id, convive, montant_cents, moyen, regle_le) "
                  "VALUES (?,?,?,?,?,?,?)",
                  (_id(), restaurant_id, table_id, convive, part["reste_cents"], moyen, _maintenant()))
    return {"convive": convive, "montant_cents": part["reste_cents"], "moyen": moyen}
