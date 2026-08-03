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
# Glossaire — bulles interactives + légende PDF (FR). Chaque id est
# stable (jamais traduit) ; son libellé (`label`) suit la langue via
# `_GLOSSAIRE_LABELS`/`_GLOSSAIRE_LABELS_EN`. Définitions : lecture
# symbolique de divertissement, 3-5 phrases.
# ══════════════════════════════════════════════════════════════════
GLOSSAIRE_FR = {
    "soleil": (
        "Soleil — signe zodiacal où se trouvait le Soleil à ta naissance. "
        "Cœur de la personnalité, identité consciente, ce que tu rayonnes au quotidien. "
        "Tradition occidentale classique ; il marque l'ego, l'essentiel de soi. "
        "À lire comme le fil conducteur du portrait : tout le reste colorie autour."
    ),
    "lune": (
        "Lune — signe traversé par la Lune à ta naissance. Gouverne les émotions, "
        "le jardin secret, les instincts et les besoins de sécurité. Tradition "
        "occidentale ; seconde signature du thème après le Soleil. À lire comme ton "
        "visage intime, rarement montré en société."
    ),
    "ascendant": (
        "Ascendant — signe se levant à l'horizon Est au moment exact de ta naissance. "
        "Apparence, premier contact, masque social, comment on te perçoit avant de te "
        "connaître. Dépend de l'heure (à la minute près). À lire comme la vitrine "
        "que le Soleil habille derrière."
    ),
    "chinoise": (
        "Astrologie chinoise — animal annuel (cycle de 12) et élément (Bois, Feu, "
        "Terre, Métal, Eau). Dépeint le moi social, l'archétype collectif qu'on "
        "incarne dans sa génération. Tradition millénaire vivante. À lire comme la "
        "couleur d'une époque plus que d'une individualité."
    ),
    "animal_heure": (
        "Animal de l'heure — deuxième animal chinois, fixé par l'heure de naissance "
        "(deux heures par animal dans le cycle de 12). Représente le moi profond et "
        "inconscient, souvent ignoré mais réapparaissant dans les choix intimes. À "
        "lire comme un ascendant chinois ; nécessite l'heure exacte."
    ),
    "vedique": (
        "Védique (rashi) — signe sidéral du Soleil selon l'astrologie indienne "
        "(Jyotish). Mesuré avec la précession des équinoxes, donc souvent décalé "
        "d'un signe par rapport au zodiaque occidental. Reflète la lecture karmique. "
        "Tradition sanskrite vivante. À lire comme un Soleil lu sans le filtre "
        "occidental."
    ),
    "nakshatra": (
        "Nakshatra — maison lunaire (27 au total) où se trouvait la Lune à ta "
        "naissance. Lecture védique fine : psychologie profonde, karma, traits "
        "karmiques potentiels. Chaque nakshatra est divisé en 4 padas (quarts). "
        "Tradition Jyotish. À lire comme une radiographie lunaire plus fine qu'un "
        "signe lunaire occidental."
    ),
    "egypte": (
        "Égypte — divinité tutélaire calculée selon le calendrier égyptien antique. "
        "Archétype divin qui protège et guide. Tradition dérivée du calendrier de "
        "l'Égypte pharaonique. À lire comme un masque sacré qui synthétise des "
        "traits déjà présents dans le reste du portrait."
    ),
    "celte": (
        "Celte — arbre protecteur selon le calendrier oghamique des druides. Chaque "
        "jour de l'année est régi par un arbre porteur d'une vertu. Tradition "
        "gauloise reconstructive. À lire comme ton ancrage saisonnier, une racine "
        "de plus dans le portrait."
    ),
    "totem": (
        "Totem amérindien — animal totem selon la medicine wheel, calée sur les "
        "mois du zodiaque occidental. Énergie animale qui t'accompagne. Tradition "
        "des Premières Nations d'Amérique du Nord. À lire comme une guidance "
        "instinctive plus proche de la nature."
    ),
    "maya": (
        "Maya (Tzolkin) — glyphe (20 au total) et tonalité (1-13) du jour dans le "
        "calendrier sacré Tzolkin. Combinaison unique tous les 260 jours. Représente "
        "l'énergie du jour où tu es venu au monde. Tradition mésoaméricaine. À lire "
        "comme la signature énergétique du calendrier maya."
    ),
    "chemin_de_vie": (
        "Chemin de vie — nombre réduit de ta date de naissance (somme des chiffres). "
        "Pilier numérologique : mission, leçon majeure, direction de vie. Numérologie "
        "occidentale classique. À lire comme le fil rouge de ta destinée numérique."
    ),
    "expression": (
        "Expression (nom) — somme numérologique des lettres du nom complet. Reflète "
        "talents naturels, tempérament, savoir-faire, ce que tu exprimes. "
        "Numérologie occidentale. À lire comme le complément du chemin de vie, au "
        "niveau des capacités plutôt que du but."
    ),
    "archetype": (
        "Archétype — synthèse narrative du portrait, agrège toutes les traditions "
        "calculées (soleil, lune, ascendant, chinoise, védique, nakshatra, égypte, "
        "celte, totem, maya, chemin de vie, expression). Résume à une figure "
        "archétypale mémorable. À lire comme la légende du portrait, pas une "
        "prédiction."
    ),
    "forces": (
        "Forces dominantes — 3 traits statistiquement les plus élevés parmi les "
        "statistiques de personnalité (Charisme, Combativité, Sagesse, Créativité, "
        "Discrétion, Stabilité, Émotivité, Énergie), agrégées depuis toutes les "
        "traditions. À lire comme tes atouts saillants."
    ),
    "faiblesse": (
        "Point à travailler — trait statistique le plus bas parmi les stats. Pas "
        "une fatalité mais un axe de vigilance. À lire comme un miroir, pas un "
        "verdict."
    ),
    "pierre": (
        "Pierre d'équilibrage — gemme compensatoire choisie selon le point à "
        "travailler. Lecture symbolique de gemmologie traditionnelle, pas "
        "minéralogique. À lire comme un talisman illustratif."
    ),
    "stat_charisme": (
        "Charisme — magnétisme personnel, capacité à rayonner et à fédérer. "
        "Nourri surtout par le Soleil, le Dragon chinois et les divinités solaires "
        "(Amon-Rê, Horus). À lire comme ton magnétisme naturel, utile en "
        "leadership et prise de parole publique."
    ),
    "stat_combativite": (
        "Combativité — ardeur à défendre ses idées, ténacité face à l'adversité. "
        "Nourri par Bélier, Aries, Mars, Seth, le Tigre. À lire comme ton "
        "réservoir d'opiniâtreté."
    ),
    "stat_sagesse": (
        "Sagesse — profondeur de réflexion, intuition posée, sens de la "
        "mesure. Nourrie par Thot, Osiris, le Serpent, les nakshatras "
        "calmes (Pushya, Shravana). À lire comme ta voix tranquille."
    ),
    "stat_creativite": (
        "Créativité — imagination, expressivité, capacité à inventer. Nourrie "
        "par Bastet, Chuen (Maya Singe), le Loutre, la Chèvre. À lire comme ton "
        "jaillissement inventif."
    ),
    "stat_discretion": (
        "Discrétion — réserve, capacité à se faire oublier, élégance du silence. "
        "Nourrie par Anubis, le Scorpion, le Hibou, Ashlesha. À lire comme ton "
        "art de l'effacement volontaire."
    ),
    "stat_stabilite": (
        "Stabilité — ancrage, constance, résistance aux tempêtes émotionnelles. "
        "Nourrie par Geb, le Taureau, le Chêne, le Buffle. À lire comme ta "
        "racine tranquille."
    ),
    "stat_emotivite": (
        "Émotivité — intensité du ressenti, sensibilité aux climats intérieurs "
        "et extérieurs. Nourrie par la Lune, Cancer, le Saule, Muluc. À lire "
        "comme ton paysage intérieur."
    ),
    "stat_energie": (
        "Énergie — vitalité, capacité d'action, drive physique. Nourrie par Mars, "
        "le Cheval, le Sagittaire, Imix. À lire comme ton carburant "
        "motivationnel."
    ),
}

