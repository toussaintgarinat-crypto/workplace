"""Catalogue vivant (S244) : liste lue chez le fournisseur, URL/clé côté serveur, cache.

$ cd core && python3 -m pytest test_catalogue_modeles.py -v
"""
import asyncio
import os

os.environ.setdefault("VAULT_SECRET", "test-secret-0123456789")
os.environ.setdefault("GATEWAY_KEY", "test")

import httpx  # noqa: E402
import pytest  # noqa: E402
import respx  # noqa: E402

import catalogue_modeles as cm  # noqa: E402
import config_assistant  # noqa: E402
import modeles_gateway as mg  # noqa: E402


@pytest.fixture(autouse=True)
def _propre(monkeypatch):
    cm._cache.clear()
    cles = {"MISTRAL_API_KEY": "mk-123", "ZAI_API_KEY": "zk-123", "GEMINI_API_KEY": "gk-123"}
    monkeypatch.setattr(config_assistant, "_lire_cle_env", lambda n: cles.get(n, ""))


def run(c):
    return asyncio.run(c)


def test_nouveaux_fournisseurs_ajoutables():
    ids = {f["id"] for f in mg.fournisseurs()}
    assert {"zai", "together", "fireworks", "xai", "cohere"} <= ids
    assert mg.params_litellm("zai", "glm-5.3") == {"model": "zai/glm-5.3"}


def test_toute_source_est_un_fournisseur_du_catalogue_en_https():
    assert set(cm.SOURCES) == set(mg._catalogue())
    assert all(s["url"].startswith("https://") for s in cm.SOURCES.values())


def test_fournisseur_inconnu_refuse():
    with pytest.raises(mg.ValeurInvalide):
        run(cm.lister("evil"))
    with pytest.raises(mg.ValeurInvalide):
        run(cm.lister("opencode"))


@respx.mock
def test_cle_absente_aucun_appel():
    r = run(cm.lister("groq"))
    assert r["etat"] == "cle_absente" and r["modeles"] == []
    assert not respx.calls


@respx.mock
def test_mistral_filtre_chat_et_envoie_la_cle_au_bon_hote():
    route = respx.get("https://api.mistral.ai/v1/models").mock(return_value=httpx.Response(200, json={"data": [
        {"id": "mistral-large-latest", "capabilities": {"completion_chat": True}},
        {"id": "mistral-embed", "capabilities": {"completion_chat": False}},
        {"id": "ministral-8b", "capabilities": {"completion_chat": True}},
        {"id": "mistral-ocr-latest", "capabilities": {"completion_chat": True}},
        {"id": "bad id with spaces", "capabilities": {"completion_chat": True}}]}))
    r = run(cm.lister("mistral"))
    assert r["modeles"] == ["ministral-8b", "mistral-large-latest"]
    assert route.calls[0].request.headers["authorization"] == "Bearer mk-123"
    assert "mk-123" not in str(r)


@respx.mock
def test_zai_glm_apparait():
    respx.get("https://api.z.ai/api/paas/v4/models").mock(return_value=httpx.Response(
        200, json={"data": [{"id": "glm-5.3"}, {"id": "glm-5.3-flash"}]}))
    assert run(cm.lister("zai"))["modeles"] == ["glm-5.3", "glm-5.3-flash"]


@respx.mock
def test_openrouter_public_sans_cle_texte_seulement():
    respx.get("https://openrouter.ai/api/v1/models").mock(return_value=httpx.Response(200, json={"data": [
        {"id": "z-ai/glm-5.3", "architecture": {"output_modalities": ["text"]}},
        {"id": "x/img", "architecture": {"output_modalities": ["text", "image"]}}]}))
    r = run(cm.lister("openrouter"))
    assert r["etat"] == "ok" and r["modeles"] == ["z-ai/glm-5.3"]


@respx.mock
def test_gemini_retire_prefixe_models_et_garde_generatecontent():
    respx.get(url__startswith="https://generativelanguage.googleapis.com/v1beta/models").mock(
        return_value=httpx.Response(200, json={"models": [
            {"name": "models/gemini-2.5-flash", "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/text-embedding-004", "supportedGenerationMethods": ["embedContent"]}]}))
    assert run(cm.lister("gemini"))["modeles"] == ["gemini-2.5-flash"]


@respx.mock
def test_cache_puis_actualiser():
    route = respx.get("https://api.z.ai/api/paas/v4/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "glm-5"}]}))
    run(cm.lister("zai")); run(cm.lister("zai"))
    assert route.call_count == 1
    run(cm.lister("zai", actualiser=True))
    assert route.call_count == 2


@respx.mock
def test_erreur_sans_cache_message_sobre_sans_cle():
    respx.get("https://api.z.ai/api/paas/v4/models").mock(return_value=httpx.Response(401))
    r = run(cm.lister("zai"))
    assert r["etat"] == "erreur" and r["modeles"] == [] and "401" in r["detail"]
    assert "zk-123" not in str(r)


@respx.mock
def test_erreur_apres_succes_renvoie_la_liste_en_cache():
    route = respx.get("https://api.z.ai/api/paas/v4/models")
    route.mock(return_value=httpx.Response(200, json={"data": [{"id": "glm-5"}]}))
    run(cm.lister("zai"))
    route.mock(return_value=httpx.Response(500))
    r = run(cm.lister("zai", actualiser=True))
    assert r["etat"] == "ok" and r["modeles"] == ["glm-5"] and "cache" in r["detail"]


@respx.mock
def test_reponse_mal_formee_ne_plante_pas():
    respx.get("https://api.z.ai/api/paas/v4/models").mock(return_value=httpx.Response(200, json="oops"))
    assert run(cm.lister("zai"))["etat"] == "erreur"
