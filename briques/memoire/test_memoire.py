"""Tests offline de la brique « memoire » — le backend Memory est mocké (respx).

But : prouver le contrat (retenir/rappeler/souvenirs/taxonomy/delete) et le
mapping vers l'API Memory (location wing/room, frontmatter, type, score) sans
DB ni réseau réel.

    pip install -r requirements-dev.txt && pytest -q
"""

import httpx
import pytest
import respx

import main

API = main.MEMORY_API
ESPACE_ID = "11111111-1111-1111-1111-111111111111"


@pytest.fixture(autouse=True)
def _reset_session():
    """Repart d'une session/espaces vierges à chaque test."""
    main._session["token"] = None
    main._espaces.clear()
    yield
    main._session["token"] = None
    main._espaces.clear()


def _mock_auth_et_espace(rsx: respx.MockRouter):
    """Câble l'auth de service + la résolution d'espace (Workplace) commune à tout."""
    rsx.post(f"{API}/api/v1/auth/register").mock(return_value=httpx.Response(200, json={}))
    rsx.post(f"{API}/api/v1/auth/login").mock(
        return_value=httpx.Response(200, json={"access_token": "jwt-de-service"})
    )
    rsx.get(f"{API}/api/v1/spaces").mock(
        return_value=httpx.Response(200, json=[{"id": ESPACE_ID, "name": "Workplace"}])
    )


async def _appel(method: str, url: str, **kw):
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://brique") as c:
        return await c.request(method, url, **kw)


@pytest.mark.asyncio
@respx.mock
async def test_sante_ok():
    _mock_auth_et_espace(respx.mock)
    r = await _appel("GET", "/sante")
    assert r.status_code == 200
    body = r.json()
    assert body["statut"] == "ok"
    assert body["version"] == main.VERSION
    assert body["espaces"]["Workplace"] == ESPACE_ID


@pytest.mark.asyncio
@respx.mock
async def test_retenir_mappe_location_et_frontmatter():
    _mock_auth_et_espace(respx.mock)
    route = respx.post(f"{API}/api/v1/spaces/{ESPACE_ID}/nodes").mock(
        return_value=httpx.Response(201, json={
            "id": "node-1", "title": "Note", "type": "input",
            "location": {"wing": "wing_user", "room": "documents"},
        })
    )
    r = await _appel("POST", "/retenir", json={
        "contenu": "Le client préfère le bleu",
        "titre": "Note",
        "wing": "wing_user", "room": "documents",
        "hall": "hall_facts", "metadata": {"doc_id": "d42"},
    })
    assert r.status_code == 200
    assert r.json() == {"retenu": True, "id": "node-1", "titre": "Note",
                        "type": "input", "wing": "wing_user", "room": "documents"}
    # Le corps envoyé à Memory porte bien location + frontmatter fusionné.
    # wing/room sont AUSSI dans le frontmatter (round-trip fiable si Memory ne
    # persiste pas location).
    envoye = route.calls.last.request
    import json as _json
    corps = _json.loads(envoye.content)
    assert corps["location"] == {"wing": "wing_user", "room": "documents"}
    assert corps["frontmatter"] == {"doc_id": "d42", "hall": "hall_facts",
                                    "wing": "wing_user", "room": "documents"}
    assert corps["type"] == "input"


@pytest.mark.asyncio
@respx.mock
async def test_retenir_reessaie_une_fois_si_jeton_expire():
    """Si Memory répond 401 sur le jeton mémoïsé (expiré côté Memory — `_token` ne le
    détecte jamais lui-même, il renvoie juste la valeur en cache), on invalide le cache
    et on réessaie UNE fois avec un jeton frais avant d'abandonner. Sans ce filet, un
    401 casse SILENCIEUSEMENT tout appelant jusqu'à un redémarrage manuel du conteneur —
    bug constaté en prod le 2026-07-23 (jeton de service resté ~30h en cache)."""
    _mock_auth_et_espace(respx.mock)
    route = respx.post(f"{API}/api/v1/spaces/{ESPACE_ID}/nodes").mock(
        side_effect=[
            httpx.Response(401, json={"detail": "Invalid token"}),
            httpx.Response(201, json={"id": "node-1", "title": "Note", "type": "input"}),
        ]
    )
    r = await _appel("POST", "/retenir", json={"contenu": "test", "titre": "Note"})
    assert r.status_code == 200
    assert r.json()["id"] == "node-1"
    assert route.call_count == 2


