"""Synthèse holistique — le « cœur » du moteur de génération de personnages (S49).

Deux modes, tous deux PURS (sans état, sans réseau, sans horloge) :

  • DESCENDANT (`portrait`) : les traditions calculées (traditions.calculer) sont traduites
    en TAGS psychologiques pondérés, agrégés en STATS (Charisme, Combativité, …), d'où l'on
    dérive un ARCHÉTYPE, des forces / une faiblesse, et une PIERRE D'ÉQUILIBRAGE choisie en
    SORTIE selon la faiblesse (gemmologie compensatoire), puis un récit de fiche.

  • MONTANT (`recherche_inverse`) : à partir d'une description libre de caractère, on infère
    le vecteur de stats visé, puis on cherche les signes / nombres / dates qui le maximisent.
    La non-unicité est assumée : on propose « UNE date qui matche », pas « LA ».

Le dictionnaire de tags est la même donnée dans les deux sens (descendant l'agrège,
montant l'inverse). L'interprétation reste du DIVERTISSEMENT — c'est le calcul, pas un fait.
"""
from __future__ import annotations

import difflib
import re
import unicodedata
from datetime import date, timedelta

import significations as SIG
import traditions as T


# ── Axes de personnalité (stats) ─────────────────────────────────
STATS = ["Charisme", "Combativité", "Sagesse", "Créativité",
         "Discrétion", "Stabilité", "Émotivité", "Énergie"]

# Contribution (tags pondérés) de chaque SIGNE solaire aux stats.
_TAGS_SIGNE = {
    "Bélier": {"Combativité": 3, "Énergie": 3, "Charisme": 1},
    "Taureau": {"Stabilité": 3, "Discrétion": 1, "Sagesse": 1},
    "Gémeaux": {"Créativité": 2, "Charisme": 2, "Énergie": 1},
    "Cancer": {"Émotivité": 3, "Sagesse": 1, "Discrétion": 1},
    "Lion": {"Charisme": 3, "Énergie": 2, "Combativité": 1},
    "Vierge": {"Sagesse": 2, "Stabilité": 2, "Discrétion": 2},
    "Balance": {"Charisme": 2, "Créativité": 1, "Stabilité": 1},
    "Scorpion": {"Combativité": 2, "Discrétion": 3, "Émotivité": 1},
    "Sagittaire": {"Énergie": 2, "Sagesse": 2, "Charisme": 1},
    "Capricorne": {"Stabilité": 3, "Combativité": 1, "Discrétion": 1},
    "Verseau": {"Créativité": 3, "Sagesse": 1, "Discrétion": 1},
    "Poissons": {"Émotivité": 3, "Créativité": 2, "Sagesse": 1},
}

# Contribution de l'ÉLÉMENT (renforce une tendance).
_TAGS_ELEMENT = {
    "Feu": {"Énergie": 2, "Combativité": 1},
    "Terre": {"Stabilité": 2, "Discrétion": 1},
    "Air": {"Créativité": 2, "Charisme": 1},
    "Eau": {"Émotivité": 2, "Sagesse": 1},
}

# Contribution du CHEMIN DE VIE (numérologie ; nombres maîtres inclus).
_TAGS_NOMBRE = {
    1: {"Combativité": 2, "Charisme": 1}, 2: {"Émotivité": 2, "Discrétion": 1},
    3: {"Créativité": 3, "Charisme": 1}, 4: {"Stabilité": 3},
    5: {"Énergie": 2, "Créativité": 1}, 6: {"Émotivité": 2, "Sagesse": 1},
    7: {"Sagesse": 3, "Discrétion": 1}, 8: {"Combativité": 2, "Charisme": 1, "Stabilité": 1},
    9: {"Sagesse": 2, "Émotivité": 1, "Charisme": 1},
    11: {"Sagesse": 2, "Créativité": 2}, 22: {"Stabilité": 2, "Sagesse": 1, "Charisme": 1},
    33: {"Émotivité": 2, "Sagesse": 2},
}

# Contribution de l'ANIMAL chinois.
_TAGS_CHINOIS = {
    "Rat": {"Créativité": 1, "Charisme": 1, "Discrétion": 1},
    "Buffle": {"Stabilité": 2, "Combativité": 1}, "Tigre": {"Combativité": 2, "Charisme": 1, "Énergie": 1},
    "Lapin": {"Discrétion": 2, "Émotivité": 1}, "Dragon": {"Charisme": 2, "Énergie": 2},
    "Serpent": {"Sagesse": 2, "Discrétion": 2}, "Cheval": {"Énergie": 3, "Charisme": 1},
    "Chèvre": {"Créativité": 2, "Émotivité": 1}, "Singe": {"Créativité": 2, "Charisme": 1, "Énergie": 1},
    "Coq": {"Discrétion": 1, "Stabilité": 1, "Charisme": 1},
    "Chien": {"Stabilité": 1, "Sagesse": 1, "Émotivité": 1},
    "Cochon": {"Émotivité": 1, "Stabilité": 1, "Sagesse": 1},
}

