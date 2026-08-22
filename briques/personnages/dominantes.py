"""Dominantes astrologiques — élément, mode, planète, signe, maison.

2 méthodes : comptage_dignite (task 6) et score_complexe (task 7).
Tables de dignités essentielles embarquées (domicile, exaltation, triplicité,
terme égyptien, face chaldéenne).
"""
from __future__ import annotations

METHODES = ["comptage_dignite", "score_complexe"]

# ── Tables de dignités essentielles ────────────────────────────────
DOMICILES = {
    "Soleil": ["Lion"], "Lune": ["Cancer"],
    "Mercure": ["Gémeaux", "Vierge"], "Vénus": ["Taureau", "Balance"],
    "Mars": ["Bélier", "Scorpion"], "Jupiter": ["Sagittaire", "Poissons"],
    "Saturne": ["Capricorne", "Verseau"],
    "Uranus": ["Verseau"], "Neptune": ["Poissons"], "Pluton": ["Scorpion"],
}

EXALTATIONS = {
    "Soleil": "Bélier", "Lune": "Taureau", "Mercure": "Vierge",
    "Vénus": "Poissons", "Mars": "Capricorne",
    "Jupiter": "Cancer", "Saturne": "Balance",
    "Uranus": "Scorpion", "Neptune": "Verseau",  # débattu ; convention
    "Pluton": "Lion",  # débattu ; convention
}

# Triplicités (Dorotheus) : (élément, secteur) → gouverneur.
# Dorotheus est le système classique retenu ici (Lilly propose une variante
# à 3 gouverneurs par élément avec partenaire/participant).
TRIPPLICITES = {
    ("Feu", "diurne"): "Soleil", ("Feu", "nocturne"): "Jupiter",
    ("Terre", "diurne"): "Saturne", ("Terre", "nocturne"): "Mercure",
    ("Air", "diurne"): "Saturne", ("Air", "nocturne"): "Mercure",
    ("Eau", "diurne"): "Vénus", ("Eau", "nocturne"): "Mars",
}

# TERMES_EGYPTIENS : signe → [(borne_sup_deg, planète), ...]
# Table égyptienne (Dorotheus/Lilly) — 12 signes × 5 termes.
TERMES_EGYPTIENS = {
    "Bélier": [(6, "Jupiter"), (14, "Vénus"), (21, "Mercure"), (26, "Mars"), (30, "Saturne")],
    "Taureau": [(8, "Vénus"), (15, "Mercure"), (22, "Jupiter"), (26, "Saturne"), (30, "Mars")],
    "Gémeaux": [(7, "Mercure"), (14, "Jupiter"), (21, "Vénus"), (25, "Mars"), (30, "Saturne")],
    "Cancer": [(7, "Mars"), (13, "Vénus"), (20, "Mercure"), (27, "Jupiter"), (30, "Saturne")],
    "Lion": [(6, "Jupiter"), (13, "Mercure"), (20, "Saturne"), (25, "Vénus"), (30, "Mars")],
    "Vierge": [(7, "Mercure"), (13, "Vénus"), (18, "Jupiter"), (24, "Saturne"), (30, "Mars")],
    "Balance": [(6, "Saturne"), (14, "Mercure"), (21, "Jupiter"), (28, "Vénus"), (30, "Mars")],
    "Scorpion": [(6, "Mars"), (14, "Jupiter"), (21, "Vénus"), (27, "Mercure"), (30, "Saturne")],
    "Sagittaire": [(8, "Jupiter"), (14, "Mercure"), (21, "Saturne"), (26, "Vénus"), (30, "Mars")],
    "Capricorne": [(6, "Mercure"), (12, "Jupiter"), (19, "Vénus"), (25, "Saturne"), (30, "Mars")],
    "Verseau": [(6, "Mercure"), (12, "Vénus"), (20, "Jupiter"), (25, "Saturne"), (30, "Mars")],
    "Poissons": [(8, "Vénus"), (14, "Jupiter"), (20, "Mercure"), (25, "Saturne"), (30, "Mars")],
}

# FACES_CHALDEENNES : signe → [décan1, décan2, décan3]
# Séquence chaldéenne (Mars, Soleil, Vénus, Mercure, Lune, Saturne, Jupiter)
# répétée sur les 36 décans.
FACES_CHALDEENNES = {
    "Bélier": ["Mars", "Soleil", "Vénus"],
    "Taureau": ["Mercure", "Lune", "Saturne"],
    "Gémeaux": ["Jupiter", "Mars", "Soleil"],
    "Cancer": ["Vénus", "Mercure", "Lune"],
    "Lion": ["Saturne", "Jupiter", "Mars"],
    "Vierge": ["Soleil", "Vénus", "Mercure"],
    "Balance": ["Lune", "Saturne", "Jupiter"],
    "Scorpion": ["Mars", "Soleil", "Vénus"],
    "Sagittaire": ["Mercure", "Lune", "Saturne"],
    "Capricorne": ["Jupiter", "Mars", "Soleil"],
    "Verseau": ["Vénus", "Mercure", "Lune"],
    "Poissons": ["Saturne", "Jupiter", "Mars"],
}

