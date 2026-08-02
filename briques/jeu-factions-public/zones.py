"""Zones de signe (PvE partagé) — 12 zones fixes, une par signe solaire. Nation = élément,
guilde = signe : mapping figé, mirroir de `personnages/traditions.py::ELEMENTS_SIGNE` (pure
donnée de référence, pas un recalcul du moteur)."""
from __future__ import annotations

import uuid

import stockage as S

ZONES_SEED = [
    ("Bélier", "Feu"), ("Taureau", "Terre"), ("Gémeaux", "Air"), ("Cancer", "Eau"),
    ("Lion", "Feu"), ("Vierge", "Terre"), ("Balance", "Air"), ("Scorpion", "Eau"),
    ("Sagittaire", "Feu"), ("Capricorne", "Terre"), ("Verseau", "Air"), ("Poissons", "Eau"),
]
DIFFICULTE_PAR_DEFAUT = 150


def seed_zones() -> None:
    with S._conn() as c:
        for signe, element in ZONES_SEED:
            existe = c.execute("SELECT 1 FROM zones WHERE signe_natif=?", (signe,)).fetchone()
            if existe:
                continue
            c.execute("""INSERT INTO zones (id, nom, element_natif, signe_natif,
                         difficulte_pve, etat) VALUES (?,?,?,?,?, 'en_cours')""",
                      (uuid.uuid4().hex, f"Zone du {signe}", element, signe,
                       DIFFICULTE_PAR_DEFAUT))


def _ligne_zone(r) -> dict:
    return {"id": r["id"], "nom": r["nom"], "element_natif": r["element_natif"],
            "signe_natif": r["signe_natif"], "difficulte_pve": r["difficulte_pve"],
            "etat": r["etat"]}


def _scores_zone(zone_id: str) -> list[dict]:
    with S._conn() as c:
        rows = c.execute(
            "SELECT guilde, points_cumules FROM scores_zone_guilde WHERE zone_id=? "
            "ORDER BY points_cumules DESC", (zone_id,)).fetchall()
    return [{"guilde": r["guilde"], "points_cumules": r["points_cumules"]} for r in rows]


def _historique_zone(zone_id: str, limite: int = 5) -> list[dict]:
    import json
    with S._conn() as c:
        rows = c.execute(
            "SELECT horodatage, contributions, etat_resultant FROM resolutions "
            "WHERE zone_id=? ORDER BY horodatage DESC LIMIT ?", (zone_id, limite)).fetchall()
    return [{"horodatage": r["horodatage"], "etat_resultant": r["etat_resultant"],
             "contributions": json.loads(r["contributions"])} for r in rows]


def lister_zones() -> list[dict]:
    with S._conn() as c:
        rows = c.execute("SELECT * FROM zones ORDER BY nom").fetchall()
    return [{**_ligne_zone(r), "scores": _scores_zone(r["id"])} for r in rows]


def lire_zone(zone_id: str) -> dict | None:
    with S._conn() as c:
        r = c.execute("SELECT * FROM zones WHERE id=?", (zone_id,)).fetchone()
    if not r:
        return None
    return {**_ligne_zone(r), "scores": _scores_zone(zone_id), "historique": _historique_zone(zone_id)}


def signe_personnage(snapshot: dict) -> str | None:
    return ((snapshot.get("traditions") or {}).get("signe_solaire") or {}).get("nom")


def marquer_vaincue_si_premiere_fois(zone_id: str) -> bool:
    with S._conn() as c:
        cur = c.execute("UPDATE zones SET etat='vaincue' WHERE id=? AND etat='en_cours'", (zone_id,))
        return cur.rowcount > 0


def ajouter_score(zone_id: str, guilde: str, points: float) -> None:
    if points <= 0:
        return
    with S._conn() as c:
        c.execute("""INSERT INTO scores_zone_guilde (zone_id, guilde, points_cumules)
                     VALUES (?,?,?)
                     ON CONFLICT(zone_id, guilde) DO UPDATE SET
                     points_cumules = points_cumules + excluded.points_cumules""",
                  (zone_id, guilde, int(points)))