GLOSSAIRE_EN = {
    "soleil": (
        "Sun — zodiac sign the Sun was in at your birth. Core of the personality, "
        "conscious identity, what you radiate day to day. Classical Western "
        "tradition; marks the ego, the essence of self. Read as the throughline "
        "of the portrait: everything else colors around it."
    ),
    "lune": (
        "Moon — sign the Moon was passing through at your birth. Governs emotions, "
        "the secret garden, instincts and security needs. Western tradition; "
        "second signature of the chart after the Sun. Read as your intimate face, "
        "rarely shown in public."
    ),
    "ascendant": (
        "Ascendant — sign rising on the eastern horizon at the exact moment of "
        "your birth. Appearance, first impression, social mask, how you are "
        "perceived before being known. Depends on birth time (to the minute). Read "
        "as the storefront that the Sun dresses behind."
    ),
    "chinoise": (
        "Chinese astrology — yearly animal (12-cycle) and element (Wood, Fire, "
        "Earth, Metal, Water). Depicts the social self, the collective archetype "
        "embodied by your generation. Ancient living tradition. Read as the color "
        "of an era rather than of an individual."
    ),
    "animal_heure": (
        "Hour animal — second Chinese animal, fixed by birth time (two hours per "
        "animal in the 12-cycle). Represents the deep and unconscious self, often "
        "ignored but resurfacing in private choices. Read as a Chinese ascendant; "
        "requires exact birth time."
    ),
    "vedique": (
        "Vedic (rashi) — sidereal sign of the Sun according to Indian astrology "
        "(Jyotish). Measured with precession of the equinoxes, so often shifted "
        "by one sign from the Western zodiac. Reflects karmic reading. Living "
        "Sanskritic tradition. Read as a Sun read without the Western frame."
    ),
    "nakshatra": (
        "Nakshatra — lunar mansion (27 in total) where the Moon was at your "
        "birth. Fine Vedic reading: deep psychology, karma, potential traits. "
        "Each nakshatra is divided into 4 padas (quarters). Jyotish tradition. "
        "Read as a finer lunar X-ray than a Western lunar sign."
    ),
    "egypte": (
        "Egyptian — tutelary deity calculated from the ancient Egyptian calendar. "
        "Divine archetype that protects and guides. Tradition derived from "
        "pharaonic Egypt's calendar. Read as a sacred mask that synthesizes "
        "traits already present in the rest of the portrait."
    ),
    "celte": (
        "Celtic — protective tree according to the druids' oghamic calendar. "
        "Each day of the year is ruled by a tree carrying a virtue. Reconstructive "
        "Gaulish tradition. Read as your seasonal grounding, one more root in "
        "the portrait."
    ),
    "totem": (
        "Native American totem — totem animal according to the medicine wheel, "
        "aligned with the Western zodiac months. Animal energy that accompanies "
        "you. Tradition of the First Nations of North America. Read as instinctive "
        "guidance closer to nature."
    ),
    "maya": (
        "Maya (Tzolkin) — glyph (20 in total) and tone (1-13) of the day in the "
        "sacred Tzolkin calendar. Unique combination every 260 days. Represents "
        "the energy of the day you came into the world. Mesoamerican tradition. "
        "Read as the calendrical energy signature of the Maya."
    ),
    "chemin_de_vie": (
        "Life path — number reduced from your birth date (sum of the digits). "
        "Numerological pillar: mission, major lesson, life direction. Classical "
        "Western numerology. Read as the red thread of your numerical destiny."
    ),
    "expression": (
        "Expression (name) — numerological sum of the letters of the full name. "
        "Reflects natural talents, temperament, know-how, what you express. "
        "Western numerology. Read as the complement to the life path, at the "
        "level of capacities rather than purpose."
    ),
    "archetype": (
        "Archetype — narrative synthesis of the portrait; aggregates all the "
        "calculated traditions (sun, moon, ascendant, Chinese, Vedic, nakshatra, "
        "Egyptian, Celtic, totem, Maya, life path, expression). Summarizes to a "
        "memorable archetypal figure. Read as the legend of the portrait, not a "
        "prediction."
    ),
    "forces": (
        "Dominant strengths — 3 statistically highest traits among the personality "
        "stats (Charisma, Combativeness, Wisdom, Creativity, Discretion, "
        "Stability, Emotionality, Energy), aggregated from all traditions. Read "
        "as your salient assets."
    ),
    "faiblesse": (
        "Point to work on — lowest statistical trait among the stats. Not a fate "
        "but an axis of vigilance. Read as a mirror, not a verdict."
    ),
    "pierre": (
        "Balancing stone — compensatory gem chosen according to the point to "
        "work on. Symbolic reading of traditional gemology, not mineralogical. "
        "Read as an illustrative talisman."
    ),
    "stat_charisme": (
        "Charisma — personal magnetism, capacity to radiate and gather. Fed "
        "chiefly by the Sun, the Chinese Dragon and the solar deities (Amun-Ra, "
        "Horus). Read as your natural magnetism, useful in leadership and public "
        "speaking."
    ),
    "stat_combativite": (
        "Combativeness — fire to defend your ideas, tenacity against adversity. "
        "Fed by Aries, Mars, Set, the Tiger. Read as your reservoir of "
        "doggedness."
    ),
    "stat_sagesse": (
        "Wisdom — depth of reflection, poised intuition, sense of measure. Fed "
        "by Thoth, Osiris, the Snake, the calm nakshatras (Pushya, Shravana). "
        "Read as your quiet voice."
    ),
    "stat_creativite": (
        "Creativity — imagination, expressiveness, capacity to invent. Fed by "
        "Bastet, Chuen (Maya Monkey), Otter, Goat. Read as your inventive "
        "spring."
    ),
    "stat_discretion": (
        "Discretion — reserve, capacity to be overlooked, elegance of silence. "
        "Fed by Anubis, Scorpio, Owl, Ashlesha. Read as your art of voluntary "
        "withdrawal."
    ),
    "stat_stabilite": (
        "Stability — grounding, constance, resistance to emotional storms. Fed "
        "by Geb, Taurus, Oak, Ox. Read as your quiet root."
    ),
    "stat_emotivite": (
        "Emotionality — intensity of feeling, sensitivity to inner and outer "
        "climates. Fed by the Moon, Cancer, Willow, Muluc. Read as your inner "
        "landscape."
    ),
    "stat_energie": (
        "Energy — vitality, capacity for action, physical drive. Fed by Mars, "
        "Horse, Sagittarius, Imix. Read as your motivational fuel."
    ),
}

