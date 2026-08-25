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
import stockage
import stockage_federation
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


VERROU_DESTINATION_TIMEOUT_S = 5.0


async def _acquerir_verrou_destination(monde_id: str) -> asyncio.Lock | None:
    """Tente d'acquérir le verrou de tick du pays DESTINATION d'une migration
    transfrontière, avec un timeout court.

    Un ordre d'acquisition trié par `monde_id` ne suffirait PAS à éliminer
    l'interblocage ici : le verrou du pays D'ORIGINE est déjà tenu en entrée du
    tick (`executer_tick`), avant même de savoir qu'une migration transfrontière
    aura lieu — l'ordre n'est donc jamais neutre, et 2 tics concurrents faisant le
    mouvement inverse l'un de l'autre (A→B et B→A au même instant) resteraient en
    interblocage classique malgré un tri (voir design, section corrigée).

    Renvoie le verrou ACQUIS (à libérer par l'appelant), ou None si le timeout est
    dépassé — dans ce cas CETTE émigration précise échoue proprement (capturée
    dans `avertissements` par l'appelant), sans jamais bloquer indéfiniment."""
    verrou = _verrou_tick(monde_id)
    try:
        await asyncio.wait_for(verrou.acquire(), timeout=VERROU_DESTINATION_TIMEOUT_S)
        return verrou
    except asyncio.TimeoutError:
        return None


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

    # Un pays n'est JAMAIS adjacent à lui-même pour la migration (correctif revue
    # Task 4, Important) : une auto-adjacence stockée en amont ferait cibler à chaque
    # émigrant le pays dont le verrou de tick est DÉJÀ tenu par ce tick — verrou non
    # réentrant, donc N émigrants = N × VERROU_DESTINATION_TIMEOUT_S de blocage, le
    # verrou d'origine tenu pendant tout ce temps. Filtré au point d'usage, quoi que
    # la table d'adjacences contienne.
    pays_adjacents_ids = [p for p in stockage_federation.pays_adjacents(monde_id) if p != monde_id]
    nb_cellules_adjacents = {pid: stockage_spatial.nb_cellules_monde(pid) for pid in pays_adjacents_ids}

    avertissements: list[str] = []
    naissances = morts = migrations = migrations_transfrontieres = couples_formes = couples_dissous = 0
    niveaux_tech: list[float] = []

    # --- Phase 1 : instantané figé du monde en début de tick (3 requêtes au total,
    # quel que soit le nombre de cellules) ---
    # `lire_monde` rapporte déjà `ressources_stock` et `niveau_technologie` de chaque
    # cellule : pas de `lire_ressources_stock`/`lire_niveau_technologie` par cellule.
    population = stockage_spatial.population_vivante_monde(monde_id)
    couples_par_cellule = stockage_horloge.couples_actifs_monde(monde_id)

    # --- Phase 2 : calcul pur (aucune écriture encore) ---
    #
    # ⚠️ Découpée en DEUX passes sur les cellules (correctif 2e revue finale,
    # Important ×2). Les couples sont indexés par `cellule_id`, mais dès qu'un
    # membre migre, le couple SUIT le migrant (`deplacer_couples_habitants`) et sa
    # `cellule_id` ne correspond plus à celle de l'autre membre. Deux décisions ne
    # peuvent donc plus se prendre cellule par cellule :
    #   - `deja_en_couple` : le membre resté sur place ne voyait plus AUCUN couple
    #     dans sa propre cellule et repartait dans le vivier des célibataires — il
    #     pouvait former un SECOND couple actif pendant que le premier vivait encore
    #     ailleurs ;
    #   - la dissolution par décès : chercher le couple du défunt dans SA seule
    #     cellule le manquait quand le couple avait suivi le partenaire migré, et le
    #     couple restait `actif=1` à jamais.
    # Les deux se règlent avec une vue MONDIALE, sans une seule requête de plus :
    # `couples_par_cellule` contient déjà tous les couples actifs du monde.
    # Le découpage est ce qui rend cette vue JUSTE : la passe 2a arrête d'abord les
    # morts ET les dissolutions aléatoires de TOUTES les cellules, la vue mondiale
    # est calculée UNE fois entre les deux, et la passe 2b (formation +
    # reproduction) la consomme — une dissolution décidée en traitant la cellule X
    # est donc bien prise en compte quand la cellule Y est traitée ensuite.
    maj_cellules: dict[int, tuple[dict, float]] = {}  # cellule_id -> (stock, niveau_technologie)
    morts_a_appliquer: list[str] = []
    migrations_a_appliquer: list[tuple[str, int]] = []
    emigrations_a_appliquer: list[tuple[str, str, int, int]] = []  # eid, monde_id_dest, cellule_id_dest, age
    couples_a_dissoudre: list[str] = []
    couples_a_former: list[tuple[int, str, str]] = []
    naissances_a_tenter: list[tuple[int, str, str, str, str]] = []  # cid, a, b, sexe_a, sexe_b

    cellules_triees = sorted(monde["cellules"], key=lambda c: c["cellule_id"])
    # Vue mondiale à plat des couples actifs (ordre déterministe : par cellule
    # croissante, puis ordre de lecture). Chaque couple actif du monde y figure
    # exactement une fois, quelle que soit la cellule où sa ligne réside.
    tous_couples_actifs = [c for cid_ in sorted(couples_par_cellule)
                           for c in couples_par_cellule[cid_]]

    # --- Passe 2a : ressources, technologie, mortalité, migration, et le tirage de
    # dissolution aléatoire des couples de chaque cellule. ---
    etat_cellules: dict[int, tuple[list[dict], list[dict], Random]] = {}  # cid -> (vivants, actifs, rng_c)
    morts_tous: set[str] = set()
    dissous_ids: set[str] = set()

    for cel in cellules_triees:
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
        for h in pop:
            age = tick_suivant - h["ne_au_tick"]
            if horloge.meurt(age, niveau_cellule, rng_m):
                morts_a_appliquer.append(h["id"])
                morts_tous.add(h["id"])
            else:
                vivants.append(h)

        # 4) Migration — décidée sur l'état du DÉBUT de tick.
        #
        # 4a) Transfrontière (Sprint D) D'ABORD, repli sur l'intra-pays existant
        # ENSUITE — jamais les deux pour le même habitant le même tick. Contrairement
        # à un migrant intra-pays, un émigrant est retiré de `vivants` MAINTENANT :
        # il ne participe plus aux couples/reproduction de sa cellule d'origine ce
        # tick (franchir une frontière est un choix plus lourd que changer de
        # cellule voisine — voir design). Son couple actif éventuel est dissous via
        # le mécanisme de dissolution mondiale ci-dessous (5b), pas ici.
        rng_front = _rng(seed, tick_suivant, cid, "migration_frontiere")
        cellule_saturee_ici = horloge.cellule_saturee(len(vivants), stock_cellule)
        if cellule_saturee_ici and pays_adjacents_ids:
            restants = []
            for h in vivants:
                if horloge.migre_frontiere(rng_front):
                    dest_pays = horloge.tirer_pays_destination(pays_adjacents_ids, rng_front)
                    nb_dest = nb_cellules_adjacents.get(dest_pays)
                    if nb_dest:  # défensif : un pays adjacent supprimé (DELETE /spatial/mondes)
                                 # entre le rattachement et ce tick renverrait None ici — la
                                 # fédération ne cascade pas sur la suppression d'un monde (le
                                 # monde reste l'entité première, voir design) ; l'habitant reste
                                 # alors simplement dans son pays d'origine ce tick.
                        dest_cellule = horloge.tirer_cellule_destination(nb_dest, rng_front)
                        age = tick_suivant - h["ne_au_tick"]
                        emigrations_a_appliquer.append((h["id"], dest_pays, dest_cellule, age))
                        continue
                restants.append(h)
            vivants = restants

        # 4b) Intra-pays (Sprint C, inchangé) — sur les habitants NON émigrés ci-dessus.
        rng_mig = _rng(seed, tick_suivant, cid, "migration")
        if cel["voisins"] and cellule_saturee_ici:
            for h in vivants:
                if horloge.migre(rng_mig):
                    migrations_a_appliquer.append((h["id"], rng_mig.choice(cel["voisins"])))

        # 5a) Dissolution par hasard — le tirage est fait pour CHAQUE couple actif,
        # y compris ceux que le décès d'un membre va dissoudre plus bas : ne pas
        # sauter de tirage garde le flux du RNG identique quelle que soit la
        # mortalité du tick (déterminisme par (seed, tick, cellule)). Le tirage
        # reste bien PAR CELLULE — chaque couple actif appartient à exactement une
        # cellule, donc chacun est tiré une fois et une seule sur le monde entier.
        rng_c = _rng(seed, tick_suivant, cid, "couples")
        actifs = couples_par_cellule.get(cid, [])
        dissous_ids |= {c["id"] for c in actifs if horloge.dissout(rng_c)}
        etat_cellules[cid] = (vivants, actifs, rng_c)

    # --- Résolution des verrous des pays DESTINATION (correctif revue Task 4,
    # Important) ---
    #
    # Les verrous de tick des pays destination sont acquis ICI, AVANT que les
    # dissolutions de couple ne soient arrêtées — et non plus juste avant l'écriture
    # de chaque émigration. Auparavant le couple d'un émigrant était dissous (et
    # commité) sur la seule INTENTION d'émigrer : quand le verrou du pays destination
    # s'avérait indisponible bien plus bas, l'habitant restait chez lui mais son
    # couple était détruit pour rien. Décider la dissolution APRÈS le verrou rend les
    # deux cohérents : un couple ne se dissout que si le départ va réellement avoir lieu.
    #
    # Un seul verrou par pays destination (dédupliqué) : deux émigrants vers le même
    # pays ne doivent pas tenter d'acquérir deux fois le même `asyncio.Lock` (non
    # réentrant → interblocage contre soi-même). Les verrous obtenus sont TENUS
    # jusqu'à la fin du tick (passe 2b + phase 3) et libérés dans le `finally` final.
    # La passe 2b ne fait aucune E/S sur ces pays (calcul pur en mémoire) : les tenir
    # pendant ce temps n'ajoute aucune dépendance croisée nouvelle.
    #
    # ⚠️ Honnêteté : un émigrant dont le verrou échoue reste dans son pays d'origine
    # et GARDE son couple, mais il a déjà été retiré de `vivants` en passe 2a — il ne
    # participe donc pas aux couples/naissances de CE tick. Écart assumé : le
    # réinjecter changerait le flux du RNG, donc le déterminisme du tick.
    verrous_destinations: dict[str, asyncio.Lock] = {}
    destinations_indisponibles: set[str] = set()
    emigrations_confirmees: list[tuple[str, str, int, int]] = []
    for candidat in emigrations_a_appliquer:
        eid_c, dest_c = candidat[0], candidat[1]
        if dest_c not in verrous_destinations and dest_c not in destinations_indisponibles:
            verrou_obtenu = await _acquerir_verrou_destination(dest_c)
            if verrou_obtenu is None:
                destinations_indisponibles.add(dest_c)
            else:
                verrous_destinations[dest_c] = verrou_obtenu
        if dest_c in destinations_indisponibles:
            avertissements.append(
                f"Émigration de {eid_c} vers {dest_c} non appliquée : "
                "verrou du pays destination indisponible (retentera au tick suivant).")
            continue
        emigrations_confirmees.append(candidat)

    try:
        # Seules les émigrations CONFIRMÉES (verrou destination en main) alimentent la
        # dissolution mondiale ci-dessous — jamais la liste brute des candidats.
        emigrants_tous = {eid for eid, _, _, _ in emigrations_confirmees}

        # 5b) Dissolution par décès — recherche MONDIALE (correctif 2e revue finale,
        # Important) — design §3 : « tout couple actif impliquant cet habitant est
        # dissous ». La ligne du couple peut résider dans une cellule où le défunt
        # n'habite plus (ou n'a jamais habité) si son partenaire a migré avant : la
        # chercher dans la seule cellule du défunt la manquait, et le couple restait
        # `actif=1` à jamais.
        dissous_ids |= {c["id"] for c in tous_couples_actifs
                        if c["habitant_a_id"] in morts_tous or c["habitant_b_id"] in morts_tous
                        or c["habitant_a_id"] in emigrants_tous or c["habitant_b_id"] in emigrants_tous}
        couples_a_dissoudre.extend(c["id"] for c in tous_couples_actifs if c["id"] in dissous_ids)

        # `deja_en_couple` MONDIAL (correctif 2e revue finale, Important) : un habitant
        # est « déjà en couple » s'il apparaît dans N'IMPORTE QUEL couple encore actif
        # du monde, pas seulement dans un couple indexé sur sa propre cellule. Calculé
        # UNE fois, après que toutes les dissolutions du tick (hasard + décès, toutes
        # cellules) sont arrêtées — c'est ce qui fait enfin tenir l'invariant du design
        # « un habitant n'a au plus qu'un couple actif à la fois ».
        deja_en_couple = {h for c in tous_couples_actifs if c["id"] not in dissous_ids
                          for h in (c["habitant_a_id"], c["habitant_b_id"])}

        # --- Passe 2b : formation de couples puis reproduction, cellule par cellule. ---
        for cel in cellules_triees:
            cid = cel["cellule_id"]
            vivants, actifs, rng_c = etat_cellules[cid]

            # 5c) Formation
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
            # Un couple formé ici verrouille ses deux membres pour les cellules encore à
            # traiter dans cette même passe. Ceinture-et-bretelles : un habitant n'ayant
            # qu'un seul placement (clé primaire `(enfant_id, monde_id)`), il n'apparaît
            # dans les `vivants` que d'UNE cellule — mais l'index mondial doit rester
            # vrai à tout instant de la passe, pas seulement à son début.
            deja_en_couple |= nouvellement_pris

            # 6) Reproduction — SEULS les couples déjà actifs AVANT ce tick tentent une
            # naissance (les couples formés à l'étape 5c ci-dessus attendent le tick
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

        for eid, dest_monde_id, dest_cellule_id, age in emigrations_confirmees:
            # Verrou du pays destination déjà acquis plus haut et toujours tenu : ne
            # jamais le ré-acquérir ici (`asyncio.Lock` n'est pas réentrant). Chaque
            # écriture reste isolée : une émigration ratée n'interrompt pas les autres.
            try:
                horloge_dest = stockage_horloge.lire_horloge(dest_monde_id)
                tick_dest = horloge_dest["tick_actuel"] if horloge_dest else 0
                stockage_spatial.marquer_emigre(monde_id, eid, tick_suivant, dest_monde_id)
                stockage_spatial.placer(dest_monde_id, eid, dest_cellule_id,
                                          ne_au_tick=tick_dest - age)
                # Transfert de propriété (correctif revue finale, Important) : « il vit
                # là-bas maintenant, c'est un habitant de ce tenant ». Sans lui, un
                # migrant arrivé chez un tenant DIFFÉRENT ne pouvait plus jamais se
                # reproduire : le tick de destination appelle
                # `genome_moteur.executer_croisement(..., cle_api_destination)`, qui
                # résout ses parents par `stockage.lire(cle_api, parent_id)` — cloisonné.
                # Sa ligne `enfants` restant au tenant d'origine, la naissance échouait
                # silencieusement (simple « introuvable » dans `avertissements`).
                # `None` = monde destination disparu entre-temps : on saute le transfert
                # plutôt que d'écrire une propriété absurde (ne devrait pas arriver —
                # `nb_cellules_monde` a déjà répondu non-None pour ce pays en passe 2a).
                proprietaire_dest = stockage_spatial.proprietaire_monde(dest_monde_id)
                if proprietaire_dest is not None:
                    stockage.transferer_proprietaire(eid, proprietaire_dest)
                migrations_transfrontieres += 1
            except Exception as e:
                avertissements.append(f"Émigration de {eid} vers {dest_monde_id} non appliquée : {e}")

        return {
            "monde_id": monde_id, "tick_actuel": tick_suivant,
            "naissances": naissances, "morts": morts, "migrations": migrations,
            "migrations_transfrontieres": migrations_transfrontieres,
            "couples_formes": couples_formes, "couples_dissous": couples_dissous,
            "niveau_technologie_moyen": (sum(niveaux_tech) / len(niveaux_tech)) if niveaux_tech else 0.0,
            "avertissements": avertissements,
        }
    finally:
        # Un `release()` par verrou acquis, exactement une fois (dict dédupliqué par
        # pays destination), même si une écriture a levé.
        for verrou_dest in verrous_destinations.values():
            verrou_dest.release()
