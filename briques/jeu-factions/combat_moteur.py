"""Cœur de simulation du combat temps réel — fonction PURE, zéro I/O (pas de DB, pas de
réseau, pas d'horloge système lue directement : `dt`/`horodatage` sont des paramètres,
jamais `time.monotonic()` appelé ici). Testable en pytest sans WebSocket ni asyncio réel.
Voir docs/superpowers/specs/2026-07-29-jeu-factions-combat-design.md."""
from __future__ import annotations

import math

VITESSE_JOUEUR = 120.0   # unités d'arène / seconde
VITESSE_MOB = 60.0
PV_MAX_JOUEUR = 100       # V1 : fixe, pas dérivé des stats holistiques (hors scope du spec)
DUREE_DOT_S = 5.0         # le spec ne définit pas de colonne « durée » pour les DOT (V1 fixe)

_CIBLE_MOB = {"degats", "etourdissement", "dot"}
_CIBLE_JOUEUR = {"soin", "bouclier"}


def _instancier_mob(gabarit: dict, x: float, y: float) -> dict:
    return {"template_id": gabarit["id"], "nom": gabarit["nom"], "role": gabarit["role"],
            "x": x, "y": y, "pv": gabarit["pv_max"], "pv_max": gabarit["pv_max"],
            "degats_attaque": gabarit["degats_attaque"],
            "cooldown_attaque_s": gabarit["cooldown_attaque_s"], "cooldown_restant": 0.0,
            "portee_aggro": gabarit["portee_aggro"], "portee_attaque": gabarit["portee_attaque"],
            "cible_id": None, "bouclier": 0, "etourdi_jusqua": 0.0, "dots": [],
            "degats_recus_par_guilde": {}}


def nouvel_etat_instance(zone_id: str, arene_taille: int, mobs_zone: list[dict]) -> dict:
    """`mobs_zone` = `mobs.lister_mobs_zone(zone_id)` (Task 1). Place le boss au centre, les
    autres mobs éparpillés en cercle autour."""
    centre = arene_taille / 2
    gabarit_boss = next((m for m in mobs_zone if m["role"] == "boss"), None)
    autres = [m for m in mobs_zone if m["role"] != "boss"]
    mobs: dict[str, dict] = {}
    for i, m in enumerate(autres):
        angle = (2 * math.pi * i) / max(len(autres), 1)
        rayon = arene_taille * 0.3
        mobs[f"{m['id']}-{i}"] = _instancier_mob(m, centre + rayon * math.cos(angle),
                                                  centre + rayon * math.sin(angle))
    if gabarit_boss:
        mobs[f"{gabarit_boss['id']}-boss"] = _instancier_mob(gabarit_boss, centre, centre)
    return {"zone_id": zone_id, "arene_taille": arene_taille, "joueurs": {}, "mobs": mobs,
            "_gabarit_boss": gabarit_boss, "boss_mort_horodatage": None}


def ajouter_joueur(etat: dict, personnage_id: str, element: str, signe: str) -> dict:
    bord = etat["arene_taille"] * 0.05
    etat["joueurs"][personnage_id] = {
        "x": bord, "y": bord, "pv": PV_MAX_JOUEUR, "pv_max": PV_MAX_JOUEUR,
        "element": element, "signe": signe, "etat": "actif",
        "cooldowns": {}, "bouclier": 0, "dots": [],
    }
    return etat


def retirer_joueur(etat: dict, personnage_id: str) -> dict:
    etat["joueurs"].pop(personnage_id, None)
    for m in etat["mobs"].values():
        if m["cible_id"] == personnage_id:
            m["cible_id"] = None
    return etat


def _distance(a: dict, b: dict) -> float:
    return math.hypot(a["x"] - b["x"], a["y"] - b["y"])


def _trouver_entite(etat: dict, entite_id: str) -> tuple[dict | None, str]:
    if entite_id in etat["joueurs"]:
        return etat["joueurs"][entite_id], "joueur"
    if entite_id in etat["mobs"]:
        return etat["mobs"][entite_id], "mob"
    return None, ""


def _infliger_degats(cible: dict, degats: float) -> float:
    """Absorbe d'abord via `bouclier`, puis réduit `pv` (jamais sous 0). Renvoie les PV
    réellement perdus (hors bouclier) — sert au calcul des contributions par guilde."""
    absorbe = min(cible.get("bouclier", 0), degats)
    cible["bouclier"] = cible.get("bouclier", 0) - absorbe
    reste = degats - absorbe
    avant = cible["pv"]
    cible["pv"] = max(0, cible["pv"] - reste)
    return avant - cible["pv"]