# Libellés (labels) FR/EN par id — ce que le front affiche comme titre court.
_GLOSSAIRE_LABELS = {
    "soleil": "Soleil", "lune": "Lune", "ascendant": "Ascendant",
    "chinoise": "Astrologie chinoise", "animal_heure": "Animal de l'heure",
    "vedique": "Védique (rashi)", "nakshatra": "Nakshatra", "egypte": "Égypte",
    "celte": "Celte", "totem": "Totem amérindien", "maya": "Maya (Tzolkin)",
    "chemin_de_vie": "Chemin de vie", "expression": "Expression (nom)",
    "archetype": "Archétype", "forces": "Forces dominantes",
    "faiblesse": "Point à travailler", "pierre": "Pierre d'équilibrage",
    "stat_charisme": "Charisme", "stat_combativite": "Combativité",
    "stat_sagesse": "Sagesse", "stat_creativite": "Créativité",
    "stat_discretion": "Discrétion", "stat_stabilite": "Stabilité",
    "stat_emotivite": "Émotivité", "stat_energie": "Énergie",
}
_GLOSSAIRE_LABELS_EN = {
    "soleil": "Sun", "lune": "Moon", "ascendant": "Ascendant",
    "chinoise": "Chinese Astrology", "animal_heure": "Hour Animal",
    "vedique": "Vedic (Rashi)", "nakshatra": "Nakshatra", "egypte": "Egyptian",
    "celte": "Celtic", "totem": "Native American Totem", "maya": "Maya (Tzolkin)",
    "chemin_de_vie": "Life Path", "expression": "Expression (Name)",
    "archetype": "Archetype", "forces": "Dominant Strengths",
    "faiblesse": "Point to Work On", "pierre": "Balancing Stone",
    "stat_charisme": "Charisma", "stat_combativite": "Combativeness",
    "stat_sagesse": "Wisdom", "stat_creativite": "Creativity",
    "stat_discretion": "Discretion", "stat_stabilite": "Stability",
    "stat_emotivite": "Emotionality", "stat_energie": "Energy",
}

