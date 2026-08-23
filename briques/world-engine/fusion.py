"""Logique pure de croisement cosmique — aucun appel réseau ici, tout est testable
en isolation. Les 12 plages de dates du zodiaque occidental sont un savoir
calendaire public, indépendant du moteur astro de `personnages` (pas de
duplication du moteur : on ne recalcule aucune position planétaire ici)."""

# (mois, jour) = DÉBUT officiel de chaque signe + 4 jours de marge anti-cuspide.
# Ancrer pile sur le premier jour du signe est le point le PLUS fragile : la vraie
# ingression solaire dérive de ±1 jour d'une année à l'autre (éphéméride réelle),
# alors que cette table est figée. Vérifié empiriquement contre l'éphéméride réelle
# de `personnages` sur 2000-2030 (revue finale du plan world-engine) : 6/60 dates
# auraient un Soleil réel différent du signe demandé sans cette marge ; +4 jours
# élimine tous les cas testés. Capricorne (22+4=26 déc) reste dans l'année demandée,
# la propriété anti-bascule d'année est donc préservée.
SIGNE_PLAGES: dict[str, tuple[int, int]] = {
    "Bélier": (3, 25), "Taureau": (4, 24), "Gémeaux": (5, 25), "Cancer": (6, 25),
    "Lion": (7, 27), "Vierge": (8, 27), "Balance": (9, 27), "Scorpion": (10, 27),
    "Sagittaire": (11, 26), "Capricorne": (12, 26), "Verseau": (1, 24), "Poissons": (2, 23),
}


def date_pour_signe(signe: str, annee: int) -> str:
    """Date ISO plausible (quelques jours après le début officiel de la plage, pour
    éviter la cuspide) pour naître sous `signe`, dans `annee`.

    Ce choix d'année n'a AUCUNE signification d'hérédité (comme le lieu de
    naissance) — c'est un choix pratique pour obtenir une vraie date calculable."""
    mois, jour = SIGNE_PLAGES[signe]
    return f"{annee:04d}-{mois:02d}-{jour:02d}"


# Traits « mutants » : pool local à world-engine, volontairement indépendant des
# tables de significations de `personnages` (pure flaveur narrative, pas de lien
# avec le moteur astro — donc pas d'import de code entre les deux briques).
MOTS_MUTATION = [
    "Rébellion", "Étrangeté", "Prescience", "Chaos créateur", "Magnétisme sombre",
    "Don occulte", "Instabilité géniale", "Charisme brut", "Intuition foudroyante",
    "Ombre habitée", "Force tellurique", "Éclat imprévisible",
]


def fusionner_description(theme_a: dict, theme_b: dict, mutation_rate: float, rng) -> tuple[str, bool]:
    """Fusionne les traits dominants de 2 réponses `/holistique/portrait` en une
    description texte, destinée à `/holistique/recherche-inverse`.

    Avec probabilité `mutation_rate` (tirée via `rng.random()`), injecte un trait
    absent des deux parents (`rng.choice(MOTS_MUTATION)`). Renvoie
    (description, mutation_survenue)."""
    forces_a = theme_a["portrait"]["forces"][:2]
    forces_b = theme_b["portrait"]["forces"][:2]
    dom_a = theme_a["theme_complet"]["dominantes"]
    dom_b = theme_b["theme_complet"]["dominantes"]
    traits = [*forces_a, *forces_b,
              dom_a["planete"]["dominante"], dom_b["planete"]["dominante"],
              dom_a["signe"]["dominant"], dom_b["signe"]["dominant"]]

    mutation_survenue = rng.random() < mutation_rate
    if mutation_survenue:
        traits.append(rng.choice(MOTS_MUTATION))

    return "Personnage combinant " + ", ".join(traits) + ".", mutation_survenue


CORPS = ["Soleil", "Lune", "Mercure", "Vénus", "Mars", "Jupiter",
         "Saturne", "Uranus", "Neptune", "Pluton"]


def comparer_dix_corps(dix_corps_enfant: dict, dix_corps_a: dict, dix_corps_b: dict) -> dict:
    """Compare le signe de chacun des 10 corps de l'enfant à ceux des 2 parents.

    C'est un post-traitement NARRATIF : le thème de l'enfant est calculé
    indépendamment (vraie date, vraie astronomie) — une correspondance de signe
    est donc une coïncidence assumée, pas une vraie hérédité génétique."""
    par_corps = []
    resume = {"A": 0, "B": 0, "commun": 0, "mutation": 0}
    for corps in CORPS:
        signe_e = dix_corps_enfant[corps]["signe"]
        match_a = signe_e == dix_corps_a[corps]["signe"]
        match_b = signe_e == dix_corps_b[corps]["signe"]
        if match_a and match_b:
            origine = "commun"
        elif match_a:
            origine = "A"
        elif match_b:
            origine = "B"
        else:
            origine = "mutation"
        resume[origine] += 1
        par_corps.append({"corps": corps, "signe_enfant": signe_e, "origine": origine})
    return {"par_corps": par_corps, "resume": resume}
