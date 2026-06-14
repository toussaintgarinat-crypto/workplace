"""Tests — construction des prompts visuels (fonctions pures, cœur de la synergie)."""
import prompts


def test_portrait_minimal_avec_nom():
    p = prompts.prompt_portrait({"nom": "Elara"})
    assert "portrait of Elara" in p["prompt"]
    assert p["negatif"]                         # négatif toujours fourni


def test_portrait_sans_nom_reste_valide():
    p = prompts.prompt_portrait({})
    assert "character portrait" in p["prompt"]


def test_portrait_integre_role_description_archetype():
    p = prompts.prompt_portrait({
        "nom": "Kael", "role": "antagoniste", "archetype": "le Gardien",
        "description": "vieil homme balafré"})
    txt = p["prompt"]
    assert "Kael" in txt and "antagoniste" in txt
    assert "le Gardien" in txt and "balafré" in txt


def test_portrait_traduit_l_empreinte_en_traits_visuels():
    # tags holistiques → descripteurs visuels curés
    p = prompts.prompt_portrait({"nom": "Sol", "empreinte": ["feu", "solaire"]})
    assert "fiery" in p["prompt"] and "golden" in p["prompt"]


def test_portrait_ignore_les_tags_inconnus():
    p = prompts.prompt_portrait({"nom": "X", "tags": ["xyzzy", "eau"]})
    assert "blue palette" in p["prompt"]        # eau reconnu
    assert "xyzzy" not in p["prompt"]           # inconnu ignoré


def test_portrait_empreinte_dict_acceptee():
    p = prompts.prompt_portrait({"nom": "Lune", "empreinte": {"element": "lunaire"}})
    assert "moonlight" in p["prompt"]


def test_portrait_style_personnalise_prime():
    p = prompts.prompt_portrait({"nom": "A"}, style="aquarelle douce")
    assert "aquarelle douce" in p["prompt"]


def test_couverture_titre_synopsis_personnages():
    p = prompts.prompt_couverture("La Cité de Verre", "un archipel botanique magique",
                                  personnages=[{"nom": "Elara"}, {"nom": "Kael"}])
    assert "La Cité de Verre" in p["prompt"]
    assert "archipel botanique" in p["prompt"]
    assert "Elara" in p["prompt"] and "Kael" in p["prompt"]


def test_couverture_limite_a_quatre_personnages():
    persos = [{"nom": f"P{i}"} for i in range(8)]
    p = prompts.prompt_couverture("T", "S", personnages=persos)
    assert "P0" in p["prompt"] and "P3" in p["prompt"]
    assert "P5" not in p["prompt"]              # tronqué à 4
