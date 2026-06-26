"""Workflow ComfyUI : graphe SDXL par défaut + gabarit personnalisé (Boogu/FLUX…)."""
import importlib
import json

import workflow


def test_defaut_sdxl_sans_gabarit(monkeypatch):
    monkeypatch.delenv("COMFY_WORKFLOW_JSON", raising=False)
    g = workflow.construire("un chat roux", negatif="flou", largeur=512, hauteur=768, seed=42)
    # Graphe SDXL standard : on retrouve le prompt et la taille aux bons nœuds.
    assert g["6"]["inputs"]["text"] == "un chat roux"
    assert g["7"]["inputs"]["text"] == "flou"
    assert g["5"]["inputs"]["width"] == 512 and g["5"]["inputs"]["height"] == 768
    assert g["3"]["inputs"]["seed"] == 42


def test_gabarit_personnalise_substitue_les_jetons(monkeypatch, tmp_path):
    # Gabarit minimal façon « exporté depuis ComfyUI », avec les 5 jetons.
    gabarit = {
        "10": {"class_type": "BooguTextEncode", "inputs": {"text": "{{PROMPT}}"}},
        "11": {"class_type": "BooguTextEncode", "inputs": {"text": "à éviter : {{NEGATIF}}"}},
        "12": {"class_type": "EmptyLatentImage",
               "inputs": {"width": "{{LARGEUR}}", "height": "{{HAUTEUR}}"}},
        "13": {"class_type": "BooguSampler", "inputs": {"seed": "{{SEED}}"}},
    }
    f = tmp_path / "boogu.json"
    f.write_text(json.dumps(gabarit), encoding="utf-8")
    monkeypatch.setenv("COMFY_WORKFLOW_JSON", str(f))

    g = workflow.construire("un dragon", negatif="texte", largeur=1024, hauteur=1024, seed=7)
    assert g["10"]["inputs"]["text"] == "un dragon"            # jeton seul → str
    assert g["11"]["inputs"]["text"] == "à éviter : texte"     # jeton inclus → remplacé
    assert g["12"]["inputs"]["width"] == 1024                  # jeton seul → int TYPÉ
    assert isinstance(g["12"]["inputs"]["width"], int)
    assert g["13"]["inputs"]["seed"] == 7 and isinstance(g["13"]["inputs"]["seed"], int)


def test_gabarit_illisible_replie_sur_sdxl(monkeypatch, tmp_path):
    f = tmp_path / "casse.json"
    f.write_text("{ ceci n'est pas du json", encoding="utf-8")
    monkeypatch.setenv("COMFY_WORKFLOW_JSON", str(f))
    g = workflow.construire("repli", seed=1)
    assert g["6"]["inputs"]["text"] == "repli"                 # retombé sur le graphe SDXL
