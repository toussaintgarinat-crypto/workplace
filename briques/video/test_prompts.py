"""Tests — construction des prompts vidéo (fonctions pures, cœur de la synergie)."""
import prompts


def test_animation_minimal_avec_nom():
    p = prompts.prompt_animation({"nom": "Elara"})
    assert "animated portrait of Elara" in p["prompt"]
    assert "motion" in p["prompt"]                  # orienté MOUVEMENT


def test_animation_sans_nom_reste_valide():
    p = prompts.prompt_animation({})
    assert "animated character portrait" in p["prompt"]


def test_animation_integre_role_description_archetype():
    p = prompts.prompt_animation({
        "nom": "Kael", "role": "antagoniste", "archetype": "le Gardien",
        "description": "vieil homme balafré"})
    txt = p["prompt"]
    assert "Kael" in txt and "antagoniste" in txt
    assert "le Gardien" in txt and "balafré" in txt


def test_animation_traduit_l_empreinte_en_traits_visuels():
    p = prompts.prompt_animation({"nom": "Sol", "empreinte": ["feu", "solaire"]})
    assert "fiery" in p["prompt"] and "golden" in p["prompt"]


def test_animation_ignore_les_tags_inconnus():
    p = prompts.prompt_animation({"nom": "X", "tags": ["xyzzy", "eau"]})
    assert "blue palette" in p["prompt"]            # eau reconnu
    assert "xyzzy" not in p["prompt"]               # inconnu ignoré


def test_animation_style_personnalise_prime():
    p = prompts.prompt_animation({"nom": "A"}, style="aquarelle douce animée")
    assert "aquarelle douce animée" in p["prompt"]


def test_teaser_titre_synopsis_personnages():
    p = prompts.prompt_teaser("La Cité de Verre", "un archipel botanique magique",
                              personnages=[{"nom": "Elara"}, {"nom": "Kael"}])
    assert "La Cité de Verre" in p["prompt"]
    assert "archipel botanique" in p["prompt"]
    assert "Elara" in p["prompt"] and "Kael" in p["prompt"]
    assert "trailer" in p["prompt"]                 # style teaser par défaut


def test_teaser_limite_a_quatre_personnages():
    persos = [{"nom": f"P{i}"} for i in range(8)]
    p = prompts.prompt_teaser("T", "S", personnages=persos)
    assert "P0" in p["prompt"] and "P3" in p["prompt"]
    assert "P5" not in p["prompt"]                  # tronqué à 4
