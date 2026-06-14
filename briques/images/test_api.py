"""Tests — API de la brique images (placeholder honnête, endpoints de synergie)."""
from fastapi.testclient import TestClient

import main

c = TestClient(main.app)


def test_sante_annonce_le_backend():
    r = c.get("/sante")
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] is True
    assert d["backend"] == "placeholder"        # aucun fournisseur configuré en test
    assert d["actif"] is None                   # aucun moteur utilisable
    assert d["configures"] == []                # aucune clé/URL en test
    assert "comfyui" in d["fournisseurs"]       # mais le catalogue est exposé
    assert "nanobanana" in d["fournisseurs"]


def test_fournisseurs_liste_le_catalogue():
    r = c.get("/fournisseurs")
    assert r.status_code == 200
    noms = {f["nom"] for f in r.json()["fournisseurs"]}
    assert {"comfyui", "nanobanana", "fal", "replicate", "openai", "pruna"} <= noms
    assert all(f["configure"] is False for f in r.json()["fournisseurs"])  # rien configuré


def test_generer_fournisseur_inconnu_donne_placeholder():
    r = c.post("/generer", json={"prompt": "un phare", "fournisseur": "nexistepas"})
    assert r.status_code == 200
    assert r.json()["place_holder"] is True


def test_generer_refuse_un_prompt_vide():
    assert c.post("/generer", json={"prompt": "   "}).status_code == 422


def test_generer_rend_un_placeholder_servable():
    r = c.post("/generer", json={"prompt": "une forêt de cristal"})
    assert r.status_code == 200
    d = r.json()
    assert d["place_holder"] is True
    # l'URL rendue est réellement servie par la brique
    img = c.get(d["url"])
    assert img.status_code == 200
    assert img.headers["content-type"].startswith("image/")


def test_portrait_derive_le_prompt_de_la_fiche():
    r = c.post("/portrait", json={"fiche": {"nom": "Elara", "role": "héroïne",
                                            "empreinte": ["feu"]}})
    assert r.status_code == 200
    d = r.json()
    assert "Elara" in d["prompt_visuel"] and "fiery" in d["prompt_visuel"]
    assert d["place_holder"] is True


def test_couverture_derive_le_prompt():
    r = c.post("/couverture", json={"titre": "La Cité de Verre",
                                    "synopsis": "un Paris dystopique en béton"})
    assert r.status_code == 200
    assert "Cité de Verre" in r.json()["prompt_visuel"]


def test_fichier_inconnu_404():
    assert c.get("/fichiers/inexistant.png").status_code == 404


def test_fichier_anti_traversee():
    # pas d'évasion hors du dossier d'images
    assert c.get("/fichiers/..%2f..%2fetc%2fpasswd").status_code == 404
