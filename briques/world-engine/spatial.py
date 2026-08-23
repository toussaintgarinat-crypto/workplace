"""Génération procédurale d'un monde spatial : maillage Voronoï + biomes/ressources
dérivés d'un bruit cohérent (altitude/humidité). Fonctions pures, déterministes pour
un (nb_cellules, seed) donné — aucune I/O, aucune dépendance à `stockage_spatial`."""
from __future__ import annotations

import random

from opensimplex import OpenSimplex
from scipy.spatial import Voronoi

TAILLE_MONDE = 1000.0  # espace [0, TAILLE_MONDE] x [0, TAILLE_MONDE]

BIOMES = ("ocean", "plaine", "foret", "colline", "montagne", "desert", "toundra", "marais")

RESSOURCES_PAR_BIOME = {
    "ocean": ["poisson", "sel"],
    "plaine": ["ble", "betail"],
    "foret": ["bois", "gibier"],
    "colline": ["pierre", "cuivre"],
    "montagne": ["minerai", "pierre"],
    "desert": ["cristal", "petrole"],
    "toundra": ["fourrure", "gibier"],
    "marais": ["tourbe", "herbes"],
}


def determiner_biome(altitude: float, humidite: float) -> str:
    """Mappe 2 axes de bruit cohérent (chacun dans ~[-1, 1]) vers l'un des 8 biomes."""
    if altitude < -0.3:
        return "ocean"
    if altitude < 0.0:
        return "marais" if humidite > 0.4 else "plaine"
    if altitude < 0.4:
        if humidite < -0.3:
            return "desert"
        if humidite < 0.3:
            return "plaine"
        return "foret"
    if altitude < 0.7:
        return "toundra" if humidite < 0.0 else "colline"
    return "montagne"


def _voisins_par_voronoi(points: list[tuple[float, float]]) -> dict[int, list[int]]:
    """Adjacence des cellules via les arêtes du diagramme de Voronoï (`ridge_points` :
    paires d'index de points séparés par une seule arête, donc voisins directs). En
    dessous de 4 points, Qhull ne peut pas construire de diagramme 2D — repli
    explicite : aucun voisin, jamais une exception."""
    n = len(points)
    if n < 4:
        return {i: [] for i in range(n)}
    voisins: dict[int, set[int]] = {i: set() for i in range(n)}
    vor = Voronoi(points)
    for a, b in vor.ridge_points:
        voisins[int(a)].add(int(b))
        voisins[int(b)].add(int(a))
    return {i: sorted(v) for i, v in voisins.items()}


def _tirer_ressources(biome: str, rng: random.Random) -> list[str]:
    pool = RESSOURCES_PAR_BIOME[biome]
    n = rng.randint(0, min(2, len(pool)))
    return rng.sample(pool, n)


def generer_monde(nb_cellules: int, seed: int) -> list[dict]:
    """Génère `nb_cellules` cellules déterministes pour `seed` : positions Voronoï,
    biome dérivé d'un bruit cohérent, ressources tirées selon le biome. Chaque
    élément : {cellule_id, x, y, biome, ressources, voisins}."""
    rng = random.Random(seed)
    points = [(rng.uniform(0, TAILLE_MONDE), rng.uniform(0, TAILLE_MONDE)) for _ in range(nb_cellules)]
    voisins = _voisins_par_voronoi(points)

    bruit_altitude = OpenSimplex(seed=seed)
    bruit_humidite = OpenSimplex(seed=seed + 1)  # graine décorrélée de l'altitude

    cellules = []
    for i, (x, y) in enumerate(points):
        altitude = bruit_altitude.noise2(x / TAILLE_MONDE, y / TAILLE_MONDE)
        humidite = bruit_humidite.noise2(x / TAILLE_MONDE, y / TAILLE_MONDE)
        biome = determiner_biome(altitude, humidite)
        cellules.append({
            "cellule_id": i, "x": x, "y": y, "biome": biome,
            "ressources": _tirer_ressources(biome, rng), "voisins": voisins[i],
        })
    return cellules