# Thèmes (ordre de la légende) — couples (label_fr, label_en, [ids]).
_GLOSSAIRE_THEMES = [
    ("Astrologie occidentale", "Western Astrology",
        ["soleil", "lune", "ascendant"]),
    ("Astrologie chinoise", "Chinese Astrology",
        ["chinoise", "animal_heure"]),
    ("Astrologie védique", "Vedic Astrology",
        ["vedique", "nakshatra"]),
    ("Autres traditions", "Other Traditions",
        ["egypte", "celte", "totem", "maya"]),
    ("Numérologie", "Numerology",
        ["chemin_de_vie", "expression"]),
    ("Statistiques de personnalité", "Personality Stats",
        ["stat_charisme", "stat_combativite", "stat_sagesse", "stat_creativite",
         "stat_discretion", "stat_stabilite", "stat_emotivite", "stat_energie"]),
    ("Synthèse du portrait", "Portrait Synthesis",
        ["archetype", "forces", "faiblesse", "pierre"]),
]
_GLOSSAIRE_THEMES_IDS = [i for *_, lst in _GLOSSAIRE_THEMES for i in lst]


def glossaire(langue: str = "fr") -> list:
    """Légende lisible groupée par thèmes, pour la fin du document PDF.

    Renvoie : [{"theme": str, "items": [{"id": str, "label": str, "definition": str}]}].
    `langue="fr"` (défaut) ou `"en"`. Les ids sont stables, jamais traduits."""
    en = (langue or "fr").lower().startswith("en")
    labels = _GLOSSAIRE_LABELS_EN if en else _GLOSSAIRE_LABELS
    table = GLOSSAIRE_EN if en else GLOSSAIRE_FR
    out = []
    for theme_fr, theme_en, ids in _GLOSSAIRE_THEMES:
        out.append({
            "theme": theme_en if en else theme_fr,
            "items": [{"id": i, "label": labels[i],
                       "definition": table[i]} for i in ids],
        })
    return out


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


