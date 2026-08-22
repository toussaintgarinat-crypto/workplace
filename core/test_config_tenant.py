"""Couches de patch déclaratif pour la config assistant (3e chantier veille dsh/Cordis).

Autonome : aucune vraie brique données (httpx.MockTransport). Mêmes conventions que
core/test_muscle.py.
    $ cd core && python3 -m pytest test_config_tenant.py -v
    $ cd core && python3 test_config_tenant.py
"""
import asyncio
import os
import sys
import tempfile

os.environ["ASSISTANT_CONFIG_PATH"] = os.path.join(tempfile.mkdtemp(), "cfg.json")
os.environ.setdefault("GATEWAY_KEY", "sk-test-local")   # config_assistant l'exige à l'import
sys.path.insert(0, os.path.dirname(__file__))

import httpx  # noqa: E402

import config_tenant  # noqa: E402


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _reset_cache():
    config_tenant._cache.clear()


# ── _fusion (JSON Merge Patch, RFC 7386) ────────────────────────────────────

def test_fusion_remplace_cle_simple():
    base = {"a": 1, "b": 2}
    patch = {"b": 3}
    assert config_tenant._fusion(base, patch) == {"a": 1, "b": 3}


def test_fusion_recursive_sur_dict_imbrique():
    base = {"a": {"x": 1, "y": 2}}
    patch = {"a": {"y": 9}}
    assert config_tenant._fusion(base, patch) == {"a": {"x": 1, "y": 9}}


def test_fusion_remplace_liste_entierement():
    base = {"fallback_models": ["m1", "m2"]}
    patch = {"fallback_models": ["m3"]}
    assert config_tenant._fusion(base, patch) == {"fallback_models": ["m3"]}


def test_fusion_ne_mute_pas_base():
    base = {"a": 1}
    config_tenant._fusion(base, {"a": 2})
    assert base == {"a": 1}


# ── _lire_couche / lire_couche_organisation / lire_couche_utilisateur ──────

def test_lire_couche_absente_renvoie_vide():
    _reset_cache()
    def h(req):
        assert req.headers.get("X-Org-ID") == "acme"
        return httpx.Response(200, json=[])
    async def go():
        async with _client(h) as c:
            return await config_tenant.lire_couche_organisation("acme", client=c)
    assert asyncio.run(go()) == {}


def test_lire_couche_existante_sans_metadonnees():
    _reset_cache()
    def h(req):
        return httpx.Response(200, json=[
            {"persona": "pro", "_id": "r1", "_cree": "t0", "_maj": "t1"}
        ])
    async def go():
        async with _client(h) as c:
            return await config_tenant.lire_couche_utilisateur("acme", "alice", client=c)
    assert asyncio.run(go()) == {"persona": "pro"}


def test_cache_evite_appel_reseau_dans_ttl():
    _reset_cache()
    appels = []
    def h(req):
        appels.append(1)
        return httpx.Response(200, json=[{"persona": "pro", "_id": "r1"}])
    async def go():
        async with _client(h) as c:
            await config_tenant.lire_couche_organisation("acme", client=c)
            return await config_tenant.lire_couche_organisation("acme", client=c)
    resultat = asyncio.run(go())
    assert resultat == {"persona": "pro"}
    assert len(appels) == 1


def test_panne_reseau_repli_cache_expire():
    _reset_cache()
    def h_ok(req):
        return httpx.Response(200, json=[{"persona": "pro", "_id": "r1"}])
    async def premiere_lecture():
        async with _client(h_ok) as c:
            return await config_tenant.lire_couche_organisation("acme", client=c)
    asyncio.run(premiere_lecture())
    # Fait vieillir l'entrée de cache au-delà du TTL sans la vider.
    cle = ("organisation", "acme", config_tenant.ENTITE_ORGANISATION)
    _, patch = config_tenant._cache[cle]
    config_tenant._cache[cle] = (0.0, patch)

    def h_down(req):
        raise httpx.ConnectError("refused", request=req)
    async def deuxieme_lecture():
        async with _client(h_down) as c:
            return await config_tenant.lire_couche_organisation("acme", client=c)
    assert asyncio.run(deuxieme_lecture()) == {"persona": "pro"}


def test_panne_reseau_sans_cache_renvoie_vide():
    _reset_cache()
    def h_down(req):
        raise httpx.ConnectError("refused", request=req)
    async def go():
        async with _client(h_down) as c:
            return await config_tenant.lire_couche_organisation("acme", client=c)
    assert asyncio.run(go()) == {}


# ── resoudre / resoudre_avec_provenance ─────────────────────────────────────

def test_resoudre_sans_couches_egale_charger():
    import config_assistant
    _reset_cache()
    def h(req):
        return httpx.Response(200, json=[])
    async def go():
        async with _client(h) as c:
            return await config_tenant.resoudre("acme", "alice", client=c)
    assert asyncio.run(go()) == config_assistant.charger()


def test_resoudre_precedence_global_organisation_utilisateur():
    _reset_cache()
    def h(req):
        if "/entites/_organisation/" in req.url.path:
            return httpx.Response(200, json=[
                {"persona": "pro", "fallback_models": ["m-org"], "_id": "r1"}
            ])
        if "/entites/alice/" in req.url.path:
            return httpx.Response(200, json=[{"persona": "chaleureux", "_id": "r2"}])
        return httpx.Response(200, json=[])
    async def go():
        async with _client(h) as c:
            return await config_tenant.resoudre("acme", "alice", client=c)
    conf = asyncio.run(go())
    assert conf["persona"] == "chaleureux"          # utilisateur gagne sur organisation
    assert conf["fallback_models"] == ["m-org"]      # organisation gagne sur global
    assert conf["langue"] == "fr"                    # ni touché : reste le global


