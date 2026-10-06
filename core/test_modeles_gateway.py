"""Modèles ajoutés par l'utilisateur depuis ⚙ Cerveau, servis en base par LiteLLM (S240, T2).

Points verrouillés :
- le catalogue est SERVEUR : l'appelant ne fournit que `fournisseur` + identifiant, jamais
  d'`api_base` ni de clé (sinon une clé existante pourrait partir vers un serveur arbitraire) ;
- aucun `api_key` dans les paramètres envoyés à LiteLLM : un modèle en base ne résout PAS
  `os.environ/…` (prouvé sur v1.86.2, la chaîne littérale partait en `Bearer`), on laisse
  donc LiteLLM lire la variable par défaut du fournisseur dans son environnement ;
- un modèle est TESTÉ avant d'être gardé ; échec (erreur, délai) → retiré, jamais laissé ;
- on ne retire que ses propres modèles (`perso/*` en base), jamais YAML/gratuits/Forge.

$ cd core && python3 -m pytest test_modeles_gateway.py -v
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


@pytest.fixture(autouse=True)
def _verrou_neuf():
    mg._verrou_forge = asyncio.Lock()  # lié à la boucle de chaque asyncio.run


def _info(*modeles):
    """Réponse /model/info : (nom, db_model, id, model litellm)."""
    return {"data": [{"model_name": n, "litellm_params": {"model": lm, "api_key": "sk-secret"},
                      "model_info": {"id": i, "db_model": db}} for n, db, i, lm in modeles]}


# ── Catalogue et validation ──────────────────────────────────────────────────

def test_catalogue_sans_api_base_ni_opencode():
    ids = {f["id"] for f in mg.fournisseurs()}
    assert {"mistral", "groq", "gemini", "anthropic", "openai", "deepseek", "openrouter"} <= ids
    # OpenCode Go exige un api_base + SA clé : sans résolution de `os.environ/` en base,
    # LiteLLM y enverrait OPENAI_API_KEY. Exclu du catalogue.
    assert "opencode" not in ids
    for f in mg.fournisseurs():
        assert "api_base" not in f and "env" not in f


@pytest.mark.parametrize("ident", ["mistral-large-latest", "llama-3.3-70b-versatile",
                                   "meta-llama/llama-3.3-70b-instruct:free", "gemini-2.5-flash",
                                   "claude-haiku-4-5@20251001"])
def test_identifiants_acceptes(ident):
    assert mg.valider_identifiant(ident) == ident


@pytest.mark.parametrize("ident", ["", " ", "../x", "a/../b", "a//b", "/x", "x/",
                                   "http://evil.example/v1", "x y", "a" * 121, "x\ny", "é"])
def test_identifiants_refuses(ident):
    with pytest.raises(mg.ValeurInvalide):
        mg.valider_identifiant(ident)


def test_params_sans_cle_ni_api_base():
    assert mg.params_litellm("groq", "llama-3.1-8b-instant") == {"model": "groq/llama-3.1-8b-instant"}
    assert mg.params_litellm("openrouter", "qwen/qwen3-coder") == {"model": "openrouter/qwen/qwen3-coder"}


def test_fournisseur_inconnu_refuse():
    with pytest.raises(mg.ValeurInvalide):
        mg.params_litellm("opencode", "glm-5")
    with pytest.raises(mg.ValeurInvalide):
        mg.params_litellm("evil", "x")


def test_nom_perso():
    assert mg.nom_perso("groq", "llama-3.1-8b-instant") == "perso/groq/llama-3.1-8b-instant"
    assert mg.analyser_nom_perso("perso/openrouter/qwen/qwen3-coder") == ("openrouter", "qwen/qwen3-coder")
    assert mg.analyser_nom_perso("free/qwen/x") is None


# ── Ajout testé ──────────────────────────────────────────────────────────────

@respx.mock
def test_ajout_ok_teste_puis_garde():
    respx.get(f"{GW}/model/info").respond(json=_info(("mistral/small", False, "y1", "mistral/m")))
    nouveau = respx.post(f"{GW}/model/new").respond(json={"model_id": "id-1"})
    chat = respx.post(f"{GW}/v1/chat/completions").respond(
        json={"choices": [{"message": {"content": "pong"}}]})
    suppr = respx.post(f"{GW}/model/delete").respond(json={})
    r = asyncio.run(mg.ajouter("groq", "llama-3.1-8b-instant"))
    assert r["ok"] is True and r["nom"] == "perso/groq/llama-3.1-8b-instant"
    envoye = json.loads(nouveau.calls[0].request.content)
    assert envoye == {"model_name": "perso/groq/llama-3.1-8b-instant",
                      "litellm_params": {"model": "groq/llama-3.1-8b-instant"}}
    test = json.loads(chat.calls[0].request.content)
    assert test["model"] == "perso/groq/llama-3.1-8b-instant" and test["max_tokens"] <= 5
    assert not suppr.called


@respx.mock
def test_ajout_echec_du_test_retire_le_modele():
    gw = FausseGateway(chat=lambda corps: httpx.Response(
        401, json={"error": {"message": "AuthenticationError: clé absente"}}))
    r = asyncio.run(mg.ajouter("mistral", "mistral-medium-latest"))
    assert r["ok"] is False and "clé absente" in r["detail"]
    assert ("del", "n1") in gw.journal and gw.noms() == []


@respx.mock
def test_ajout_delai_depasse_retire_le_modele():
    def pend(corps):
        raise httpx.ReadTimeout("trop long")
    gw = FausseGateway(chat=pend)
    r = asyncio.run(mg.ajouter("gemini", "gemini-2.5-flash"))
    assert r["ok"] is False and "délai" in r["detail"].lower()
    assert gw.noms() == []


@respx.mock
def test_ajout_deja_present_conflit():
    respx.get(f"{GW}/model/info").respond(
        json=_info(("perso/groq/llama-3.1-8b-instant", True, "id-x", "groq/llama-3.1-8b-instant")))
    nouveau = respx.post(f"{GW}/model/new").respond(json={"model_id": "id-4"})
    with pytest.raises(mg.Conflit):
        asyncio.run(mg.ajouter("groq", "llama-3.1-8b-instant"))
    assert not nouveau.called


@respx.mock
def test_gateway_injoignable():
    respx.get(f"{GW}/model/info").mock(side_effect=httpx.ConnectError("refusé"))
    with pytest.raises(mg.GatewayInjoignable):
        asyncio.run(mg.ajouter("groq", "llama-3.1-8b-instant"))


# ── Retrait ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("nom", ["mistral/small", "free/qwen/x", "kilo/nvidia/y",
                                 "forge/defaut", "gratuit/auto"])
def test_retrait_refuse_hors_perso(nom):
    with pytest.raises(mg.ValeurInvalide):
        asyncio.run(mg.retirer(nom))


@respx.mock
def test_retrait_refuse_un_perso_du_yaml():
    respx.get(f"{GW}/model/info").respond(json=_info(("perso/groq/x", False, "y", "groq/x")))
    suppr = respx.post(f"{GW}/model/delete").respond(json={})
    with pytest.raises(mg.Introuvable):
        asyncio.run(mg.retirer("perso/groq/x"))
    assert not suppr.called


@respx.mock
def test_retrait_ok_retire_tous_les_deploiements_du_nom():
    respx.get(f"{GW}/model/info").respond(json=_info(
        ("perso/groq/x", True, "a", "groq/x"), ("perso/groq/x", True, "b", "groq/x"),
        ("perso/groq/autre", True, "c", "groq/autre")))
    suppr = respx.post(f"{GW}/model/delete").respond(json={})
    r = asyncio.run(mg.retirer("perso/groq/x"))
    assert r["ok"] is True
    assert sorted(json.loads(c.request.content)["id"] for c in suppr.calls) == ["a", "b"]


# ── Liste ────────────────────────────────────────────────────────────────────

@respx.mock
def test_liste_origines_sans_secret():
    respx.get(f"{GW}/model/info").respond(json=_info(
        ("mistral/small", False, "1", "mistral/m"), ("free/q/x", True, "2", "openrouter/q/x"),
        ("kilo/n/y", True, "3", "openai/n/y"), ("perso/groq/z", True, "4", "groq/z"),
        ("forge/defaut", True, "5", "mistral/m"), ("gratuit/auto", False, "6", "openai/k")))
    r = asyncio.run(mg.lister())
    origines = {m["nom"]: (m["origine"], m["retirable"]) for m in r}
    assert origines == {"mistral/small": ("yaml", False), "free/q/x": ("gratuit", False),
                        "kilo/n/y": ("gratuit", False), "perso/groq/z": ("perso", True),
                        "forge/defaut": ("forge", False), "gratuit/auto": ("forge", False)}
    assert "sk-secret" not in json.dumps(r)


@respx.mock
def test_retrait_refuse_si_tete_du_coeur():
    precedent = config_assistant.charger()["model"]  # restauré tel quel (revue S240, M9)
    config_assistant.definir_modele("perso/groq/x")
    try:
        respx.get(f"{GW}/model/info").respond(json=_info(("perso/groq/x", True, "a", "groq/x")))
        suppr = respx.post(f"{GW}/model/delete").respond(json={})
        with pytest.raises(mg.Conflit):
            asyncio.run(mg.retirer("perso/groq/x"))
        assert not suppr.called
    finally:
        config_assistant.definir_modele(precedent)


# ── Routes ───────────────────────────────────────────────────────────────────

def _client():
    from fastapi.testclient import TestClient
    import main
    return TestClient(main.app)


@respx.mock
def test_route_ajout_ignore_api_base_et_cle_du_corps():
    respx.get(f"{GW}/model/info").respond(json=_info())
    nouveau = respx.post(f"{GW}/model/new").respond(json={"model_id": "id-9"})
    respx.post(f"{GW}/v1/chat/completions").respond(json={"choices": []})
    r = _client().post("/assistant/modeles", json={
        "fournisseur": "groq", "modele": "llama-3.1-8b-instant",
        "api_base": "https://evil.example/v1", "api_key": "sk-vole", "litellm_params": {"x": 1}})
    assert r.status_code == 200 and r.json()["ok"] is True
    envoye = nouveau.calls[0].request.content.decode()
    assert "evil" not in envoye and "sk-vole" not in envoye and '"x"' not in envoye


@respx.mock
def test_routes_codes_erreur():
    respx.get(f"{GW}/model/info").respond(
        json=_info(("perso/groq/x", True, "a", "groq/x")))
    c = _client()
    assert c.post("/assistant/modeles", json={"fournisseur": "evil", "modele": "x"}).status_code == 400
    assert c.post("/assistant/modeles", json={"fournisseur": "groq", "modele": "x"}).status_code == 409
    assert c.delete("/assistant/modeles/mistral/small").status_code == 400
    assert c.delete("/assistant/modeles/perso/groq/absent").status_code == 404


@respx.mock
def test_route_liste():
    respx.get(f"{GW}/model/info").respond(json=_info(("perso/groq/x", True, "a", "groq/x")))
    r = _client().get("/assistant/modeles").json()
    assert r["modeles"] == [{"nom": "perso/groq/x", "origine": "perso", "retirable": True}]
    assert any(f["id"] == "groq" for f in r["fournisseurs"])


@respx.mock
def test_route_liste_gateway_injoignable_502():
    respx.get(f"{GW}/model/info").mock(side_effect=httpx.ConnectError("refusé"))
    assert _client().get("/assistant/modeles").status_code == 502



# ── Fausse Gateway à état (revue S240) : /model/info reflète les créations/retraits ──

class FausseGateway:
    def __init__(self, *modeles, new_echoue=None, chat=None):
        self.deps = [{"nom": n, "db": db, "id": i, "model": lm} for n, db, i, lm in modeles]
        self.journal, self.n = [], 0
        self.new_echoue, self.chat = new_echoue, chat or (lambda corps: httpx.Response(200, json={}))
        respx.get(f"{GW}/model/info").mock(side_effect=self._info)
        respx.post(f"{GW}/model/new").mock(side_effect=self._new)
        respx.post(f"{GW}/model/delete").mock(side_effect=self._delete)
        respx.post(f"{GW}/v1/chat/completions").mock(
            side_effect=lambda req: self.chat(json.loads(req.content)))

    def _info(self, req):
        return httpx.Response(200, json=_info(*[(d["nom"], d["db"], d["id"], d["model"]) for d in self.deps]))

    def _new(self, req):
        c = json.loads(req.content)
        self.n += 1
        d = {"nom": c["model_name"], "db": True, "id": f"n{self.n}", "model": c["litellm_params"]["model"]}
        self.deps.append(d)  # créé côté LiteLLM même si la réponse se perd ensuite
        self.journal.append(("new", d["nom"], d["model"]))
        if self.new_echoue:
            raise self.new_echoue
        return httpx.Response(200, json={"model_id": d["id"]})

    def _delete(self, req):
        i = json.loads(req.content)["id"]
        self.deps = [d for d in self.deps if d["id"] != i]
        self.journal.append(("del", i))
        return httpx.Response(200, json={})

    def noms(self):
        return sorted(d["nom"] for d in self.deps)


@respx.mock
def test_m1_new_en_timeout_mais_cree_retire_par_nom():
    gw = FausseGateway(new_echoue=httpx.ReadTimeout("perdu"))
    with pytest.raises(mg.GatewayInjoignable):
        asyncio.run(mg.ajouter("groq", "llama-3.1-8b-instant"))
    assert gw.noms() == []


@respx.mock
def test_m1_exception_pendant_le_test_retire_par_nom(monkeypatch):
    gw = FausseGateway()

    async def test_qui_plante(nom):
        raise RuntimeError("inattendu")
    monkeypatch.setattr(mg, "tester", test_qui_plante)
    with pytest.raises(RuntimeError):
        asyncio.run(mg.ajouter("groq", "llama-3.1-8b-instant"))
    assert gw.noms() == []
