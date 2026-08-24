"""Orchestrateur du tick de simulation (Sprint C) : exécute un tick complet sur
un monde. Lit un instantané figé de l'état en DÉBUT de tick (population, stocks,
technologie, couples), applique la mécanique pure de `horloge.py` cellule par
cellule SUR CET INSTANTANÉ (jamais de re-lecture après une écriture DANS le même
tick — un habitant n'est traité qu'une seule fois par tick, voir design), déclenche
les naissances via `genome_moteur.executer_croisement`, puis applique toutes les
écritures en une dernière phase. Chaque groupe d'écritures est isolé : une erreur
n'interrompt jamais le reste du tick (repli honnête, même motif que Sprint A/B).

Toutes les lectures et écritures d'un tick sont GROUPÉES (une connexion SQLite par
groupe, jamais une par cellule ni par habitant) — correctif revue finale, voir
`stockage_spatial.population_vivante_monde`.

⚠️ Limite honnête du déterminisme. La mécanique du tick est bien reproductible par
(seed, tick, cellule) : qui meurt, qui migre, qui s'apparie, quels couples se
dissolvent, et si une naissance est TENTÉE. En revanche
`genome_moteur.executer_croisement` (code Sprint A/B, partagé avec la route
manuelle `POST /genome/croiser`) utilise en interne deux `Random()` NON seedés —
l'un pour la mutation de la description fusionnée, l'autre pour choisir la cellule
voisine où l'enfant est placé. Le récit exact et la cellule exacte d'un nouveau-né
ne sont donc PAS reproductibles à seed égal. Y injecter un RNG seedé déborderait de
ce sprint (fonction partagée avec d'autres appelants) : la limite est documentée
plutôt que masquée derrière une promesse de déterminisme total."""
from __future__ import annotations

import asyncio
from random import Random

from fastapi import HTTPException

import genome_moteur
import horloge
import stockage_horloge
import stockage_spatial

ANNEE_BASE_HORLOGE = 2000  # année narrative de départ pour les naissances automatiques —
                            # sans lien avec l'année réelle, juste une base valide pour
                            # calculer un thème astral (voir genome_moteur.Croisement.annee_enfant)

_VERROUS_TICK: dict[str, asyncio.Lock] = {}


def _rng(seed: int, tick: int, cellule_id: int, etape: str) -> Random:
    return Random(f"{seed}:{tick}:{cellule_id}:{etape}")


def _verrou_tick(monde_id: str) -> asyncio.Lock:
    """Verrou par monde, en mémoire de CE processus.

    Correctif revue finale (Important) : `executer_tick` `await` (appels HTTP vers
    `personnages` lors d'une naissance). Un tick manuel (`POST /horloge/{id}/tick`)
    et le tick du scheduler sur le MÊME monde pouvaient donc s'entrelacer, partir du
    même `tick_actuel`, et appliquer chacun un tick complet d'effets (morts,
    naissances, couples) pour un seul `tick_actuel` d'avancement.

    `setdefault` suffit à la création concurrente : aucune `await` entre le `get` et
    l'affectation, donc la boucle asyncio ne peut pas basculer de tâche au milieu.
    ⚠️ Garde in-process uniquement : plusieurs workers uvicorn (ou plusieurs
    conteneurs) sur la même base ne seraient pas protégés — hors périmètre Sprint C
    (scheduler in-process mono-processus, voir design). Le dictionnaire ne se vide
    jamais (un `asyncio.Lock` par monde jamais tické : quelques dizaines d'octets),
    volontairement : le purger exigerait un comptage de références, sans bénéfice au
    volume visé."""
    verrou = _VERROUS_TICK.get(monde_id)
    if verrou is None:
        verrou = _VERROUS_TICK.setdefault(monde_id, asyncio.Lock())
    return verrou


async def executer_tick(monde_id: str, cle_api_val: str) -> dict:
    """Avance `monde_id` d'exactement 1 tick. Sérialisé par monde : un second
    appelant simultané ATTEND la fin du premier (il n'échoue pas)."""
    async with _verrou_tick(monde_id):
        return await _executer_tick(monde_id, cle_api_val)


