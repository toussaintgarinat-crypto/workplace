"""Dictionnaire de significations — donne du SENS aux valeurs calculées (S49).

Le moteur (traditions.py) calcule des valeurs (« Bastet », « Orme », « Pushya », chemin
de vie 7…) ; ici on leur attache une courte lecture en mots-clés, pour que le portrait
soit compréhensible et pas juste une liste d'étiquettes. C'est le « dictionnaire des
données » du rapport de cadrage.

Tout est concis (quelques mots-clés) et reste une lecture de DIVERTISSEMENT. `expliquer()`
assemble l'empreinte lisible à partir de la sortie de traditions.calculer()."""
from __future__ import annotations


# ── Signes du zodiaque (Soleil / Lune / Ascendant / rashi védique) ──
SIGNES_SENS = {
    "Bélier": "élan, courage, initiative, impatience",
    "Taureau": "ténacité, sensualité, ancrage, obstination",
    "Gémeaux": "curiosité, vivacité, communication, dispersion",
    "Cancer": "sensibilité, protection, mémoire, pudeur",
    "Lion": "fierté, rayonnement, générosité, ego",
    "Vierge": "analyse, rigueur, sens du service, exigence",
    "Balance": "harmonie, diplomatie, esthétique, indécision",
    "Scorpion": "intensité, secret, transformation, méfiance",
    "Sagittaire": "liberté, foi, aventure, excès",
    "Capricorne": "ambition, discipline, patience, austérité",
    "Verseau": "originalité, idéal, indépendance, détachement",
    "Poissons": "intuition, compassion, rêve, évasion",
}

# Rôle de chaque placement astral (ce que la position éclaire).
ROLE_PLACEMENT = {
    "soleil": "noyau, ego",
    "lune": "émotions, jardin secret",
    "ascendant": "apparence, masque social",
    "vedique": "lecture sidérale, karma",
}

# ── Animaux chinois (année & heure) ──────────────────────────────
CHINOIS_SENS = {
    "Rat": "vif, débrouillard, charmeur",
    "Buffle": "endurant, fiable, têtu",
    "Tigre": "audacieux, passionné, rebelle",
    "Lapin": "doux, prudent, diplomate",
    "Dragon": "charismatique, ambitieux, fier",
    "Serpent": "sage, intuitif, secret",
    "Cheval": "énergique, libre, impatient",
    "Chèvre": "créatif, sensible, rêveur",
    "Singe": "malin, inventif, joueur",
    "Coq": "franc, organisé, fier",
    "Chien": "loyal, juste, anxieux",
    "Cochon": "généreux, sincère, bon vivant",
}

# ── Divinités égyptiennes ────────────────────────────────────────
EGYPTE_SENS = {
    "Le Nil": "abondance, intuition, renouveau",
    "Amon-Rê": "leadership, fierté, autorité",
    "Mout": "protection maternelle, loyauté",
    "Geb": "ancrage, stabilité, patience",
    "Osiris": "sagesse, renaissance, justice",
    "Isis": "magie, dévotion, intuition",
    "Thot": "savoir, écriture, stratégie",
    "Horus": "victoire, courage, commandement",
    "Anubis": "gardien des secrets, observation",
    "Seth": "force brute, défi, chaos",
    "Bastet": "joie, charme, créativité",
    "Sekhmet": "puissance guerrière, intensité",
}

# ── Arbres celtes (gaulois) ──────────────────────────────────────
CELTE_SENS = {
    "Chêne": "force, justice, autorité naturelle",
    "Bouleau": "calme, modestie, exemplarité",
    "Olivier": "sagesse, paix, équilibre",
    "Hêtre": "organisation, ambition, bon goût",
    "Noisetier": "savoir, intuition, finesse",
    "Sorbier": "idéalisme, vision, indépendance",
    "Érable": "originalité, réserve, ambition",
    "Noyer": "passion, stratégie, singularité",
    "Peuplier": "sensibilité, hésitation, courage discret",
    "Châtaignier": "justice, honnêteté, détermination",
    "Frêne": "ambition, charme, impulsivité",
    "Charme": "discipline, goût, mesure",
    "Figuier": "sociabilité, sensibilité, indépendance",
    "Pommier": "charme, générosité, amour",
    "If": "résilience, introspection, ténacité",
    "Orme": "noblesse, honnêteté, sens du devoir",
    "Cyprès": "force, adaptabilité, contentement",
    "Micocoulier": "douceur, sagesse tranquille",
    "Pin": "raffinement, robustesse, choix assumés",
    "Saule": "intuition, mélancolie, émotion",
    "Tilleul": "douceur, dévouement, conciliation",
}