# Contribution des 12 divinités ÉGYPTIENNES.
_TAGS_EGYPTE = {
    "Le Nil": {"Émotivité": 1, "Stabilité": 1, "Sagesse": 1}, "Amon-Rê": {"Charisme": 2, "Combativité": 1},
    "Mout": {"Émotivité": 2, "Stabilité": 1}, "Geb": {"Stabilité": 2, "Discrétion": 1},
    "Osiris": {"Sagesse": 2, "Charisme": 1}, "Isis": {"Sagesse": 1, "Émotivité": 2},
    "Thot": {"Sagesse": 2, "Créativité": 1}, "Horus": {"Combativité": 2, "Charisme": 1},
    "Anubis": {"Discrétion": 3, "Sagesse": 1}, "Seth": {"Combativité": 3, "Énergie": 1},
    "Bastet": {"Charisme": 2, "Créativité": 1}, "Sekhmet": {"Combativité": 2, "Énergie": 2},
}

# Contribution des 12 totems AMÉRINDIENS.
_TAGS_TOTEM = {
    "Oie": {"Combativité": 1, "Stabilité": 2}, "Loutre": {"Créativité": 2, "Charisme": 1},
    "Loup": {"Sagesse": 2, "Discrétion": 1}, "Faucon": {"Charisme": 1, "Combativité": 2, "Énergie": 1},
    "Castor": {"Stabilité": 3}, "Cerf": {"Charisme": 2, "Énergie": 1},
    "Pic-vert": {"Émotivité": 3}, "Saumon": {"Énergie": 2, "Charisme": 1},
    "Ours": {"Stabilité": 2, "Sagesse": 1}, "Corbeau": {"Charisme": 2, "Créativité": 1},
    "Serpent": {"Sagesse": 2, "Discrétion": 2}, "Hibou": {"Sagesse": 2, "Discrétion": 1},
}

# Contribution des 21 arbres CELTES (gaulois).
_TAGS_CELTE = {
    "Chêne": {"Combativité": 1, "Stabilité": 1, "Charisme": 1}, "Bouleau": {"Stabilité": 1, "Sagesse": 1, "Discrétion": 1},
    "Olivier": {"Sagesse": 2, "Charisme": 1}, "Hêtre": {"Stabilité": 1, "Charisme": 1, "Combativité": 1},
    "Noisetier": {"Sagesse": 2, "Créativité": 1}, "Sorbier": {"Créativité": 1, "Sagesse": 1, "Discrétion": 1},
    "Érable": {"Créativité": 1, "Discrétion": 1, "Énergie": 1}, "Noyer": {"Combativité": 1, "Sagesse": 1, "Charisme": 1},
    "Peuplier": {"Émotivité": 2, "Discrétion": 1}, "Châtaignier": {"Sagesse": 1, "Combativité": 1, "Stabilité": 1},
    "Frêne": {"Charisme": 1, "Énergie": 1, "Créativité": 1}, "Charme": {"Stabilité": 2, "Discrétion": 1},
    "Figuier": {"Charisme": 1, "Émotivité": 1, "Créativité": 1}, "Pommier": {"Charisme": 2, "Émotivité": 1},
    "If": {"Discrétion": 2, "Stabilité": 1}, "Orme": {"Stabilité": 1, "Charisme": 1, "Sagesse": 1},
    "Cyprès": {"Stabilité": 2, "Énergie": 1}, "Micocoulier": {"Sagesse": 1, "Émotivité": 1},
    "Pin": {"Stabilité": 1, "Combativité": 1, "Sagesse": 1}, "Saule": {"Émotivité": 2, "Sagesse": 1},
    "Tilleul": {"Émotivité": 2, "Stabilité": 1},
}

# Contribution des 20 glyphes MAYA (Tzolkin), pondération légère.
_TAGS_MAYA = {
    "Imix": {"Émotivité": 1, "Énergie": 1}, "Ik": {"Créativité": 1, "Charisme": 1},
    "Akbal": {"Discrétion": 1, "Sagesse": 1}, "Kan": {"Stabilité": 1, "Sagesse": 1},
    "Chicchan": {"Énergie": 1, "Combativité": 1}, "Cimi": {"Sagesse": 1, "Discrétion": 1},
    "Manik": {"Émotivité": 1, "Stabilité": 1}, "Lamat": {"Créativité": 1, "Charisme": 1},
    "Muluc": {"Émotivité": 2}, "Oc": {"Stabilité": 1, "Émotivité": 1},
    "Chuen": {"Créativité": 2}, "Eb": {"Stabilité": 1, "Sagesse": 1},
    "Ben": {"Charisme": 1, "Combativité": 1}, "Ix": {"Discrétion": 2, "Sagesse": 1},
    "Men": {"Sagesse": 1, "Créativité": 1}, "Cib": {"Sagesse": 2},
    "Caban": {"Sagesse": 1, "Stabilité": 1}, "Etznab": {"Combativité": 1, "Discrétion": 1},
    "Cauac": {"Énergie": 2}, "Ahau": {"Charisme": 2, "Sagesse": 1},
}

