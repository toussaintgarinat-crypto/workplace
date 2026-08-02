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
import archetypes
import groupes


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
    contexte: str = "zone"                              # "zone" | "archetype"
    connexions: dict = field(default_factory=dict)     # personnage_id -> WebSocket
    file_actions: list = field(default_factory=list)   # actions en attente du prochain tick
    derniere_activite: float | None = None              # horodatage depuis lequel vide
    tache: asyncio.Task | None = None


_INSTANCES: dict[str, list[InstanceCombat]] = {}


def _cle_partition(cle: str, contexte: str) -> str:
    return cle if contexte == "zone" else f"{contexte}:{cle}"


def _instance_disponible(cle: str, contexte: str) -> InstanceCombat | None:
    for inst in _INSTANCES.get(_cle_partition(cle, contexte), []):
        if len(inst.connexions) < capacite():
            return inst
    return None


def _creer_instance(zone_id: str, mobs_zone: list[dict], contexte: str) -> InstanceCombat:
    import uuid
    etat = CM.nouvel_etat_instance(zone_id, arene_taille(), mobs_zone)
    inst = InstanceCombat(id=uuid.uuid4().hex, zone_id=zone_id, etat=etat, contexte=contexte)
    _INSTANCES.setdefault(_cle_partition(zone_id, contexte), []).append(inst)
    return inst


async def rejoindre(zone_id: str, personnage_id: str, element: str, signe: str,
                    mobs_zone: list[dict], contexte: str = "zone",
                    cle_contribution: str | None = None) -> InstanceCombat:
    inst = _instance_disponible(zone_id, contexte) or _creer_instance(zone_id, mobs_zone, contexte)
    inst.etat = CM.ajouter_joueur(inst.etat, personnage_id, element, signe, cle_contribution)
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
    liste = _INSTANCES.get(_cle_partition(inst.zone_id, inst.contexte), [])
    if inst in liste:
        liste.remove(inst)


def persister_evenements(inst: InstanceCombat, evenements: list[dict]) -> None:
    for ev in evenements:
        if ev["type"] not in ("mob_tue", "boss_tue"):
            continue
        contributions = ev.get("contributions", {})
        if inst.contexte == "zone":
            for guilde, points in contributions.items():
                zones.ajouter_score(inst.zone_id, guilde, points)
            stockage.log_resolution(inst.zone_id, None, contributions, ev["type"])
            if ev["type"] == "boss_tue":
                zones.marquer_vaincue_si_premiere_fois(inst.zone_id)
        else:
            stockage.log_resolution(None, inst.zone_id, contributions, ev["type"])
            if ev["type"] == "boss_tue":
                etape = archetypes.lire_etape(inst.zone_id)
                if etape:
                    for personnage_id in contributions:
                        if archetypes.prochaine_etape(personnage_id, etape["archetype"]) == inst.zone_id:
                            archetypes.marquer_etape_vaincue(personnage_id, inst.zone_id)
                            archetypes.debloquer_competence_si_existe(personnage_id, inst.zone_id)
                groupes.dissoudre_groupes_de_letape(inst.zone_id)


async def un_tick(inst: InstanceCombat, actions: list[dict], dt: float,
                  competences: dict[str, dict], horodatage: float) -> list[dict]:
    inst.etat, evenements = CM.avancer_tick(inst.etat, actions, dt, competences, horodatage,
                                            respawn_delai_s())
    persister_evenements(inst, evenements)
    return evenements


def appliquer_bonus_idle(inst: InstanceCombat, degats: float, cle_contribution: str) -> None:
    inst.etat = CM.appliquer_bonus_degats(inst.etat, degats, cle_contribution)


def etat_public(inst: InstanceCombat) -> dict:
    return {"instance_id": inst.id, "zone_id": inst.zone_id,
            "joueurs": inst.etat["joueurs"], "mobs": inst.etat["mobs"]}


async def diffuser_etat(inst: InstanceCombat, evenements: list[dict] | None = None,
                        horodatage: float | None = None) -> None:
    message = {"type": "etat", **etat_public(inst), "evenements": evenements or []}
    deconnectes = []
    for personnage_id, ws in inst.connexions.items():
        try:
            await ws.send_json(message)
        except Exception:
            deconnectes.append(personnage_id)
    for personnage_id in deconnectes:
        inst.connexions.pop(personnage_id, None)
    if deconnectes and not inst.connexions:
        inst.derniere_activite = horodatage if horodatage is not None else time.monotonic()


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
        try:
            horodatage = time.monotonic()
            actions = vider_actions(inst)
            evenements = await un_tick(inst, actions, dt, competences, horodatage)
            await diffuser_etat(inst, evenements, horodatage)
        except Exception as e:
            # Défense en profondeur : une exception inattendue dans un tick ne doit jamais
            # tuer silencieusement la Task et figer l'instance (fix 1 de combat_moteur.py
            # empêche déjà la cause connue — ceci couvre l'imprévu).
            print(f"[combat] tick error instance={inst.id}: {e}")
        # Vérification d'expiration : s'exécute même après une exception pour permettre
        # la fermeture d'instances devenues vides dont le délai de grâce a expiré.
        if instance_expiree(inst, time.monotonic()):
            fermer_instance(inst)
            return
