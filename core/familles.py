"""Taxonomie des familles de briques (S142).

Source de vérité pour les labels, icônes et ordre d'affichage utilisés
par l'endpoint /briques?grouper=famille et le dashboard.
"""

FAMILLES: list[dict] = [
    {"slug": "ia",            "label": "Socle IA",                    "icone": "🧠", "ordre": 1},
    {"slug": "ingestion",     "label": "Ingestion & Analyse",          "icone": "📄", "ordre": 2},
    {"slug": "generation",    "label": "Génération & Livraison",       "icone": "🏗️", "ordre": 3},
    {"slug": "collaboration", "label": "Collaboration & Communication", "icone": "💬", "ordre": 4},
    {"slug": "media",         "label": "Média & Contenu",              "icone": "🎬", "ordre": 5},
    {"slug": "veille",        "label": "Veille",                      "icone": "🔭", "ordre": 6},
    {"slug": "metier",        "label": "Applications Métier",          "icone": "🏢", "ordre": 7},
    {"slug": "dev",           "label": "Persistance & Dev",            "icone": "🛠️", "ordre": 8},
]

# Index slug → métadonnées (accès O(1))
_INDEX: dict[str, dict] = {f["slug"]: f for f in FAMILLES}


def meta(slug: str) -> dict:
    """Retourne les métadonnées d'une famille. Repli sur 'autre' si slug inconnu."""
    return _INDEX.get(slug, {"slug": slug, "label": slug.capitalize(), "icone": "📦", "ordre": 99})


def grouper(briques: list[dict]) -> dict:
    """Répartit une liste de briques par famille (ordre canonique).

    Les briques sans champ `famille` tombent dans le groupe 'autre'.
    Renvoie un dict ordonné : slug → {label, icone, briques:[…]}."""
    groupes: dict[str, dict] = {}
    # On initialise dans l'ordre canonique pour que le résultat soit trié.
    for f in FAMILLES:
        groupes[f["slug"]] = {"label": f["label"], "icone": f["icone"], "briques": []}

    for b in briques:
        slug = b.get("famille", "autre")
        if slug not in groupes:
            m = meta(slug)
            groupes[slug] = {"label": m["label"], "icone": m["icone"], "briques": []}
        groupes[slug]["briques"].append(b)

    # Supprimer les familles vides pour ne pas polluer la réponse.
    return {k: v for k, v in groupes.items() if v["briques"]}
