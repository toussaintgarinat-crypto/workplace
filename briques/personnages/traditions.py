"""Moteur de traditions — le socle « holistique » de la brique personnages (S49).

À partir d'une fiche minimale (nom, date / heure / lieu de naissance) on calcule, SANS
aucune dépendance externe (stdlib seulement), un faisceau de lectures issues de plusieurs
traditions. Chaque fonction est PURE (entrées → sortie, pas d'état, pas d'horloge) donc
testable hors ligne.

Honnêteté technique (garde-fou) : tout ce qui est étiqueté « calculé » l'est vraiment
(numérologie, signe solaire, animal chinois, thème astral Soleil/Ascendant/MC exact,
Tzolkin maya déterministe, rashi védique sidéral). L'INTERPRÉTATION qu'on en tire reste
du DIVERTISSEMENT — l'API le rappelle, le module se contente de calculer.

Ce module est volontairement autonome (copié/étendu depuis core/identite.py du Cœur) :
la brique personnages est un produit vendable seul, elle ne dépend pas de Workplace.

Lune, planètes, Design Humain, nakshatra lunaire = palier v2 (éphéméride kerykeion).
"""
from __future__ import annotations

import math
import unicodedata
from datetime import date, datetime


# ── Tables zodiacales occidentales ───────────────────────────────
SIGNES = [
    ("Bélier", "♈"), ("Taureau", "♉"), ("Gémeaux", "♊"), ("Cancer", "♋"),
    ("Lion", "♌"), ("Vierge", "♍"), ("Balance", "♎"), ("Scorpion", "♏"),
    ("Sagittaire", "♐"), ("Capricorne", "♑"), ("Verseau", "♒"), ("Poissons", "♓"),
]
ELEMENTS_SIGNE = ["Feu", "Terre", "Air", "Eau"]   # Bélier=Feu, Taureau=Terre, …

# Plage de dates (début → fin) de chaque signe tropical — utile au mode montant.
SIGNE_PLAGES = {
    "Bélier": ((3, 21), (4, 19)), "Taureau": ((4, 20), (5, 20)),
    "Gémeaux": ((5, 21), (6, 20)), "Cancer": ((6, 21), (7, 22)),
    "Lion": ((7, 23), (8, 22)), "Vierge": ((8, 23), (9, 22)),
    "Balance": ((9, 23), (10, 22)), "Scorpion": ((10, 23), (11, 21)),
    "Sagittaire": ((11, 22), (12, 21)), "Capricorne": ((12, 22), (1, 19)),
    "Verseau": ((1, 20), (2, 18)), "Poissons": ((2, 19), (3, 20)),
}

_BORNES_SOLAIRE = [
    (1, 20, "Verseau"), (2, 19, "Poissons"), (3, 21, "Bélier"), (4, 20, "Taureau"),
    (5, 21, "Gémeaux"), (6, 21, "Cancer"), (7, 23, "Lion"), (8, 23, "Vierge"),
    (9, 23, "Balance"), (10, 23, "Scorpion"), (11, 22, "Sagittaire"),
    (12, 22, "Capricorne"), (12, 31, "Capricorne"),
]

# ── Astrologie chinoise ──────────────────────────────────────────
ANIMAUX_CHINOIS = [
    ("Rat", "🐀"), ("Buffle", "🐂"), ("Tigre", "🐅"), ("Lapin", "🐇"),
    ("Dragon", "🐉"), ("Serpent", "🐍"), ("Cheval", "🐴"), ("Chèvre", "🐐"),
    ("Singe", "🐒"), ("Coq", "🐓"), ("Chien", "🐕"), ("Cochon", "🐖"),
]
ELEMENTS_CHINOIS = ["Métal", "Eau", "Bois", "Feu", "Terre"]

# Animal de l'heure (12 branches terrestres, tranches de 2 h ; le Rat couvre 23 h–01 h).
ANIMAUX_HEURE = [
    ("Rat", 23, 1), ("Buffle", 1, 3), ("Tigre", 3, 5), ("Lapin", 5, 7),
    ("Dragon", 7, 9), ("Serpent", 9, 11), ("Cheval", 11, 13), ("Chèvre", 13, 15),
    ("Singe", 15, 17), ("Coq", 17, 19), ("Chien", 19, 21), ("Cochon", 21, 23),
]