# Archétypes : chacun signé par ses 3 stats dominantes (le portrait choisit le plus proche).
_ARCHETYPES = [
    ("Le Stratège Solitaire", ("Discrétion", "Sagesse", "Combativité")),
    ("Le Meneur Charismatique", ("Charisme", "Combativité", "Énergie")),
    ("Le Sage Contemplatif", ("Sagesse", "Discrétion", "Stabilité")),
    ("L'Artiste Visionnaire", ("Créativité", "Émotivité", "Charisme")),
    ("Le Gardien Loyal", ("Stabilité", "Émotivité", "Sagesse")),
    ("L'Aventurier Indomptable", ("Énergie", "Combativité", "Charisme")),
    ("Le Diplomate Sensible", ("Charisme", "Émotivité", "Sagesse")),
    ("Le Bâtisseur Méthodique", ("Stabilité", "Combativité", "Discrétion")),
    ("L'Âme Empathique", ("Émotivité", "Sagesse", "Créativité")),
    ("L'Électron Libre", ("Créativité", "Énergie", "Discrétion")),
]

# Pierre d'équilibrage : choisie selon la stat la PLUS FAIBLE (gemmologie en SORTIE).
_EQUILIBRAGE = {
    "Charisme": ("Citrine", "rayonnement et confiance en soi"),
    "Combativité": ("Cornaline", "courage et élan d'action"),
    "Sagesse": ("Améthyste", "clarté mentale et intuition"),
    "Créativité": ("Apatite", "inspiration et liberté d'expression"),
    "Discrétion": ("Onyx", "ancrage et maîtrise de soi"),
    "Stabilité": ("Hématite", "enracinement et constance"),
    "Émotivité": ("Quartz rose", "ouverture du cœur et douceur"),
    "Énergie": ("Œil-de-tigre", "vitalité et dynamisme"),
}

# ══════════════════════════════════════════════════════════════════
# i18n anglais — traduction d'AFFICHAGE uniquement (S194). Le calcul
# (stats_depuis_traditions, _archetype, tables _TAGS_*) reste en français
# en interne (clés canoniques) ; ces tables ne servent qu'à produire la
# sortie de `portrait()`/`_recit()` en anglais quand `langue="en"`.
# ══════════════════════════════════════════════════════════════════
STATS_LABEL_EN = {
    "Charisme": "Charisma", "Combativité": "Drive", "Sagesse": "Wisdom",
    "Créativité": "Creativity", "Discrétion": "Discretion", "Stabilité": "Stability",
    "Émotivité": "Emotionality", "Énergie": "Energy",
}

_ARCHETYPES_EN = {
    "Le Stratège Solitaire": "The Solitary Strategist",
    "Le Meneur Charismatique": "The Charismatic Leader",
    "Le Sage Contemplatif": "The Contemplative Sage",
    "L'Artiste Visionnaire": "The Visionary Artist",
    "Le Gardien Loyal": "The Loyal Guardian",
    "L'Aventurier Indomptable": "The Untamed Adventurer",
    "Le Diplomate Sensible": "The Sensitive Diplomat",
    "Le Bâtisseur Méthodique": "The Methodical Builder",
    "L'Âme Empathique": "The Empathic Soul",
    "L'Électron Libre": "The Free Spirit",
}

_EQUILIBRAGE_EN = {
    "Charisme": ("Citrine", "radiance and self-confidence"),
    "Combativité": ("Carnelian", "courage and drive to act"),
    "Sagesse": ("Amethyst", "mental clarity and intuition"),
    "Créativité": ("Apatite", "inspiration and freedom of expression"),
    "Discrétion": ("Onyx", "grounding and self-mastery"),
    "Stabilité": ("Hematite", "rootedness and constancy"),
    "Émotivité": ("Rose Quartz", "openness of heart and gentleness"),
    "Énergie": ("Tiger's Eye", "vitality and dynamism"),
}