def test_resoudre_avec_provenance():
    _reset_cache()
    def h(req):
        if "/entites/_organisation/" in req.url.path:
            return httpx.Response(200, json=[{"langue": "en", "_id": "r1"}])
        if "/entites/alice/" in req.url.path:
            return httpx.Response(200, json=[{"persona": "pro", "_id": "r2"}])
        return httpx.Response(200, json=[])
    async def go():
        async with _client(h) as c:
            return await config_tenant.resoudre_avec_provenance("acme", "alice", client=c)
    r = asyncio.run(go())
    assert r["resolu"]["langue"] == "en"
    assert r["resolu"]["persona"] == "pro"
    assert r["provenance"] == {"langue": "organisation", "persona": "utilisateur"}
    assert "model" not in r["provenance"]            # jamais touché → pas de provenance


# ── valider_patch / ecrire_couche_* ─────────────────────────────────────────

def test_valider_patch_rejette_cle_inconnue():
    try:
        config_tenant.valider_patch({"persona": "pro", "bidule": 1})
        assert False, "aurait dû lever ValueError"
    except ValueError as e:
        assert "bidule" in str(e)


def test_valider_patch_accepte_patch_partiel_valide():
    config_tenant.valider_patch({"persona": "pro", "langue": "en"})  # ne lève pas


def test_ecrire_couche_creation():
    _reset_cache()
    def h(req):
        if req.method == "GET":
            return httpx.Response(200, json=[])
        assert req.method == "POST"
        assert req.headers.get("X-Org-ID") == "acme"
        import json as _json
        assert _json.loads(req.content) == {"persona": "pro"}
        return httpx.Response(201, json={"persona": "pro", "_id": "r1",
                                         "_cree": "t0", "_maj": "t0"})
    async def go():
        async with _client(h) as c:
            return await config_tenant.ecrire_couche_organisation("acme", {"persona": "pro"}, client=c)
    assert asyncio.run(go()) == {"persona": "pro"}


def test_ecrire_couche_mise_a_jour_fusionne_sur_existant():
    _reset_cache()
    def h(req):
        if req.method == "GET":
            return httpx.Response(200, json=[
                {"persona": "pro", "langue": "en", "_id": "r1", "_cree": "t0", "_maj": "t0"}
            ])
        assert req.method == "PUT"
        assert req.url.path.endswith("/r1")
        import json as _json
        assert _json.loads(req.content) == {"persona": "pro", "langue": "fr"}
        return httpx.Response(200, json={"persona": "pro", "langue": "fr",
                                         "_id": "r1", "_cree": "t0", "_maj": "t1"})
    async def go():
        async with _client(h) as c:
            return await config_tenant.ecrire_couche_organisation("acme", {"langue": "fr"}, client=c)
    assert asyncio.run(go()) == {"persona": "pro", "langue": "fr"}


def test_ecrire_couche_invalide_cache_avant_expiration():
    _reset_cache()
    def h(req):
        if req.method == "GET":
            return httpx.Response(200, json=[])
        return httpx.Response(201, json={"persona": "pro", "_id": "r1"})
    async def ecrire():
        async with _client(h) as c:
            return await config_tenant.ecrire_couche_organisation("acme", {"persona": "pro"}, client=c)
    asyncio.run(ecrire())

    def h_jamais_appele(req):
        raise AssertionError("ne doit pas taper le réseau : le cache vient d'être posé")
    async def relire():
        async with _client(h_jamais_appele) as c:
            return await config_tenant.lire_couche_organisation("acme", client=c)
    assert asyncio.run(relire()) == {"persona": "pro"}


def test_ecrire_couche_panne_reseau_remonte_erreur():
    _reset_cache()
    def h_down(req):
        raise httpx.ConnectError("refused", request=req)
    async def go():
        async with _client(h_down) as c:
            return await config_tenant.ecrire_couche_organisation("acme", {"persona": "pro"}, client=c)
    try:
        asyncio.run(go())
        assert False, "aurait dû laisser remonter httpx.ConnectError"
    except httpx.ConnectError:
        pass


def test_ecrire_couche_utilisateur_cle_cache_distincte_de_organisation():
    _reset_cache()
    def h(req):
        if req.method == "GET":
            return httpx.Response(200, json=[])
        return httpx.Response(201, json={"persona": "chaleureux", "_id": "r1"})
    async def go():
        async with _client(h) as c:
            return await config_tenant.ecrire_couche_utilisateur(
                "acme", "alice", {"persona": "chaleureux"}, client=c)
    asyncio.run(go())
    assert ("utilisateur", "acme", "alice") in config_tenant._cache
    assert ("organisation", "acme", config_tenant.ENTITE_ORGANISATION) not in config_tenant._cache


if __name__ == "__main__":
    for nom, fn in list(globals().items()):
        if nom.startswith("test_") and callable(fn):
            fn()
            print(f"  ✓ {nom}")
    print("\n✅ TOUS LES TESTS PASSENT")