PIERRES = {
    1: "Grenat", 2: "Améthyste", 3: "Aigue-marine", 4: "Diamant", 5: "Émeraude",
    6: "Perle", 7: "Rubis", 8: "Péridot", 9: "Saphir", 10: "Opale",
    11: "Topaze", 12: "Turquoise",
}

# ── Tradition égyptienne (divinité selon segments de l'année) ─────
# Version « zodiaque égyptien » répandue : segments contigus couvrant l'année entière.
_SEGMENTS_EGYPTE = [
    (1, 1, 1, 7, "Le Nil"), (1, 8, 1, 21, "Amon-Rê"), (1, 22, 1, 31, "Mout"),
    (2, 1, 2, 11, "Amon-Rê"), (2, 12, 2, 29, "Geb"), (3, 1, 3, 10, "Osiris"),
    (3, 11, 3, 31, "Isis"), (4, 1, 4, 19, "Thot"), (4, 20, 5, 7, "Horus"),
    (5, 8, 5, 27, "Anubis"), (5, 28, 6, 18, "Seth"), (6, 19, 6, 28, "Le Nil"),
    (6, 29, 7, 13, "Anubis"), (7, 14, 7, 28, "Bastet"), (7, 29, 8, 11, "Sekhmet"),
    (8, 12, 8, 19, "Horus"), (8, 20, 8, 31, "Geb"), (9, 1, 9, 7, "Le Nil"),
    (9, 8, 9, 22, "Mout"), (9, 23, 9, 27, "Bastet"), (9, 28, 10, 2, "Seth"),
    (10, 3, 10, 17, "Bastet"), (10, 18, 10, 29, "Isis"), (10, 30, 11, 7, "Sekhmet"),
    (11, 8, 11, 17, "Thot"), (11, 18, 11, 26, "Le Nil"), (11, 27, 12, 18, "Osiris"),
    (12, 19, 12, 31, "Isis"),
]

# ── Calendrier des arbres druidiques (astrologie celte gauloise, 21 arbres) ──
# Plusieurs arbres reviennent sur DEUX (ou quatre) périodes symétriques de l'année, et
# quatre signes d'un seul jour marquent les solstices / équinoxes (Chêne, Bouleau, Olivier,
# Hêtre). Caveat d'honnêteté : cette « astrologie celtique » est une création moderne
# (XXᵉ s.), pas un héritage druidique authentifié — interprétation = divertissement.
_SEGMENTS_CELTE = [
    (3, 21, 3, 21, "Chêne"), (6, 24, 6, 24, "Bouleau"),       # solstices / équinoxes :
    (9, 23, 9, 23, "Olivier"), (12, 22, 12, 22, "Hêtre"),     # signes d'un seul jour
    (3, 22, 3, 31, "Noisetier"), (9, 24, 10, 3, "Noisetier"),
    (4, 1, 4, 10, "Sorbier"), (10, 4, 10, 13, "Sorbier"),
    (4, 11, 4, 20, "Érable"), (10, 14, 10, 23, "Érable"),
    (4, 21, 4, 30, "Noyer"), (10, 24, 11, 2, "Noyer"),
    (5, 1, 5, 14, "Peuplier"), (8, 5, 8, 13, "Peuplier"),
    (11, 3, 11, 11, "Peuplier"), (2, 4, 2, 8, "Peuplier"),
    (5, 15, 5, 24, "Châtaignier"), (11, 12, 11, 21, "Châtaignier"),
    (5, 25, 6, 3, "Frêne"), (11, 22, 12, 1, "Frêne"),
    (6, 4, 6, 13, "Charme"), (12, 2, 12, 11, "Charme"),
    (6, 14, 6, 23, "Figuier"), (12, 12, 12, 21, "Figuier"),
    (6, 25, 7, 4, "Pommier"), (12, 23, 1, 1, "Pommier"),
    (7, 5, 7, 14, "If"), (1, 2, 1, 11, "If"),
    (7, 15, 7, 25, "Orme"), (1, 12, 1, 24, "Orme"),
    (7, 26, 8, 4, "Cyprès"), (1, 25, 2, 3, "Cyprès"),
    (8, 14, 8, 23, "Micocoulier"), (2, 9, 2, 18, "Micocoulier"),
    (8, 24, 9, 2, "Pin"), (2, 19, 2, 29, "Pin"),
    (9, 3, 9, 12, "Saule"), (3, 1, 3, 10, "Saule"),
    (9, 13, 9, 22, "Tilleul"), (3, 11, 3, 20, "Tilleul"),
]

