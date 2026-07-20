"""Isolation PAR PERSONNE (S186) : chaque utilisateur du cercle privé a SON compte Memory,
son espace « Perso-<utilisateur> » privé (le compte de service n'y a PAS accès), et rejoint
automatiquement l'espace PARTAGÉ Workplace (invite idempotente).

Le mono-user historique (pas de X-User-Id / pas de session) reste sur le compte de service
et l'espace "Perso" tel qu'il existait avant S186 — zéro migration, cf. test_memoire.py qui
continue de passer inchangé.
"""
import json as _json

import httpx
import pytest
import respx

import main

API = main.MEMORY_API
WORKPLACE_ID = "11111111-1111-1111-1111-111111111111"
PERSO_CLAIRE_ID = "22222222-2222-2222-2222-222222222222"
PERSO_MARINA_ID = "33333333-3333-3333-3333-333333333333"


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    main._session["token"] = None
    main._espaces.clear()
    main._sessions_personne.clear()
    main._espaces_personne.clear()
    monkeypatch.setenv("MEMOIRE_KEY", "cle-coeur-memoire")
    yield
    main._session["token"] = None
    main._espaces.clear()
    main._sessions_personne.clear()
    main._espaces_personne.clear()


async def _appel(method: str, url: str, **kw):
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://brique") as c:
        return await c.request(method, url, **kw)


def _entetes(utilisateur: str) -> dict:
    return {"X-API-Key": "cle-coeur-memoire", "X-User-Id": utilisateur}


def _cablage_complet(rsx: respx.MockRouter):
    """Câble : compte de service (Workplace + invite), et un compte par personne dont le
    JWT encode son nom (« jwt-<utilisateur> ») pour router les réponses par Authorization."""
    rsx.post(f"{API}/api/v1/auth/register").mock(return_value=httpx.Response(200, json={}))

    def _login(request):
        corps = _json.loads(request.content)
        email = corps["email"]
        if email == main.EMAIL:
            return httpx.Response(200, json={"access_token": "jwt-service"})
        utilisateur = email.split("@")[0]
        return httpx.Response(200, json={"access_token": f"jwt-{utilisateur}"})

    rsx.post(f"{API}/api/v1/auth/login").mock(side_effect=_login)

    espaces_par_personne = {
        "claire": PERSO_CLAIRE_ID,
        "marina": PERSO_MARINA_ID,
    }

    def _list_spaces(request):
        jwt = request.headers["authorization"].removeprefix("Bearer ")
        if jwt == "jwt-service":
            return httpx.Response(200, json=[{"id": WORKPLACE_ID, "name": "Workplace"}])
        utilisateur = jwt.removeprefix("jwt-")
        # La personne est déjà membre de Workplace (invite faite) ET a déjà son Perso créé.
        return httpx.Response(200, json=[
            {"id": WORKPLACE_ID, "name": "Workplace"},
            {"id": espaces_par_personne[utilisateur], "name": f"Perso-{utilisateur}"},
        ])

    rsx.get(f"{API}/api/v1/spaces").mock(side_effect=_list_spaces)
    rsx.post(f"{API}/api/v1/spaces/{WORKPLACE_ID}/invite").mock(
        return_value=httpx.Response(200, json={"detail": "invited"}))