# ── Totems amérindiens ───────────────────────────────────────────
TOTEM_SENS = {
    "Oie": "ambition, persévérance",
    "Loutre": "créativité, originalité",
    "Loup": "intuition, indépendance",
    "Faucon": "leadership, décision",
    "Castor": "travail, méthode",
    "Cerf": "charme, vivacité",
    "Pic-vert": "écoute, empathie",
    "Saumon": "confiance, énergie",
    "Ours": "pragmatisme, ancrage",
    "Corbeau": "charme, diplomatie",
    "Serpent": "mystère, spiritualité",
    "Hibou": "sagesse, adaptabilité, discrétion",
}

# ── Glyphes maya (Tzolkin) ───────────────────────────────────────
MAYA_SENS = {
    "Imix": "origine, instinct nourricier",
    "Ik": "souffle, communication",
    "Akbal": "nuit, introspection",
    "Kan": "graine, potentiel, ordre",
    "Chicchan": "force vitale, instinct",
    "Cimi": "transformation, lâcher-prise",
    "Manik": "guérison, coopération",
    "Lamat": "abondance, jeu, harmonie",
    "Muluc": "émotion, eau, offrande",
    "Oc": "loyauté, cœur, fidélité",
    "Chuen": "art, espièglerie",
    "Eb": "chemin, service, humilité",
    "Ben": "principe, autorité, voyage",
    "Ix": "magie, jaguar, discrétion",
    "Men": "vision, aigle, idéal",
    "Cib": "sagesse, mémoire ancestrale",
    "Caban": "intellect, synergie, Terre",
    "Etznab": "vérité tranchante, miroir",
    "Cauac": "tempête, énergie, renouveau",
    "Ahau": "rayonnement, accomplissement",
}

# ── Nakshatras (27 maisons lunaires) ─────────────────────────────
NAKSHATRA_SENS = {
    "Ashwini": "élan, guérison, rapidité",
    "Bharani": "intensité, transformation, endurance",
    "Krittika": "ardeur, détermination, tranchant",
    "Rohini": "charme, fertilité, sensualité",
    "Mrigashira": "quête, curiosité, douceur",
    "Ardra": "orage, rupture, lucidité",
    "Punarvasu": "renouveau, retour, optimisme",
    "Pushya": "nourrir, protéger, stabilité",
    "Ashlesha": "intuition, emprise, mystère",
    "Magha": "héritage, autorité, dignité",
    "Purva Phalguni": "plaisir, créativité, repos",
    "Uttara Phalguni": "alliance, générosité, service",
    "Hasta": "habileté, savoir-faire manuel",
    "Chitra": "éclat, art, architecture",
    "Swati": "indépendance, souplesse, négoce",
    "Vishakha": "ambition, détermination, but",
    "Anuradha": "amitié, dévotion, discipline",
    "Jyeshtha": "pouvoir, protection, ancienneté",
    "Mula": "racine, recherche, déracinement",
    "Purva Ashadha": "invincibilité, conviction",
    "Uttara Ashadha": "victoire durable, intégrité",
    "Shravana": "écoute, savoir, connexion",
    "Dhanishta": "rythme, abondance, musique",
    "Shatabhisha": "guérison, mystère, indépendance",
    "Purva Bhadrapada": "intensité, idéal, ascèse",
    "Uttara Bhadrapada": "profondeur, sagesse, calme",
    "Revati": "douceur, protection, achèvement",
}

# ── Nombres (chemin de vie & expression) ─────────────────────────
NOMBRE_SENS = {
    1: "indépendance, initiative, leadership",
    2: "coopération, sensibilité, diplomatie",
    3: "expression, créativité, sociabilité",
    4: "travail, ordre, stabilité",
    5: "liberté, changement, aventure",
    6: "responsabilité, harmonie, soin des autres",
    7: "introspection, analyse, spiritualité",
    8: "pouvoir, réussite matérielle, ambition",
    9: "altruisme, idéal, accomplissement",
    11: "inspiration, intuition (nombre maître)",
    22: "bâtisseur, vision concrète (nombre maître)",
    33: "amour, enseignement, service (nombre maître)",
}