# ── Totems amérindiens (12 animaux, alignés sur les dates tropicales) ─
_SEGMENTS_TOTEM = [
    (12, 22, 1, 19, "Oie"), (1, 20, 2, 18, "Loutre"), (2, 19, 3, 20, "Loup"),
    (3, 21, 4, 19, "Faucon"), (4, 20, 5, 20, "Castor"), (5, 21, 6, 20, "Cerf"),
    (6, 21, 7, 21, "Pic-vert"), (7, 22, 8, 21, "Saumon"), (8, 22, 9, 21, "Ours"),
    (9, 22, 10, 22, "Corbeau"), (10, 23, 11, 22, "Serpent"), (11, 23, 12, 21, "Hibou"),
]

# ── Maya — Tzolkin (260 j = 20 glyphes × 13 tonalités), corrélation GMT 584283 ──
GLYPHES_MAYA = [
    "Imix", "Ik", "Akbal", "Kan", "Chicchan", "Cimi", "Manik", "Lamat", "Muluc",
    "Oc", "Chuen", "Eb", "Ben", "Ix", "Men", "Cib", "Caban", "Etznab", "Cauac", "Ahau",
]
_CORRELATION_GMT = 584283   # JJ ↔ 4 Ahau (point d'ancrage du compte long)

MOIS_FR = ["", "janvier", "février", "mars", "avril", "mai", "juin", "juillet",
           "août", "septembre", "octobre", "novembre", "décembre"]
JOURS_FR = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


# ── Outils ────────────────────────────────────────────────────────
def _sans_accents(txt: str) -> str:
    nfkd = unicodedata.normalize("NFKD", txt or "")
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower()


def _dans_segment(mois: int, jour: int, segments: list) -> str:
    """Trouve l'étiquette du segment (m1,j1,m2,j2,nom) contenant (mois,jour).

    Gère les segments à cheval sur le Nouvel An (m1 > m2, ex. 24/12→20/01)."""
    pos = (mois, jour)
    for m1, j1, m2, j2, nom in segments:
        if (m1, j1) <= (m2, j2):           # segment dans l'année civile
            if (m1, j1) <= pos <= (m2, j2):
                return nom
        else:                               # segment à cheval (décembre→janvier)
            if pos >= (m1, j1) or pos <= (m2, j2):
                return nom
    return segments[0][4]


# ── Numérologie pythagoricienne ──────────────────────────────────
def _reduire(n: int) -> int:
    """Réduit à un chiffre en gardant les nombres maîtres 11 / 22 / 33."""
    while n > 9 and n not in (11, 22, 33):
        n = sum(int(c) for c in str(n))
    return n


def chemin_de_vie(naissance: date) -> int:
    chiffres = f"{naissance.year}{naissance.month:02d}{naissance.day:02d}"
    return _reduire(sum(int(c) for c in chiffres))


# Deux systèmes de gématrie : pythagoricien (A=1…I=9 puis cycle) et « classique »
# A=1…Z=26 (réduction théosophique). Le rapport de cadrage utilise le second.
_VALEUR_PYTHAGORE = {c: (i % 9) + 1 for i, c in enumerate("abcdefghijklmnopqrstuvwxyz")}
_VALEUR_CLASSIQUE = {c: i + 1 for i, c in enumerate("abcdefghijklmnopqrstuvwxyz")}
_VOYELLES = set("aeiouy")


