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

# ── Clefs theme_complet (carte astro complète) ────────────────────
# Mots-clés pour les 10 corps, points évolutifs, aspects et dominantes
# de la carte astro complète (theme_complet). FR/EN dans la même table.
CLEFS_CORPS = {
    "Soleil":   {"fr": "identité, vitalité, essence consciente",
                 "en": "identity, vitality, conscious essence"},
    "Lune":     {"fr": "émotions, jardin secret, instincts",
                 "en": "emotions, inner world, instincts"},
    "Mercure":  {"fr": "communication, raisonnement, échanges",
                 "en": "communication, reasoning, exchanges"},
    "Vénus":    {"fr": "amour, valeurs, séduction",
                 "en": "love, values, attraction"},
    "Mars":     {"fr": "action, désir, combativité",
                 "en": "action, desire, drive"},
    "Jupiter":  {"fr": "expansion, vision, confiance",
                 "en": "expansion, vision, confidence"},
    "Saturne":  {"fr": "structure, limite, responsabilité",
                 "en": "structure, limit, responsibility"},
    "Uranus":   {"fr": "liberté, rupture, innovation",
                 "en": "freedom, disruption, innovation"},
    "Neptune":  {"fr": "rêve, compassion, dissolution",
                 "en": "dream, compassion, dissolution"},
    "Pluton":   {"fr": "transformation, pouvoir, régénération",
                 "en": "transformation, power, regeneration"},
}

CLEFS_POINTS_EVOLUTIFS = {
    "noeud_nord": {"fr": "direction de vie, évolution à intégrer",
                   "en": "life direction, evolution to integrate"},
    "noeud_sud":  {"fr": "acquis karmique, zone de confort à quitter",
                   "en": "karmic background, comfort zone to leave"},
    "chiron":     {"fr": "blessure et guérison, vulnérabilité enseignante",
                   "en": "wound and healing, teaching vulnerability"},
    "lilith":     {"fr": "ombre, désir refoulé, intuition sauvage",
                   "en": "shadow, repressed desire, wild intuition"},
}

CLEFS_ASPECTS = {
    "conjonction":  {"fr": "fusion des énergies", "en": "fusion of energies"},
    "opposition":   {"fr": "tension polarisée, mise en balance", "en": "polarized tension, balancing"},
    "trigone":      {"fr": "harmonie naturelle, flow", "en": "natural harmony, flow"},
    "carre":        {"fr": "tension constructive, défi à résoudre", "en": "constructive tension, challenge"},
    "sextile":      {"fr": "opportunité, coopération", "en": "opportunity, cooperation"},
    "semi_sextile": {"fr": "ajustement subtil", "en": "subtle adjustment"},
    "semi_carre":   {"fr": "friction mineure", "en": "minor friction"},
    "quintile":     {"fr": "créativité, talent", "en": "creativity, talent"},
    "sesquicarre":  {"fr": "tension créative", "en": "creative tension"},
    "quinconce":    {"fr": "désajustement, adaptation", "en": "mismatch, adaptation"},
}