def _entree(cle: str, valeur: str, sens: str, role: str = "", id: str = "") -> dict:
    return {"cle": cle, "valeur": valeur, "sens": sens, "role": role, "id": id}


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
                            signes_sens.get(sol["nom"], ""), role_placement["soleil"], id="soleil"))
    lun = trad.get("signe_lunaire") or {}
    if lun.get("signe"):
        out.append(_entree(cle("Lune"), f"{nom(lun['signe'])} {lun.get('symbole','')}".strip(),
                            signes_sens.get(lun["signe"], ""), role_placement["lune"], id="lune"))
    asc = (trad.get("theme_astral") or {}).get("ascendant") or {}
    if asc.get("signe"):
        out.append(_entree(cle("Ascendant"), f"{nom(asc['signe'])} {asc.get('symbole','')}".strip(),
                            signes_sens.get(asc["signe"], ""), role_placement["ascendant"], id="ascendant"))
    chi = trad.get("signe_chinois") or {}
    if chi.get("animal"):
        elt = nom(chi.get("element", "")) if en else chi.get("element", "")
        liaison = "of" if en else "de"
        out.append(_entree(cle("Astrologie chinoise"), f"{nom(chi['animal'])} {liaison} {elt}".strip(),
                            chinois_sens.get(chi["animal"], ""), role("moi social"), id="chinoise"))
    ah = trad.get("animal_heure") or {}
    if ah.get("animal"):
        out.append(_entree(cle("Animal de l'heure"), nom(ah["animal"]),
                            chinois_sens.get(ah["animal"], ""), role("moi profond"), id="animal_heure"))
    ved = trad.get("vedique") or {}
    if ved.get("rashi"):
        out.append(_entree(cle("Védique (rashi)"), nom(ved["rashi"]),
                            signes_sens.get(ved["rashi"], ""), role_placement["vedique"], id="vedique"))
    nak = trad.get("nakshatra") or {}
    if nak.get("nakshatra"):
        out.append(_entree(cle("Nakshatra"), f"{nak['nakshatra']} (pada {nak.get('pada','?')})",
                            nakshatra_sens.get(nak["nakshatra"], ""), role("maison lunaire"), id="nakshatra"))
    if trad.get("egyptien"):
        out.append(_entree(cle("Égypte"), nom(trad["egyptien"]), egypte_sens.get(trad["egyptien"], ""),
                            role("divinité tutélaire"), id="egypte"))
    if trad.get("celte"):
        out.append(_entree(cle("Celte"), nom(trad["celte"]), celte_sens.get(trad["celte"], ""),
                            role("arbre protecteur"), id="celte"))
    if trad.get("amerindien"):
        out.append(_entree(cle("Totem amérindien"), nom(trad["amerindien"]),
                            totem_sens.get(trad["amerindien"], ""), role("animal totem"), id="totem"))
    maya = trad.get("maya") or {}
    if maya.get("glyphe"):
        tonalite_label = "tone" if en else "ton"
        out.append(_entree(cle("Maya (Tzolkin)"), f"{maya.get('tonalite','')} {maya['glyphe']}".strip(),
                            maya_sens.get(maya["glyphe"], ""),
                            f"{tonalite_label} {maya.get('tonalite','?')}/13", id="maya"))
    if isinstance(trad.get("chemin_de_vie"), int):
        out.append(_entree(cle("Chemin de vie"), str(trad["chemin_de_vie"]),
                            nombre_sens.get(trad["chemin_de_vie"], ""), role("destinée"), id="chemin_de_vie"))
    expr = (trad.get("numerologie_nom") or {}).get("expression")
    if isinstance(expr, int):
        out.append(_entree(cle("Expression (nom)"), str(expr),
                            nombre_sens.get(expr, ""), role("talents, tempérament"), id="expression"))
    return out
