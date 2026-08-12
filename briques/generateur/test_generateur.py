"""Non-régression S229 : prompt_plan_app avec/sans cahier des charges."""
import os
import tempfile

os.environ.setdefault("GATEWAY_KEY", "test-offline")
os.environ.setdefault("DB_PATH", os.path.join(tempfile.gettempdir(), "test_generateur_plan.db"))

from prompts import prompt_plan_app

AUDIT = {
    "nom_entreprise": "Atelier Fleurs",
    "territoire": {
        "ddd": {"bounded_contexts": [{"nom": "Atelier"}], "agregats": ["Composition"]},
        "glossaire_metier": [{"terme_generique": "produit", "terme_entreprise": "composition"}],
        "business_model_canvas": {"proposition_valeur": "Fleurs sur-mesure"},
    },
    "flux": {"value_stream_map": {"efficacite_flux_pct": 60}},
    "problemes": {"theory_of_constraints": {"goulot_principal": "Atelier"}},
    "priorites": {
        "swot": {"forces": ["Savoir-faire"]},
        "moscow": {"must": ["Devis rapides"]},
        "okrs_proposes": [{"objectif": "Réduire les délais"}],
    },
}


def test_sans_cdc_utilise_l_assemblage_informel_existant():
    prompt = prompt_plan_app(AUDIT, "fr")
    assert "Fleurs sur-mesure" in prompt  # proposition_valeur du canvas, toujours présent en repli
    assert "Devis rapides" in prompt      # must_have du moscow
    assert "CAHIER DES CHARGES" not in prompt


def test_avec_cdc_utilise_le_document_et_garde_le_vocabulaire():
    cdc_markdown = "## Objectifs\n\nAugmenter le CA de 20%.\n\n## Fonctionnalités\n\nGestion des devis."
    prompt = prompt_plan_app(AUDIT, "fr", cahier_des_charges=cdc_markdown)
    assert cdc_markdown in prompt
    assert "composition" in prompt.lower()  # glossaire_metier toujours injecté
    assert "Composition" in prompt  # agregats toujours injecté
    assert "RÈGLE DE VOCABULAIRE" in prompt


def test_les_deux_branches_contiennent_le_meme_schema_json():
    sans_cdc = prompt_plan_app(AUDIT, "fr")
    avec_cdc = prompt_plan_app(AUDIT, "fr", cahier_des_charges="## Objectifs\n\nX")
    for cle in ('"nom_app"', '"navigation"', '"entites"', '"kpis"', '"actions_immediates"'):
        assert cle in sans_cdc
        assert cle in avec_cdc