async def _executer_tick(monde_id: str, cle_api_val: str) -> dict:
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

    # --- Phase 1 : instantané figé du monde en début de tick (3 requêtes au total,
    # quel que soit le nombre de cellules) ---
    # `lire_monde` rapporte déjà `ressources_stock` et `niveau_technologie` de chaque
    # cellule : pas de `lire_ressources_stock`/`lire_niveau_technologie` par cellule.
    population = stockage_spatial.population_vivante_monde(monde_id)
    couples_par_cellule = stockage_horloge.couples_actifs_monde(monde_id)

    # --- Phase 2 : calcul pur (aucune écriture encore) ---
    maj_cellules: dict[int, tuple[dict, float]] = {}  # cellule_id -> (stock, niveau_technologie)
    morts_a_appliquer: list[str] = []
    migrations_a_appliquer: list[tuple[str, int]] = []
    couples_a_dissoudre: list[str] = []
    couples_a_former: list[tuple[int, str, str]] = []
    naissances_a_tenter: list[tuple[int, str, str, str, str]] = []  # cid, a, b, sexe_a, sexe_b

    for cel in sorted(monde["cellules"], key=lambda c: c["cellule_id"]):
        cid = cel["cellule_id"]
        pop = population.get(cid, [])
        stock_cellule = cel["ressources_stock"]
        niveau_cellule = cel["niveau_technologie"]

        # 1) Ressources + 2) Technologie
        nouveau_stock, nouveau_niveau, _ = horloge.evoluer_ressources_et_technologie(
            stock_cellule, niveau_cellule, len(pop))
        maj_cellules[cid] = (nouveau_stock, nouveau_niveau)
        niveaux_tech.append(nouveau_niveau)

        # 3) Mortalité
        rng_m = _rng(seed, tick_suivant, cid, "mortalite")
        vivants = []
        morts_ici: set[str] = set()
        for h in pop:
            age = tick_suivant - h["ne_au_tick"]
            if horloge.meurt(age, niveau_cellule, rng_m):
                morts_a_appliquer.append(h["id"])
                morts_ici.add(h["id"])
            else:
                vivants.append(h)

        # 4) Migration — décidée sur l'état du DÉBUT de tick ; un habitant qui migre
        # reste éligible couples/reproduction dans SA cellule d'origine ce même tick.
        rng_mig = _rng(seed, tick_suivant, cid, "migration")
        if cel["voisins"] and horloge.cellule_saturee(len(vivants), stock_cellule):
            for h in vivants:
                if horloge.migre(rng_mig):
                    migrations_a_appliquer.append((h["id"], rng_mig.choice(cel["voisins"])))

        # 5) Couples : dissolution puis formation
        rng_c = _rng(seed, tick_suivant, cid, "couples")
        actifs = couples_par_cellule.get(cid, [])
        # Dissolution par hasard — le tirage est fait pour CHAQUE couple actif, y
        # compris ceux que le décès d'un membre va dissoudre juste en dessous : ne
        # pas sauter de tirage garde le flux du RNG identique quelle que soit la
        # mortalité du tick (déterminisme par (seed, tick, cellule)).
        dissous_ids = {c["id"] for c in actifs if horloge.dissout(rng_c)}
        # Dissolution par décès (correctif revue finale, Important) — design §3 :
        # « tout couple actif impliquant cet habitant est dissous ». Sans ça le
        # couple restait `actif=1` à jamais, et surtout le SURVIVANT restait exclu
        # des célibataires de sa cellule (via `deja_en_couple`) jusqu'à ce que la
        # dissolution aléatoire (5 %/tick) finisse par tomber — sans raison de fiction.
        dissous_ids |= {c["id"] for c in actifs
                        if c["habitant_a_id"] in morts_ici or c["habitant_b_id"] in morts_ici}
        couples_a_dissoudre.extend(c["id"] for c in actifs if c["id"] in dissous_ids)
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

    # --- Phase 3 : application des écritures (chaque groupe isolé, ET chaque groupe
    # en UNE seule connexion/transaction — jamais une par cellule ni par habitant) ---
    if maj_cellules:
        try:
            stockage_spatial.ecrire_ressources_et_technologie_monde(monde_id, maj_cellules)
        except Exception as e:
            avertissements.append(f"Ressources/technologie non écrites : {e}")

    if morts_a_appliquer:
        try:
            stockage_spatial.marquer_morts(monde_id, morts_a_appliquer, tick_suivant)
            morts = len(morts_a_appliquer)
        except Exception as e:
            avertissements.append(f"Morts non appliquées : {e}")

    if couples_a_dissoudre:
        try:
            stockage_horloge.dissoudre_couples(couples_a_dissoudre, tick_suivant)
            couples_dissous = len(couples_a_dissoudre)
        except Exception as e:
            avertissements.append(f"Dissolutions de couples non appliquées : {e}")

    # Formations AVANT les migrations : un même habitant peut à la fois former un
    # couple (étape 5) et migrer (étape 4) ce tick — le couple doit exister en base
    # avant `deplacer_couples_habitants` pour être recalé sur sa cellule d'arrivée.
    if couples_a_former:
        try:
            stockage_horloge.former_couples_lot(monde_id, couples_a_former, tick_suivant)
            couples_formes = len(couples_a_former)
        except Exception as e:
            avertissements.append(f"Formations de couples non appliquées : {e}")

    # `marquer_execution` AVANT les naissances (correctif revue finale, Important) :
    # `genome_moteur.executer_croisement` relit l'horloge EN DIRECT pour fixer le
    # `ne_au_tick` du nouveau-né. Appelée en dernier comme auparavant, tout enfant né
    # au tick N recevait `ne_au_tick = N-1` — le design §6 exige `tick_actuel + 1`.
    # Isolée comme les autres écritures : sans ce try/except, une exception ici,
    # combinée au `except: continue` du scheduler, rejouerait le même tick (et donc
    # ses effets) indéfiniment, sans erreur visible.
    try:
        stockage_horloge.marquer_execution(monde_id, tick_suivant)
    except Exception as e:
        avertissements.append(f"Avancement de l'horloge non enregistré : {e}")

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
        # ⚠️ Honnêteté : ces coordonnées décrivent la cellule des PARENTS, pas
        # forcément celle de l'enfant. La cellule réelle du nouveau-né est choisie
        # plus loin, DANS `executer_croisement` (`_cellule_naissance` : une VOISINE
        # de celle du parent de référence, comportement Sprint B partagé avec les
        # croisements manuels), donc après que le thème astral a déjà été calculé à
        # partir de ces latitude/longitude. Le design demande que ces coordonnées
        # décrivent la cellule d'arrivée ; les faire coïncider supposerait de
        # rejouer ici la sélection de voisine (fonction privée de `genome_moteur`,
        # qui fait sa propre lecture DB et son propre tirage non seedé) puis de
        # l'imposer au croisement — nouveau couplage jugé plus coûteux que l'écart
        # cosmétique qu'il corrige. Écart connu et assumé, pas un oubli.
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

    if migrations_a_appliquer:
        try:
            stockage_spatial.deplacer_placements(monde_id, migrations_a_appliquer)
            migrations = len(migrations_a_appliquer)
        except Exception as e:
            avertissements.append(f"Migrations non appliquées : {e}")
        # Le couple actif d'un migrant suit son habitant (correctif revue finale,
        # Important) — sinon il resterait indexé sur la cellule d'origine et
        # l'habitant pourrait former un SECOND couple actif dans sa cellule
        # d'arrivée : voir `stockage_horloge.deplacer_couples_habitants`.
        try:
            stockage_horloge.deplacer_couples_habitants(monde_id, migrations_a_appliquer)
        except Exception as e:
            avertissements.append(f"Couples des migrants non recalés : {e}")

    return {
        "monde_id": monde_id, "tick_actuel": tick_suivant,
        "naissances": naissances, "morts": morts, "migrations": migrations,
        "couples_formes": couples_formes, "couples_dissous": couples_dissous,
        "niveau_technologie_moyen": (sum(niveaux_tech) / len(niveaux_tech)) if niveaux_tech else 0.0,
        "avertissements": avertissements,
    }
