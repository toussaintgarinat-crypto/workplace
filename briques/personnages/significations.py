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


def _entree(cle: str, valeur: str, sens: str, role: str = "") -> dict:
    return {"cle": cle, "valeur": valeur, "sens": sens, "role": role}


def expliquer(trad: dict) -> list:
    """Empreinte LISIBLE : pour chaque tradition calculée, {clé, valeur, sens, rôle}.

    Ordonnée comme on la lit (Soleil → Lune → Ascendant → … → numérologie). Une section
    absente est simplement omise. C'est ce que le front affiche sous le portrait."""
    out: list = []

    sol = trad.get("signe_solaire") or {}
    if sol.get("nom"):
        out.append(_entree("Soleil", f"{sol['nom']} {sol.get('symbole','')}".strip(),
                            SIGNES_SENS.get(sol["nom"], ""), ROLE_PLACEMENT["soleil"]))
    lun = trad.get("signe_lunaire") or {}
    if lun.get("signe"):
        out.append(_entree("Lune", f"{lun['signe']} {lun.get('symbole','')}".strip(),
                            SIGNES_SENS.get(lun["signe"], ""), ROLE_PLACEMENT["lune"]))
    asc = (trad.get("theme_astral") or {}).get("ascendant") or {}
    if asc.get("signe"):
        out.append(_entree("Ascendant", f"{asc['signe']} {asc.get('symbole','')}".strip(),
                            SIGNES_SENS.get(asc["signe"], ""), ROLE_PLACEMENT["ascendant"]))
    chi = trad.get("signe_chinois") or {}
    if chi.get("animal"):
        out.append(_entree("Astrologie chinoise", f"{chi['animal']} de {chi.get('element','')}".strip(),
                            CHINOIS_SENS.get(chi["animal"], ""), "moi social"))
    ah = trad.get("animal_heure") or {}
    if ah.get("animal"):
        out.append(_entree("Animal de l'heure", ah["animal"],
                            CHINOIS_SENS.get(ah["animal"], ""), "moi profond"))
    ved = trad.get("vedique") or {}
    if ved.get("rashi"):
        out.append(_entree("Védique (rashi)", ved["rashi"],
                            SIGNES_SENS.get(ved["rashi"], ""), ROLE_PLACEMENT["vedique"]))
    nak = trad.get("nakshatra") or {}
    if nak.get("nakshatra"):
        out.append(_entree("Nakshatra", f"{nak['nakshatra']} (pada {nak.get('pada','?')})",
                            NAKSHATRA_SENS.get(nak["nakshatra"], ""), "maison lunaire"))
    if trad.get("egyptien"):
        out.append(_entree("Égypte", trad["egyptien"], EGYPTE_SENS.get(trad["egyptien"], ""),
                            "divinité tutélaire"))
    if trad.get("celte"):
        out.append(_entree("Celte", trad["celte"], CELTE_SENS.get(trad["celte"], ""),
                            "arbre protecteur"))
    if trad.get("amerindien"):
        out.append(_entree("Totem amérindien", trad["amerindien"],
                            TOTEM_SENS.get(trad["amerindien"], ""), "animal totem"))
    maya = trad.get("maya") or {}
    if maya.get("glyphe"):
        out.append(_entree("Maya (Tzolkin)", f"{maya.get('tonalite','')} {maya['glyphe']}".strip(),
                            MAYA_SENS.get(maya["glyphe"], ""), f"ton {maya.get('tonalite','?')}/13"))
    if isinstance(trad.get("chemin_de_vie"), int):
        out.append(_entree("Chemin de vie", str(trad["chemin_de_vie"]),
                            NOMBRE_SENS.get(trad["chemin_de_vie"], ""), "destinée"))
    expr = (trad.get("numerologie_nom") or {}).get("expression")
    if isinstance(expr, int):
        out.append(_entree("Expression (nom)", str(expr),
                            NOMBRE_SENS.get(expr, ""), "talents, tempérament"))
    return out