def avancer_tick(etat: dict, actions: list[dict], dt: float, competences: dict[str, dict],
                 horodatage: float, respawn_delai_s: float) -> tuple[dict, list[dict]]:
    """`competences` = {competence_id: {"effet_type", "magnitude", "portee", "cooldown_s"}}
    (chargé une fois par l'appelant — Task 5 — jamais lu depuis la DB ici). `actions` =
    [{"type": "deplacement"|"sort", "personnage_id", ...}]."""
    evenements: list[dict] = []

    # 1. Déplacement
    for a in actions:
        if a.get("type") != "deplacement":
            continue
        j = etat["joueurs"].get(a.get("personnage_id"))
        if not j or j["etat"] != "actif":
            continue
        direction = a.get("direction")
        if not isinstance(direction, dict):
            continue
        dx, dy = direction.get("x", 0), direction.get("y", 0)
        if not isinstance(dx, (int, float)) or not isinstance(dy, (int, float)):
            continue
        norme = math.hypot(dx, dy)
        if norme == 0:
            continue
        j["x"] = min(max(j["x"] + (dx / norme) * VITESSE_JOUEUR * dt, 0), etat["arene_taille"])
        j["y"] = min(max(j["y"] + (dy / norme) * VITESSE_JOUEUR * dt, 0), etat["arene_taille"])

    # 2. Cooldowns
    for j in etat["joueurs"].values():
        for cid in list(j["cooldowns"]):
            j["cooldowns"][cid] = max(0.0, j["cooldowns"][cid] - dt)
    for m in etat["mobs"].values():
        m["cooldown_restant"] = max(0.0, m["cooldown_restant"] - dt)

    # 3. Sorts
    for a in actions:
        if a.get("type") != "sort":
            continue
        j = etat["joueurs"].get(a.get("personnage_id"))
        comp = competences.get(a.get("competence_id", ""))
        if not j or j["etat"] != "actif" or not comp or not comp.get("effet_type"):
            continue
        if j["cooldowns"].get(a.get("competence_id"), 0) > 0:
            continue
        cible, genre = _trouver_entite(etat, a.get("cible_id", ""))
        if cible is None:
            continue
        effet = comp["effet_type"]
        if effet in _CIBLE_MOB and genre != "mob":
            continue
        if effet in _CIBLE_JOUEUR and genre != "joueur":
            continue
        if _distance(j, cible) > comp["portee"]:
            continue
        j["cooldowns"][a.get("competence_id")] = comp["cooldown_s"]
        if effet == "degats":
            reels = _infliger_degats(cible, comp["magnitude"])
            cible["degats_recus_par_guilde"][j["signe"]] = \
                cible["degats_recus_par_guilde"].get(j["signe"], 0) + reels
            evenements.append({"type": "mob_touche", "mob_id": a.get("cible_id"), "degats": reels})
        elif effet == "soin":
            cible["pv"] = min(cible["pv_max"], cible["pv"] + comp["magnitude"])
            if cible.get("etat") == "ko" and cible["pv"] > 0:
                cible["etat"] = "actif"
        elif effet == "bouclier":
            cible["bouclier"] = cible.get("bouclier", 0) + comp["magnitude"]
        elif effet == "etourdissement":
            cible["etourdi_jusqua"] = horodatage + comp["magnitude"]
        elif effet == "dot":
            cible.setdefault("dots", []).append(
                {"degats_par_seconde": comp["magnitude"], "expire_a": horodatage + DUREE_DOT_S,
                 "guilde": j["signe"]})

    # 4. DOT (joueurs et mobs)
    for entites in (etat["joueurs"], etat["mobs"]):
        for e in entites.values():
            actifs = []
            for d in e.get("dots", []):
                if horodatage >= d["expire_a"]:
                    continue
                reels = _infliger_degats(e, d["degats_par_seconde"] * dt)
                if "degats_recus_par_guilde" in e:
                    e["degats_recus_par_guilde"][d["guilde"]] = \
                        e["degats_recus_par_guilde"].get(d["guilde"], 0) + reels
                actifs.append(d)
            e["dots"] = actifs

    # 5. IA des mobs (aggro le plus proche dans sa portée, pas de pathfinding)
    joueurs_actifs = [(pid, j) for pid, j in etat["joueurs"].items() if j["etat"] == "actif"]
    for m in etat["mobs"].values():
        if horodatage < m.get("etourdi_jusqua", 0):
            continue
        cible_id, cible, meilleure_distance = None, None, None
        for pid, j in joueurs_actifs:
            d = _distance(m, j)
            if d <= m["portee_aggro"] and (meilleure_distance is None or d < meilleure_distance):
                cible_id, cible, meilleure_distance = pid, j, d
        m["cible_id"] = cible_id
        if cible is None:
            continue
        distance = _distance(m, cible)
        if distance > m["portee_attaque"]:
            dx, dy = cible["x"] - m["x"], cible["y"] - m["y"]
            norme = math.hypot(dx, dy) or 1
            m["x"] += (dx / norme) * VITESSE_MOB * dt
            m["y"] += (dy / norme) * VITESSE_MOB * dt
        elif m["cooldown_restant"] <= 0:
            m["cooldown_restant"] = m["cooldown_attaque_s"]
            reels = _infliger_degats(cible, m["degats_attaque"])
            evenements.append({"type": "joueur_touche", "personnage_id": cible_id, "degats": reels})
            if cible["pv"] <= 0 and cible["etat"] == "actif":
                cible["etat"] = "ko"
                evenements.append({"type": "joueur_ko", "personnage_id": cible_id})

    # 6. Morts de mobs (retrait + événement) + respawn du boss
    for mid in [mid for mid, m in etat["mobs"].items() if m["pv"] <= 0]:
        m = etat["mobs"].pop(mid)
        type_evenement = "boss_tue" if m["role"] == "boss" else "mob_tue"
        evenements.append({"type": type_evenement, "mob_id": mid,
                           "contributions": dict(m["degats_recus_par_guilde"])})
        if m["role"] == "boss":
            etat["boss_mort_horodatage"] = horodatage

    boss_present = any(m["role"] == "boss" for m in etat["mobs"].values())
    if (etat["boss_mort_horodatage"] is not None and not boss_present and etat["_gabarit_boss"]
            and horodatage - etat["boss_mort_horodatage"] >= respawn_delai_s):
        centre = etat["arene_taille"] / 2
        gabarit = etat["_gabarit_boss"]
        etat["mobs"][f"{gabarit['id']}-boss-{int(horodatage)}"] = \
            _instancier_mob(gabarit, centre, centre)
        etat["boss_mort_horodatage"] = None
        evenements.append({"type": "boss_reapparu"})

    return etat, evenements
