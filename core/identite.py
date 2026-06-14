"""Dérivation d'informations à partir de la fiche d'identité de l'utilisateur (S48).

À partir des 5 champs de « se présenter » — prénoms, nom, date / heure / lieu de
naissance — on calcule, SANS aucune dépendance externe (stdlib seulement), tout ce
qui est dérivable honnêtement :

  • calendaire   : âge, jour de naissance, prochain anniversaire, jours vécus + jalons ;
  • culturel     : signe solaire, signe chinois + élément, génération, saison,
                   pierre & fleur du mois ;
  • numérologie  : chemin de vie (date), nombres d'expression / d'âme / de personnalité (nom) ;
  • biorythmes   : cycles physique / émotionnel / intellectuel ;
  • mini-thème astral : Soleil (degré), Ascendant, Milieu du Ciel, maisons — calcul
                   astronomique EXACT (rotation terrestre + obliquité de l'écliptique),
                   donc sans éphéméride. Lune + planètes + aspects = v1 (kerykeion).

Tout est en fonctions pures (date/heure/coordonnées en paramètres) → testable sans
réseau ni horloge. L'astrologie est un calcul exact mais reste une lecture de
DIVERTISSEMENT — l'API l'étiquette comme telle, le module se contente de calculer.
"""
from __future__ import annotations

import json
import math
import os
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path

# Fiche persistée dans le volume du Cœur (survit aux rebuilds) ; un défaut peut être
# baké dans l'image (identite_defaut.json), même motif que profil.md/profil_defaut.md.
FICHE_PATH = Path(os.getenv("IDENTITE_PATH", "/data/identite.json"))
FICHE_DEFAUT_PATH = Path(os.getenv("IDENTITE_DEFAUT_PATH", "/app/identite_defaut.json"))

# Champs reconnus de la fiche (on ignore tout le reste à l'enregistrement).
CHAMPS = ("prenoms", "nom", "date_naissance", "heure_naissance", "lieu_naissance",
          "latitude", "longitude", "utc_offset", "hemisphere")


# ── Tables de référence ──────────────────────────────────────────
SIGNES = [
    ("Bélier", "♈"), ("Taureau", "♉"), ("Gémeaux", "♊"), ("Cancer", "♋"),
    ("Lion", "♌"), ("Vierge", "♍"), ("Balance", "♎"), ("Scorpion", "♏"),
    ("Sagittaire", "♐"), ("Capricorne", "♑"), ("Verseau", "♒"), ("Poissons", "♓"),
]
ELEMENTS_SIGNE = ["Feu", "Terre", "Air", "Eau"]   # Bélier=Feu, Taureau=Terre, …

# Bornes du zodiaque tropical (mois, jour de DÉBUT du signe).
_BORNES_SOLAIRE = [
    (1, 20, "Verseau"), (2, 19, "Poissons"), (3, 21, "Bélier"), (4, 20, "Taureau"),
    (5, 21, "Gémeaux"), (6, 21, "Cancer"), (7, 23, "Lion"), (8, 23, "Vierge"),
    (9, 23, "Balance"), (10, 23, "Scorpion"), (11, 22, "Sagittaire"),
    (12, 22, "Capricorne"), (12, 31, "Capricorne"),
]

ANIMAUX_CHINOIS = [
    ("Rat", "🐀"), ("Buffle", "🐂"), ("Tigre", "🐅"), ("Lapin", "🐇"),
    ("Dragon", "🐉"), ("Serpent", "🐍"), ("Cheval", "🐴"), ("Chèvre", "🐐"),
    ("Singe", "🐒"), ("Coq", "🐓"), ("Chien", "🐕"), ("Cochon", "🐖"),
]
ELEMENTS_CHINOIS = ["Métal", "Eau", "Bois", "Feu", "Terre"]   # par paires de dernières décimales

PIERRES = {
    1: "Grenat", 2: "Améthyste", 3: "Aigue-marine", 4: "Diamant", 5: "Émeraude",
    6: "Perle", 7: "Rubis", 8: "Péridot", 9: "Saphir", 10: "Opale",
    11: "Topaze", 12: "Turquoise",
}
FLEURS = {
    1: "Œillet", 2: "Violette", 3: "Jonquille", 4: "Marguerite", 5: "Muguet",
    6: "Rose", 7: "Pied-d'alouette", 8: "Glaïeul", 9: "Aster", 10: "Souci",
    11: "Chrysanthème", 12: "Houx",
}
MOIS_FR = ["", "janvier", "février", "mars", "avril", "mai", "juin", "juillet",
           "août", "septembre", "octobre", "novembre", "décembre"]
JOURS_FR = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


