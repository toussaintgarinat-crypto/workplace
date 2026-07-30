"""Mobs/boss de combat par étape de voie d'archétype — même motif que mobs.py, mais une
ligne dédiée par étape (zone_archetype_id) plutôt que par zone_id (S218). Les stats sont
dérivées de difficulte_pve (seule variable réelle entre étapes d'un même archétype) ; le nom
du boss reprend le titre de l'étape (cf. archetypes.py, contenu narratif S219)."""
from __future__ import annotations

import uuid

import stockage as S


def _gabarit_boss_etape(difficulte: int, nom_etape: str) -> tuple:
    return ("boss", f"{nom_etape} — Gardien", difficulte * 3, max(8, difficulte // 8),
            1.5, difficulte + 140, 30)


def _gabarits_mobs_etape(difficulte: int) -> list[tuple]:
    pv = max(30, difficulte // 3)
    degats = max(4, difficulte // 20)
    return [("mob", "Disciple de la voie", pv, degats, 1.0, difficulte + 70, 25),
            ("mob", "Disciple de la voie", pv, degats, 1.0, difficulte + 70, 25)]


def seed_mobs_archetype() -> None:
    with S._conn() as c:
        etapes = c.execute("SELECT id, nom, difficulte_pve FROM zones_archetype").fetchall()
        for e in etapes:
            existe = c.execute(
                "SELECT 1 FROM mobs_zone_archetype WHERE zone_archetype_id=?",
                (e["id"],)).fetchone()
            if existe:
                continue
            gabarits = [_gabarit_boss_etape(e["difficulte_pve"], e["nom"]),
                        *_gabarits_mobs_etape(e["difficulte_pve"])]
            for role, nom, pv_max, degats, cooldown, aggro, portee in gabarits:
                c.execute("""INSERT INTO mobs_zone_archetype
                             (id, zone_archetype_id, nom, role, pv_max, degats_attaque,
                              cooldown_attaque_s, portee_aggro, portee_attaque)
                             VALUES (?,?,?,?,?,?,?,?,?)""",
                          (uuid.uuid4().hex, e["id"], nom, role, pv_max, degats,
                           cooldown, aggro, portee))


def _ligne_mob(r) -> dict:
    return {"id": r["id"], "zone_archetype_id": r["zone_archetype_id"], "nom": r["nom"],
            "role": r["role"], "pv_max": r["pv_max"], "degats_attaque": r["degats_attaque"],
            "cooldown_attaque_s": r["cooldown_attaque_s"], "portee_aggro": r["portee_aggro"],
            "portee_attaque": r["portee_attaque"]}


def lister_mobs_etape(zone_archetype_id: str) -> list[dict]:
    with S._conn() as c:
        rows = c.execute(
            "SELECT * FROM mobs_zone_archetype WHERE zone_archetype_id=? ORDER BY role DESC",
            (zone_archetype_id,)).fetchall()
    return [_ligne_mob(r) for r in rows]
