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


def calculer_resolution(personnages: list[dict], stats_cles: list[str], difficulte: int) -> dict:
    """Fonction PURE : `personnages` = [{"id", "signe", "stats": {...}}]. Somme les stats
    pertinentes, tous comptes confondus, et répartit les points par guilde (signe)."""
    total = 0
    par_guilde: dict[str, int] = {}
    for p in personnages:
        contribution = sum(int(p["stats"].get(s, 0)) for s in stats_cles)
        total += contribution
        par_guilde[p["signe"]] = par_guilde.get(p["signe"], 0) + contribution
    return {"total": total, "par_guilde": par_guilde, "vaincue": total >= difficulte}


def _signe_personnage(snapshot: dict) -> str | None:
    return ((snapshot.get("traditions") or {}).get("signe_solaire") or {}).get("nom")


def _stats_personnage(snapshot: dict) -> dict:
    return (snapshot.get("portrait") or {}).get("stats") or {}


def resoudre_toutes_zones(stats_cles: list[str]) -> list[dict]:
    """Orchestration DB : pour chaque zone `en_cours`, agrège les personnages assignés,
    résout, met à jour l'état + les scores + le log. Renvoie un résumé par zone traitée.

    Chaque zone est traitée dans sa propre transaction courte (connexion SQLite dédiée,
    validée avant de passer à la suivante) : `stockage.log_resolution` ouvre elle-même
    sa propre connexion, et une transaction d'écriture englobant tout le traitement se
    verrouillerait elle-même face à cette seconde connexion (`database is locked`)."""
    import json

    resultats = []
    with S._conn() as c:
        zones_en_cours = c.execute("SELECT * FROM zones WHERE etat='en_cours'").fetchall()
    for zr in zones_en_cours:
        with S._conn() as c:
            rows = c.execute(
                "SELECT * FROM personnages_jeu WHERE zone_actuelle=?", (zr["id"],)).fetchall()
            personnages = []
            for r in rows:
                snap = json.loads(r["snapshot_holistique"])
                signe = _signe_personnage(snap)
                if not signe:
                    continue
                personnages.append({"id": r["id"], "signe": signe, "stats": _stats_personnage(snap)})
            res = calculer_resolution(personnages, stats_cles, zr["difficulte_pve"])
            etat_resultant = "vaincue" if res["vaincue"] else "en_cours"
            if res["vaincue"]:
                c.execute("UPDATE zones SET etat='vaincue' WHERE id=?", (zr["id"],))
            for guilde, points in res["par_guilde"].items():
                c.execute("""INSERT INTO scores_zone_guilde (zone_id, guilde, points_cumules)
                             VALUES (?,?,?)
                             ON CONFLICT(zone_id, guilde) DO UPDATE SET
                             points_cumules = points_cumules + excluded.points_cumules""",
                          (zr["id"], guilde, points))
        S.log_resolution(zr["id"], None, res["par_guilde"], etat_resultant)
        resultats.append({"zone_id": zr["id"], "etat_resultant": etat_resultant, **res})
    return resultats
