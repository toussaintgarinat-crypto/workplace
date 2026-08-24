"""Mécanique pure du tick de simulation (Sprint C) : ressources/technologie,
mortalité, migration, couples, reproduction — aucune I/O, aucune dépendance à
sqlite/fastapi/httpx (même esprit que spatial.py/fusion.py). Le RNG est TOUJOURS
reçu en paramètre (jamais de module `random` global) pour un déterminisme
reproductible par (seed, tick, cellule) — voir horloge_moteur.py."""
from __future__ import annotations

from random import Random

from spatial import TAILLE_MONDE

# --- Ressources / technologie ---
PLAFOND_RESSOURCE = 100.0
TAUX_REGENERATION = 0.10          # fraction du manque au plafond regagnée par tick
CONSOMMATION_PAR_HABITANT = 1.0   # unités consommées par habitant vivant et par tick,
                                    # réparties également entre les ressources présentes
TAUX_PROGRESSION_TECH = 0.01      # niveau_technologie gagné par unité de ressource consommée
PLAFOND_TECHNOLOGIE = 10.0

# --- Âge / mortalité ---
AGE_ADULTE_MIN = 16
AGE_FECONDITE_MAX = 45
AGE_MORTALITE_MIN = 50
MORTALITE_BASE_ADULTE = 0.005     # risque plancher entre AGE_ADULTE_MIN et AGE_MORTALITE_MIN
MORTALITE_PENTE = 0.02            # + de risque par année au-delà de AGE_MORTALITE_MIN

# --- Migration ---
SEUIL_SATURATION_RATIO = 1.0      # population > stock total des ressources ⇒ saturé
PROBABILITE_MIGRATION_SI_SATURE = 0.20

# --- Couples / reproduction ---
PROBABILITE_FORMATION_COUPLE = 0.30
PROBABILITE_DISSOLUTION_COUPLE = 0.05
PROBABILITE_NAISSANCE_COUPLE = 0.25
PROBABILITE_NAISSANCE_ACCIDENT = 0.03  # « rencontre occasionnelle » hors couple, plus rare


def evoluer_ressources_et_technologie(stock: dict, niveau_technologie: float,
                                        population_vivante: int) -> tuple[dict, float, float]:
    """Régénère chaque ressource d'une fraction du manque au plafond, puis retire une
    consommation proportionnelle à la population vivante (répartie également entre
    les ressources présentes) ; le total consommé alimente la progression
    technologique. Bornes : stock dans [0, PLAFOND_RESSOURCE], technologie dans
    [0, PLAFOND_TECHNOLOGIE]. Renvoie (nouveau_stock, nouveau_niveau, consomme_reel)."""
    if not stock:
        return {}, min(niveau_technologie, PLAFOND_TECHNOLOGIE), 0.0
    consommation_totale = population_vivante * CONSOMMATION_PAR_HABITANT
    part_par_ressource = consommation_totale / len(stock)
    nouveau_stock = {}
    consomme_reel = 0.0
    for nom, quantite in stock.items():
        regenere = quantite + (PLAFOND_RESSOURCE - quantite) * TAUX_REGENERATION
        consomme = min(regenere, part_par_ressource)
        nouveau_stock[nom] = max(0.0, min(PLAFOND_RESSOURCE, regenere - consomme))
        consomme_reel += consomme
    nouveau_niveau = min(PLAFOND_TECHNOLOGIE, niveau_technologie + consomme_reel * TAUX_PROGRESSION_TECH)
    return nouveau_stock, nouveau_niveau, consomme_reel


def meurt(age: int, niveau_technologie: float, rng: Random) -> bool:
    """Probabilité de mort ce tick : nulle avant AGE_ADULTE_MIN (les enfants ne
    meurent pas dans ce modèle simple), risque plancher constant jusqu'à
    AGE_MORTALITE_MIN, puis croissant avec l'âge — réduit par le niveau de
    technologie de la cellule (plus de technologie ⇒ espérance de vie plus longue)."""
    if age < AGE_ADULTE_MIN:
        return False
    if age < AGE_MORTALITE_MIN:
        base = MORTALITE_BASE_ADULTE
    else:
        base = MORTALITE_BASE_ADULTE + MORTALITE_PENTE * (age - AGE_MORTALITE_MIN)
    proba = min(0.95, base / (1.0 + niveau_technologie))
    return rng.random() < proba


def cellule_saturee(population_vivante: int, stock: dict) -> bool:
    """Une cellule est saturée si sa population vivante dépasse son stock total de
    ressources restantes — pousse la migration (étape suivante du tick)."""
    return population_vivante > sum(stock.values()) * SEUIL_SATURATION_RATIO


def migre(rng: Random) -> bool:
    return rng.random() < PROBABILITE_MIGRATION_SI_SATURE


def est_adulte_fecond(age: int) -> bool:
    return AGE_ADULTE_MIN <= age <= AGE_FECONDITE_MAX


def former_couples(celibataires_f: list, celibataires_m: list, rng: Random) -> list[tuple[str, str]]:
    """Apparie au hasard des célibataires F/M (ordre mélangé, un habitant entre au
    plus dans un nouveau couple ce tick — bornée par le plus petit des 2 groupes) ;
    chaque paire candidate a une probabilité indépendante de former un couple — le
    hasard/destin plutôt qu'un appariement systématique."""
    f, m = list(celibataires_f), list(celibataires_m)
    rng.shuffle(f)
    rng.shuffle(m)
    return [(a, b) for a, b in zip(f, m) if rng.random() < PROBABILITE_FORMATION_COUPLE]


def dissout(rng: Random) -> bool:
    return rng.random() < PROBABILITE_DISSOLUTION_COUPLE


def tente_naissance_couple(rng: Random) -> bool:
    return rng.random() < PROBABILITE_NAISSANCE_COUPLE


def tenter_rencontres_occasionnelles(celibataires_f: list, celibataires_m: list,
                                       rng: Random) -> list[tuple[str, str]]:
    """Rencontres hors couple (« accident ») : même règle d'appariement que
    `former_couples`, probabilité bien plus faible, et ne forme jamais de couple
    persistant — seulement une tentative de naissance isolée ce tick."""
    f, m = list(celibataires_f), list(celibataires_m)
    rng.shuffle(f)
    rng.shuffle(m)
    return [(a, b) for a, b in zip(f, m) if rng.random() < PROBABILITE_NAISSANCE_ACCIDENT]


def derive_position_naissance(x: float, y: float) -> tuple[float, float]:
    """Convertit la position (x, y) d'une cellule (espace [0, TAILLE_MONDE]²) en
    latitude/longitude valides — déterministe, sans signification géographique
    réelle : seulement des coordonnées valides à fournir à `personnages` pour une
    naissance automatique, où aucun humain ne peut en fournir (voir design)."""
    latitude = (y / TAILLE_MONDE) * 180.0 - 90.0
    longitude = (x / TAILLE_MONDE) * 360.0 - 180.0
    return latitude, longitude


def derive_heure_et_offset(rng: Random) -> tuple[str, float]:
    """Heure de naissance et décalage UTC tirés du RNG seedé du monde — aucun
    humain ne peut les fournir pour une naissance automatique."""
    heure = rng.randrange(0, 24)
    minute = rng.randrange(0, 60)
    utc_offset = float(rng.randrange(-12, 13))
    return f"{heure:02d}:{minute:02d}", utc_offset


def tirer_sexe(rng: Random) -> str:
    return rng.choice(["F", "M"])
