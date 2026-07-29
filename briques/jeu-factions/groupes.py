"""Groupes ouverts sur une voie d'archétype — n'importe qui peut rejoindre pour aider
(« carry »), mais seuls les membres pour qui l'étape ciblée est EXACTEMENT leur propre
prochaine étape voient leur progression avancer (pas de saut, pas de re-completion)."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import archetypes as A
import stockage as S


def _maintenant() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ligne_groupe(c, groupe_id: str) -> dict:
    g = c.execute("SELECT * FROM groupes WHERE id=?", (groupe_id,)).fetchone()
    membres = [r["personnage_id"] for r in
              c.execute("SELECT personnage_id FROM membres_groupe WHERE groupe_id=?",
                       (groupe_id,)).fetchall()]
    return {"id": g["id"], "personnage_cible_id": g["personnage_cible_id"],
            "zone_archetype_id": g["zone_archetype_id"], "etat": g["etat"],
            "cree_le": g["cree_le"], "membres": membres}


def creer_groupe(personnage_cible_id: str, zone_archetype_id: str) -> dict:
    etape = A.lire_etape(zone_archetype_id)
    if not etape:
        raise ValueError("Étape d'archétype introuvable.")
    attendu = A.prochaine_etape(personnage_cible_id, etape["archetype"])
    if attendu != zone_archetype_id:
        raise ValueError("Cette étape n'est pas la prochaine de ce personnage sur cette voie.")
    gid = uuid.uuid4().hex
    cree_le = _maintenant()
    with S._conn() as c:
        c.execute("""INSERT INTO groupes (id, personnage_cible_id, zone_archetype_id, etat, cree_le)
                     VALUES (?,?,?, 'actif', ?)""",
                  (gid, personnage_cible_id, zone_archetype_id, cree_le))
        c.execute("INSERT INTO membres_groupe (groupe_id, personnage_id) VALUES (?,?)",
                 (gid, personnage_cible_id))
        return _ligne_groupe(c, gid)


def rejoindre_groupe(groupe_id: str, personnage_id: str) -> dict:
    with S._conn() as c:
        g = c.execute("SELECT etat FROM groupes WHERE id=?", (groupe_id,)).fetchone()
        if not g:
            raise ValueError("Groupe introuvable.")
        if g["etat"] != "actif":
            raise ValueError("Ce groupe n'est plus actif (déjà résolu ou dissous).")
        c.execute("INSERT OR IGNORE INTO membres_groupe (groupe_id, personnage_id) VALUES (?,?)",
                 (groupe_id, personnage_id))
        return _ligne_groupe(c, groupe_id)


def resoudre_groupes_actifs() -> list[dict]:
    """Orchestration DB — même discipline de connexions courtes que `zones.ajouter_score`/
    `marquer_vaincue_si_premiere_fois` (voir stockage.py) : chaque lecture/écriture utilise sa
    PROPRE connexion courte, refermée avant d'appeler une fonction qui ouvre la sienne
    (`archetypes.py`, `stockage.log_resolution`). Tenir une connexion ouverte pendant ces
    appels imbriqués se verrouille elle-même (`database is locked`) — NE PAS envelopper toute
    la fonction dans un seul `with S._conn() as c:`."""
    resultats = []
    with S._conn() as c:
        groupes_actifs = c.execute("SELECT * FROM groupes WHERE etat='actif'").fetchall()
    for gr in groupes_actifs:
        etape = A.lire_etape(gr["zone_archetype_id"])
        if not etape:
            continue
        stats_cles = A.ARCHETYPES_SIGNATURE[etape["archetype"]]
        with S._conn() as c:
            membres_ids = [r["personnage_id"] for r in c.execute(
                "SELECT personnage_id FROM membres_groupe WHERE groupe_id=?", (gr["id"],)).fetchall()]
            membres_stats = []
            for mid in membres_ids:
                row = c.execute("SELECT snapshot_holistique FROM personnages_jeu WHERE id=?",
                                (mid,)).fetchone()
                if not row:
                    continue
                snap = json.loads(row["snapshot_holistique"])
                stats = (snap.get("portrait") or {}).get("stats") or {}
                membres_stats.append({"personnage_id": mid, "stats": stats})
        res = A.calculer_resolution(membres_stats, stats_cles, etape["difficulte_pve"])
        etat_resultant = "vaincue" if res["vaincue"] else "en_cours"
        if res["vaincue"]:
            for mid in membres_ids:
                if A.prochaine_etape(mid, etape["archetype"]) == gr["zone_archetype_id"]:
                    A.marquer_etape_vaincue(mid, gr["zone_archetype_id"])
                    A.debloquer_competence_si_existe(mid, gr["zone_archetype_id"])
            with S._conn() as c:
                c.execute("UPDATE groupes SET etat='dissous' WHERE id=?", (gr["id"],))
        contributions = {m["personnage_id"]: sum(int(m["stats"].get(s, 0)) for s in stats_cles)
                         for m in membres_stats}
        S.log_resolution(None, gr["zone_archetype_id"], contributions, etat_resultant)
        resultats.append({"groupe_id": gr["id"], "etat_resultant": etat_resultant, **res})
    return resultats