@pytest.mark.asyncio
@respx.mock
async def test_retenir_abandonne_si_le_jeton_frais_echoue_aussi():
    """Un seul essai de plus (pas de boucle infinie) : si le second essai échoue aussi,
    on relaie l'erreur normalement (502)."""
    _mock_auth_et_espace(respx.mock)
    route = respx.post(f"{API}/api/v1/spaces/{ESPACE_ID}/nodes").mock(
        return_value=httpx.Response(401, json={"detail": "Invalid token"})
    )
    r = await _appel("POST", "/retenir", json={"contenu": "test", "titre": "Note"})
    assert r.status_code == 502
    assert route.call_count == 2


@pytest.mark.asyncio
@respx.mock
async def test_taxonomy_reessaie_une_fois_si_jeton_expire():
    """Même filet que /retenir, sur une route GET (chemin _appel différent : /stats)."""
    _mock_auth_et_espace(respx.mock)
    respx.get(f"{API}/api/v1/spaces/{ESPACE_ID}/stats").mock(
        side_effect=[
            httpx.Response(401, json={"detail": "Invalid token"}),
            httpx.Response(200, json={"total_nodes": 3, "by_type": {}, "by_stage": {}}),
        ]
    )
    r = await _appel("GET", "/taxonomy")
    assert r.status_code == 200
    assert r.json()["total"] == 3


@pytest.mark.asyncio
@respx.mock
async def test_retenir_wing_defaut_reflete_le_type():
    _mock_auth_et_espace(respx.mock)
    route = respx.post(f"{API}/api/v1/spaces/{ESPACE_ID}/nodes").mock(
        return_value=httpx.Response(201, json={"id": "n", "title": "t", "type": "projet"})
    )
    await _appel("POST", "/retenir", json={"contenu": "x", "type": "projet"})
    import json as _json
    corps = _json.loads(route.calls.last.request.content)
    assert corps["type"] == "projet"
    assert corps["location"] == {"wing": "projet", "room": "general"}


@pytest.mark.asyncio
@respx.mock
async def test_retenir_type_invalide_retombe_sur_input():
    _mock_auth_et_espace(respx.mock)
    route = respx.post(f"{API}/api/v1/spaces/{ESPACE_ID}/nodes").mock(
        return_value=httpx.Response(201, json={"id": "n", "title": "t", "type": "input"})
    )
    await _appel("POST", "/retenir", json={"contenu": "x", "type": "n_importe_quoi"})
    import json as _json
    assert _json.loads(route.calls.last.request.content)["type"] == "input"


@pytest.mark.asyncio
@respx.mock
async def test_rappeler_remonte_le_score():
    _mock_auth_et_espace(respx.mock)
    respx.get(f"{API}/api/v1/spaces/{ESPACE_ID}/search").mock(
        return_value=httpx.Response(200, json=[
            {"id": "a", "title": "Aria", "content_md": "voix calme", "type": "input", "score": 0.87},
        ])
    )
    r = await _appel("GET", "/rappeler", params={"q": "voix"})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["souvenirs"][0]["score"] == 0.87
    assert body["souvenirs"][0]["extrait"] == "voix calme"


@pytest.mark.asyncio
@respx.mock
async def test_rappeler_filtre_par_type():
    _mock_auth_et_espace(respx.mock)
    route = respx.get(f"{API}/api/v1/spaces/{ESPACE_ID}/search").mock(
        return_value=httpx.Response(200, json=[])
    )
    await _appel("GET", "/rappeler", params={"q": "x", "type": "projet"})
    assert route.calls.last.request.url.params["type"] == "projet"


@pytest.mark.asyncio
@respx.mock
async def test_souvenirs_filtre_et_vue_location():
    _mock_auth_et_espace(respx.mock)
    route = respx.get(f"{API}/api/v1/spaces/{ESPACE_ID}/nodes").mock(
        return_value=httpx.Response(200, json=[
            {"id": "n1", "title": "T1", "content_md": "c1", "type": "input",
             "location": {"wing": "wing_user", "room": "documents"},
             "frontmatter": {"hall": "hall_facts"},
             "ipcra_stage": "captured", "storage_tier": "hot"},
        ])
    )
    r = await _appel("GET", "/souvenirs", params={"type": "input", "wing": "wing_user"})
    assert r.status_code == 200
    s = r.json()["souvenirs"][0]
    assert s["wing"] == "wing_user" and s["room"] == "documents"
    assert s["metadata"] == {"hall": "hall_facts"}
    p = route.calls.last.request.url.params
    assert p["type"] == "input" and p["wing"] == "wing_user"


