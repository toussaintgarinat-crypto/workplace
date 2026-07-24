"""Tests — API de la brique images (placeholder honnête, endpoints de synergie)."""
from fastapi.testclient import TestClient

import fournisseurs
import historique
import main

c = TestClient(main.app)


def _reset_historique():
    historique._chemin().unlink(missing_ok=True)


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


def test_generer_transmet_le_modele(monkeypatch):
    captes = {}

    async def _faux_generer(prompt, negatif, largeur, hauteur, seed=None,
                            fournisseur=None, modele=None):
        captes["modele"] = modele
        return {"url": "/fichiers/x.png", "prompt": prompt, "backend": "gateway",
                "place_holder": False, "modele": modele}

    monkeypatch.setattr(main.moteur, "generer", _faux_generer)
    r = c.post("/generer", json={"prompt": "un chat", "fournisseur": "gateway",
                                 "modele": "openai/gpt-5-image"})
    assert r.status_code == 200
    assert captes["modele"] == "openai/gpt-5-image"
    assert r.json()["modele"] == "openai/gpt-5-image"


def test_modeles_liste_le_catalogue_openrouter(monkeypatch):
    async def _faux_modeles():
        return [{"id": "google/gemini-2.5-flash-image", "prix_image": "0.0000003"}]

    monkeypatch.setattr(fournisseurs, "modeles_image_openrouter", _faux_modeles)
    r = c.get("/modeles")
    assert r.status_code == 200
    assert r.json()["modeles"] == [
        {"id": "google/gemini-2.5-flash-image", "prix_image": "0.0000003"}]


def test_modeles_openrouter_injoignable_renvoie_502(monkeypatch):
    async def _boom():
        raise RuntimeError("timeout OpenRouter")

    monkeypatch.setattr(fournisseurs, "modeles_image_openrouter", _boom)
    r = c.get("/modeles")
    assert r.status_code == 502


# ── Historique (retrouver une image déjà générée) ──────────────────────────

def _faux_reel(url="/fichiers/x.png", backend="fal"):
    async def _generer(prompt, negatif, largeur, hauteur, seed=None, fournisseur=None, modele=None):
        return {"url": url, "prompt": prompt, "backend": backend, "place_holder": False}
    return _generer


def test_generer_reel_consigne_dans_l_historique(monkeypatch):
    _reset_historique()
    monkeypatch.setattr(main.moteur, "generer", _faux_reel())
    c.post("/generer", json={"prompt": "un chat qui dort au soleil"})
    r = c.get("/historique")
    assert r.json()["total"] == 1
    assert r.json()["images"][0]["prompt"] == "un chat qui dort au soleil"


def test_generer_placeholder_ne_consigne_rien(monkeypatch):
    _reset_historique()
    # Sans fournisseur configuré (mode test), /generer rend un placeholder.
    c.post("/generer", json={"prompt": "une forêt de cristal"})
    assert c.get("/historique").json()["total"] == 0


def test_portrait_et_couverture_reels_consignent_le_prompt_visuel(monkeypatch):
    _reset_historique()
    monkeypatch.setattr(main.moteur, "generer", _faux_reel())
    c.post("/portrait", json={"fiche": {"nom": "Elara", "role": "héroïne"}})
    c.post("/couverture", json={"titre": "La Cité de Verre"})
    prompts_ = {i["type"]: i["prompt"] for i in c.get("/historique", params={"limite": 10}).json()["images"]}
    assert "Elara" in prompts_["portrait"]
    assert "Cité de Verre" in prompts_["couverture"]


def test_historique_filtre_par_mot_cle(monkeypatch):
    _reset_historique()
    monkeypatch.setattr(main.moteur, "generer", _faux_reel())
    c.post("/generer", json={"prompt": "un chat qui dort"})
    c.post("/generer", json={"prompt": "une forêt de cristal"})
    r = c.get("/historique", params={"q": "chat"})
    assert r.json()["total"] == 1
    assert "chat" in r.json()["images"][0]["prompt"]


def test_historique_expose_la_meilleure_correspondance_a_la_racine(monkeypatch):
    """`url`/`prompt`/`backend` dupliqués à la racine → réutilise TEL QUEL l'affichage
    média déjà câblé (S196 : réécriture d'URL, relais Telegram) sans code supplémentaire."""
    _reset_historique()
    monkeypatch.setattr(main.moteur, "generer", _faux_reel(url="/fichiers/chat.png"))
    c.post("/generer", json={"prompt": "un chat"})
    r = c.get("/historique").json()
    assert r["url"] == "/fichiers/chat.png"
    assert r["prompt"] == "un chat"
    assert r["backend"] == "fal"


def test_historique_vide_sans_url_a_la_racine():
    _reset_historique()
    r = c.get("/historique").json()
    assert r == {"images": [], "total": 0}