# Champs lexicaux du mode montant : pour chaque stat, une FAMILLE de radicaux courts
# (normalisés, sans accent). Les radicaux sont des PRÉFIXES → ils captent les variantes
# (manipul → manipuler/manipulateur/manipulation). Traits « sombres » inclus. Un mot
# hors liste est rattrapé par similarité (cibler_stats), pour éviter les manques.
_LEXIQUE = {
    "Charisme": ["charism", "charm", "leader", "social", "sociab", "rayonn", "magnet", "seduc",
                 "seduis", "meneur", "popul", "narciss", "egocentr", "vanit", "orgueil", "fier",
                 "arrogan", "pretenti", "extraver", "theatral", "histrion", "exhib", "flamboy",
                 "eloquen", "persuas", "influen", "prestanc", "mondain", "expansif", "assuranc",
                 "confian", "eclatan", "solaire", "aura"],
    "Combativité": ["coler", "guerr", "combat", "agress", "batail", "battan", "fonceu", "bagarr",
                    "competit", "violen", "fougu", "impuls", "domin", "autorit", "tyran", "cruel",
                    "brutal", "vindicat", "rancun", "impitoy", "hargn", "belliq", "conquer", "rebell",
                    "provoc", "courag", "audac", "pugnac", "teign", "irascib", "emport", "venge",
                    "lutteur", "ambiti", "determin", "offensif", "fonce", "sanguin", "fureur"],
    "Sagesse": ["spirit", "sage", "reflech", "intuit", "philosoph", "profond", "mystiq", "medit",
                "lucid", "clairvoy", "intellig", "cultiv", "erudit", "perspic", "rationn", "savant",
                "penseur", "eclair", "contempl", "zen", "eveil", "conscien", "introspec", "analyt",
                "ponder", "raisonn", "mature", "percept", "illumin", "ascet", "devot", "sagac"],
    "Créativité": ["creati", "artist", "imaginat", "imaginai", "invent", "original", "reveur", "vision",
                   "innov", "fantais", "excentr", "fantasq", "atypiq", "bohem", "poet", "inspir",
                   "ludiq", "espiegl", "novateur", "facetieux", "ingenieux", "creativ", "fantaisist"],
    "Discrétion": ["discret", "secre", "solitair", "reserv", "mysterieu", "introver", "silencieux",
                   "pruden", "calme", "renferm", "manipul", "pervers", "calculat", "sournois", "menteur",
                   "hypocrit", "fourbe", "ruse", "machiavel", "strateg", "cyniq", "froid", "distan",
                   "dissimul", "intrigan", "mefian", "tacitur", "observ", "cachott", "evasif",
                   "impenetr", "retir", "sauvage", "asocial", "fuyan", "espion", "calculateur"],
    "Stabilité": ["stable", "fiable", "disciplin", "pose", "organis", "methodi", "rigoureux", "loyal",
                  "constan", "patien", "tenace", "obstin", "perfectionn", "conscienci", "ponctuel",
                  "serieux", "responsab", "perseveran", "fidel", "solide", "ancr", "pragmati", "structur",
                  "ordonn", "regulier", "endur", "robust", "equilibr", "sobre", "mesur", "tradition",
                  "conservat", "casanier", "droit", "integr", "honnet", "stabilit"],
    "Émotivité": ["emotif", "emotion", "sensib", "empath", "passionn", "tendre", "affect", "doux",
                  "vulnerab", "compatiss", "compassion", "romanti", "jalou", "susceptib", "anxieux",
                  "angoiss", "depress", "lunatiq", "hypersensib", "melancoli", "nerveux", "craintif",
                  "timide", "sentiment", "fragile", "chaleureux", "aiman", "bienveillan", "genereux",
                  "devou", "attentionn", "larmoyan", "tourment", "cyclothy", "attach", "pudiq", "ombrag"],
    "Énergie": ["energi", "dynami", "actif", "aventur", "vif", "vital", "enthousias", "explor",
                "infatigab", "exuberan", "hyperactif", "impatien", "intrepid", "remuan", "petillan",
                "vivac", "bouillonn", "sportif", "endiabl", "frenetiq", "debord", "tonique", "agite",
                "turbulen", "jovial", "peps", "vigoureux", "ardent"],
}


def _sans_accents(txt: str) -> str:
    nfkd = unicodedata.normalize("NFKD", txt or "")
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower()


def _ajouter(cumul: dict, tags: dict, poids: float = 1.0):
    for stat, pts in (tags or {}).items():
        cumul[stat] = cumul.get(stat, 0.0) + pts * poids


def _normaliser(brut: dict) -> dict:
    """Met les stats à l'échelle 0–100 (dominante = 100), avec une base pour éviter le zéro."""
    base = {s: brut.get(s, 0.0) + 2.0 for s in STATS}   # socle commun (personne n'est « à zéro »)
    plafond = max(base.values()) or 1.0
    return {s: round(100 * v / plafond) for s, v in base.items()}


# ── MODE DESCENDANT : traditions → stats → archétype → fiche ─────
def stats_depuis_traditions(trad: dict) -> dict:
    """Agrège les tags de TOUTES les traditions calculées en stats (0–100 normalisées).

    `trad` = sortie de traditions.calculer(). C'est le « cumul à travers les cultures »
    du rapport : un trait porté par plusieurs traditions ressort comme majeur. Les poids
    hiérarchisent les apports (signe solaire en tête). Repli honnête : section manquante
    = simplement pas de vote."""
    cumul: dict = {}
    sig = trad.get("signe_solaire") or {}
    if sig.get("nom"):
        _ajouter(cumul, _TAGS_SIGNE.get(sig["nom"], {}), 1.5)
        _ajouter(cumul, _TAGS_ELEMENT.get(sig.get("element"), {}), 1.0)
    if isinstance(trad.get("chemin_de_vie"), int):
        _ajouter(cumul, _TAGS_NOMBRE.get(trad["chemin_de_vie"], {}), 1.2)
    chi = trad.get("signe_chinois") or {}
    if chi.get("animal"):
        _ajouter(cumul, _TAGS_CHINOIS.get(chi["animal"], {}), 1.0)
        _ajouter(cumul, _TAGS_ELEMENT.get(_element_chinois_vers_signe(chi.get("element")), {}), 0.4)
    if trad.get("egyptien"):
        _ajouter(cumul, _TAGS_EGYPTE.get(trad["egyptien"], {}), 0.8)
    if trad.get("celte"):
        _ajouter(cumul, _TAGS_CELTE.get(trad["celte"], {}), 0.6)
    if trad.get("amerindien"):
        _ajouter(cumul, _TAGS_TOTEM.get(trad["amerindien"], {}), 0.8)
    maya = trad.get("maya") or {}
    if maya.get("glyphe"):
        _ajouter(cumul, _TAGS_MAYA.get(maya["glyphe"], {}), 0.5)
    # Védique : le rashi (signe sidéral) vote via la table des signes occidentaux.
    ved = trad.get("vedique") or {}
    if ved.get("rashi"):
        _ajouter(cumul, _TAGS_SIGNE.get(ved["rashi"], {}), 0.7)
    # Signe lunaire (émotions / jardin secret) : facteur majeur quand l'heure est connue.
    lun = trad.get("signe_lunaire") or {}
    if lun.get("signe"):
        _ajouter(cumul, _TAGS_SIGNE.get(lun["signe"], {}), 0.9)
    # Ascendant (apparence/masque social) : signe d'ascendant, poids modéré.
    asc = (trad.get("theme_astral") or {}).get("ascendant") or {}
    if asc.get("signe"):
        _ajouter(cumul, _TAGS_SIGNE.get(asc["signe"], {}), 0.8)
    # Nombre d'expression (talents/tempérament du nom) : même table que le chemin de vie.
    expr = (trad.get("numerologie_nom") or {}).get("expression")
    if isinstance(expr, int):
        _ajouter(cumul, _TAGS_NOMBRE.get(expr, {}), 0.6)
    return _normaliser(cumul)