# ══════════════════════════════════════════════════════════════════
# i18n anglais — traduction d'AFFICHAGE uniquement (S194). Le calcul
# (traditions.py) reste en français en interne (clés canoniques, jamais
# affichées telles quelles) ; ces tables ne servent qu'à produire la
# sortie de `expliquer()` en anglais quand `langue="en"`. Les noms Maya
# (Tzolkin) et Nakshatra (sanskrit) ne sont PAS traduits : c'est aussi
# l'usage dans les sources anglophones.
# ══════════════════════════════════════════════════════════════════

NOMS_EN = {   # traduction du LIBELLÉ (valeur affichée), pas de la clé de calcul
    # Signes du zodiaque
    "Bélier": "Aries", "Taureau": "Taurus", "Gémeaux": "Gemini", "Cancer": "Cancer",
    "Lion": "Leo", "Vierge": "Virgo", "Balance": "Libra", "Scorpion": "Scorpio",
    "Sagittaire": "Sagittarius", "Capricorne": "Capricorn", "Verseau": "Aquarius",
    "Poissons": "Pisces",
    # Animaux chinois
    "Rat": "Rat", "Buffle": "Ox", "Tigre": "Tiger", "Lapin": "Rabbit", "Dragon": "Dragon",
    "Serpent": "Snake", "Cheval": "Horse", "Chèvre": "Goat", "Singe": "Monkey",
    "Coq": "Rooster", "Chien": "Dog", "Cochon": "Pig",
    # Divinités égyptiennes
    "Le Nil": "The Nile", "Amon-Rê": "Amun-Ra", "Mout": "Mut", "Geb": "Geb",
    "Osiris": "Osiris", "Isis": "Isis", "Thot": "Thoth", "Horus": "Horus",
    "Anubis": "Anubis", "Seth": "Set", "Bastet": "Bastet", "Sekhmet": "Sekhmet",
    # Arbres celtes
    "Chêne": "Oak", "Bouleau": "Birch", "Olivier": "Olive", "Hêtre": "Beech",
    "Noisetier": "Hazel", "Sorbier": "Rowan", "Érable": "Maple", "Noyer": "Walnut",
    "Peuplier": "Poplar", "Châtaignier": "Chestnut", "Frêne": "Ash", "Charme": "Hornbeam",
    "Figuier": "Fig", "Pommier": "Apple", "If": "Yew", "Orme": "Elm", "Cyprès": "Cypress",
    "Micocoulier": "Hackberry", "Pin": "Pine", "Saule": "Willow", "Tilleul": "Linden",
    # Totems amérindiens (noms distincts des animaux chinois homonymes, même table)
    "Oie": "Goose", "Loutre": "Otter", "Loup": "Wolf", "Faucon": "Falcon",
    "Castor": "Beaver", "Cerf": "Deer", "Pic-vert": "Woodpecker", "Saumon": "Salmon",
    "Ours": "Bear", "Corbeau": "Raven", "Hibou": "Owl",
    # Éléments (occidentaux + chinois)
    "Feu": "Fire", "Terre": "Earth", "Air": "Air", "Eau": "Water",
    "Métal": "Metal", "Bois": "Wood",
}

SIGNES_SENS_EN = {
    "Bélier": "drive, courage, initiative, impatience",
    "Taureau": "tenacity, sensuality, groundedness, stubbornness",
    "Gémeaux": "curiosity, quick-wittedness, communication, scatteredness",
    "Cancer": "sensitivity, protectiveness, memory, reserve",
    "Lion": "pride, radiance, generosity, ego",
    "Vierge": "analysis, rigor, sense of service, exactingness",
    "Balance": "harmony, diplomacy, aesthetics, indecision",
    "Scorpion": "intensity, secrecy, transformation, distrust",
    "Sagittaire": "freedom, faith, adventure, excess",
    "Capricorne": "ambition, discipline, patience, austerity",
    "Verseau": "originality, ideals, independence, detachment",
    "Poissons": "intuition, compassion, dreaminess, escapism",
}