@pytest.mark.asyncio
@respx.mock
async def test_deux_personnes_espaces_perso_distincts():
    _cablage_complet(respx.mock)
    route = respx.post(f"{API}/api/v1/spaces/{PERSO_CLAIRE_ID}/nodes").mock(
        return_value=httpx.Response(201, json={"id": "n1", "title": "t", "type": "input"}))
    r = await _appel("POST", "/retenir",
                     json={"contenu": "préfère le bleu", "espace": "perso"},
                     headers=_entetes("claire"))
    assert r.status_code == 200
    assert route.called

    route_marina = respx.post(f"{API}/api/v1/spaces/{PERSO_MARINA_ID}/nodes").mock(
        return_value=httpx.Response(201, json={"id": "n2", "title": "t", "type": "input"}))
    r2 = await _appel("POST", "/retenir",
                      json={"contenu": "préfère le vert", "espace": "perso"},
                      headers=_entetes("marina"))
    assert r2.status_code == 200
    assert route_marina.called
    # Chaque souvenir a tapé SON espace, jamais celui de l'autre (routes distinctes par id).
    assert route.calls.call_count == 1
    assert route_marina.calls.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_personne_invitee_automatiquement_dans_workplace():
    rsx = respx.mock
    _cablage_complet(rsx)
    invite = rsx.post(f"{API}/api/v1/spaces/{WORKPLACE_ID}/invite")
    respx.get(f"{API}/api/v1/spaces/{PERSO_CLAIRE_ID}/search").mock(
        return_value=httpx.Response(200, json=[]))
    await _appel("GET", "/rappeler", params={"q": "x", "espace": "perso"},
                headers=_entetes("claire"))
    assert invite.called
    corps = _json.loads(invite.calls.last.request.content)
    assert corps == {"email": "claire@workplace.local", "role": "member"}


@pytest.mark.asyncio
@respx.mock
async def test_mono_user_historique_reste_sur_le_compte_de_service():
    """Sans X-User-Id (ou X-User-Id="perso") : le motif AVANT S186, zéro migration."""
    rsx = respx.mock
    rsx.post(f"{API}/api/v1/auth/register").mock(return_value=httpx.Response(200, json={}))
    rsx.post(f"{API}/api/v1/auth/login").mock(
        return_value=httpx.Response(200, json={"access_token": "jwt-service"}))
    rsx.get(f"{API}/api/v1/spaces").mock(return_value=httpx.Response(200, json=[
        {"id": WORKPLACE_ID, "name": "Workplace"},
        {"id": "perso-legacy-id", "name": "Perso"},
    ]))
    route = rsx.post(f"{API}/api/v1/spaces/perso-legacy-id/nodes").mock(
        return_value=httpx.Response(201, json={"id": "n", "title": "t", "type": "input"}))
    # Le Cœur appelle avec sa clé de service mais SANS X-User-Id résolu (ex. tâche de fond) :
    # identité par défaut "perso", motif inchangé depuis avant S186.
    r = await _appel("POST", "/retenir", json={"contenu": "x", "espace": "perso"},
                     headers={"X-API-Key": "cle-coeur-memoire"})
    assert r.status_code == 200
    assert route.called
    # Aucun compte par personne créé : un seul login (le service), pas de register "perso@…".
    assert main._sessions_personne == {}


@pytest.mark.asyncio
@respx.mock
async def test_cle_invalide_401():
    r = await _appel("GET", "/rappeler", params={"q": "x"},
                     headers={"X-API-Key": "mauvaise-cle", "X-User-Id": "claire"})
    assert r.status_code == 401


@pytest.mark.asyncio
@respx.mock
async def test_sans_cle_configuree_mode_ouvert(monkeypatch):
    monkeypatch.delenv("MEMOIRE_KEY", raising=False)
    rsx = respx.mock
    rsx.post(f"{API}/api/v1/auth/register").mock(return_value=httpx.Response(200, json={}))
    rsx.post(f"{API}/api/v1/auth/login").mock(
        return_value=httpx.Response(200, json={"access_token": "jwt-x"}))
    rsx.get(f"{API}/api/v1/spaces").mock(return_value=httpx.Response(200, json=[
        {"id": WORKPLACE_ID, "name": "Workplace"}]))
    respx.get(f"{API}/api/v1/spaces/{WORKPLACE_ID}/search").mock(
        return_value=httpx.Response(200, json=[]))
    r = await _appel("GET", "/rappeler", params={"q": "x"}, headers={"X-User-Id": "claire"})
    assert r.status_code == 200