def _element_chinois_vers_signe(el: str | None) -> str | None:
    """Rapproche l'élément chinois (Bois/Feu/Terre/Métal/Eau) des 4 éléments occidentaux."""
    return {"Bois": "Air", "Feu": "Feu", "Terre": "Terre", "Métal": "Terre", "Eau": "Eau"}.get(el)


def _archetype(stats: dict) -> str:
    """Archétype dont les 3 stats signature totalisent le plus chez le personnage."""
    return max(_ARCHETYPES, key=lambda a: sum(stats.get(s, 0) for s in a[1]))[0]


def portrait(trad: dict, nom: str = "", langue: str = "fr") -> dict:
    """Fiche de personnage complète à partir des traditions calculées.

    `langue="fr"` (défaut) : sortie STRICTEMENT identique à avant l'i18n (S194), zéro
    régression. `langue="en"` : même forme (mêmes clés JSON), valeurs traduites.
    Retourne {stats, archetype, forces, faiblesse, pierre_equilibrage, recit}."""
    stats = stats_depuis_traditions(trad)
    classe = sorted(STATS, key=lambda s: stats[s], reverse=True)
    forces = classe[:3]
    faiblesse = classe[-1]
    pierre_nom, pierre_vertu = _EQUILIBRAGE[faiblesse]
    arch = _archetype(stats)
    recit = _recit(arch, stats, forces, faiblesse, pierre_nom, pierre_vertu, trad, nom, langue)

    if (langue or "fr").lower().startswith("en"):
        return {
            "stats": {STATS_LABEL_EN[s]: v for s, v in stats.items()},
            "archetype": _ARCHETYPES_EN.get(arch, arch),
            "forces": [STATS_LABEL_EN[f] for f in forces],
            "faiblesse": STATS_LABEL_EN[faiblesse],
            "pierre_equilibrage": {"pierre": _EQUILIBRAGE_EN[faiblesse][0],
                                   "vertu": _EQUILIBRAGE_EN[faiblesse][1],
                                   "compense": STATS_LABEL_EN[faiblesse]},
            "recit": recit,
        }
    return {
        "stats": stats,
        "archetype": arch,
        "forces": forces,
        "faiblesse": faiblesse,
        "pierre_equilibrage": {"pierre": pierre_nom, "vertu": pierre_vertu,
                               "compense": faiblesse},
        "recit": recit,
    }


# Élément d'un signe (pour la tonalité d'ouverture).
_ELEMENT_PAR_SIGNE = {
    "Bélier": "Feu", "Lion": "Feu", "Sagittaire": "Feu",
    "Taureau": "Terre", "Vierge": "Terre", "Capricorne": "Terre",
    "Gémeaux": "Air", "Balance": "Air", "Verseau": "Air",
    "Cancer": "Eau", "Scorpion": "Eau", "Poissons": "Eau",
}
_ELEMENT_TON = {
    "Feu": "une énergie ardente, tournée vers l'action et l'élan",
    "Terre": "un tempérament concret, patient, attaché au réel",
    "Air": "un esprit mobile, sociable, porté par les idées",
    "Eau": "une nature sensible, intuitive, à fleur d'émotion",
}
_ELEMENT_TON_EN = {
    "Feu": "a fiery energy, driven toward action and momentum",
    "Terre": "a grounded temperament, patient, attached to the concrete",
    "Air": "a nimble mind, sociable, carried by ideas",
    "Eau": "a sensitive nature, intuitive, close to its emotions",
}


def _element_dominant(trad: dict) -> str | None:
    """Élément le plus présent sur Soleil / Lune / Ascendant / rashi + élément chinois."""
    cumul: dict = {}
    sol = (trad.get("signe_solaire") or {}).get("nom")
    lun = (trad.get("signe_lunaire") or {}).get("signe")
    asc = ((trad.get("theme_astral") or {}).get("ascendant") or {}).get("signe")
    ved = (trad.get("vedique") or {}).get("rashi")
    for s in (sol, lun, asc, ved):
        el = _ELEMENT_PAR_SIGNE.get(s)
        if el:
            cumul[el] = cumul.get(el, 0) + 1
    elc = (trad.get("signe_chinois") or {}).get("element")
    if elc in _ELEMENT_TON:
        cumul[elc] = cumul.get(elc, 0) + 1
    if not cumul:
        return None
    # ex æquo départagé par l'élément solaire (l'identité de base)
    sol_el = _ELEMENT_PAR_SIGNE.get(sol)
    return max(cumul, key=lambda e: (cumul[e], e == sol_el))


