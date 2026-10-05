"""Modèle de la Forge choisi dans ⚙ Cerveau : `forge/defaut` EN BASE LiteLLM (S240, T3).

`forge/defaut` sort du YAML : le Cœur le (re)crée en base selon le choix persisté
(`forge_modele` : "" = Mistral small par défaut, sinon un `perso/*`). Le repli
`forge/defaut → [gratuit/auto, gratuit/secours]` reste dans `router_settings.fallbacks` du
YAML (prouvé sur LiteLLM v1.86.2 locale : il s'applique au groupe créé en base).

$ cd core && python3 -m pytest test_forge_modele.py -v
"""
import asyncio
import json
import os

os.environ.setdefault("VAULT_SECRET", "test-secret-0123456789")
os.environ.setdefault("GATEWAY_KEY", "test")

import httpx  # noqa: E402
import pytest  # noqa: E402
import respx  # noqa: E402

import config_assistant  # noqa: E402
import modeles_gateway as mg  # noqa: E402

GW = config_assistant.GATEWAY_URL


def _info(*modeles):
    return {"data": [{"model_name": n, "litellm_params": {"model": lm},
                      "model_info": {"id": i, "db_model": db}} for n, db, i, lm in modeles]}


@pytest.fixture(autouse=True)
def _choix_par_defaut():
    config_assistant.definir_forge_modele("")
    yield
    config_assistant.definir_forge_modele("")


def test_params_forge_defaut_mistral_small_frigo_court():
    assert mg.params_forge("") == {"model": "mistral/mistral-small-latest", "cooldown_time": 120}
    assert mg.params_forge("perso/groq/x") == {"model": "groq/x", "cooldown_time": 120}
    for invalide in ("mistral/small", "free/a/b", "gratuit/auto", "perso/opencode/glm"):
        with pytest.raises(mg.ValeurInvalide):
            mg.params_forge(invalide)


@respx.mock
def test_base_vide_cree_forge_defaut():
    respx.get(f"{GW}/model/info").respond(json=_info(("mistral/small", False, "y", "mistral/m")))
    nouveau = respx.post(f"{GW}/model/new").respond(json={"model_id": "f1"})
    suppr = respx.post(f"{GW}/model/delete").respond(json={})
    r = asyncio.run(mg.assurer_forge())
    assert r["statut"] == "cree"
    assert json.loads(nouveau.calls[0].request.content) == {
        "model_name": "forge/defaut",
        "litellm_params": {"model": "mistral/mistral-small-latest", "cooldown_time": 120}}
    assert not suppr.called


@respx.mock
def test_deja_bon_rien_a_faire():
    respx.get(f"{GW}/model/info").respond(
        json=_info(("forge/defaut", True, "f1", "mistral/mistral-small-latest")))
    nouveau = respx.post(f"{GW}/model/new").respond(json={"model_id": "x"})
    suppr = respx.post(f"{GW}/model/delete").respond(json={})
    assert asyncio.run(mg.assurer_forge())["statut"] == "ok"
    assert not nouveau.called and not suppr.called


@respx.mock
def test_repointage_cree_le_nouveau_avant_de_retirer_l_ancien():
    respx.get(f"{GW}/model/info").respond(json=_info(
        ("forge/defaut", True, "ancien", "mistral/mistral-small-latest"),
        ("perso/groq/x", True, "p", "groq/x")))
    ordre = []
    respx.post(f"{GW}/model/new").mock(
        side_effect=lambda req: ordre.append("new") or httpx.Response(200, json={"model_id": "neuf"}))
    respx.post(f"{GW}/model/delete").mock(
        side_effect=lambda req: ordre.append(("del", json.loads(req.content)["id"]))
        or httpx.Response(200, json={}))
    r = asyncio.run(mg.assurer_forge("perso/groq/x"))
    assert r["statut"] == "repointe"
    assert ordre == ["new", ("del", "ancien")]


@respx.mock
def test_doublons_ramenes_a_un_seul():
    respx.get(f"{GW}/model/info").respond(json=_info(
        ("forge/defaut", True, "a", "mistral/mistral-small-latest"),
        ("forge/defaut", True, "b", "mistral/mistral-small-latest")))
    nouveau = respx.post(f"{GW}/model/new").respond(json={"model_id": "x"})
    suppr = respx.post(f"{GW}/model/delete").respond(json={})
    asyncio.run(mg.assurer_forge())
    assert not nouveau.called
    assert [json.loads(c.request.content)["id"] for c in suppr.calls] == ["b"]


