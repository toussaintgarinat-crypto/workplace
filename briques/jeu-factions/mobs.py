"""Mobs/boss de combat par zone de signe — données de seed (même motif que
`zones.ZONES_SEED`) : un boss + deux mobs de « trash » par zone. Voir
docs/superpowers/specs/2026-07-29-jeu-factions-combat-design.md."""
from __future__ import annotations

import uuid

import stockage as S

# (role, nom, pv_max, degats_attaque, cooldown_attaque_s, portee_aggro, portee_attaque)
GABARIT_BOSS = ("boss", "Gardien de la zone", 400, 12, 1.5, 250, 30)
GABARITS_MOBS = [
    ("mob", "Sentinelle", 60, 6, 1.0, 150, 25),
    ("mob", "Sentinelle", 60, 6, 1.0, 150, 25),
]


def seed_mobs() -> None:
    with S._conn() as c:
        zones_existantes = c.execute("SELECT id, nom FROM zones").fetchall()
        for zone in zones_existantes:
            existe = c.execute("SELECT 1 FROM mobs_zone WHERE zone_id=?", (zone["id"],)).fetchone()
            if existe:
                continue
            for role, nom, pv_max, degats, cooldown, aggro, portee in [GABARIT_BOSS, *GABARITS_MOBS]:
                nom_final = f"{nom} — {zone['nom']}" if role == "boss" else nom
                c.execute("""INSERT INTO mobs_zone (id, zone_id, nom, role, pv_max,
                             degats_attaque, cooldown_attaque_s, portee_aggro, portee_attaque)
                             VALUES (?,?,?,?,?,?,?,?,?)""",
                          (uuid.uuid4().hex, zone["id"], nom_final, role, pv_max, degats,
                           cooldown, aggro, portee))


def _ligne_mob(r) -> dict:
    return {"id": r["id"], "zone_id": r["zone_id"], "nom": r["nom"], "role": r["role"],
            "pv_max": r["pv_max"], "degats_attaque": r["degats_attaque"],
            "cooldown_attaque_s": r["cooldown_attaque_s"], "portee_aggro": r["portee_aggro"],
            "portee_attaque": r["portee_attaque"]}


def lister_mobs_zone(zone_id: str) -> list[dict]:
    with S._conn() as c:
        rows = c.execute("SELECT * FROM mobs_zone WHERE zone_id=? ORDER BY role DESC",
                         (zone_id,)).fetchall()
    return [_ligne_mob(r) for r in rows]