CLEFS_DOMINANTES = {
    "element": {
        "Feu":   {"fr": "sensible, passionné, instinctif", "en": "passionate, instinctive"},
        "Terre": {"fr": "concret, pragmatique, stable", "en": "grounded, pragmatic, stable"},
        "Air":   {"fr": "mental, social, communicant", "en": "mental, social, communicative"},
        "Eau":   {"fr": "sensible, intuitif, empathique", "en": "sensitive, intuitive, empathic"},
    },
    "mode": {
        "Cardinal": {"fr": "initiateur, lanceur de projets", "en": "initiator, project starter"},
        "Fixe":     {"fr": "persévérant, constant", "en": "steadfast, persistent"},
        "Mutable":  {"fr": "adaptable, flexible", "en": "adaptable, flexible"},
    },
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
    # ── Carte astro complète (theme_complet) ───────────────────────
    "theme_fondation_soleil": (
        "Soleil — essence consciente, identité, ce que tu rayonnes. Dans la carte "
        "complète, il est le pilier central : tout s'organise autour de lui."
    ),
    "theme_fondation_lune": (
        "Lune — émotions, jardin secret, instincts. Pilier de ta vie intime, "
        "comment tu réagis au monde avant de penser."
    ),
    "theme_fondation_ascendant": (
        "Ascendant — masque social, première impression. Comment on te perçoit "
        "avant de te connaître. Pilier de ta vitrine extérieure."
    ),
    "theme_fondation_descendant": (
        "Descendant — axe relationnel opposé à l'Ascendant. Ce que tu cherches "
        "chez l'autre, comment tu te projettes dans le partenariat."
    ),
    "theme_fondation_milieu_du_ciel": (
        "Milieu du Ciel (MC) — vocation, destin public, axe de réalisation "
        "sociale. Ce que tu projettes dans le monde professionnel."
    ),
    "theme_fondation_fond_du_ciel": (
        "Fond du Ciel (IC) — racines, foyer intérieur, fondation privée. "
        "D'où tu viens, ton ancrage émotionnel le plus profond."
    ),
    "theme_corps_soleil": (
        "Soleil — identité consciente, vitalité. Le noyau de ta personnalité."
    ),
    "theme_corps_lune": (
        "Lune — émotions, instincts, besoins de sécurité. Ton jardin secret."
    ),
    "theme_corps_mercure": (
        "Mercure — communication, raisonnement, échanges. Comment tu penses et "
        "transmets tes idées."
    ),
    "theme_corps_vénus": (
        "Vénus — amour, valeurs, séduction. Ce que tu aimes et comment tu aimes."
    ),
    "theme_corps_mars": (
        "Mars — action, désir, combativité. Comment tu passes à l'acte."
    ),
    "theme_corps_jupiter": (
        "Jupiter — expansion, vision, confiance. Où tu grandis et prends du recul."
    ),
    "theme_corps_saturne": (
        "Saturne — structure, limite, responsabilité. Ce qui te cadre et te freine."
    ),
    "theme_corps_uranus": (
        "Uranus — liberté, rupture, innovation. Où tu sors du cadre et surprends."
    ),
    "theme_corps_neptune": (
        "Neptune — rêve, compassion, dissolution. Ce qui te fascine et t'efface."
    ),
    "theme_corps_pluton": (
        "Pluton — transformation, pouvoir, régénération. Ce qui meurt et renaît en toi."
    ),
    "theme_point_noeud_nord": (
        "Nœud Nord — direction de vie, évolution à intégrer. L'axe de croissance "
        "qui te demande un effort conscient."
    ),
    "theme_point_noeud_sud": (
        "Nœud Sud — acquis karmique, zone de confort. Ce que tu maîtrises déjà "
        "mais dois quitter pour grandir."
    ),
    "theme_point_chiron": (
        "Chiron — blessure et guérison. La vulnérabilité qui t'enseigne et "
        "t'ouvre à la compassion."
    ),
    "theme_point_lilith": (
        "Lilith — ombre, désir refoulé, intuition sauvage. La part libre et "
        "incontrôlable de ton psychisme."
    ),
    "theme_fondations": (
        "Fondations — les piliers du thème : Soleil, Lune, Ascendant/Descendant, "
        "Milieu du Ciel/Fond du Ciel. Ensemble, ils dessinent l'ossature de la "
        "personnalité avant même de regarder les planètes une à une."
    ),
    "theme_corps": (
        "Les 10 corps — les dix points célestes utilisés en astrologie occidentale "
        "(Soleil, Lune, Mercure, Vénus, Mars, Jupiter, Saturne, Uranus, Neptune, "
        "Pluton). Chacun représente une fonction psychique distincte ; son signe "
        "indique comment elle s'exprime, sa maison où."
    ),
    "theme_points_evolutifs": (
        "Points évolutifs — Nœuds lunaires, Chiron, Lilith : des points "
        "mathématiques (pas des corps physiques) qui marquent une trajectoire "
        "de transformation plutôt qu'un trait fixe."
    ),
    "maison_1": (
        "Maison 1 (Ascendant) — identité, apparence, façon d'aborder le monde. "
        "Le moi visible, le premier réflexe face à une situation nouvelle. "
        "À lire comme la porte d'entrée de toute la carte."
    ),
    "maison_2": (
        "Maison 2 — ressources, valeurs, argent, estime de soi. Ce que tu "
        "possèdes et ce que tu juges avoir de la valeur, y compris en toi-même. "
        "À lire comme ton rapport à la sécurité matérielle."
    ),
    "maison_3": (
        "Maison 3 — communication, apprentissage, entourage proche (fratrie, "
        "voisinage), petits déplacements. À lire comme ton style d'échange avec "
        "le monde immédiat."
    ),
    "maison_4": (
        "Maison 4 (Fond du Ciel) — foyer, racines, famille, vie privée. La base "
        "intime sur laquelle tout le reste s'appuie. À lire comme ton port "
        "d'attache émotionnel."
    ),
    "maison_5": (
        "Maison 5 — créativité, plaisir, romance, enfants, expression de soi. "
        "À lire comme ton terrain de jeu, ce qui te fait rayonner sans calcul."
    ),
    "maison_6": (
        "Maison 6 — travail quotidien, santé, service, habitudes. À lire comme "
        "l'organisation concrète de ta vie de tous les jours."
    ),
    "maison_7": (
        "Maison 7 (Descendant) — relations, partenariats, mariage. L'autre en "
        "miroir : ce que tu cherches ou attires chez autrui. À lire comme l'axe "
        "« moi face à l'autre », opposé à la maison 1."
    ),
    "maison_8": (
        "Maison 8 — transformation, intimité profonde, ressources partagées, "
        "crises et renaissances. À lire comme ce qui te change en profondeur, "
        "rarement en douceur."
    ),
    "maison_9": (
        "Maison 9 — expansion, voyages lointains, philosophie, sens, études "
        "supérieures. À lire comme ta quête d'horizon, mentale ou géographique."
    ),
    "maison_10": (
        "Maison 10 (Milieu du Ciel) — vocation, carrière, image publique, "
        "réussite sociale. À lire comme ce que tu montres au monde et ce que le "
        "monde retient de toi."
    ),
    "maison_11": (
        "Maison 11 — amis, groupes, projets collectifs, idéaux. À lire comme "
        "ton réseau et les causes plus grandes que toi auxquelles tu "
        "participes."
    ),
    "maison_12": (
        "Maison 12 — inconscient, retrait, spiritualité, épreuves cachées, "
        "lâcher-prise. À lire comme la part la plus discrète de toi, souvent la "
        "plus difficile à nommer."
    ),
    "theme_maisons": (
        "Maisons — douze secteurs de l'expérience de vie. Chaque maison indique "
        "où se jouent les énergies planétaires : maison 1 = identité, "
        "maison 7 = relations, maison 10 = carrière, maison 4 = foyer."
    ),
    "theme_aspects": (
        "Aspects — angles entre les planètes. Un aspect relie deux énergies : "
        "harmonie (trigone, sextile), tension (carré, opposition), fusion "
        "(conjonction). Plus l'orbe est petit, plus l'aspect est exact et puissant."
    ),
    "theme_aspect_conjonction": (
        "Conjonction (0°) — fusion des énergies. Les deux planètes agissent "
        "ensemble, se renforcent ou se confondent."
    ),
    "theme_aspect_opposition": (
        "Opposition (180°) — tension polarisée. Deux forces contraires "
        "qu'il faut équilibrer par la conscience."
    ),
    "theme_aspect_trigone": (
        "Trigone (120°) — harmonie naturelle. Flux d'énergie fluide, "
        "talent inné, aisance."
    ),
    "theme_aspect_carre": (
        "Carré (90°) — tension constructive. Conflit interne qui pousse "
        "à l'action et forge le caractère."
    ),
    "theme_aspect_sextile": (
        "Sextile (60°) — opportunité, coopération. Une facilité à activer "
        "consciemment."
    ),
    "theme_axe_noeuds": (
        "Axe des Nœuds — Nœud Nord et Nœud Sud sont toujours exactement à "
        "l'opposé l'un de l'autre (180°), par construction géométrique, jamais "
        "par calcul d'aspect. Le Nœud Sud représente les acquis, les automatismes "
        "du passé ; le Nœud Nord, la direction vers laquelle grandir. Cet axe "
        "n'est pas un aspect au sens classique mais la colonne vertébrale du "
        "chemin karmique du thème."
    ),
    "theme_axe_horizon": (
        "Axe Ascendant-Descendant — l'Ascendant et le Descendant sont toujours "
        "exactement opposés (180°), par définition géométrique (l'horizon a deux "
        "bouts). L'Ascendant = comment tu abordes le monde ; le Descendant = ce "
        "que tu cherches chez l'autre, en miroir. À lire comme l'axe du « moi "
        "face à l'autre »."
    ),
    "theme_axe_meridien": (
        "Axe Milieu du Ciel-Fond du Ciel — le Milieu du Ciel (MC) et le Fond du "
        "Ciel (FC/IC) sont toujours exactement opposés (180°), par définition "
        "géométrique (le méridien a deux bouts). Le MC = vocation, image "
        "publique ; le FC = racines, vie privée. À lire comme l'axe « public "
        "face à intime »."
    ),
    "theme_dominante_element": (
        "Élément dominant (Feu, Terre, Air, Eau) — tempérament global. "
        "Feu = passion, Terre = pragmatisme, Air = mental, Eau = sensibilité."
    ),
    "theme_dominante_mode": (
        "Mode dominant (Cardinal, Fixe, Mutable) — style d'action. "
        "Cardinal = initier, Fixe = persévérer, Mutable = s'adapter."
    ),
    "theme_dominante_planete": (
        "Planète dominante — l'énergie qui colore tout le thème. "
        "Déterminée par sa position, sa dignité, sa vitesse et ses aspects."
    ),
    "theme_dominante_signe": (
        "Signe dominant — la teinte qui imprègne la personnalité. "
        "Souvent lié au signe de la planète dominante."
    ),
    "theme_dominante_maison": (
        "Maison dominante — le domaine de vie le plus actif. "
        "Là où l'énergie du thème se concentre et se manifeste."
    ),
    "theme_dominantes": (
        "Dominantes — synthèse de ce qui ressort le plus du thème : élément, "
        "mode, planète, signe et maison dominants. À lire comme la signature "
        "globale qui se dégage de l'ensemble de la carte."
    ),
}