def _mots(sens: str) -> list:
    return [m.strip() for m in (sens or "").replace(";", ",").split(",") if m.strip()]


def _fil_rouge(empreinte: list) -> str | None:
    """Repère les mots-clés portés par ≥2 SYMBOLES DISTINCTS — le motif central qui fait
    une *lecture* plutôt qu'une liste. On compte par valeur (Bélier, Isis…) et non par
    placement : un Soleil et un Ascendant sur le même signe ne comptent qu'une fois.
    Renvoie une phrase, ou None si rien ne converge vraiment."""
    porteurs: dict = {}     # mot_normalisé → {"mot": affichage, "valeurs": set, "cles": [..]}
    for e in empreinte:
        valeur = e.get("valeur", "")
        for m in set(_mots(e.get("sens", ""))):
            k = _sans_accents(m).lower()
            d = porteurs.setdefault(k, {"mot": m, "valeurs": set(), "cles": []})
            if valeur not in d["valeurs"]:     # même mot via 2 placements du même signe = 1 voix
                d["valeurs"].add(valeur)
                d["cles"].append(e.get("cle", ""))
    recurrents = sorted([k for k, d in porteurs.items() if len(d["valeurs"]) >= 2],
                        key=lambda k: (-len(porteurs[k]["valeurs"]), k))
    if not recurrents:
        return None
    motifs = []
    for k in recurrents[:2]:
        d = porteurs[k]
        cles_u = [c for c in dict.fromkeys(d["cles"]) if c][:3]
        motifs.append(f"**{d['mot']}** ({' · '.join(cles_u)})")
    return "Plusieurs traditions convergent vers le même motif : " + " ; ".join(motifs) + "."


def _recit(arch, stats, forces, faiblesse, pierre, vertu, trad, nom, langue: str = "fr") -> str:
    """Dispatch FR/EN (S194). `langue="fr"` (défaut) : comportement identique à avant
    l'i18n. `langue="en"` : gabarit anglais dédié (`_recit_en`), pas une traduction à la
    volée d'un texte français — les deux gabarits restent lisibles indépendamment."""
    en = (langue or "fr").lower().startswith("en")
    emp = SIG.expliquer(trad, "en" if en else "fr")
    if en:
        return _recit_en(arch, stats, forces, faiblesse, trad, nom, emp)
    return _recit_fr(arch, stats, forces, faiblesse, pierre, vertu, trad, nom, emp)


def _recit_fr(arch, stats, forces, faiblesse, pierre, vertu, trad, nom, emp) -> str:
    """Lecture symbolique en sections, qui TISSE les sens calculés (significations) et
    dégage un fil rouge, au lieu d'énumérer les sources. Reste du divertissement."""
    sujet = nom.strip() if (nom and nom.strip()) else "Ce personnage"
    par_cle = {e["cle"]: e for e in emp}
    sections = []

    # — Le noyau : archétype + élément dominant + Soleil / Lune / Ascendant —
    el = _element_dominant(trad)
    noyau = f"**Le noyau.** {sujet} est **{arch}**"
    noyau += f", porté par {_ELEMENT_TON[el]}." if el else "."
    sol = par_cle.get("Soleil")
    if sol and sol.get("sens"):
        noyau += f" Son Soleil en {sol['valeur']} en donne le grain : {sol['sens']}."
    lun = par_cle.get("Lune")
    if lun and lun.get("sens"):
        noyau += f" Au-dedans, une Lune en {lun['valeur']} — {lun['sens']}."
    asc = par_cle.get("Ascendant")
    if asc and asc.get("sens"):
        noyau += f" Au-dehors, un ascendant {asc['valeur']} : {asc['sens']}."
    forces_txt = ", ".join(f"{f} ({stats[f]})" for f in forces)
    noyau += f" Ses forces dominantes : {forces_txt}."
    sections.append(noyau)

    # — Le fil rouge : mots-clés récurrents entre traditions —
    fr = _fil_rouge(emp)
    if fr:
        sections.append("**Le fil rouge.** " + fr)
    else:
        sections.append(f"**Le fil rouge.** Une dominante nette se détache : {forces[0]} "
                        f"({stats[forces[0]]}), qui colore le reste du tempérament.")

    # — Les autres voix : on fait parler 3 traditions de plus (par leur sens) —
    voix = []
    for cle, intro in (("Astrologie chinoise", "côté chinois"), ("Égypte", "en Égypte"),
                       ("Celte", "côté celte"), ("Totem amérindien", "comme totem"),
                       ("Maya (Tzolkin)", "dans le Tzolkin"), ("Nakshatra", "côté védique")):
        e = par_cle.get(cle)
        if e and e.get("sens"):
            voix.append(f"{intro}, {e['valeur']} ({e['sens']})")
        if len(voix) >= 3:
            break
    if voix:
        phrase = " ; ".join(voix)
        sections.append("**Les autres voix.** " + phrase[:1].upper() + phrase[1:] + ".")

    # — L'ombre & le remède : faiblesse + pierre d'équilibrage —
    sections.append(
        f"**L'ombre & le remède.** Le point à travailler est {faiblesse} ({stats[faiblesse]}), "
        f"là où l'énergie se fait rare. La gemmologie compensatoire propose **{pierre}** "
        f"({vertu}) pour rouvrir cette porte.")

    # — Le chemin des nombres : chemin de vie + expression du nom —
    nums = []
    cdv = par_cle.get("Chemin de vie")
    if cdv and cdv.get("sens"):
        nums.append(f"un chemin de vie {cdv['valeur']} — {cdv['sens']}")
    expr = par_cle.get("Expression (nom)")
    if expr and expr.get("sens"):
        nums.append(f"une expression du nom en {expr['valeur']} — {expr['sens']}")
    if nums:
        phrase = " ; ".join(nums)
        sections.append("**Le chemin des nombres.** " + phrase[:1].upper() + phrase[1:] + ".")

    sections.append("_Lecture symbolique — divertissement, pas un fait._")
    return "\n\n".join(sections)