@pytest.mark.asyncio
@respx.mock
async def test_taxonomy_comptes_par_type():
    _mock_auth_et_espace(respx.mock)
    respx.get(f"{API}/api/v1/spaces/{ESPACE_ID}/stats").mock(
        return_value=httpx.Response(200, json={
            "total_nodes": 5, "by_type": {"input": 3, "projet": 2}, "by_stage": {}, "by_tier": {}})
    )
    r = await _appel("GET", "/taxonomy")
    assert r.status_code == 200
    assert r.json()["par_type"] == {"input": 3, "projet": 2}
    assert r.json()["total"] == 5


@pytest.mark.asyncio
@respx.mock
async def test_supprimer_souvenir():
    _mock_auth_et_espace(respx.mock)
    route = respx.delete(f"{API}/api/v1/spaces/{ESPACE_ID}/nodes/node-1").mock(
        return_value=httpx.Response(200, json={"detail": "deleted"})
    )
    r = await _appel("DELETE", "/souvenir/node-1")
    assert r.status_code == 200
    assert r.json() == {"supprime": True, "id": "node-1"}
    assert route.called


@pytest.mark.asyncio
@respx.mock
async def test_supprimer_404_tolere():
    _mock_auth_et_espace(respx.mock)
    respx.delete(f"{API}/api/v1/spaces/{ESPACE_ID}/nodes/absent").mock(
        return_value=httpx.Response(404, json={"detail": "not found"})
    )
    r = await _appel("DELETE", "/souvenir/absent")
    assert r.status_code == 200
    assert r.json()["supprime"] is True


# ── Front React (S108) : proxy /api/v1, redirection, bootstrap d'auth ────────────


@pytest.mark.asyncio
@respx.mock
async def test_proxy_force_le_jwt_de_service():
    """Le proxy /api/v1 relaie vers le backend en posant TOUJOURS l'auth de service."""
    _mock_auth_et_espace(respx.mock)
    route = respx.get(f"{API}/api/v1/spaces/{ESPACE_ID}/graph").mock(
        return_value=httpx.Response(200, json={"nodes": [], "edges": []})
    )
    # On envoie un Authorization bidon : le proxy doit l'écraser par le JWT de service.
    r = await _appel("GET", f"/api/v1/spaces/{ESPACE_ID}/graph",
                     headers={"Authorization": "Bearer perime"})
    assert r.status_code == 200
    assert r.json() == {"nodes": [], "edges": []}
    assert route.calls.last.request.headers["authorization"] == "Bearer jwt-de-service"


@pytest.mark.asyncio
@respx.mock
async def test_proxy_relaie_corps_et_query():
    """POST proxifié : corps et paramètres de requête traversent vers le backend."""
    _mock_auth_et_espace(respx.mock)
    route = respx.post(f"{API}/api/v1/spaces/{ESPACE_ID}/nodes").mock(
        return_value=httpx.Response(201, json={"id": "n9"})
    )
    r = await _appel("POST", f"/api/v1/spaces/{ESPACE_ID}/nodes?dry=1",
                     json={"title": "T", "type": "input"})
    assert r.status_code == 201 and r.json()["id"] == "n9"
    req = route.calls.last.request
    assert req.url.params["dry"] == "1"
    import json as _json
    assert _json.loads(req.content)["title"] == "T"


@pytest.mark.asyncio
async def test_racine_redirige_vers_memoire():
    r = await _appel("GET", "/", follow_redirects=False)
    assert r.status_code in (307, 308)
    assert r.headers["location"] == "/memory"


@pytest.mark.asyncio
@respx.mock
async def test_spa_injecte_le_bootstrap(tmp_path, monkeypatch):
    """La route SPA /memory rend l'index avec le pré-remplissage localStorage (auth+espace)."""
    _mock_auth_et_espace(respx.mock)
    (tmp_path / "index.html").write_text(
        "<!doctype html><html><head><title>x</title></head><body></body></html>",
        encoding="utf-8",
    )
    monkeypatch.setattr(main, "UI_DIR", tmp_path)
    r = await _appel("GET", "/memory")
    assert r.status_code == 200
    html = r.text
    assert "localStorage.setItem('auth_token'" in html
    assert "jwt-de-service" in html
    assert ESPACE_ID in html
    assert "</head>" in html  # le script est injecté AVANT la fermeture de head


@pytest.mark.asyncio
async def test_spa_sans_front_rend_un_repli_honnete():
    """Sans front buildé (UI_DIR absent), la SPA renvoie un repli HTML sans planter."""
    r = await _appel("GET", "/memory/graph")
    assert r.status_code == 200
    assert "Front non buildé" in r.text