ROLE_PLACEMENT_EN = {
    "soleil": "core, ego",
    "lune": "emotions, secret garden",
    "ascendant": "appearance, social mask",
    "vedique": "sidereal reading, karma",
}

CHINOIS_SENS_EN = {
    "Rat": "quick-witted, resourceful, charming",
    "Buffle": "enduring, reliable, stubborn",
    "Tigre": "bold, passionate, rebellious",
    "Lapin": "gentle, cautious, diplomatic",
    "Dragon": "charismatic, ambitious, proud",
    "Serpent": "wise, intuitive, secretive",
    "Cheval": "energetic, free, impatient",
    "Chèvre": "creative, sensitive, dreamy",
    "Singe": "clever, inventive, playful",
    "Coq": "frank, organized, proud",
    "Chien": "loyal, fair, anxious",
    "Cochon": "generous, sincere, good-natured",
}

EGYPTE_SENS_EN = {
    "Le Nil": "abundance, intuition, renewal",
    "Amon-Rê": "leadership, pride, authority",
    "Mout": "maternal protection, loyalty",
    "Geb": "groundedness, stability, patience",
    "Osiris": "wisdom, rebirth, justice",
    "Isis": "magic, devotion, intuition",
    "Thot": "knowledge, writing, strategy",
    "Horus": "victory, courage, command",
    "Anubis": "keeper of secrets, watchfulness",
    "Seth": "raw force, defiance, chaos",
    "Bastet": "joy, charm, creativity",
    "Sekhmet": "warrior power, intensity",
}

CELTE_SENS_EN = {
    "Chêne": "strength, justice, natural authority",
    "Bouleau": "calm, modesty, exemplarity",
    "Olivier": "wisdom, peace, balance",
    "Hêtre": "organization, ambition, good taste",
    "Noisetier": "knowledge, intuition, finesse",
    "Sorbier": "idealism, vision, independence",
    "Érable": "originality, reserve, ambition",
    "Noyer": "passion, strategy, singularity",
    "Peuplier": "sensitivity, hesitation, quiet courage",
    "Châtaignier": "justice, honesty, determination",
    "Frêne": "ambition, charm, impulsiveness",
    "Charme": "discipline, taste, restraint",
    "Figuier": "sociability, sensitivity, independence",
    "Pommier": "charm, generosity, love",
    "If": "resilience, introspection, tenacity",
    "Orme": "nobility, honesty, sense of duty",
    "Cyprès": "strength, adaptability, contentment",
    "Micocoulier": "gentleness, quiet wisdom",
    "Pin": "refinement, robustness, deliberate choices",
    "Saule": "intuition, melancholy, emotion",
    "Tilleul": "gentleness, devotion, conciliation",
}

TOTEM_SENS_EN = {
    "Oie": "ambition, perseverance",
    "Loutre": "creativity, originality",
    "Loup": "intuition, independence",
    "Faucon": "leadership, decisiveness",
    "Castor": "work ethic, method",
    "Cerf": "charm, liveliness",
    "Pic-vert": "listening, empathy",
    "Saumon": "confidence, energy",
    "Ours": "pragmatism, groundedness",
    "Corbeau": "charm, diplomacy",
    "Serpent": "mystery, spirituality",
    "Hibou": "wisdom, adaptability, discretion",
}

MAYA_SENS_EN = {   # noms de glyphes inchangés (Imix, Ik…)
    "Imix": "origin, nurturing instinct",
    "Ik": "breath, communication",
    "Akbal": "night, introspection",
    "Kan": "seed, potential, order",
    "Chicchan": "life force, instinct",
    "Cimi": "transformation, letting go",
    "Manik": "healing, cooperation",
    "Lamat": "abundance, play, harmony",
    "Muluc": "emotion, water, offering",
    "Oc": "loyalty, heart, faithfulness",
    "Chuen": "art, playfulness",
    "Eb": "path, service, humility",
    "Ben": "principle, authority, journey",
    "Ix": "magic, jaguar, discretion",
    "Men": "vision, eagle, ideal",
    "Cib": "wisdom, ancestral memory",
    "Caban": "intellect, synergy, Earth",
    "Etznab": "cutting truth, mirror",
    "Cauac": "storm, energy, renewal",
    "Ahau": "radiance, accomplishment",
}