def numerologie_nom(prenoms: str, nom: str, systeme: str = "classique") -> dict:
    """Nombres d'expression (toutes lettres), d'âme (voyelles), de personnalité (consonnes).

    `systeme` : "classique" (A=1…Z=26, défaut, comme le rapport) ou "pythagoricien"
    (A=1…I=9 puis cycle). Réduction théosophique dans les deux cas (maîtres 11/22/33)."""
    table = _VALEUR_PYTHAGORE if systeme == "pythagoricien" else _VALEUR_CLASSIQUE
    lettres = [c for c in _sans_accents(f"{prenoms}{nom}") if c.isalpha()]
    if not lettres:
        return {}
    total = sum(table[c] for c in lettres)
    voyelles = sum(table[c] for c in lettres if c in _VOYELLES)
    consonnes = sum(table[c] for c in lettres if c not in _VOYELLES)
    return {"expression": _reduire(total), "ame": _reduire(voyelles),
            "personnalite": _reduire(consonnes), "systeme": systeme}


# ── Signes occidental & chinois ──────────────────────────────────
def signe_solaire(mois: int, jour: int) -> dict:
    nom = "Capricorne"
    for m, j, signe in _BORNES_SOLAIRE:
        if (mois, jour) < (m, j):
            break
        nom = signe
    idx = [s[0] for s in SIGNES].index(nom)
    return {"nom": nom, "symbole": SIGNES[idx][1], "element": ELEMENTS_SIGNE[idx % 4]}


