"""Orchestrateur du tick de simulation (Sprint C) : exécute un tick complet sur
un monde. Lit un instantané figé de l'état en DÉBUT de tick (population, stocks,
technologie, couples), applique la mécanique pure de `horloge.py` cellule par
cellule SUR CET INSTANTANÉ (jamais de re-lecture après une écriture DANS le même
tick — un habitant n'est traité qu'une seule fois par tick, voir design), déclenche
les naissances via `genome_moteur.executer_croisement`, puis applique toutes les
écritures en une dernière phase. Chaque groupe d'écritures est isolé : une erreur
n'interrompt jamais le reste du tick (repli honnête, même motif que Sprint A/B)."""
from __future__ import annotations

from random import Random

from fastapi import HTTPException

import genome_moteur
import horloge
import stockage_horloge
import stockage_spatial

ANNEE_BASE_HORLOGE = 2000  # année narrative de départ pour les naissances automatiques —
                            # sans lien avec l'année réelle, juste une base valide pour
                            # calculer un thème astral (voir genome_moteur.Croisement.annee_enfant)


def _rng(seed: int, tick: int, cellule_id: int, etape: str) -> Random:
    return Random(f"{seed}:{tick}:{cellule_id}:{etape}")


async def executer_tick(monde_id: str, cle_api_val: str) -> dict:
    horloge_etat = stockage_horloge.lire_horloge(monde_id)
    if horloge_etat is None:
        raise HTTPException(404, f"Horloge du monde '{monde_id}' introuvable.")
    tick_suivant = horloge_etat["tick_actuel"] + 1

    monde = stockage_spatial.lire_monde(cle_api_val, monde_id)
    if monde is None:
        raise HTTPException(404, f"Monde '{monde_id}' introuvable.")
    seed = monde["seed"]

    avertissements: list[str] = []
    naissances = morts = migrations = couples_formes = couples_dissous = 0
    niveaux_tech: list[float] = []

    # --- Phase 1 : instantané figé du monde en début de tick ---
    population = {}
    stocks = {}
    niveaux = {}
    couples_par_cellule = {}
    for cel in monde["cellules"]:
        cid = cel["cellule_id"]
        population[cid] = stockage_spatial.population_vivante_cellule(monde_id, cid)
        stocks[cid] = stockage_spatial.lire_ressources_stock(monde_id, cid)
        niveaux[cid] = stockage_spatial.lire_niveau_technologie(monde_id, cid)
        couples_par_cellule[cid] = stockage_horloge.couples_actifs_cellule(monde_id, cid)

    # --- Phase 2 : calcul pur (aucune écriture encore) ---
    nouveaux_stocks, nouveaux_niveaux = {}, {}
    morts_a_appliquer: list[str] = []
    migrations_a_appliquer: list[tuple[str, int]] = []
    couples_a_dissoudre: list[str] = []
    couples_a_former: list[tuple[int, str, str]] = []
    naissances_a_tenter: list[tuple[int, str, str, str, str]] = []  # cid, a, b, sexe_a, sexe_b

    for cel in sorted(monde["cellules"], key=lambda c: c["cellule_id"]):
        cid = cel["cellule_id"]
        pop = population[cid]

        # 1) Ressources + 2) Technologie
        rng_r = _rng(seed, tick_suivant, cid, "ressources")
        nouveau_stock, nouveau_niveau, _ = horloge.evoluer_ressources_et_technologie(
            stocks[cid], niveaux[cid], len(pop))
        nouveaux_stocks[cid] = nouveau_stock
        nouveaux_niveaux[cid] = nouveau_niveau
        niveaux_tech.append(nouveau_niveau)

        # 3) Mortalité
        rng_m = _rng(seed, tick_suivant, cid, "mortalite")
        vivants = []
        for h in pop:
            age = tick_suivant - h["ne_au_tick"]
            if horloge.meurt(age, niveaux[cid], rng_m):
                morts_a_appliquer.append(h["id"])
            else:
                vivants.append(h)

        # 4) Migration — décidée sur l'état du DÉBUT de tick ; un habitant qui migre
        # reste éligible couples/reproduction dans SA cellule d'origine ce même tick.
        rng_mig = _rng(seed, tick_suivant, cid, "migration")
        if cel["voisins"] and horloge.cellule_saturee(len(vivants), stocks[cid]):
            for h in vivants:
                if horloge.migre(rng_mig):
                    migrations_a_appliquer.append((h["id"], rng_mig.choice(cel["voisins"])))

        # 5) Couples : dissolution puis formation
        rng_c = _rng(seed, tick_suivant, cid, "couples")
        actifs = couples_par_cellule[cid]
        dissous_ici = [c for c in actifs if horloge.dissout(rng_c)]
        couples_a_dissoudre.extend(c["id"] for c in dissous_ici)
        dissous_ids = {c["id"] for c in dissous_ici}
        deja_en_couple = ({c["habitant_a_id"] for c in actifs if c["id"] not in dissous_ids} |
                           {c["habitant_b_id"] for c in actifs if c["id"] not in dissous_ids})

        vivants_par_id = {h["id"]: h for h in vivants}
        celibataires_f = [h["id"] for h in vivants if h["sexe"] == "F"
                           and h["id"] not in deja_en_couple
                           and horloge.est_adulte_fecond(tick_suivant - h["ne_au_tick"])]
        celibataires_m = [h["id"] for h in vivants if h["sexe"] == "M"
                           and h["id"] not in deja_en_couple
                           and horloge.est_adulte_fecond(tick_suivant - h["ne_au_tick"])]
        nouveaux = horloge.former_couples(celibataires_f, celibataires_m, rng_c)
        couples_a_former.extend((cid, a, b) for a, b in nouveaux)
        nouvellement_pris = {a for a, _ in nouveaux} | {b for _, b in nouveaux}

        # 6) Reproduction — SEULS les couples déjà actifs AVANT ce tick tentent une
        # naissance (les couples formés à l'étape 5 ci-dessus attendent le tick
        # suivant — évite "formé et déjà parent le même tick").
        rng_n = _rng(seed, tick_suivant, cid, "naissances")
        for c in actifs:
            if c["id"] in dissous_ids:
                continue
            ha, hb = vivants_par_id.get(c["habitant_a_id"]), vivants_par_id.get(c["habitant_b_id"])
            if (ha and hb
                    and horloge.est_adulte_fecond(tick_suivant - ha["ne_au_tick"])
                    and horloge.est_adulte_fecond(tick_suivant - hb["ne_au_tick"])
                    and horloge.tente_naissance_couple(rng_n)):
                naissances_a_tenter.append((cid, ha["id"], hb["id"], ha["sexe"], hb["sexe"]))

        restants_f = [i for i in celibataires_f if i not in nouvellement_pris]
        restants_m = [i for i in celibataires_m if i not in nouvellement_pris]
        for a, b in horloge.tenter_rencontres_occasionnelles(restants_f, restants_m, rng_n):
            naissances_a_tenter.append((cid, a, b, "F", "M"))

    # --- Phase 3 : application des écritures (chaque groupe isolé) ---
    for cid, stock in nouveaux_stocks.items():
        try:
            stockage_spatial.ecrire_ressources_stock(monde_id, cid, stock)
            stockage_spatial.ecrire_niveau_technologie(monde_id, cid, nouveaux_niveaux[cid])
        except Exception as e:
            avertissements.append(f"Cellule {cid} : ressources/technologie non écrites : {e}")

    for enfant_id in morts_a_appliquer:
        try:
            stockage_spatial.marquer_mort(monde_id, enfant_id, tick_suivant)
            morts += 1
        except Exception as e:
            avertissements.append(f"Mort de {enfant_id} non appliquée : {e}")

    # Naissances AVANT migrations : `genome_moteur._cellule_naissance` fait une
    # lecture LIVE du placement du parent de référence pour situer le nouveau-né.
    # Si une migration de ce même tick était déjà écrite en base, un parent
    # migré-mais-encore-fécondable-ici verrait sa naissance placée relativement à
    # sa cellule d'ARRIVÉE au lieu de la cellule qui a servi à décider cette
    # reproduction — voir design/constante "instantané figé, pas de contamination
    # entre groupes d'écritures d'un même tick".
    cellules_par_id = {c["cellule_id"]: c for c in monde["cellules"]}
    for cid, a, b, sexe_a, sexe_b in naissances_a_tenter:
        rng_naissance = _rng(seed, tick_suivant, cid, f"naissance:{a}:{b}")
        cellule = cellules_par_id[cid]
        latitude, longitude = horloge.derive_position_naissance(cellule["x"], cellule["y"])
        heure, utc_offset = horloge.derive_heure_et_offset(rng_naissance)
        corps = genome_moteur.Croisement(
            parent_a=genome_moteur.ReferenceParent(id=a, sexe=sexe_a),
            parent_b=genome_moteur.ReferenceParent(id=b, sexe=sexe_b),
            prenoms_enfant="", nom_enfant="",
            latitude_enfant=latitude, longitude_enfant=longitude,
            heure_naissance_enfant=heure, utc_offset_enfant=utc_offset,
            annee_enfant=min(9999, ANNEE_BASE_HORLOGE + tick_suivant),
            sexe_enfant=horloge.tirer_sexe(rng_naissance),
            monde_id=monde_id,
        )
        try:
            resultat = await genome_moteur.executer_croisement(corps, cle_api_val)
            if resultat["enfant_id"] is not None:
                naissances += 1
            if resultat.get("avertissement"):
                avertissements.append(f"Naissance {a}/{b} : {resultat['avertissement']}")
        except HTTPException as e:
            avertissements.append(f"Naissance {a}/{b} non aboutie : {e.detail}")
        except Exception as e:
            avertissements.append(f"Naissance {a}/{b} non aboutie : {e}")

    for enfant_id, nouvelle_cellule in migrations_a_appliquer:
        try:
            stockage_spatial.deplacer_placement(monde_id, enfant_id, nouvelle_cellule)
            migrations += 1
        except Exception as e:
            avertissements.append(f"Migration de {enfant_id} non appliquée : {e}")

    for couple_id in couples_a_dissoudre:
        try:
            stockage_horloge.dissoudre_couple(couple_id, tick_suivant)
            couples_dissous += 1
        except Exception as e:
            avertissements.append(f"Dissolution du couple {couple_id} non appliquée : {e}")

    for cid, a, b in couples_a_former:
        try:
            stockage_horloge.former_couple(monde_id, cid, a, b, tick_suivant)
            couples_formes += 1
        except Exception as e:
            avertissements.append(f"Formation du couple {a}/{b} non appliquée : {e}")

    stockage_horloge.marquer_execution(monde_id, tick_suivant)

    return {
        "monde_id": monde_id, "tick_actuel": tick_suivant,
        "naissances": naissances, "morts": morts, "migrations": migrations,
        "couples_formes": couples_formes, "couples_dissous": couples_dissous,
        "niveau_technologie_moyen": (sum(niveaux_tech) / len(niveaux_tech)) if niveaux_tech else 0.0,
        "avertissements": avertissements,
    }