def _recit_en(arch, stats, forces, faiblesse, trad, nom, emp) -> str:
    """Gabarit anglais du récit — même structure que `_recit_fr`, phrases dédiées (pas
    une traduction mécanique) ; s'appuie sur l'empreinte déjà traduite (`cle` en anglais)."""
    sujet = nom.strip() if (nom and nom.strip()) else "This character"
    par_cle = {e["cle"]: e for e in emp}
    sections = []

    arch_en = _ARCHETYPES_EN.get(arch, arch)
    el = _element_dominant(trad)
    noyau = f"**The Core.** {sujet} is **{arch_en}**"
    noyau += f", carried by {_ELEMENT_TON_EN[el]}." if el else "."
    sol = par_cle.get("Sun")
    if sol and sol.get("sens"):
        noyau += f" Their Sun in {sol['valeur']} sets the tone: {sol['sens']}."
    lun = par_cle.get("Moon")
    if lun and lun.get("sens"):
        noyau += f" Within, a Moon in {lun['valeur']} — {lun['sens']}."
    asc = par_cle.get("Ascendant")
    if asc and asc.get("sens"):
        noyau += f" Outwardly, a {asc['valeur']} ascendant: {asc['sens']}."
    forces_txt = ", ".join(f"{STATS_LABEL_EN[f]} ({stats[f]})" for f in forces)
    noyau += f" Dominant strengths: {forces_txt}."
    sections.append(noyau)

    fr = _fil_rouge(emp)
    if fr:
        sections.append("**The Common Thread.** " + fr)
    else:
        sections.append(f"**The Common Thread.** One trait clearly stands out: "
                        f"{STATS_LABEL_EN[forces[0]]} ({stats[forces[0]]}), coloring the "
                        f"rest of the temperament.")

    voix = []
    for cle, intro in (("Chinese Astrology", "on the Chinese side"), ("Egyptian", "in Egypt"),
                       ("Celtic", "on the Celtic side"), ("Native American Totem", "as a totem"),
                       ("Maya (Tzolkin)", "in the Tzolkin"), ("Nakshatra", "on the Vedic side")):
        e = par_cle.get(cle)
        if e and e.get("sens"):
            voix.append(f"{intro}, {e['valeur']} ({e['sens']})")
        if len(voix) >= 3:
            break
    if voix:
        phrase = " ; ".join(voix)
        sections.append("**Other Voices.** " + phrase[:1].upper() + phrase[1:] + ".")

    pierre_en, vertu_en = _EQUILIBRAGE_EN[faiblesse]
    sections.append(
        f"**The Shadow & the Remedy.** The point to work on is {STATS_LABEL_EN[faiblesse]} "
        f"({stats[faiblesse]}), where energy runs low. Compensatory gemmology suggests "
        f"**{pierre_en}** ({vertu_en}) to reopen that door.")

    nums = []
    cdv = par_cle.get("Life Path")
    if cdv and cdv.get("sens"):
        nums.append(f"a life path of {cdv['valeur']} — {cdv['sens']}")
    expr = par_cle.get("Expression (Name)")
    if expr and expr.get("sens"):
        nums.append(f"a name expression of {expr['valeur']} — {expr['sens']}")
    if nums:
        phrase = " ; ".join(nums)
        sections.append("**The Path of Numbers.** " + phrase[:1].upper() + phrase[1:] + ".")

    sections.append("_Symbolic reading — entertainment, not fact._")
    return "\n\n".join(sections)


# ── MODE MONTANT : description → signes / nombres / date ──────────
# Pré-calcul : liste plate (radical → stat) et index des radicaux (premier gagne pour le flou).
_PAIRES = [(r, stat) for stat, lst in _LEXIQUE.items() for r in lst]
_RADICAUX = [r for r, _ in _PAIRES]
_RADICAL_STAT = {}
for _r, _s in _PAIRES:
    _RADICAL_STAT.setdefault(_r, _s)