@respx.mock
def test_forge_encore_dans_le_yaml_on_ne_touche_a_rien():
    """Déploiement par étapes : Cœur à jour, YAML pas encore — ne jamais doubler (LiteLLM
    répartirait la charge entre les deux) ni toucher au YAML."""
    respx.get(f"{GW}/model/info").respond(
        json=_info(("forge/defaut", False, "yaml", "mistral/mistral-small-latest")))
    nouveau = respx.post(f"{GW}/model/new").respond(json={"model_id": "x"})
    suppr = respx.post(f"{GW}/model/delete").respond(json={})
    assert asyncio.run(mg.assurer_forge("perso/groq/x"))["statut"] == "yaml"
    assert not nouveau.called and not suppr.called


@respx.mock
def test_definir_forge_persiste_apres_succes():
    respx.get(f"{GW}/model/info").respond(json=_info(
        ("forge/defaut", True, "ancien", "mistral/mistral-small-latest"),
        ("perso/groq/x", True, "p", "groq/x")))
    respx.post(f"{GW}/model/new").respond(json={"model_id": "neuf"})
    respx.post(f"{GW}/model/delete").respond(json={})
    chat = respx.post(f"{GW}/v1/chat/completions").respond(json={"choices": []})
    r = asyncio.run(mg.definir_forge("perso/groq/x"))
    assert r["ok"] is True and r["choix"] == "perso/groq/x"
    assert config_assistant.charger()["forge_modele"] == "perso/groq/x"
    # Test SANS repli : sinon un modèle en panne passerait pour sain via gratuit/*.
    corps = json.loads(chat.calls[0].request.content)
    assert corps["model"] == "forge/defaut" and corps["disable_fallbacks"] is True


@respx.mock
def test_definir_forge_modele_absent_refuse_sans_persister():
    respx.get(f"{GW}/model/info").respond(json=_info())
    with pytest.raises(mg.Introuvable):
        asyncio.run(mg.definir_forge("perso/groq/absent"))
    assert config_assistant.charger()["forge_modele"] == ""


@respx.mock
def test_definir_forge_gateway_muette_ne_persiste_pas():
    respx.get(f"{GW}/model/info").respond(json=_info(("perso/groq/x", True, "p", "groq/x")))
    respx.post(f"{GW}/model/new").mock(side_effect=httpx.ConnectError("refusé"))
    with pytest.raises(mg.GatewayInjoignable):
        asyncio.run(mg.definir_forge("perso/groq/x"))
    assert config_assistant.charger()["forge_modele"] == ""


@respx.mock
def test_retrait_refuse_si_modele_de_la_forge():
    config_assistant.definir_forge_modele("perso/groq/x")
    respx.get(f"{GW}/model/info").respond(json=_info(("perso/groq/x", True, "p", "groq/x")))
    with pytest.raises(mg.Conflit):
        asyncio.run(mg.retirer("perso/groq/x"))


def test_veille_reessaie_puis_espace(monkeypatch):
    """Au démarrage la Gateway peut être absente : on réessaie vite, puis on espace."""
    appels, attentes = [], []

    async def faux_assurer(choix=None):
        appels.append(1)
        if len(appels) == 1:
            raise mg.GatewayInjoignable("pas encore là")
        return {"statut": "ok"}

    async def faux_dormir(s):
        attentes.append(s)
        if len(attentes) >= 2:
            raise asyncio.CancelledError

    monkeypatch.setattr(mg, "assurer_forge", faux_assurer)
    monkeypatch.setattr(mg.asyncio, "sleep", faux_dormir)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(mg.veiller_forge(intervalle=600, reessai=30))
    assert attentes == [30, 600]


@respx.mock
def test_route_forge_et_liste():
    from fastapi.testclient import TestClient
    import main
    respx.get(f"{GW}/model/info").respond(json=_info(
        ("forge/defaut", True, "f", "mistral/mistral-small-latest"),
        ("perso/groq/x", True, "p", "groq/x")))
    respx.post(f"{GW}/model/new").respond(json={"model_id": "neuf"})
    respx.post(f"{GW}/model/delete").respond(json={})
    respx.post(f"{GW}/v1/chat/completions").respond(json={"choices": []})
    c = TestClient(main.app)
    assert c.post("/assistant/forge-modele", json={"modele": "mistral/small"}).status_code == 400
    r = c.post("/assistant/forge-modele", json={"modele": "perso/groq/x"})
    assert r.status_code == 200 and r.json()["choix"] == "perso/groq/x"
    forge = c.get("/assistant/modeles").json()["forge"]
    assert forge == {"choix": "perso/groq/x", "defaut": "mistral/mistral-small-latest"}


def test_forge_modele_non_surchargeable_par_tenant():
    """Un seul `forge/defaut` dans la Gateway : une couche org/utilisateur n'aurait aucun effet."""
    import config_tenant
    with pytest.raises(config_tenant.ValeurInvalide):
        config_tenant.valider_patch({"forge_modele": "perso/groq/x"})