# ── Persistance de la fiche ──────────────────────────────────────
def charger_fiche() -> dict:
    """Fiche enregistrée si elle existe, sinon le défaut baké, sinon {}."""
    for chemin in (FICHE_PATH, FICHE_DEFAUT_PATH):
        try:
            return json.loads(chemin.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            continue
    return {}


def enregistrer_fiche(maj: dict) -> dict:
    """Fusionne `maj` (champs connus) dans la fiche et la persiste. Retourne la fiche.

    Les nombres (latitude/longitude/utc_offset) sont coercés ; une chaîne vide efface
    le champ. Non destructif sur les champs non fournis."""
    fiche = charger_fiche()
    if FICHE_PATH.exists():       # repart de la version perso, pas du défaut baké
        try:
            fiche = json.loads(FICHE_PATH.read_text(encoding="utf-8"))
        except ValueError:
            fiche = {}
    for champ in CHAMPS:
        if champ not in maj:
            continue
        val = maj[champ]
        if champ in ("latitude", "longitude", "utc_offset"):
            try:
                val = float(val) if val not in (None, "") else None
            except (TypeError, ValueError):
                val = None
        if val in (None, ""):
            fiche.pop(champ, None)
        else:
            fiche[champ] = val
    FICHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    FICHE_PATH.write_text(json.dumps(fiche, ensure_ascii=False, indent=2), encoding="utf-8")
    return fiche


# ── Outils ────────────────────────────────────────────────────────
def _sans_accents(txt: str) -> str:
    """Minuscules ASCII : 'Rémi' → 'remi' (pour la numérologie du nom)."""
    nfkd = unicodedata.normalize("NFKD", txt or "")
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower()


def signe_solaire(mois: int, jour: int) -> dict:
    """Signe astrologique tropical d'après la date (table de bornes standard)."""
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


def generation(annee: int) -> str:
    for debut, fin, nom in [
        (1928, 1945, "Génération silencieuse"), (1946, 1964, "Baby-boomer"),
        (1965, 1980, "Génération X"), (1981, 1996, "Millennial (Génération Y)"),
        (1997, 2012, "Génération Z"), (2013, 2025, "Génération Alpha"),
    ]:
        if debut <= annee <= fin:
            return nom
    return "—"


def saison(mois: int, jour: int, hemisphere: str = "nord") -> str:
    """Saison astronomique approchée (bornes au 21). Inversée dans l'hémisphère sud."""
    nord = ("hiver" if (mois, jour) < (3, 21) else "printemps" if (mois, jour) < (6, 21)
            else "été" if (mois, jour) < (9, 21) else "automne" if (mois, jour) < (12, 21)
            else "hiver")
    if hemisphere == "sud":
        nord = {"hiver": "été", "printemps": "automne", "été": "hiver", "automne": "printemps"}[nord]
    return nord


def age(naissance: date, aujourdhui: date) -> dict:
    """Âge en années / mois / jours pleins."""
    ans = aujourdhui.year - naissance.year
    mois = aujourdhui.month - naissance.month
    jours = aujourdhui.day - naissance.day
    if jours < 0:
        mois -= 1
        # jours du mois précédent
        prem = aujourdhui.replace(day=1)
        dernier_mois_precedent = prem - timedelta(days=1)
        jours += dernier_mois_precedent.day
    if mois < 0:
        ans -= 1
        mois += 12
    return {"ans": ans, "mois": mois, "jours": jours}


def prochain_anniversaire(naissance: date, aujourdhui: date) -> dict:
    """Date du prochain anniversaire et nombre de jours d'ici là (0 = c'est aujourd'hui)."""
    an = aujourdhui.year
    try:
        cible = naissance.replace(year=an)
    except ValueError:           # 29 février → on vise le 1er mars
        cible = date(an, 3, 1)
    if cible < aujourdhui:
        try:
            cible = naissance.replace(year=an + 1)
        except ValueError:
            cible = date(an + 1, 3, 1)
    jours = (cible - aujourdhui).days
    return {"date": cible.isoformat(), "dans_jours": jours,
            "ages": aujourdhui.year - naissance.year + (0 if cible.year == aujourdhui.year else 1)}


def jours_vecus(naissance: date, aujourdhui: date) -> dict:
    """Jours vécus + prochain jalon « rond » (multiple de 1000 jours)."""
    n = (aujourdhui - naissance).days
    prochain_mille = ((n // 1000) + 1) * 1000
    return {"jours": n, "semaines": n // 7,
            "prochain_jalon": prochain_mille,
            "jalon_le": (naissance + timedelta(days=prochain_mille)).isoformat(),
            "dans_jours": prochain_mille - n}


def biorythmes(naissance: date, aujourdhui: date) -> dict:
    """Cycles sinusoïdaux classiques (%) : physique 23 j, émotionnel 28 j, intellectuel 33 j."""
    n = (aujourdhui - naissance).days
    pct = lambda p: round(100 * math.sin(2 * math.pi * n / p))
    return {"physique": pct(23), "emotionnel": pct(28), "intellectuel": pct(33)}


# ── Numérologie (pythagoricienne) ────────────────────────────────
def _reduire(n: int) -> int:
    """Réduit à un chiffre, en gardant les nombres maîtres 11 / 22 / 33."""
    while n > 9 and n not in (11, 22, 33):
        n = sum(int(c) for c in str(n))
    return n


def chemin_de_vie(naissance: date) -> int:
    chiffres = f"{naissance.year}{naissance.month:02d}{naissance.day:02d}"
    return _reduire(sum(int(c) for c in chiffres))


_VALEUR_LETTRE = {c: (i % 9) + 1 for i, c in enumerate("abcdefghijklmnopqrstuvwxyz")}
_VOYELLES = set("aeiouy")


def numerologie_nom(prenoms: str, nom: str) -> dict:
    """Nombres d'expression (toutes lettres), d'âme (voyelles) et de personnalité
    (consonnes). Y compté comme voyelle (convention française courante)."""
    lettres = [c for c in _sans_accents(f"{prenoms}{nom}") if c.isalpha()]
    total = sum(_VALEUR_LETTRE[c] for c in lettres)
    voyelles = sum(_VALEUR_LETTRE[c] for c in lettres if c in _VOYELLES)
    consonnes = sum(_VALEUR_LETTRE[c] for c in lettres if c not in _VOYELLES)
    return {"expression": _reduire(total), "ame": _reduire(voyelles),
            "personnalite": _reduire(consonnes)}


# ── Mini-thème astral (calcul astronomique exact, sans éphéméride) ─
# Soleil, Ascendant, Milieu du Ciel et maisons ne dépendent que du temps et de la
# géométrie Terre/écliptique — donc calculables précisément en stdlib. Lune et
# planètes (positions héliocentriques) exigeraient une éphéméride → v1 (kerykeion).

def _jour_julien(an: int, mois: int, jour: int, heure_ut: float) -> float:
    if mois <= 2:
        an -= 1
        mois += 12
    a = an // 100
    b = 2 - a + a // 4
    return (int(365.25 * (an + 4716)) + int(30.6001 * (mois + 1)) + jour
            + b - 1524.5 + heure_ut / 24.0)


def _signe_depuis_longitude(lon: float) -> dict:
    lon %= 360
    idx = int(lon // 30)
    nom, sym = SIGNES[idx]
    return {"signe": nom, "symbole": sym, "degre": round(lon - idx * 30, 2),
            "longitude": round(lon, 2)}


def theme_astral(naissance: datetime, utc_offset_h: float,
                 latitude: float, longitude: float) -> dict:
    """Soleil / Ascendant / MC / maisons (maisons en signes entiers depuis l'ascendant).

    `naissance` = heure LOCALE ; `utc_offset_h` = décalage local→UTC (ex. +2.0 pour
    la France en été 1990). `longitude` est EST-positive (Toulouse ≈ +1.44)."""
    heure_ut = naissance.hour + naissance.minute / 60 - utc_offset_h
    jj = _jour_julien(naissance.year, naissance.month, naissance.day, heure_ut)
    t = (jj - 2451545.0) / 36525.0

    # Obliquité de l'écliptique (deg).
    eps = math.radians(23.439291 - 0.0130042 * t)

    # Soleil — formule basse précision de Meeus (longitude apparente ≈ exacte au 0,01°).
    l0 = 280.46646 + 36000.76983 * t + 0.0003032 * t * t
    m = math.radians(357.52911 + 35999.05029 * t - 0.0001537 * t * t)
    c = ((1.914602 - 0.004817 * t - 0.000014 * t * t) * math.sin(m)
         + (0.019993 - 0.000101 * t) * math.sin(2 * m)
         + 0.000289 * math.sin(3 * m))
    soleil_lon = (l0 + c) % 360

    # Temps sidéral local (deg) → ascension droite du MC.
    gmst = (280.46061837 + 360.98564736629 * (jj - 2451545.0)
            + 0.000387933 * t * t - t * t * t / 38710000.0)
    lst = math.radians((gmst + longitude) % 360)

    # Milieu du Ciel (longitude écliptique du méridien).
    mc = math.degrees(math.atan2(math.sin(lst), math.cos(lst) * math.cos(eps))) % 360

    # Ascendant (point écliptique levant à l'est).
    phi = math.radians(latitude)
    asc = math.degrees(math.atan2(
        math.cos(lst),
        -(math.sin(lst) * math.cos(eps) + math.tan(phi) * math.sin(eps)))) % 360

    asc_info = _signe_depuis_longitude(asc)
    # Maisons en signes entiers : 12 signes à partir du signe de l'ascendant.
    idx_asc = int(asc // 30)
    maisons = [{"maison": i + 1, "signe": SIGNES[(idx_asc + i) % 12][0],
                "symbole": SIGNES[(idx_asc + i) % 12][1]} for i in range(12)]
    return {
        "soleil": _signe_depuis_longitude(soleil_lon),
        "ascendant": asc_info,
        "milieu_du_ciel": _signe_depuis_longitude(mc),
        "maisons": maisons,
        "heure_utc": round(heure_ut % 24, 2),
        "note": "Soleil, Ascendant et MC calculés (exact). Lune et planètes : à venir (éphéméride).",
    }


# ── Synthèse : tout ce qui est dérivable de la fiche ─────────────
def deriver(fiche: dict, aujourdhui: date | None = None) -> dict:
    """Agrège TOUTES les dérivations à partir de la fiche d'identité.

    `fiche` : {prenoms, nom, date_naissance "YYYY-MM-DD", heure_naissance "HH:MM"?,
               lieu_naissance?, latitude?, longitude?, utc_offset?, hemisphere?}.
    Chaque section est indépendante : un champ manquant désactive juste sa section,
    sans jamais lever d'erreur (repli honnête)."""
    aujourdhui = aujourdhui or date.today()
    out: dict = {}

    dn = (fiche.get("date_naissance") or "").strip()
    naissance = None
    if dn:
        try:
            naissance = date.fromisoformat(dn)
        except ValueError:
            naissance = None

    if naissance:
        out["age"] = age(naissance, aujourdhui)
        out["jour_naissance"] = JOURS_FR[naissance.weekday()]
        out["anniversaire"] = prochain_anniversaire(naissance, aujourdhui)
        out["jours_vecus"] = jours_vecus(naissance, aujourdhui)
        out["signe_solaire"] = signe_solaire(naissance.month, naissance.day)
        out["signe_chinois"] = signe_chinois(naissance.year)
        out["generation"] = generation(naissance.year)
        out["saison"] = saison(naissance.month, naissance.day,
                               fiche.get("hemisphere") or "nord")
        out["pierre_du_mois"] = PIERRES.get(naissance.month)
        out["fleur_du_mois"] = FLEURS.get(naissance.month)
        out["biorythmes"] = biorythmes(naissance, aujourdhui)
        out["chemin_de_vie"] = chemin_de_vie(naissance)

    if (fiche.get("prenoms") or fiche.get("nom")):
        out["numerologie_nom"] = numerologie_nom(fiche.get("prenoms") or "",
                                                 fiche.get("nom") or "")

    # Thème astral : nécessite date + heure + coordonnées.
    he = (fiche.get("heure_naissance") or "").strip()
    lat, lon = fiche.get("latitude"), fiche.get("longitude")
    if naissance and he and isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
        try:
            hh, mm = (int(x) for x in he.split(":")[:2])
            dt = datetime(naissance.year, naissance.month, naissance.day, hh, mm)
            out["theme_astral"] = theme_astral(
                dt, float(fiche.get("utc_offset") or 0), float(lat), float(lon))
        except (ValueError, TypeError):
            pass

    return out


def resume_texte(fiche: dict, aujourdhui: date | None = None) -> str:
    """Digest court (Markdown) à injecter dans le contexte de l'assistant.

    Donne au Jarvis les faits utiles (prénom, âge, anniversaire) + la couche ludique
    (signes, thème), clairement cadrée comme du divertissement pour l'astrologie."""
    d = deriver(fiche, aujourdhui)
    prenom = (fiche.get("prenoms") or "").split()[0] if fiche.get("prenoms") else None
    lignes = []
    if prenom:
        lignes.append(f"Prénom usuel : {prenom}.")
    if "age" in d:
        a = d["age"]
        lignes.append(f"Âge : {a['ans']} ans.")
    if "anniversaire" in d:
        an = d["anniversaire"]
        quand = "aujourd'hui 🎉" if an["dans_jours"] == 0 else f"dans {an['dans_jours']} j"
        lignes.append(f"Prochain anniversaire : {quand} ({an['date']}).")
    if "signe_solaire" in d:
        s = d["signe_solaire"]
        lignes.append(f"Signe solaire : {s['nom']} {s['symbole']} ({s['element']}).")
    if "signe_chinois" in d:
        c = d["signe_chinois"]
        lignes.append(f"Astrologie chinoise : {c['animal']} de {c['element']} ({c['polarite']}).")
    if "theme_astral" in d:
        a = d["theme_astral"]["ascendant"]
        lignes.append(f"Ascendant : {a['signe']} {a['symbole']} (calculé).")
    if "chemin_de_vie" in d:
        lignes.append(f"Numérologie — chemin de vie : {d['chemin_de_vie']}.")
    if not lignes:
        return ""
    return ("Repères dérivés de l'état civil (l'astrologie/numérologie est du "
            "divertissement, pas un fait) :\n- " + "\n- ".join(lignes))
