"""Résolution planifiée des groupes actifs (voies d'archétype). Les zones de signe ne sont
plus résolues ici — elles se jouent en temps réel (cf. combat.py, combat_moteur.py).
`executer_tick()` est une passe unique, appelée par les tests SANS sleep, et par
`boucle_tick()` en production."""
import asyncio
import os

import groupes

TICK_INTERVAL_HOURS = float(os.getenv("TICK_INTERVAL_HOURS", "24"))


def executer_tick() -> dict:
    return {"groupes": groupes.resoudre_groupes_actifs()}


async def boucle_tick() -> None:
    while True:
        executer_tick()
        await asyncio.sleep(TICK_INTERVAL_HOURS * 3600)
