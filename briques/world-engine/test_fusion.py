"""Tests de fusion.py — logique pure de world-engine, sans réseau."""
import fusion


def test_date_pour_signe_vierge():
    assert fusion.date_pour_signe("Vierge", 1990) == "1990-08-23"


def test_date_pour_signe_capricorne_reste_dans_l_annee_donnee():
    """Capricorne est à cheval sur le nouvel an (22 déc → 19 jan) : on ancre sur le
    DÉBUT de plage (22 décembre), qui reste toujours dans l'année demandée."""
    assert fusion.date_pour_signe("Capricorne", 2000) == "2000-12-22"


def test_date_pour_signe_verseau_janvier():
    assert fusion.date_pour_signe("Verseau", 2010) == "2010-01-20"


class _RngFactice:
    """Faux générateur aléatoire : renvoie des valeurs FIXÉES pour un test déterministe
    (plutôt que de chercher une seed qui tombe juste — plus lisible, jamais fragile)."""
    def __init__(self, valeur_random: float, choix: str = ""):
        self._valeur = valeur_random
        self._choix = choix

    def random(self) -> float:
        return self._valeur

    def choice(self, seq):
        return self._choix


def _theme_portrait_factice(forces, dominante_planete, dominante_signe) -> dict:
    return {
        "portrait": {"forces": forces},
        "theme_complet": {"dominantes": {
            "planete": {"dominante": dominante_planete},
            "signe": {"dominant": dominante_signe},
        }},
    }


def test_fusionner_description_sans_mutation():
    theme_a = _theme_portrait_factice(["Sagesse", "Stabilité", "Émotivité"], "Mercure", "Vierge")
    theme_b = _theme_portrait_factice(["Courage", "Passion", "Loyauté"], "Mars", "Bélier")
    rng = _RngFactice(valeur_random=0.99)   # > mutation_rate → pas de mutation
    description, mutation_survenue = fusion.fusionner_description(theme_a, theme_b, 0.10, rng)
    assert mutation_survenue is False
    for mot in ("Sagesse", "Stabilité", "Courage", "Passion", "Mercure", "Mars", "Vierge", "Bélier"):
        assert mot in description


def test_fusionner_description_avec_mutation_forcee():
    theme_a = _theme_portrait_factice(["Sagesse", "Stabilité", "Émotivité"], "Mercure", "Vierge")
    theme_b = _theme_portrait_factice(["Courage", "Passion", "Loyauté"], "Mars", "Bélier")
    rng = _RngFactice(valeur_random=0.01, choix=fusion.MOTS_MUTATION[0])   # < mutation_rate
    description, mutation_survenue = fusion.fusionner_description(theme_a, theme_b, 0.10, rng)
    assert mutation_survenue is True
    assert fusion.MOTS_MUTATION[0] in description