NAKSHATRA_SENS_EN = {   # noms sanskrits inchangés (Ashwini, Bharani…)
    "Ashwini": "drive, healing, speed",
    "Bharani": "intensity, transformation, endurance",
    "Krittika": "ardor, determination, sharpness",
    "Rohini": "charm, fertility, sensuality",
    "Mrigashira": "quest, curiosity, gentleness",
    "Ardra": "storm, rupture, lucidity",
    "Punarvasu": "renewal, return, optimism",
    "Pushya": "nurture, protect, stability",
    "Ashlesha": "intuition, grip, mystery",
    "Magha": "heritage, authority, dignity",
    "Purva Phalguni": "pleasure, creativity, rest",
    "Uttara Phalguni": "alliance, generosity, service",
    "Hasta": "skill, craftsmanship",
    "Chitra": "brilliance, art, architecture",
    "Swati": "independence, flexibility, trade",
    "Vishakha": "ambition, determination, purpose",
    "Anuradha": "friendship, devotion, discipline",
    "Jyeshtha": "power, protection, seniority",
    "Mula": "root, search, uprooting",
    "Purva Ashadha": "invincibility, conviction",
    "Uttara Ashadha": "lasting victory, integrity",
    "Shravana": "listening, knowledge, connection",
    "Dhanishta": "rhythm, abundance, music",
    "Shatabhisha": "healing, mystery, independence",
    "Purva Bhadrapada": "intensity, ideal, asceticism",
    "Uttara Bhadrapada": "depth, wisdom, calm",
    "Revati": "gentleness, protection, completion",
}

NOMBRE_SENS_EN = {
    1: "independence, initiative, leadership",
    2: "cooperation, sensitivity, diplomacy",
    3: "expression, creativity, sociability",
    4: "work, order, stability",
    5: "freedom, change, adventure",
    6: "responsibility, harmony, care for others",
    7: "introspection, analysis, spirituality",
    8: "power, material success, ambition",
    9: "altruism, ideals, accomplishment",
    11: "inspiration, intuition (master number)",
    22: "builder, concrete vision (master number)",
    33: "love, teaching, service (master number)",
}

# Libellés de section (`cle`) et de `role`, par langue.
_CLE_EN = {
    "Soleil": "Sun", "Lune": "Moon", "Ascendant": "Ascendant",
    "Astrologie chinoise": "Chinese Astrology", "Animal de l'heure": "Hour Animal",
    "Védique (rashi)": "Vedic (Rashi)", "Nakshatra": "Nakshatra", "Égypte": "Egyptian",
    "Celte": "Celtic", "Totem amérindien": "Native American Totem",
    "Maya (Tzolkin)": "Maya (Tzolkin)", "Chemin de vie": "Life Path",
    "Expression (nom)": "Expression (Name)",
}
_ROLE_EN = {
    "moi social": "social self", "moi profond": "inner self",
    "divinité tutélaire": "tutelary deity", "arbre protecteur": "protective tree",
    "animal totem": "totem animal", "destinée": "destiny",
    "talents, tempérament": "talents, temperament", "maison lunaire": "lunar house",
}


def _entree(cle: str, valeur: str, sens: str, role: str = "") -> dict:
    return {"cle": cle, "valeur": valeur, "sens": sens, "role": role}