def cibler_stats(description: str) -> dict:
    """Vecteur de stats visé, déduit de la description — recherche par CHAMP LEXICAL.

    Deux niveaux pour éviter les manques :
    1) chaque mot est rattaché à une stat si un radical de la famille le préfixe
       (manipulateur → « manipul » → Discrétion) ;
    2) un mot inconnu est rapproché par SIMILARITÉ (difflib) du radical le plus proche
       (rattrape fautes de frappe et variantes : « manipulteur », « colèrique »…)."""
    txt = _sans_accents(description)
    cible = {s: 0 for s in STATS}
    for tok in (t for t in re.findall(r"[a-z]+", txt) if len(t) >= 3):
        trouves = {stat for r, stat in _PAIRES if tok.startswith(r) or r.startswith(tok)}
        if not trouves:                       # repli flou : mot hors lexique
            proche = difflib.get_close_matches(tok, _RADICAUX, n=1, cutoff=0.82)
            if proche:
                trouves = {_RADICAL_STAT[proche[0]]}
        for stat in trouves:
            cible[stat] += 1
    return cible


def _score(profil: dict, cible: dict) -> int:
    """Produit scalaire profil·cible (overlap des tendances)."""
    return sum(profil.get(s, 0) * cible.get(s, 0) for s in STATS)


def _date_pour(signe: str, nombre: int | None) -> str | None:
    """UNE date plausible : dans la plage du signe, dont le chemin de vie vaut `nombre`.

    Balaye quelques années récentes ; renvoie la première date qui matche, ou simplement
    le début de plage si aucun nombre n'est visé. Non-unicité assumée."""
    (m1, j1), (m2, j2) = T.SIGNE_PLAGES[signe]
    if (m1, j1) > (m2, j2):                    # plage à cheval (Capricorne) → simplifie
        return f"vers le {j1} {T.MOIS_FR[m1]}"
    if not nombre:
        return f"{j1:02d}/{m1:02d}"
    for an in range(2004, 1979, -1):           # quelques années récentes, lisibles
        d, fin = date(an, m1, j1), date(an, m2, j2)
        while d <= fin:
            if T.chemin_de_vie(d) == nombre:
                return d.isoformat()
            d += timedelta(days=1)
    return f"{j1:02d}/{m1:02d}"   # repli : aucune année testée ne tombe juste


def recherche_inverse(description: str, combien: int = 3, cible: dict | None = None) -> dict:
    """Mode montant : trouve signes / nombres / dates qui collent à la description.

    Retourne {cible, signes:[…], nombres:[…], archetype, exemple_date, note}. La non-unicité
    est explicite : ce sont DES pistes qui maximisent l'overlap, pas une vérité unique.

    `cible` peut être fournie de l'extérieur (ex. analyse LLM en filet de secours) ; sinon
    elle est déduite du champ lexical local."""
    cible = cible if cible is not None else cibler_stats(description)
    if not any(cible.values()):
        return {"cible": cible, "signes": [], "nombres": [], "archetype": None,
                "exemple_date": None,
                "note": "Aucun trait reconnu dans la description — précise le caractère."}

    signes = sorted(
        ({"signe": nom, "element": T.ELEMENTS_SIGNE[i % 4],
          "plage": _plage_texte(nom),
          "score": _score(_profil_signe(nom), cible)}
         for i, (nom, _) in enumerate(T.SIGNES)),
        key=lambda x: x["score"], reverse=True)
    signes = [s for s in signes if s["score"] > 0][:combien]

    nombres = sorted(
        ({"nombre": n, "score": _score(_TAGS_NOMBRE[n], cible)} for n in _TAGS_NOMBRE),
        key=lambda x: x["score"], reverse=True)
    nombres = [n for n in nombres if n["score"] > 0][:combien]

    arch = max(_ARCHETYPES, key=lambda a: sum(cible.get(s, 0) for s in a[1]))[0]
    top_signe = signes[0]["signe"] if signes else None
    top_nombre = nombres[0]["nombre"] if nombres else None
    exemple = _date_pour(top_signe, top_nombre) if top_signe else None
    return {
        "cible": {s: v for s, v in cible.items() if v},
        "signes": signes, "nombres": nombres, "archetype": arch,
        # Pistes dans les autres traditions (comme l'exemple « Anubis / Serpent » du rapport).
        "autres_traditions": {
            "egyptien": _meilleur(_TAGS_EGYPTE, cible),
            "celte": _meilleur(_TAGS_CELTE, cible),
            "amerindien": _meilleur(_TAGS_TOTEM, cible),
            "maya": _meilleur(_TAGS_MAYA, cible),
        },
        "exemple_date": exemple,
        "note": "Pistes maximisant l'overlap des traits — plusieurs dates conviennent "
                "(non-unicité assumée). Divertissement, pas un fait.",
    }


def _meilleur(table: dict, cible: dict) -> str | None:
    """Élément d'une table de tags dont le profil colle le mieux à la cible (overlap > 0)."""
    classe = max(table, key=lambda k: _score(table[k], cible))
    return classe if _score(table[classe], cible) > 0 else None


def _profil_signe(nom: str) -> dict:
    """Profil de stats d'un signe = tags du signe + tags de son élément (même pondération
    que le mode descendant, pour que les deux sens soient cohérents)."""
    i = [s[0] for s in T.SIGNES].index(nom)
    profil = {}
    _ajouter(profil, _TAGS_SIGNE[nom], 1.5)
    _ajouter(profil, _TAGS_ELEMENT[T.ELEMENTS_SIGNE[i % 4]], 1.0)
    return profil


def _plage_texte(signe: str) -> str:
    (m1, j1), (m2, j2) = T.SIGNE_PLAGES[signe]
    return f"{j1} {T.MOIS_FR[m1]} – {j2} {T.MOIS_FR[m2]}"