_ELEMENTS = {"Bélier": "Feu", "Taureau": "Terre", "Gémeaux": "Air", "Cancer": "Eau",
             "Lion": "Feu", "Vierge": "Terre", "Balance": "Air", "Scorpion": "Eau",
             "Sagittaire": "Feu", "Capricorne": "Terre", "Verseau": "Air", "Poissons": "Eau"}
_MODES = {"Bélier": "Cardinal", "Taureau": "Fixe", "Gémeaux": "Mutable",
          "Cancer": "Cardinal", "Lion": "Fixe", "Vierge": "Mutable",
          "Balance": "Cardinal", "Scorpion": "Fixe", "Sagittaire": "Mutable",
          "Capricorne": "Cardinal", "Verseau": "Fixe", "Poissons": "Mutable"}

_LUMINAIRES = {"Soleil", "Lune"}
_ANGULAIRES = {1, 4, 7, 10}
_SUCCEDENTES = {2, 5, 8, 11}


def _chart_diurne(soleil_lon: float, asc_lon: float, mc_lon: float) -> bool:
    """Diurne si Soleil au-dessus de l'horizon (entre Asc et Desc par voie diurne).

    Approximation : Soleil dans les maisons 7-12 (moitié supérieure).
    On compare la longitude du Soleil à l'Asc — si Soleil est à plus de 180°
    de l'Asc (dans la moitié supérieure), c'est diurne.
    """
    ecart = (soleil_lon - asc_lon) % 360
    return 0 < ecart < 180


