"""Logique pure de croisement cosmique — aucun appel réseau ici, tout est testable
en isolation. Les 12 plages de dates du zodiaque occidental sont un savoir
calendaire public, indépendant du moteur astro de `personnages` (pas de
duplication du moteur : on ne recalcule aucune position planétaire ici)."""

# (mois, jour) de DÉBUT de chaque signe. On ancre systématiquement sur le début de
# plage : Capricorne (22 déc → 19 jan) reste ainsi toujours dans l'année demandée,
# aucun cas particulier de bascule d'année à gérer.
SIGNE_PLAGES: dict[str, tuple[int, int]] = {
    "Bélier": (3, 21), "Taureau": (4, 20), "Gémeaux": (5, 21), "Cancer": (6, 21),
    "Lion": (7, 23), "Vierge": (8, 23), "Balance": (9, 23), "Scorpion": (10, 23),
    "Sagittaire": (11, 22), "Capricorne": (12, 22), "Verseau": (1, 20), "Poissons": (2, 19),
}


def date_pour_signe(signe: str, annee: int) -> str:
    """Date ISO plausible (début de plage) pour naître sous `signe`, dans `annee`.

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
