"""Résolution planifiée des zones de signe et des groupes actifs. `executer_tick()` est une
passe unique, appelée par les tests SANS sleep, et par `boucle_tick()` en production."""
import asyncio
import os

import groupes
import zones

STATS_ZONE_SIGNE = [s.strip() for s in
                    os.getenv("STATS_ZONE_SIGNE", "Combativité,Énergie").split(",") if s.strip()]
TICK_INTERVAL_HOURS = float(os.getenv("TICK_INTERVAL_HOURS", "24"))


def executer_tick() -> dict:
    return {"zones": zones.resoudre_toutes_zones(STATS_ZONE_SIGNE),
            "groupes": groupes.resoudre_groupes_actifs()}


async def boucle_tick() -> None:
    while True:
        executer_tick()
        await asyncio.sleep(TICK_INTERVAL_HOURS * 3600)