# ══════════════════════════════════════════════════════════════════
# Couche didactique — cartes pédagogiques de l'onglet « Carte astro
# complète ». Chaque entrée = {question, domaines[], conclusion}.
# La clé est un id glossaire EXISTANT (pas de nouvel id) ; on l'enrichit
# d'une facette didactique. Soleil & Lune ont 2 facettes distinctes
# (pilier = theme_fondation_*, corps = theme_corps_*), ce qui rend la
# double présence §1/§2 explicite plutôt qu'un doublon.
# ══════════════════════════════════════════════════════════════════
DIDACTIQUE_FR = {
    # ── §1 Fondations (facette pilier) ──
    "theme_fondation_soleil": {
        "question": "Qui suis-je ?",
        "domaines": ["identité consciente", "volonté", "affirmation de soi",
                     "ce que tu cherches à devenir", "manière de rayonner"],
        "conclusion": "Soleil = ton centre",
    },
    "theme_fondation_lune": {
        "question": "De quoi ai-je besoin intérieurement ?",
        "domaines": ["émotions", "besoins affectifs", "sécurité",
                     "réactions instinctives", "monde intérieur",
                     "habitudes émotionnelles"],
        "conclusion": "Lune = ton monde intérieur",
    },
    "theme_fondation_ascendant": {
        "question": "Comment j'entre dans le monde ?",
        "domaines": ["première impression", "comportement spontané",
                     "manière d'aborder la vie", "façon dont tu te présentes",
                     "réflexes face au monde"],
        "conclusion": "Ascendant = ta porte d'entrée",
    },
    "theme_fondation_descendant": {
        "question": "Qui est l'autre ?",
        "domaines": ["couple", "partenaires", "associations",
                     "relations importantes",
                     "qualités recherchées chez l'autre"],
        "conclusion": "Ascendant = moi, Descendant = l'autre",
    },
    "theme_fondation_milieu_du_ciel": {
        "question": "Où vais-je dans le monde ?",
        "domaines": ["vocation", "carrière", "ambition", "réputation",
                     "réussite sociale", "contribution au monde"],
        "conclusion": "MC = ce que tu cherches à accomplir",
    },
    "theme_fondation_fond_du_ciel": {
        "question": "D'où est-ce que je viens ?",
        "domaines": ["racines", "famille", "enfance", "foyer",
                     "intimité", "sentiment d'appartenance", "monde privé"],
        "conclusion": "IC = tes racines, MC = ton accomplissement",
    },
    # ── §2 10 corps (facette corps) ──
    "theme_corps_soleil": {
        "question": "Comment je rayonne au quotidien ?",
        "domaines": ["vitalité", "identité consciente", "ce que tu exprimes"],
        "conclusion": "Soleil = ton noyau",
    },
    "theme_corps_lune": {
        "question": "Comment réagis-je instinctivement ?",
        "domaines": ["instincts", "réactions", "besoins immédiats"],
        "conclusion": "Lune = tes réflexes émotionnels",
    },
    "theme_corps_mercure": {
        "question": "Comment je pense ?",
        "domaines": ["pensée", "communication", "langage",
                     "raisonnement", "apprentissage",
                     "manière de traiter l'information"],
        "conclusion": "Mercure = ton fonctionnement mental",
    },
    "theme_corps_vénus": {
        "question": "Comment j'aime ?",
        "domaines": ["amour", "attraction", "relations", "plaisir",
                     "beauté", "valeurs", "rapport au confort"],
        "conclusion": "Vénus = ce qui t'attire",
    },
    "theme_corps_mars": {
        "question": "Comment j'agis ?",
        "domaines": ["action", "désir", "volonté", "énergie",
                     "affirmation", "confrontation"],
        "conclusion": "Mars = comment tu passes de l'intention à l'acte",
    },
    "theme_corps_jupiter": {
        "question": "Comment je grandis ?",
        "domaines": ["expansion", "confiance", "opportunités",
                     "philosophie", "connaissances", "transmission",
                     "recherche de sens"],
        "conclusion": "Jupiter = ce qui te permet de grandir",
    },
    "theme_corps_saturne": {
        "question": "Où dois-je apprendre la maîtrise ?",
        "domaines": ["responsabilités", "limites", "discipline",
                     "structure", "contraintes", "maturité",
                     "construction à long terme"],
        "conclusion": "Saturne = ta zone de maîtrise à construire",
    },
    "theme_corps_uranus": {
        "question": "Où ai-je besoin de liberté ?",
        "domaines": ["innovation", "indépendance", "rupture",
                     "changement", "originalité", "révolution"],
        "conclusion": "Uranus = où tu sors du cadre",
    },
    "theme_corps_neptune": {
        "question": "Où suis-je idéaliste ?",
        "domaines": ["imagination", "intuition", "rêves",
                     "spiritualité", "idéaux", "compassion",
                     "dissolution des frontières"],
        "conclusion": "Neptune = tes idéaux (et tes illusions)",
    },
    "theme_corps_pluton": {
        "question": "Où dois-je me transformer ?",
        "domaines": ["transformation profonde", "pouvoir", "crises",
                     "destruction/reconstruction", "obsessions", "renaissance"],
        "conclusion": "Pluton = ce qui meurt et renaît en toi",
    },
    # ── §3 Points évolutifs ──
    "theme_point_noeud_nord": {
        "question": "Vers quoi évoluer ?",
        "domaines": ["direction de vie", "évolution à intégrer",
                     "axe de croissance consciente"],
        "conclusion": "Nœud Nord = ce vers quoi évoluer",
    },
    "theme_point_noeud_sud": {
        "question": "Qu'est-ce qui est familier ?",
        "domaines": ["acquis karmique", "zone de confort",
                     "ce que tu maîtrises déjà"],
        "conclusion": "Nœud Sud = ce que tu maîtrises mais dois quitter",
    },
    "theme_point_chiron": {
        "question": "Quelle blessure peut devenir une force ?",
        "domaines": ["blessure profonde", "compréhension acquise",
                     "capacité de transmission"],
        "conclusion": "Chiron = vulnérabilité → compréhension → transmission",
    },
    "theme_point_lilith": {
        "question": "Où se trouve mon côté indomptable ?",
        "domaines": ["indépendance", "désir refoulé", "refus des normes",
                     "instinct sauvage", "ce qu'on ne veut pas soumettre"],
        "conclusion": "Lilith = ta part d'ombre libre",
    },
    # ── §1/§2/§3 Intros de section ──
    "theme_fondations": {
        "question": "Qui es-tu à la base ?",
        "domaines": ["Soleil = identité consciente", "Lune = besoins émotionnels",
                     "Ascendant/Descendant = axe de l'horizon",
                     "Milieu du Ciel/Fond du Ciel = axe vertical, vocation/racines"],
        "conclusion": "Les fondations = le squelette du thème",
    },
    "theme_corps": {
        "question": "Quelles énergies agissent en toi ?",
        "domaines": ["10 corps célestes = 10 énergies distinctes",
                     "chaque planète = un besoin ou une fonction psychique",
                     "son signe = comment cette énergie s'exprime",
                     "sa maison = où elle s'exprime"],
        "conclusion": "Les 10 corps = l'orchestre complet de la personnalité",
    },
    "theme_points_evolutifs": {
        "question": "Où se joue ton évolution ?",
        "domaines": ["Nœuds lunaires = axe karmique (passé → futur)",
                     "Chiron = blessure à transformer en force",
                     "Lilith = part sauvage et indomptée",
                     "ce sont des points, pas des planètes"],
        "conclusion": "Les points évolutifs = la trajectoire, pas la photo",
    },
    # ── §4/§5/§6 Intros de section ──
    "theme_maisons": {
        "question": "Où se joue cette énergie ?",
        "domaines": ["douze secteurs de l'expérience de vie",
                     "1=identité, 4=foyer, 7=relations, 10=carrière",
                     "chaque secteur localise une énergie planétaire"],
        "conclusion": "La planète dit QUOI, la maison dit OÙ",
    },
    "theme_aspects": {
        "question": "Comment les parties communiquent entre elles ?",
        "domaines": ["angles entre planètes", "harmonie (trigone, sextile)",
                     "tension (carré, opposition)", "fusion (conjonction)"],
        "conclusion": "Plus l'orbe est petit, plus l'aspect est exact",
    },
    "theme_dominantes": {
        "question": "Qu'est-ce qui ressort le plus du thème ?",
        "domaines": ["famille d'élément dominante", "style d'action (mode)",
                     "planète structurante", "signe récurrent",
                     "domaine de vie le plus actif"],
        "conclusion": "Les dominantes = la synthèse qui se dégage",
    },
}