def _score_dignite(planete: str, signe: str, degre_dans_signe: float,
                   diurne: bool) -> dict:
    """Score de dignités essentielles pour une planète dans un signe."""
    score = 0
    detail = {}
    if signe in DOMICILES.get(planete, []):
        score += 5
        detail["domicile"] = 5
    if EXALTATIONS.get(planete) == signe:
        score += 4
        detail["exaltation"] = 4
    elem = _ELEMENTS[signe]
    gouverneur = TRIPPLICITES.get((elem, "diurne" if diurne else "nocturne"))
    if gouverneur == planete:
        score += 2
        detail["triplicite"] = 2
    # Terme égyptien
    termes = TERMES_EGYPTIENS.get(signe, [])
    degre_prec = 0
    for borne, planete_terme in termes:
        if degre_prec <= degre_dans_signe < borne:
            if planete_terme == planete:
                score += 1
                detail["terme"] = 1
            break
        degre_prec = borne
    # Face chaldéenne
    faces = FACES_CHALDEENNES.get(signe, [])
    if faces:
        decan = int(degre_dans_signe // 10)
        if faces[decan] == planete:
            score += 1
            detail["face"] = 1
    return {"score": score, "detail": detail}


def _comptage_dignite(points: dict, maisons: list, aspects: list,
                      chart_diurne: bool) -> dict:
    """Méthode 1 : comptage + dignités essentielles."""
    scores_elem = {"Feu": 0, "Terre": 0, "Air": 0, "Eau": 0}
    scores_mode = {"Cardinal": 0, "Fixe": 0, "Mutable": 0}
    scores_planete = {p: 0 for p in DOMICILES}
    scores_signe = {s: 0 for s in _ELEMENTS}
    scores_maison = {i: 0 for i in range(1, 13)}

    for nom, info in points.items():
        if nom not in DOMICILES:
            continue  # on ne score que les 10 planètes
        signe = info["signe"]
        maison = info.get("maison", 0)
        degre = info["longitude"] % 30
        pond = 2 if nom in _LUMINAIRES else 1
        dign = _score_dignite(nom, signe, degre, chart_diurne)
        scores_planete[nom] += dign["score"] + pond
        if maison in _ANGULAIRES:
            scores_planete[nom] += 1
        elif maison in _SUCCEDENTES:
            scores_planete[nom] += 0.5
        scores_elem[_ELEMENTS[signe]] += pond
        scores_mode[_MODES[signe]] += pond
        scores_signe[signe] += pond
        if 1 <= maison <= 12:
            scores_maison[maison] += pond

    def dominant(scores: dict) -> str:
        return max(scores, key=scores.get)

    return {
        "element": {"dominant": dominant(scores_elem), "scores": scores_elem},
        "mode": {"dominant": dominant(scores_mode), "scores": scores_mode},
        "planete": {"dominante": dominant(scores_planete), "scores": scores_planete},
        "signe": {"dominant": dominant(scores_signe), "scores": scores_signe},
        "maison": {"dominante": dominant(scores_maison), "scores": scores_maison},
        "methode": "comptage_dignite",
        "chart_diurne": chart_diurne,
        "detail": {},
    }


def _score_complexe(points: dict, maisons: list, aspects: list,
                    chart_diurne: bool) -> dict:
    """Méthode 2 : score complexe (Jones/Muzzarelli). Score planète par planète sur 100."""
    soleil_lon = points.get("Soleil", {}).get("longitude", 0)
    asc_lon = points.get("Ascendant", {}).get("longitude", 0)
    mc_lon = points.get("Milieu du Ciel", {}).get("longitude", 0)
    nn_lon = points.get("Nœud Nord", {}).get("longitude", None)

    scores_planete = {}
    detail_planete = {}

    # Compter les aspects reçus par planète
    aspects_recus = {p: 0 for p in DOMICILES}
    for asp in aspects:
        for p in (asp.get("point_a"), asp.get("point_b")):
            if p in aspects_recus:
                aspects_recus[p] += 1

    for nom, info in points.items():
        if nom not in DOMICILES:
            continue
        signe = info["signe"]
        maison = info.get("maison", 0)
        degre = info["longitude"] % 30
        lon = info["longitude"]
        vitesse = info.get("vitesse_deg_j", 0)
        retro = info.get("retrograde", False)

        score = 0
        detail = {}

        # Dignité (max 30)
        dign = _score_dignite(nom, signe, degre, chart_diurne)
        score_dign = min(dign["score"] * 3, 30)  # échelle 0-30
        score += score_dign
        detail["dignite"] = score_dign

        # Maison angulaire/succédente (max 15)
        if maison in _ANGULAIRES:
            score += 15
            detail["angulaire"] = 15
        elif maison in _SUCCEDENTES:
            score += 8
            detail["succedente"] = 8

        # Proximité aux angles Asc/MC (< 8° du cuspe, max 15)
        for angle_lon in (asc_lon, mc_lon):
            ecart = min(abs(lon - angle_lon) % 360, 360 - abs(lon - angle_lon) % 360)
            if ecart < 8:
                bonus = int(15 * (1 - ecart / 8))
                score += bonus
                detail["proximite_angle"] = bonus
                break

        # Vitesse angulaire (max 10)
        if retro or abs(vitesse) < 0.1:
            score += 10
            detail["vitesse_lente"] = 10
        elif abs(vitesse) < 1.0:
            score += 5
            detail["vitesse_moyenne"] = 5

        # Aspects reçus (max 15)
        nb_asp = aspects_recus.get(nom, 0)
        score += min(nb_asp * 3, 15)
        detail["aspects_recus"] = min(nb_asp * 3, 15)

        # Luminaire bonus (+15)
        if nom in _LUMINAIRES:
            score += 15
            detail["luminaire"] = 15

        # Rétrogradation bonus (+5)
        if retro:
            score += 5
            detail["retrograde"] = 5

        # Combuste (-10) / Cazimi (+5)
        ecart_soleil = min(abs(lon - soleil_lon) % 360, 360 - abs(lon - soleil_lon) % 360)
        if ecart_soleil < 0.5 and nom != "Soleil":
            score += 5  # cazimi (cœur du Soleil)
            detail["cazimi"] = 5
        elif ecart_soleil < 17 and nom != "Soleil":
            score -= 10  # combuste
            detail["combuste"] = -10

        # Lien au nœud nord (+10)
        if nn_lon is not None:
            ecart_nn = min(abs(lon - nn_lon) % 360, 360 - abs(lon - nn_lon) % 360)
            if ecart_nn < 3:
                score += 10
                detail["noeud_nord"] = 10

        scores_planete[nom] = score
        detail_planete[nom] = detail

    # Agréger pour élément/mode/signe/maison
    scores_elem = {"Feu": 0, "Terre": 0, "Air": 0, "Eau": 0}
    scores_mode = {"Cardinal": 0, "Fixe": 0, "Mutable": 0}
    scores_signe = {s: 0 for s in _ELEMENTS}
    scores_maison = {i: 0 for i in range(1, 13)}

    for nom, score in scores_planete.items():
        info = points[nom]
        signe = info["signe"]
        maison = info.get("maison", 0)
        scores_elem[_ELEMENTS[signe]] += score
        scores_mode[_MODES[signe]] += score
        scores_signe[signe] += score
        if 1 <= maison <= 12:
            scores_maison[maison] += score

    def dominant(scores: dict) -> str:
        return max(scores, key=scores.get)

    return {
        "element": {"dominant": dominant(scores_elem), "scores": scores_elem},
        "mode": {"dominant": dominant(scores_mode), "scores": scores_mode},
        "planete": {"dominante": dominant(scores_planete), "scores": scores_planete},
        "signe": {"dominant": dominant(scores_signe), "scores": scores_signe},
        "maison": {"dominante": dominant(scores_maison), "scores": scores_maison},
        "methode": "score_complexe",
        "chart_diurne": chart_diurne,
        "detail": detail_planete,
    }


def dominantes(points: dict, maisons: list, aspects: list,
               methode: str = "comptage_dignite") -> dict:
    """Calcule les 5 dominantes selon la méthode choisie."""
    # Déterminer chart diurne
    soleil = points.get("Soleil", {}).get("longitude", 0)
    asc = points.get("Ascendant", {}).get("longitude", 0)
    mc = points.get("Milieu du Ciel", {}).get("longitude", 0)
    diurne = _chart_diurne(soleil, asc, mc)
    if methode == "comptage_dignite":
        return _comptage_dignite(points, maisons, aspects, diurne)
    if methode == "score_complexe":
        return _score_complexe(points, maisons, aspects, diurne)
    raise ValueError(f"Méthode inconnue : {methode!r}")
