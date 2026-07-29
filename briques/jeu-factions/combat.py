"""Orchestration asyncio du combat temps réel : sharding des instances par zone, cycle de
vie (jointure/départ/fermeture après grâce), et persistance des événements de simulation
(le seul point de contact entre `combat_moteur.py` — pur — et la DB). Voir
docs/superpowers/specs/2026-07-29-jeu-factions-combat-design.md."""
from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field

import combat_moteur as CM
import stockage
import zones


def capacite() -> int:
    return int(os.getenv("JEU_FACTIONS_INSTANCE_CAPACITE", "30"))


def arene_taille() -> int:
    return int(os.getenv("COMBAT_ARENE_TAILLE", "800"))


def tick_hz() -> float:
    return float(os.getenv("COMBAT_TICK_HZ", "10"))


def grace_s() -> float:
    return float(os.getenv("COMBAT_INSTANCE_GRACE_S", "30"))


def respawn_delai_s() -> float:
    return float(os.getenv("COMBAT_BOSS_RESPAWN_S", "60"))


@dataclass
class InstanceCombat:
    id: str
    zone_id: str
    etat: dict
    connexions: dict = field(default_factory=dict)     # personnage_id -> WebSocket
    file_actions: list = field(default_factory=list)   # actions en attente du prochain tick
    derniere_activite: float | None = None              # horodatage depuis lequel vide
    tache: asyncio.Task | None = None


_INSTANCES: dict[str, list[InstanceCombat]] = {}


def _instance_disponible(zone_id: str) -> InstanceCombat | None:
    for inst in _INSTANCES.get(zone_id, []):
        if len(inst.connexions) < capacite():
            return inst
    return None


def _creer_instance(zone_id: str, mobs_zone: list[dict]) -> InstanceCombat:
    import uuid
    etat = CM.nouvel_etat_instance(zone_id, arene_taille(), mobs_zone)
    inst = InstanceCombat(id=uuid.uuid4().hex, zone_id=zone_id, etat=etat)
    _INSTANCES.setdefault(zone_id, []).append(inst)
    return inst


async def rejoindre(zone_id: str, personnage_id: str, element: str, signe: str,
                    mobs_zone: list[dict]) -> InstanceCombat:
    inst = _instance_disponible(zone_id) or _creer_instance(zone_id, mobs_zone)
    inst.etat = CM.ajouter_joueur(inst.etat, personnage_id, element, signe)
    inst.derniere_activite = None
    return inst


def enregistrer_connexion(inst: InstanceCombat, personnage_id: str, websocket) -> None:
    inst.connexions[personnage_id] = websocket


def empiler_action(inst: InstanceCombat, personnage_id: str, message: dict) -> None:
    action = dict(message)
    action["personnage_id"] = personnage_id
    inst.file_actions.append(action)


def vider_actions(inst: InstanceCombat) -> list[dict]:
    actions, inst.file_actions = inst.file_actions, []
    return actions


def quitter(inst: InstanceCombat, personnage_id: str, horodatage: float) -> None:
    inst.etat = CM.retirer_joueur(inst.etat, personnage_id)
    inst.connexions.pop(personnage_id, None)
    if not inst.connexions:
        inst.derniere_activite = horodatage


def instance_expiree(inst: InstanceCombat, horodatage: float) -> bool:
    return (not inst.connexions and inst.derniere_activite is not None
            and horodatage - inst.derniere_activite >= grace_s())


def fermer_instance(inst: InstanceCombat) -> None:
    if inst.tache:
        inst.tache.cancel()
    liste = _INSTANCES.get(inst.zone_id, [])
    if inst in liste:
        liste.remove(inst)


def persister_evenements(zone_id: str, evenements: list[dict]) -> None:
    for ev in evenements:
        if ev["type"] in ("mob_tue", "boss_tue"):
            for guilde, points in ev.get("contributions", {}).items():
                zones.ajouter_score(zone_id, guilde, points)
            stockage.log_resolution(zone_id, None, ev.get("contributions", {}), ev["type"])
        if ev["type"] == "boss_tue":
            zones.marquer_vaincue_si_premiere_fois(zone_id)


async def un_tick(inst: InstanceCombat, actions: list[dict], dt: float,
                  competences: dict[str, dict], horodatage: float) -> list[dict]:
    inst.etat, evenements = CM.avancer_tick(inst.etat, actions, dt, competences, horodatage,
                                            respawn_delai_s())
    persister_evenements(inst.zone_id, evenements)
    return evenements


def etat_public(inst: InstanceCombat) -> dict:
    return {"instance_id": inst.id, "zone_id": inst.zone_id,
            "joueurs": inst.etat["joueurs"], "mobs": inst.etat["mobs"]}


async def diffuser_etat(inst: InstanceCombat) -> None:
    message = {"type": "etat", **etat_public(inst)}
    deconnectes = []
    for personnage_id, ws in inst.connexions.items():
        try:
            await ws.send_json(message)
        except Exception:
            deconnectes.append(personnage_id)
    for personnage_id in deconnectes:
        inst.connexions.pop(personnage_id, None)


def demarrer_boucle_si_necessaire(inst: InstanceCombat, competences: dict[str, dict]) -> None:
    if inst.tache is not None:
        return
    if os.getenv("JEU_FACTIONS_COMBAT_AUTOSTART", "1") == "0":
        return
    inst.tache = asyncio.create_task(_boucle_instance(inst, competences))


async def _boucle_instance(inst: InstanceCombat, competences: dict[str, dict]) -> None:
    dt = 1.0 / tick_hz()
    while True:
        await asyncio.sleep(dt)
        actions = vider_actions(inst)
        await un_tick(inst, actions, dt, competences, time.monotonic())
        await diffuser_etat(inst)
        if instance_expiree(inst, time.monotonic()):
            fermer_instance(inst)
            return