def expliquer(trad: dict, langue: str = "fr") -> list:
    """Empreinte LISIBLE : pour chaque tradition calculée, {clé, valeur, sens, rôle}.

    Ordonnée comme on la lit (Soleil → Lune → Ascendant → … → numérologie). Une section
    absente est simplement omise. C'est ce que le front affiche sous le portrait.

    `langue="fr"` (défaut) : comportement STRICTEMENT identique à avant l'i18n (S194).
    `langue="en"` : mêmes clés JSON, valeurs traduites (noms de signes/animaux/tables de
    sens en anglais ; Maya et Nakshatra gardent leurs noms d'origine, comme en anglais)."""
    en = (langue or "fr").lower().startswith("en")

    def nom(v: str) -> str:
        return NOMS_EN.get(v, v) if en else v

    signes_sens = SIGNES_SENS_EN if en else SIGNES_SENS
    chinois_sens = CHINOIS_SENS_EN if en else CHINOIS_SENS
    egypte_sens = EGYPTE_SENS_EN if en else EGYPTE_SENS
    celte_sens = CELTE_SENS_EN if en else CELTE_SENS
    totem_sens = TOTEM_SENS_EN if en else TOTEM_SENS
    maya_sens = MAYA_SENS_EN if en else MAYA_SENS
    nakshatra_sens = NAKSHATRA_SENS_EN if en else NAKSHATRA_SENS
    nombre_sens = NOMBRE_SENS_EN if en else NOMBRE_SENS
    role_placement = ROLE_PLACEMENT_EN if en else ROLE_PLACEMENT

    def cle(c: str) -> str:
        return _CLE_EN.get(c, c) if en else c

    def role(r: str) -> str:
        return _ROLE_EN.get(r, r) if en else r

    out: list = []

    sol = trad.get("signe_solaire") or {}
    if sol.get("nom"):
        out.append(_entree(cle("Soleil"), f"{nom(sol['nom'])} {sol.get('symbole','')}".strip(),
                            signes_sens.get(sol["nom"], ""), role_placement["soleil"]))
    lun = trad.get("signe_lunaire") or {}
    if lun.get("signe"):
        out.append(_entree(cle("Lune"), f"{nom(lun['signe'])} {lun.get('symbole','')}".strip(),
                            signes_sens.get(lun["signe"], ""), role_placement["lune"]))
    asc = (trad.get("theme_astral") or {}).get("ascendant") or {}
    if asc.get("signe"):
        out.append(_entree(cle("Ascendant"), f"{nom(asc['signe'])} {asc.get('symbole','')}".strip(),
                            signes_sens.get(asc["signe"], ""), role_placement["ascendant"]))
    chi = trad.get("signe_chinois") or {}
    if chi.get("animal"):
        elt = nom(chi.get("element", "")) if en else chi.get("element", "")
        liaison = "of" if en else "de"
        out.append(_entree(cle("Astrologie chinoise"), f"{nom(chi['animal'])} {liaison} {elt}".strip(),
                            chinois_sens.get(chi["animal"], ""), role("moi social")))
    ah = trad.get("animal_heure") or {}
    if ah.get("animal"):
        out.append(_entree(cle("Animal de l'heure"), nom(ah["animal"]),
                            chinois_sens.get(ah["animal"], ""), role("moi profond")))
    ved = trad.get("vedique") or {}
    if ved.get("rashi"):
        out.append(_entree(cle("Védique (rashi)"), nom(ved["rashi"]),
                            signes_sens.get(ved["rashi"], ""), role_placement["vedique"]))
    nak = trad.get("nakshatra") or {}
    if nak.get("nakshatra"):
        out.append(_entree(cle("Nakshatra"), f"{nak['nakshatra']} (pada {nak.get('pada','?')})",
                            nakshatra_sens.get(nak["nakshatra"], ""), role("maison lunaire")))
    if trad.get("egyptien"):
        out.append(_entree(cle("Égypte"), nom(trad["egyptien"]), egypte_sens.get(trad["egyptien"], ""),
                            role("divinité tutélaire")))
    if trad.get("celte"):
        out.append(_entree(cle("Celte"), nom(trad["celte"]), celte_sens.get(trad["celte"], ""),
                            role("arbre protecteur")))
    if trad.get("amerindien"):
        out.append(_entree(cle("Totem amérindien"), nom(trad["amerindien"]),
                            totem_sens.get(trad["amerindien"], ""), role("animal totem")))
    maya = trad.get("maya") or {}
    if maya.get("glyphe"):
        tonalite_label = "tone" if en else "ton"
        out.append(_entree(cle("Maya (Tzolkin)"), f"{maya.get('tonalite','')} {maya['glyphe']}".strip(),
                            maya_sens.get(maya["glyphe"], ""),
                            f"{tonalite_label} {maya.get('tonalite','?')}/13"))
    if isinstance(trad.get("chemin_de_vie"), int):
        out.append(_entree(cle("Chemin de vie"), str(trad["chemin_de_vie"]),
                            nombre_sens.get(trad["chemin_de_vie"], ""), role("destinée")))
    expr = (trad.get("numerologie_nom") or {}).get("expression")
    if isinstance(expr, int):
        out.append(_entree(cle("Expression (nom)"), str(expr),
                            nombre_sens.get(expr, ""), role("talents, tempérament")))
    return out