def signe_chinois(annee: int) -> dict:
    """Animal + élément + polarité (cycle sexagénaire). Caveat : ignore la date du
    Nouvel An lunaire (janvier/février incertains) — exact pour le reste de l'année."""
    nom, emoji = ANIMAUX_CHINOIS[(annee - 4) % 12]
    element = ELEMENTS_CHINOIS[(annee % 10) // 2]
    polarite = "Yang" if annee % 2 == 0 else "Yin"
    return {"animal": nom, "emoji": emoji, "element": element, "polarite": polarite}


def animal_heure(heure: int) -> dict:
    """Animal chinois de l'heure de naissance (12 branches terrestres, tranches de 2 h)."""
    idx = ((heure + 1) // 2) % 12
    nom, debut, fin = ANIMAUX_HEURE[idx]
    emoji = next(e for n, e in ANIMAUX_CHINOIS if n == nom)
    return {"animal": nom, "emoji": emoji, "tranche": f"{debut:02d}h–{fin:02d}h"}


# ── Traditions par date (égyptienne / celte / amérindienne) ──────
def divinite_egyptienne(mois: int, jour: int) -> str:
    return _dans_segment(mois, jour, _SEGMENTS_EGYPTE)


def arbre_celte(mois: int, jour: int) -> str:
    return _dans_segment(mois, jour, _SEGMENTS_CELTE)


def totem_amerindien(mois: int, jour: int) -> str:
    return _dans_segment(mois, jour, _SEGMENTS_TOTEM)


# ── Calcul du jour julien (partagé Tzolkin + thème astral) ───────
def _jour_julien(an: int, mois: int, jour: int, heure_ut: float) -> float:
    if mois <= 2:
        an -= 1
        mois += 12
    a = an // 100
    b = 2 - a + a // 4
    return (int(365.25 * (an + 4716)) + int(30.6001 * (mois + 1)) + jour
            + b - 1524.5 + heure_ut / 24.0)


# ── Maya Tzolkin (déterministe) ──────────────────────────────────
def tzolkin(naissance: date) -> dict:
    """Glyphe + tonalité (1–13) du jour, corrélation GMT (584283 ↔ 4 Ahau).

    Calcul exact à partir du jour julien : aucune éphéméride requise."""
    jjn = int(_jour_julien(naissance.year, naissance.month, naissance.day, 0.0) + 0.5)
    jours = jjn - _CORRELATION_GMT
    tonalite = ((jours + 3) % 13) + 1          # ancrage : jours=0 → 4
    glyphe = GLYPHES_MAYA[(jours + 19) % 20]   # ancrage : jours=0 → Ahau (index 19)
    return {"glyphe": glyphe, "tonalite": tonalite}


# ── Lune (série lunaire abrégée de Meeus, sans éphéméride) ───────
# La position de la Lune est périodique : une somme des plus grands termes de la théorie
# ELP (Meeus, Astronomical Algorithms ch. 47) donne ~0,1–0,3° — assez pour le SIGNE lunaire
# (30°) et le NAKSHATRA (13°20'). On reste géocentrique (parallaxe topocentrique ignorée,
# < 1°). Cohérent avec le Soleil/Ascendant : exact à l'usage, sans dépendance.

# (coefficient en degrés, multiplicateurs de D, M, M', F) — termes principaux de Σl.
_TERMES_LUNE = [
    (6.288774, 0, 0, 1, 0), (1.274027, 2, 0, -1, 0), (0.658314, 2, 0, 0, 0),
    (0.213618, 0, 0, 2, 0), (-0.185116, 0, 1, 0, 0), (-0.114332, 0, 0, 0, 2),
    (0.058793, 2, 0, -2, 0), (0.057066, 2, -1, -1, 0), (0.053322, 2, 0, 1, 0),
    (0.045758, 2, -1, 0, 0), (-0.040923, 0, 1, -1, 0), (-0.034720, 1, 0, 0, 0),
    (-0.030383, 0, 1, 1, 0), (0.015327, 2, 0, 0, -2), (-0.012528, 0, 0, 1, 2),
    (0.010980, 0, 0, 1, -2), (0.010675, 4, 0, -1, 0), (0.010034, 0, 0, 3, 0),
    (0.008548, 4, 0, -2, 0), (-0.007888, 2, 1, -1, 0), (-0.006766, 2, 1, 0, 0),
    (-0.005163, 1, 0, -1, 0), (0.004987, 1, 1, 0, 0), (0.004036, 2, -1, 1, 0),
]

NAKSHATRAS = [
    "Ashwini", "Bharani", "Krittika", "Rohini", "Mrigashira", "Ardra", "Punarvasu",
    "Pushya", "Ashlesha", "Magha", "Purva Phalguni", "Uttara Phalguni", "Hasta",
    "Chitra", "Swati", "Vishakha", "Anuradha", "Jyeshtha", "Mula", "Purva Ashadha",
    "Uttara Ashadha", "Shravana", "Dhanishta", "Shatabhisha", "Purva Bhadrapada",
    "Uttara Bhadrapada", "Revati",
]


def lune_longitude(naissance: datetime, utc_offset_h: float) -> float:
    """Longitude écliptique tropicale de la Lune (deg), série abrégée de Meeus (~0,1°)."""
    heure_ut = naissance.hour + naissance.minute / 60 - utc_offset_h
    jj = _jour_julien(naissance.year, naissance.month, naissance.day, heure_ut)
    t = (jj - 2451545.0) / 36525.0
    lp = 218.3164477 + 481267.88123421 * t - 0.0015786 * t * t + t**3 / 538841 - t**4 / 65194000
    d = 297.8501921 + 445267.1114034 * t - 0.0018819 * t * t + t**3 / 545868 - t**4 / 113065000
    m = 357.5291092 + 35999.0502909 * t - 0.0001536 * t * t + t**3 / 24490000
    mp = 134.9633964 + 477198.8675055 * t + 0.0087414 * t * t + t**3 / 69699 - t**4 / 14712000
    f = 93.2720950 + 483202.0175233 * t - 0.0036539 * t * t - t**3 / 3526000 + t**4 / 863310000
    e = 1 - 0.002516 * t - 0.0000074 * t * t            # correction d'excentricité (termes en M)
    somme = 0.0
    for coef, kd, km, kmp, kf in _TERMES_LUNE:
        arg = math.radians(kd * d + km * m + kmp * mp + kf * f)
        terme = coef * math.sin(arg)
        if km != 0:                                     # termes dépendant de l'anomalie solaire
            terme *= e ** abs(km)
        somme += terme
    return (lp + somme) % 360


def signe_lunaire(naissance: datetime, utc_offset_h: float) -> dict:
    """Signe (et degré) de la Lune — émotions / « jardin secret » du rapport."""
    return _signe_depuis_longitude(lune_longitude(naissance, utc_offset_h))


def nakshatra(lune_lon_tropicale: float, annee: int) -> dict:
    """Nakshatra (28e : les 27 maisons lunaires védiques de 13°20') + pada (quart).

    Calculé depuis la Lune SIDÉRALE (tropicale − ayanamsa). Exact à l'usage."""
    sid = (lune_lon_tropicale - _ayanamsa(annee)) % 360
    span = 360 / 27
    idx = int(sid // span)
    pada = int((sid % span) // (span / 4)) + 1
    return {"nakshatra": NAKSHATRAS[idx], "pada": pada,
            "longitude_siderale": round(sid, 2)}


# ── Astrologie védique (sidérale ≈ tropicale − ayanamsa) ─────────
def _ayanamsa(annee: int) -> float:
    """Ayanamsa Lahiri approché : ≈ 23,85° à J2000, dérive de ~50,29″/an."""
    return 23.85 + (annee - 2000) * 0.013969


def rashi_vedique(soleil_lon_tropicale: float, annee: int) -> dict:
    """Signe sidéral (rashi) du Soleil : longitude tropicale − ayanamsa.

    Sans éphéméride : on réutilise la longitude solaire déjà calculée (exacte). Le
    nakshatra dépend de la LUNE → palier v2 (éphéméride)."""
    lon = (soleil_lon_tropicale - _ayanamsa(annee)) % 360
    idx = int(lon // 30)
    nom, sym = SIGNES[idx]
    return {"rashi": nom, "symbole": sym, "degre": round(lon - idx * 30, 2),
            "ayanamsa": round(_ayanamsa(annee), 2)}


# ── Mini-thème astral exact (Soleil / Ascendant / MC, sans éphéméride) ─
def _signe_depuis_longitude(lon: float) -> dict:
    lon %= 360
    idx = int(lon // 30)
    nom, sym = SIGNES[idx]
    return {"signe": nom, "symbole": sym, "degre": round(lon - idx * 30, 2),
            "longitude": round(lon, 2)}


def soleil_longitude(naissance: datetime, utc_offset_h: float) -> float:
    """Longitude écliptique apparente du Soleil (deg), formule de Meeus (≈ exact au 0,01°)."""
    heure_ut = naissance.hour + naissance.minute / 60 - utc_offset_h
    jj = _jour_julien(naissance.year, naissance.month, naissance.day, heure_ut)
    t = (jj - 2451545.0) / 36525.0
    l0 = 280.46646 + 36000.76983 * t + 0.0003032 * t * t
    m = math.radians(357.52911 + 35999.05029 * t - 0.0001537 * t * t)
    c = ((1.914602 - 0.004817 * t - 0.000014 * t * t) * math.sin(m)
         + (0.019993 - 0.000101 * t) * math.sin(2 * m)
         + 0.000289 * math.sin(3 * m))
    return (l0 + c) % 360


def theme_astral(naissance: datetime, utc_offset_h: float,
                 latitude: float, longitude: float) -> dict:
    """Soleil / Ascendant / MC / maisons (maisons en signes entiers depuis l'ascendant).

    `naissance` = heure LOCALE ; `utc_offset_h` = décalage local→UTC ; `longitude`
    EST-positive. Calcul géométrique exact (obliquité + rotation terrestre)."""
    heure_ut = naissance.hour + naissance.minute / 60 - utc_offset_h
    jj = _jour_julien(naissance.year, naissance.month, naissance.day, heure_ut)
    t = (jj - 2451545.0) / 36525.0
    eps = math.radians(23.439291 - 0.0130042 * t)
    soleil_lon = soleil_longitude(naissance, utc_offset_h)

    gmst = (280.46061837 + 360.98564736629 * (jj - 2451545.0)
            + 0.000387933 * t * t - t * t * t / 38710000.0)
    lst = math.radians((gmst + longitude) % 360)
    mc = math.degrees(math.atan2(math.sin(lst), math.cos(lst) * math.cos(eps))) % 360
    phi = math.radians(latitude)
    asc = math.degrees(math.atan2(
        math.cos(lst),
        -(math.sin(lst) * math.cos(eps) + math.tan(phi) * math.sin(eps)))) % 360

    idx_asc = int(asc // 30)
    maisons = [{"maison": i + 1, "signe": SIGNES[(idx_asc + i) % 12][0],
                "symbole": SIGNES[(idx_asc + i) % 12][1]} for i in range(12)]
    return {
        "soleil": _signe_depuis_longitude(soleil_lon),
        "ascendant": _signe_depuis_longitude(asc),
        "milieu_du_ciel": _signe_depuis_longitude(mc),
        "maisons": maisons,
        "heure_utc": round(heure_ut % 24, 2),
        "note": "Soleil, Ascendant et MC calculés (exact). Lune et planètes : v2 (éphéméride).",
    }


# ── Synthèse de toutes les traditions calculables d'une fiche ────
def calculer(fiche: dict) -> dict:
    """Agrège TOUTES les traditions dérivables de la fiche. Repli honnête par section :
    un champ manquant désactive juste sa lecture, sans jamais lever d'erreur.

    `fiche` : {prenoms?, nom?, date_naissance "YYYY-MM-DD", heure_naissance "HH:MM"?,
               latitude?, longitude?, utc_offset?}."""
    out: dict = {}

    dn = (fiche.get("date_naissance") or "").strip()
    naissance = None
    if dn:
        try:
            naissance = date.fromisoformat(dn)
        except ValueError:
            naissance = None

    if naissance:
        m, j, an = naissance.month, naissance.day, naissance.year
        out["signe_solaire"] = signe_solaire(m, j)
        out["signe_chinois"] = signe_chinois(an)
        out["chemin_de_vie"] = chemin_de_vie(naissance)
        out["egyptien"] = divinite_egyptienne(m, j)
        out["celte"] = arbre_celte(m, j)
        out["amerindien"] = totem_amerindien(m, j)
        out["maya"] = tzolkin(naissance)
        out["pierre_du_mois"] = PIERRES.get(m)

    if fiche.get("prenoms") or fiche.get("nom"):
        num = numerologie_nom(fiche.get("prenoms") or "", fiche.get("nom") or "",
                              fiche.get("systeme_numerologie") or "classique")
        if num:
            out["numerologie_nom"] = num

    # Heure → animal chinois de l'heure (n'exige pas les coordonnées).
    he = (fiche.get("heure_naissance") or "").strip()
    heure = None
    if he:
        try:
            heure = int(he.split(":")[0])
            out["animal_heure"] = animal_heure(heure)
        except ValueError:
            heure = None

    # Lune (signe lunaire + nakshatra) : nécessite date + heure, PAS les coordonnées
    # (géocentrique). La Lune bouge ~0,5°/h → l'heure compte vraiment.
    if naissance and heure is not None:
        try:
            hh, mm = (int(x) for x in he.split(":")[:2])
            dt_l = datetime(naissance.year, naissance.month, naissance.day, hh, mm)
            off_l = float(fiche.get("utc_offset") or 0)
            lon_lune = lune_longitude(dt_l, off_l)
            out["signe_lunaire"] = _signe_depuis_longitude(lon_lune)
            out["nakshatra"] = nakshatra(lon_lune, naissance.year)
        except (ValueError, TypeError):
            pass

    # Thème astral + rashi védique : nécessitent date + heure + coordonnées.
    lat, lon = fiche.get("latitude"), fiche.get("longitude")
    if (naissance and heure is not None
            and isinstance(lat, (int, float)) and isinstance(lon, (int, float))):
        try:
            hh, mm = (int(x) for x in he.split(":")[:2])
            dt = datetime(naissance.year, naissance.month, naissance.day, hh, mm)
            off = float(fiche.get("utc_offset") or 0)
            ta = theme_astral(dt, off, float(lat), float(lon))
            out["theme_astral"] = ta
            out["vedique"] = rashi_vedique(ta["soleil"]["longitude"], naissance.year)
        except (ValueError, TypeError):
            pass

    return out