DIDACTIQUE_EN = {
    # ── §1 Foundations (pillar facet) ──
    "theme_fondation_soleil": {
        "question": "Who am I?",
        "domaines": ["conscious identity", "will", "self-assertion",
                     "what you strive to become", "how you shine"],
        "conclusion": "Sun = your core",
    },
    "theme_fondation_lune": {
        "question": "What do I need inwardly?",
        "domaines": ["emotions", "affective needs", "security",
                     "instinctive reactions", "inner world",
                     "emotional habits"],
        "conclusion": "Moon = your inner world",
    },
    "theme_fondation_ascendant": {
        "question": "How do I enter the world?",
        "domaines": ["first impression", "spontaneous behavior",
                     "way of approaching life", "how you present yourself",
                     "reflexes toward the world"],
        "conclusion": "Ascendant = your gateway",
    },
    "theme_fondation_descendant": {
        "question": "Who is the other?",
        "domaines": ["couple", "partners", "associations",
                     "significant relationships",
                     "qualities sought in the other"],
        "conclusion": "Ascendant = self, Descendant = the other",
    },
    "theme_fondation_milieu_du_ciel": {
        "question": "Where am I going in the world?",
        "domaines": ["vocation", "career", "ambition", "reputation",
                     "social success", "contribution to the world"],
        "conclusion": "MC = what you seek to accomplish",
    },
    "theme_fondation_fond_du_ciel": {
        "question": "Where do I come from?",
        "domaines": ["roots", "family", "childhood", "home",
                     "intimacy", "sense of belonging", "private world"],
        "conclusion": "IC = your roots, MC = your accomplishment",
    },
    # ── §2 Ten bodies (body facet) ──
    "theme_corps_soleil": {
        "question": "How do I shine day to day?",
        "domaines": ["vitality", "conscious identity", "what you express"],
        "conclusion": "Sun = your nucleus",
    },
    "theme_corps_lune": {
        "question": "How do I react instinctively?",
        "domaines": ["instincts", "reactions", "immediate needs"],
        "conclusion": "Moon = your emotional reflexes",
    },
    "theme_corps_mercure": {
        "question": "How do I think?",
        "domaines": ["thought", "communication", "language",
                     "reasoning", "learning", "how you process information"],
        "conclusion": "Mercury = your mental wiring",
    },
    "theme_corps_vénus": {
        "question": "How do I love?",
        "domaines": ["love", "attraction", "relationships", "pleasure",
                     "beauty", "values", "relationship to comfort"],
        "conclusion": "Venus = what draws you",
    },
    "theme_corps_mars": {
        "question": "How do I act?",
        "domaines": ["action", "desire", "will", "energy",
                     "assertion", "confrontation"],
        "conclusion": "Mars = how you turn intent into action",
    },
    "theme_corps_jupiter": {
        "question": "How do I grow?",
        "domaines": ["expansion", "confidence", "opportunities",
                     "philosophy", "knowledge", "transmission",
                     "search for meaning"],
        "conclusion": "Jupiter = what lets you grow",
    },
    "theme_corps_saturne": {
        "question": "Where must I learn mastery?",
        "domaines": ["responsibilities", "limits", "discipline",
                     "structure", "constraints", "maturity",
                     "long-term building"],
        "conclusion": "Saturn = your mastery zone to build",
    },
    "theme_corps_uranus": {
        "question": "Where do I need freedom?",
        "domaines": ["innovation", "independence", "rupture",
                     "change", "originality", "revolution"],
        "conclusion": "Uranus = where you break the mold",
    },
    "theme_corps_neptune": {
        "question": "Where am I idealistic?",
        "domaines": ["imagination", "intuition", "dreams",
                     "spirituality", "ideals", "compassion",
                     "dissolution of boundaries"],
        "conclusion": "Neptune = your ideals (and illusions)",
    },
    "theme_corps_pluton": {
        "question": "Where must I transform?",
        "domaines": ["deep transformation", "power", "crises",
                     "destruction/reconstruction", "obsessions", "rebirth"],
        "conclusion": "Pluto = what dies and is reborn in you",
    },
    # ── §3 Evolutionary points ──
    "theme_point_noeud_nord": {
        "question": "Toward what to evolve?",
        "domaines": ["life direction", "evolution to integrate",
                     "axis of conscious growth"],
        "conclusion": "North Node = what to evolve toward",
    },
    "theme_point_noeud_sud": {
        "question": "What is familiar?",
        "domaines": ["karmic acquisition", "comfort zone",
                     "what you already master"],
        "conclusion": "South Node = what you master but must leave",
    },
    "theme_point_chiron": {
        "question": "Which wound can become a strength?",
        "domaines": ["deep wound", "acquired understanding",
                     "capacity for transmission"],
        "conclusion": "Chiron = vulnerability → understanding → transmission",
    },
    "theme_point_lilith": {
        "question": "Where is my untamed side?",
        "domaines": ["independence", "repressed desire", "refusal of norms",
                     "wild instinct", "what you won't submit"],
        "conclusion": "Lilith = your free shadow",
    },
    # ── §1/§2/§3 Section intros ──
    "theme_fondations": {
        "question": "Who are you at your core?",
        "domaines": ["Sun = conscious identity", "Moon = emotional needs",
                     "Ascendant/Descendant = horizon axis",
                     "Midheaven/IC = vertical axis, vocation/roots"],
        "conclusion": "The foundations = the skeleton of the chart",
    },
    "theme_corps": {
        "question": "What energies are at work in you?",
        "domaines": ["10 celestial bodies = 10 distinct energies",
                     "each planet = a need or a psychic function",
                     "its sign = how that energy expresses itself",
                     "its house = where it expresses itself"],
        "conclusion": "The 10 bodies = the full orchestra of the personality",
    },
    "theme_points_evolutifs": {
        "question": "Where is your growth happening?",
        "domaines": ["lunar Nodes = karmic axis (past → future)",
                     "Chiron = wound to transform into strength",
                     "Lilith = wild, untamed part",
                     "these are points, not planets"],
        "conclusion": "The evolutionary points = the trajectory, not the snapshot",
    },
    # ── §4/§5/§6 Section intros ──
    "theme_maisons": {
        "question": "Where does this energy play out?",
        "domaines": ["twelve sectors of life experience",
                     "1=identity, 4=home, 7=relationships, 10=career",
                     "each sector localizes a planetary energy"],
        "conclusion": "The planet says WHAT, the house says WHERE",
    },
    "theme_aspects": {
        "question": "How do the parts communicate?",
        "domaines": ["angles between planets", "harmony (trine, sextile)",
                     "tension (square, opposition)", "fusion (conjunction)"],
        "conclusion": "The smaller the orb, the more exact the aspect",
    },
    "theme_dominantes": {
        "question": "What stands out most in the chart?",
        "domaines": ["dominant element family", "action style (mode)",
                     "structuring planet", "recurring sign",
                     "most active life domain"],
        "conclusion": "The dominants = the synthesis that emerges",
    },
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
    # ── Complete astro chart (theme_complet) ───────────────────────
    "theme_fondation_soleil": (
        "Sun — conscious essence, identity, what you radiate. In the complete "
        "chart, it is the central pillar: everything organizes around it."
    ),
    "theme_fondation_lune": (
        "Moon — emotions, secret garden, instincts. Pillar of your inner life, "
        "how you react to the world before thinking."
    ),
    "theme_fondation_ascendant": (
        "Ascendant — social mask, first impression. How others perceive you "
        "before knowing you. Pillar of your outer display."
    ),
    "theme_fondation_descendant": (
        "Descendant — relational axis opposite the Ascendant. What you seek "
        "in others, how you project into partnership."
    ),
    "theme_fondation_milieu_du_ciel": (
        "Midheaven (MC) — vocation, public destiny, social achievement axis. "
        "What you project into the professional world."
    ),
    "theme_fondation_fond_du_ciel": (
        "Imum Coeli (IC) — roots, inner home, private foundation. Where you "
        "come from, your deepest emotional anchor."
    ),
    "theme_corps_soleil": (
        "Sun — conscious identity, vitality. The core of your personality."
    ),
    "theme_corps_lune": (
        "Moon — emotions, instincts, security needs. Your secret garden."
    ),
    "theme_corps_mercure": (
        "Mercury — communication, reasoning, exchanges. How you think and "
        "convey your ideas."
    ),
    "theme_corps_vénus": (
        "Venus — love, values, attraction. What you love and how you love."
    ),
    "theme_corps_mars": (
        "Mars — action, desire, drive. How you spring into action."
    ),
    "theme_corps_jupiter": (
        "Jupiter — expansion, vision, confidence. Where you grow and gain perspective."
    ),
    "theme_corps_saturne": (
        "Saturn — structure, limit, responsibility. What frames and restrains you."
    ),
    "theme_corps_uranus": (
        "Uranus — freedom, disruption, innovation. Where you break the mold and surprise."
    ),
    "theme_corps_neptune": (
        "Neptune — dream, compassion, dissolution. What fascinates and dissolves you."
    ),
    "theme_corps_pluton": (
        "Pluto — transformation, power, regeneration. What dies and is reborn in you."
    ),
    "theme_point_noeud_nord": (
        "North Node — life direction, evolution to integrate. The growth axis "
        "that asks for conscious effort."
    ),
    "theme_point_noeud_sud": (
        "South Node — karmic background, comfort zone. What you already master "
        "but must leave behind to grow."
    ),
    "theme_point_chiron": (
        "Chiron — wound and healing. The vulnerability that teaches you "
        "and opens you to compassion."
    ),
    "theme_point_lilith": (
        "Lilith — shadow, repressed desire, wild intuition. The free and "
        "uncontrollable part of your psyche."
    ),
    "theme_fondations": (
        "Foundations — the pillars of the chart: Sun, Moon, Ascendant/Descendant, "
        "Midheaven/IC. Together they draw the skeleton of the personality before "
        "even looking at the planets one by one."
    ),
    "theme_corps": (
        "The 10 bodies — the ten celestial points used in Western astrology "
        "(Sun, Moon, Mercury, Venus, Mars, Jupiter, Saturn, Uranus, Neptune, "
        "Pluto). Each represents a distinct psychic function; its sign shows "
        "how it expresses, its house shows where."
    ),
    "theme_points_evolutifs": (
        "Evolutionary points — Lunar Nodes, Chiron, Lilith: mathematical points "
        "(not physical bodies) that mark a trajectory of transformation rather "
        "than a fixed trait."
    ),
    "maison_1": (
        "House 1 (Ascendant) — identity, appearance, how you approach the "
        "world. The visible self, the first reflex facing a new situation. "
        "Read as the entry door to the whole chart."
    ),
    "maison_2": (
        "House 2 — resources, values, money, self-worth. What you own and "
        "what you consider valuable, including in yourself. Read as your "
        "relationship to material security."
    ),
    "maison_3": (
        "House 3 — communication, learning, close circle (siblings, "
        "neighborhood), short trips. Read as your style of exchange with the "
        "immediate world."
    ),
    "maison_4": (
        "House 4 (IC) — home, roots, family, private life. The intimate base "
        "everything else rests on. Read as your emotional home port."
    ),
    "maison_5": (
        "House 5 — creativity, pleasure, romance, children, self-expression. "
        "Read as your playground, what makes you shine without calculation."
    ),
    "maison_6": (
        "House 6 — daily work, health, service, habits. Read as the concrete "
        "organization of your everyday life."
    ),
    "maison_7": (
        "House 7 (Descendant) — relationships, partnerships, marriage. The "
        "other as a mirror: what you seek or attract in others. Read as the "
        "\"self facing other\" axis, opposite House 1."
    ),
    "maison_8": (
        "House 8 — transformation, deep intimacy, shared resources, crises "
        "and rebirths. Read as what changes you in depth, rarely gently."
    ),
    "maison_9": (
        "House 9 — expansion, long journeys, philosophy, meaning, higher "
        "education. Read as your quest for horizon, mental or geographic."
    ),
    "maison_10": (
        "House 10 (Midheaven) — vocation, career, public image, social "
        "achievement. Read as what you show the world and what the world "
        "remembers of you."
    ),
    "maison_11": (
        "House 11 — friends, groups, collective projects, ideals. Read as "
        "your network and the causes bigger than yourself you take part in."
    ),
    "maison_12": (
        "House 12 — the unconscious, withdrawal, spirituality, hidden trials, "
        "letting go. Read as the most discreet part of you, often the hardest "
        "to name."
    ),
    "theme_maisons": (
        "Houses — twelve sectors of life experience. Each house indicates where "
        "planetary energies play out: house 1 = identity, house 7 = relationships, "
        "house 10 = career, house 4 = home."
    ),
    "theme_aspects": (
        "Aspects — angles between planets. An aspect links two energies: "
        "harmony (trine, sextile), tension (square, opposition), fusion "
        "(conjunction). The smaller the orb, the more exact and powerful the aspect."
    ),
    "theme_aspect_conjonction": (
        "Conjunction (0°) — fusion of energies. The two planets act together, "
        "reinforce or merge."
    ),
    "theme_aspect_opposition": (
        "Opposition (180°) — polarized tension. Two opposing forces "
        "to be balanced through awareness."
    ),
    "theme_aspect_trigone": (
        "Trine (120°) — natural harmony. Smooth energy flow, innate talent, ease."
    ),
    "theme_aspect_carre": (
        "Square (90°) — constructive tension. Inner conflict that drives "
        "action and forges character."
    ),
    "theme_aspect_sextile": (
        "Sextile (60°) — opportunity, cooperation. A facilitation to "
        "activate consciously."
    ),
    "theme_axe_noeuds": (
        "Nodal Axis — the North Node and South Node are always exactly "
        "opposite each other (180°), by geometric construction, never by "
        "aspect calculation. The South Node represents past habits and "
        "acquired traits; the North Node, the direction to grow toward. This "
        "axis isn't an aspect in the classical sense but the backbone of the "
        "chart's karmic path."
    ),
    "theme_axe_horizon": (
        "Ascendant-Descendant Axis — the Ascendant and Descendant are always "
        "exactly opposite (180°), by geometric definition (the horizon has two "
        "ends). The Ascendant = how you approach the world; the Descendant = "
        "what you seek in others, as a mirror. Read as the axis of \"self "
        "facing other\"."
    ),
    "theme_axe_meridien": (
        "Midheaven-IC Axis — the Midheaven (MC) and the IC are always exactly "
        "opposite (180°), by geometric definition (the meridian has two ends). "
        "The MC = vocation, public image; the IC = roots, private life. Read "
        "as the axis of \"public facing private\"."
    ),
    "theme_dominante_element": (
        "Dominant element (Fire, Earth, Air, Water) — overall temperament. "
        "Fire = passion, Earth = pragmatism, Air = mental, Water = sensitivity."
    ),
    "theme_dominante_mode": (
        "Dominant mode (Cardinal, Fixed, Mutable) — action style. "
        "Cardinal = initiate, Fixed = persist, Mutable = adapt."
    ),
    "theme_dominante_planete": (
        "Dominant planet — the energy that colors the whole chart. "
        "Determined by its position, dignity, speed and aspects."
    ),
    "theme_dominante_signe": (
        "Dominant sign — the tint permeating the personality. "
        "Often linked to the dominant planet's sign."
    ),
    "theme_dominante_maison": (
        "Dominant house — the most active life domain. "
        "Where the chart's energy concentrates and manifests."
    ),
    "theme_dominantes": (
        "Dominants — synthesis of what stands out most in the chart: "
        "dominant element, mode, planet, sign and house. Read as the overall "
        "signature that emerges from the whole chart."
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
    # Carte astro complète
    "theme_fondation_soleil": "Soleil (fondation)", "theme_fondation_lune": "Lune (fondation)",
    "theme_fondation_ascendant": "Ascendant (fondation)", "theme_fondation_descendant": "Descendant (fondation)",
    "theme_fondation_milieu_du_ciel": "MC (fondation)", "theme_fondation_fond_du_ciel": "IC (fondation)",
    "theme_corps_soleil": "Soleil", "theme_corps_lune": "Lune", "theme_corps_mercure": "Mercure",
    "theme_corps_vénus": "Vénus", "theme_corps_mars": "Mars", "theme_corps_jupiter": "Jupiter",
    "theme_corps_saturne": "Saturne", "theme_corps_uranus": "Uranus", "theme_corps_neptune": "Neptune",
    "theme_corps_pluton": "Pluton",
    "theme_point_noeud_nord": "Nœud Nord", "theme_point_noeud_sud": "Nœud Sud",
    "theme_point_chiron": "Chiron", "theme_point_lilith": "Lilith",
    "theme_fondations": "Fondations", "theme_corps": "Les 10 corps",
    "theme_points_evolutifs": "Points évolutifs",
    "maison_1": "Maison 1", "maison_2": "Maison 2", "maison_3": "Maison 3",
    "maison_4": "Maison 4", "maison_5": "Maison 5", "maison_6": "Maison 6",
    "maison_7": "Maison 7", "maison_8": "Maison 8", "maison_9": "Maison 9",
    "maison_10": "Maison 10", "maison_11": "Maison 11", "maison_12": "Maison 12",
    "theme_maisons": "Maisons", "theme_aspects": "Aspects",
    "theme_aspect_conjonction": "Conjonction", "theme_aspect_opposition": "Opposition",
    "theme_aspect_trigone": "Trigone", "theme_aspect_carre": "Carré",
    "theme_aspect_sextile": "Sextile",
    "theme_axe_noeuds": "Axe des Nœuds", "theme_axe_horizon": "Axe Ascendant-Descendant",
    "theme_axe_meridien": "Axe Milieu du Ciel-Fond du Ciel",
    "theme_dominante_element": "Élément dominant", "theme_dominante_mode": "Mode dominant",
    "theme_dominante_planete": "Planète dominante", "theme_dominante_signe": "Signe dominant",
    "theme_dominante_maison": "Maison dominante",
    "theme_dominantes": "Dominantes",
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
    # Complete astro chart
    "theme_fondation_soleil": "Sun (foundation)", "theme_fondation_lune": "Moon (foundation)",
    "theme_fondation_ascendant": "Ascendant (foundation)", "theme_fondation_descendant": "Descendant (foundation)",
    "theme_fondation_milieu_du_ciel": "MC (foundation)", "theme_fondation_fond_du_ciel": "IC (foundation)",
    "theme_corps_soleil": "Sun", "theme_corps_lune": "Moon", "theme_corps_mercure": "Mercury",
    "theme_corps_vénus": "Venus", "theme_corps_mars": "Mars", "theme_corps_jupiter": "Jupiter",
    "theme_corps_saturne": "Saturn", "theme_corps_uranus": "Uranus", "theme_corps_neptune": "Neptune",
    "theme_corps_pluton": "Pluto",
    "theme_point_noeud_nord": "North Node", "theme_point_noeud_sud": "South Node",
    "theme_point_chiron": "Chiron", "theme_point_lilith": "Lilith",
    "theme_fondations": "Foundations", "theme_corps": "The 10 bodies",
    "theme_points_evolutifs": "Evolutionary points",
    "maison_1": "House 1", "maison_2": "House 2", "maison_3": "House 3",
    "maison_4": "House 4", "maison_5": "House 5", "maison_6": "House 6",
    "maison_7": "House 7", "maison_8": "House 8", "maison_9": "House 9",
    "maison_10": "House 10", "maison_11": "House 11", "maison_12": "House 12",
    "theme_maisons": "Houses", "theme_aspects": "Aspects",
    "theme_aspect_conjonction": "Conjunction", "theme_aspect_opposition": "Opposition",
    "theme_aspect_trigone": "Trine", "theme_aspect_carre": "Square",
    "theme_aspect_sextile": "Sextile",
    "theme_axe_noeuds": "Nodal Axis", "theme_axe_horizon": "Ascendant-Descendant Axis",
    "theme_axe_meridien": "Midheaven-IC Axis",
    "theme_dominante_element": "Dominant Element", "theme_dominante_mode": "Dominant Mode",
    "theme_dominante_planete": "Dominant Planet", "theme_dominante_signe": "Dominant Sign",
    "theme_dominante_maison": "Dominant House",
    "theme_dominantes": "Dominants",
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
    ("Carte astro complète", "Complete Astro Chart",
        ["theme_fondations",
         "theme_fondation_soleil", "theme_fondation_lune", "theme_fondation_ascendant",
         "theme_fondation_descendant", "theme_fondation_milieu_du_ciel", "theme_fondation_fond_du_ciel",
         "theme_corps",
         "theme_corps_soleil", "theme_corps_lune", "theme_corps_mercure", "theme_corps_vénus",
         "theme_corps_mars", "theme_corps_jupiter", "theme_corps_saturne", "theme_corps_uranus",
         "theme_corps_neptune", "theme_corps_pluton",
         "theme_points_evolutifs",
         "theme_point_noeud_nord", "theme_point_noeud_sud", "theme_point_chiron", "theme_point_lilith",
         "theme_maisons",
         "maison_1", "maison_2", "maison_3", "maison_4", "maison_5", "maison_6",
         "maison_7", "maison_8", "maison_9", "maison_10", "maison_11", "maison_12",
         "theme_aspects",
         "theme_aspect_conjonction", "theme_aspect_opposition", "theme_aspect_trigone",
         "theme_aspect_carre", "theme_aspect_sextile",
         "theme_axe_noeuds", "theme_axe_horizon", "theme_axe_meridien",
         "theme_dominante_element", "theme_dominante_mode", "theme_dominante_planete",
          "theme_dominante_signe", "theme_dominante_maison", "theme_dominantes"]),
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


def expliquer(trad: dict, langue: str = "fr",
              theme_complet: dict | None = None) -> list:
    """Empreinte LISIBLE : pour chaque tradition calculée, {clé, valeur, sens, rôle}.

    Ordonnée comme on la lit (Soleil → Lune → Ascendant → … → numérologie). Une section
    absente est simplement omise. C'est ce que le front affiche sous le portrait.

    `langue="fr"` (défaut) : comportement STRICTEMENT identique à avant l'i18n (S194).
    `langue="en"` : mêmes clés JSON, valeurs traduites (noms de signes/animaux/tables de
    sens en anglais ; Maya et Nakshatra gardent leurs noms d'origine, comme en anglais).

    Si `theme_complet` est fourni, ajoute une sous-section « carte astro complète » avec
    les clefs des 10 corps, points évolutifs, aspects majeurs, dominantes."""
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

    if theme_complet:
        out.extend(_expliquer_theme_complet(theme_complet, "en" if en else "fr"))

    return out


# Axes structurels — paires toujours en opposition par construction géométrique
# (jamais par calcul d'aspect). Id stable par paire, indépendant du type d'aspect
# (qui serait de toute façon toujours "opposition" ici). Toute autre paire (ex.
# Nœud-Lilith, dont le type varie selon la personne) retombe sur l'id générique
# `theme_aspect_{type}` déjà présent dans le glossaire.
_AXES_STRUCTURELS = {
    frozenset({"noeud_nord", "noeud_sud"}): "theme_axe_noeuds",
    frozenset({"Ascendant", "Descendant"}): "theme_axe_horizon",
    frozenset({"Milieu du Ciel", "Fond du Ciel"}): "theme_axe_meridien",
}


def _expliquer_theme_complet(tc: dict, langue: str) -> list:
    """Sous-section empreinte pour la carte astro complète (theme_complet).

    Les entrées portent un `id` préfixé par `theme_` pour les distinguer des ids stables
    du glossaire (elles ne sont pas traduites via le glossaire). Chaque entrée conserve
    la structure `{cle, valeur, sens, role, id}` de `_entree`."""
    lg = langue if langue in ("fr", "en") else "fr"
    entries: list = []

    # — Fondations (Soleil / Lune / Ascendant / Descendant / MC / IC) —
    for nom_cle, nom_aff in (("soleil", "Soleil"), ("lune", "Lune"),
                              ("ascendant", "Ascendant"), ("descendant", "Descendant"),
                              ("milieu_du_ciel", "MC"), ("fond_du_ciel", "IC")):
        fond = tc.get("fondations", {}).get(nom_cle) or {}
        if fond:
            mots = CLEFS_CORPS.get(nom_aff, {}).get(lg, "") if nom_aff in CLEFS_CORPS else ""
            entries.append(_entree(
                nom_aff,
                f"{fond.get('signe', '?')} ({fond.get('degre', 0):.1f}°)",
                mots, "fondation", id=f"theme_fondation_{nom_cle}"))

    # — 10 corps célestes —
    for corps, info in (tc.get("dix_corps") or {}).items():
        info = info or {}
        retro = " R" if info.get("retrograde") else ""
        maison = info.get("maison", "?")
        entries.append(_entree(
            corps,
            f"{info.get('signe', '?')} {info.get('degre', 0):.1f}°{retro} (M{maison})",
            CLEFS_CORPS.get(corps, {}).get(lg, ""),
            "corps céleste", id=f"theme_corps_{corps.lower()}"))

    # — Points évolutifs (Nœud Nord/Sud, Chiron, Lilith) —
    for nom_cle, info in (tc.get("points_evolutifs") or {}).items():
        info = info or {}
        label = nom_cle.replace("_", " ").title()
        entries.append(_entree(
            label,
            f"{info.get('signe', '?')} {info.get('degre', 0):.1f}°",
            CLEFS_POINTS_EVOLUTIFS.get(nom_cle, {}).get(lg, ""),
            "point évolutif", id=f"theme_point_{nom_cle}"))

    # — Aspects majeurs (top 5 par exactitude) —
    aspects = tc.get("aspects") or []
    majeurs = sorted([a for a in aspects if a.get("type") == "majeur"],
                     key=lambda a: a.get("exactitude", 0), reverse=True)[:5]
    for asp in majeurs:
        a_type = asp.get("aspect", "?")
        pa = asp.get("point_a", "?")
        pb = asp.get("point_b", "?")
        gloss_id = _AXES_STRUCTURELS.get(frozenset({pa, pb})) or f"theme_aspect_{a_type}"
        entries.append(_entree(
            f"{a_type.title()} {pa}-{pb}",
            f"orbe {asp.get('orb', 0):.1f}°",
            CLEFS_ASPECTS.get(a_type, {}).get(lg, ""),
            "aspect", id=gloss_id))

    # — Dominantes (élément / mode / planète / signe / maison) —
    dom = tc.get("dominantes") or {}
    for categorie in ("element", "mode", "planete", "signe", "maison"):
        d = dom.get(categorie, {}) or {}
        cle_dom = d.get("dominant") or d.get("dominante")
        if not cle_dom:
            continue
        mots = (CLEFS_DOMINANTES.get(categorie, {}).get(str(cle_dom), {}).get(lg, "")
                if categorie in CLEFS_DOMINANTES else "")
        label_cat = categorie.capitalize() if lg == "fr" else categorie.capitalize()
        entries.append(_entree(
            f"Dominante {label_cat}",
            str(cle_dom), mots, "dominante",
            id=f"theme_dominante_{categorie}"))

    return entries


def didactique(langue: str = "fr") -> dict:
    """Couche didactique pour l'onglet « Carte astro complète ».

    Renvoie {id: {question, domaines, conclusion}}. Les ids sont stables
    (jamais traduits) et existent tous dans GLOSSAIRE_FR/GLOSSAIRE_EN.
    langue="fr" (défaut) ou "en". Retourne {} si la langue est absente
    (l'UI retombe sur le glossaire seul)."""
    lg = (langue or "fr").lower()
    if lg.startswith("en"):
        table = DIDACTIQUE_EN
    elif lg.startswith("fr"):
        table = DIDACTIQUE_FR
    else:
        return {}
    return {k: {"question": v["question"], "domaines": list(v["domaines"]),
                "conclusion": v["conclusion"]} for k, v in table.items()}
