"""Extension S193 : un espace memoire CUSTOM (ni 'perso', ni 'solution'/None) devient
personnellement isolé quand un vrai X-User-Id est transmis — même mécanique que 'perso'
(S186) mais générique, pour que veille-prospection/veille-info stockent leurs résumés dans
un espace "veille" séparé PAR PERSONNE.

Vérifie aussi la NON-régression : les appelants qui ne transmettent JAMAIS X-User-Id
aujourd'hui (Forge memory_palace.py, briques/transcription/main.py) doivent rester sur un
espace partagé, exactement comme avant cette extension.
"""
import json as _json

import httpx
import pytest
import respx

import main

API = main.MEMORY_API
VEILLE_ALICE_ID = "44444444-4444-4444-4444-444444444444"
VEILLE_BOB_ID = "55555555-5555-5555-5555-555555555555"
VEILLE_PARTAGE_ID = "66666666-6666-6666-6666-666666666666"
FORGE_ORG_ID = "77777777-7777-7777-7777-777777777777"
SOLUTION_ID = "88888888-8888-8888-8888-888888888888"


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


def _entetes(utilisateur: str | None = None) -> dict:
    e = {"X-API-Key": "cle-coeur-memoire"}
    if utilisateur:
        e["X-User-Id"] = utilisateur
    return e


def _cablage(rsx: respx.MockRouter):
    rsx.post(f"{API}/api/v1/auth/register").mock(return_value=httpx.Response(200, json={}))

    def _login(request):
        corps = _json.loads(request.content)
        email = corps["email"]
        if email == main.EMAIL:
            return httpx.Response(200, json={"access_token": "jwt-service"})
        utilisateur = email.split("@")[0]
        return httpx.Response(200, json={"access_token": f"jwt-{utilisateur}"})

    rsx.post(f"{API}/api/v1/auth/login").mock(side_effect=_login)

    espaces_personnels = {
        ("alice", "veille-alice"): VEILLE_ALICE_ID,
        ("bob", "veille-bob"): VEILLE_BOB_ID,
    }

    def _list_spaces(request):
        jwt = request.headers["authorization"].removeprefix("Bearer ")
        if jwt == "jwt-service":
            return httpx.Response(200, json=[
                {"id": VEILLE_PARTAGE_ID, "name": "veille"},
                {"id": FORGE_ORG_ID, "name": "forge-org-o1"},
                {"id": SOLUTION_ID, "name": "Workplace"},
            ])
        utilisateur = jwt.removeprefix("jwt-")
        connus = [(u, n) for (u, n) in espaces_personnels if u == utilisateur]
        return httpx.Response(200, json=[
            {"id": espaces_personnels[(u, n)], "name": n} for (u, n) in connus
        ])

    rsx.get(f"{API}/api/v1/spaces").mock(side_effect=_list_spaces)
    rsx.post(f"{API}/api/v1/spaces").mock(return_value=httpx.Response(201, json={
        "id": "new-space-id", "name": "new-space"}))
    rsx.post(f"{API}/api/v1/spaces/{VEILLE_PARTAGE_ID}/invite").mock(
        return_value=httpx.Response(200, json={"detail": "invited"}))
    rsx.post(f"{API}/api/v1/spaces/{SOLUTION_ID}/invite").mock(
        return_value=httpx.Response(200, json={"detail": "invited"}))


@pytest.mark.asyncio
@respx.mock
async def test_espace_custom_avec_x_user_id_devient_personnel():
    _cablage(respx.mock)
    route = respx.post(f"{API}/api/v1/spaces/{VEILLE_ALICE_ID}/nodes").mock(
        return_value=httpx.Response(201, json={"id": "n1", "title": "t", "type": "input"}))
    r = await _appel("POST", "/retenir",
                     json={"contenu": "digest du jour", "espace": "veille",
                          "wing": "veille-info"},
                     headers=_entetes("alice"))
    assert r.status_code == 200
    assert route.called


@pytest.mark.asyncio
@respx.mock
async def test_deux_personnes_espaces_veille_distincts():
    _cablage(respx.mock)
    route_alice = respx.post(f"{API}/api/v1/spaces/{VEILLE_ALICE_ID}/nodes").mock(
        return_value=httpx.Response(201, json={"id": "n1", "title": "t", "type": "input"}))
    route_bob = respx.post(f"{API}/api/v1/spaces/{VEILLE_BOB_ID}/nodes").mock(
        return_value=httpx.Response(201, json={"id": "n2", "title": "t", "type": "input"}))
    await _appel("POST", "/retenir", json={"contenu": "x", "espace": "veille"},
                headers=_entetes("alice"))
    await _appel("POST", "/retenir", json={"contenu": "y", "espace": "veille"},
                headers=_entetes("bob"))
    assert route_alice.called and route_bob.called
    assert route_alice.calls.call_count == 1
    assert route_bob.calls.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_espace_custom_sans_x_user_id_reste_partage():
    """Motif Forge (memory_palace.py) : espace custom nommé, jamais de X-User-Id — doit
    rester EXACTEMENT comme avant cette extension (compte de service, espace partagé)."""
    _cablage(respx.mock)
    route = respx.post(f"{API}/api/v1/spaces/{FORGE_ORG_ID}/nodes").mock(
        return_value=httpx.Response(201, json={"id": "n3", "title": "t", "type": "input"}))
    r = await _appel("POST", "/retenir",
                     json={"contenu": "note projet", "espace": "forge-org-o1"},
                     headers=_entetes(None))
    assert r.status_code == 200
    assert route.called
    # Régression à éviter : un register/login personnel déclenché pour un appelant qui ne
    # transmet jamais X-User-Id.
    assert main._sessions_personne == {}


@pytest.mark.asyncio
@respx.mock
async def test_espace_solution_reste_partage_meme_avec_x_user_id():
    """L'espace solution (None/'solution') ne devient JAMAIS personnel, même avec un vrai
    X-User-Id — seul un espace CUSTOM nommé peut s'isoler par personne."""
    _cablage(respx.mock)
    route = respx.post(f"{API}/api/v1/spaces/{SOLUTION_ID}/nodes").mock(
        return_value=httpx.Response(201, json={"id": "n4", "title": "t", "type": "input"}))
    r = await _appel("POST", "/retenir", json={"contenu": "note", "espace": "solution"},
                     headers=_entetes("alice"))
    assert r.status_code == 200
    assert route.called
    assert main._sessions_personne == {}


@pytest.mark.asyncio
@respx.mock
async def test_perso_garde_son_comportement_historique_inchange():
    """Le mot-clé 'perso' (S186) suit TOUJOURS sa branche dédiée — cette extension ne doit
    rien y changer (nom d'espace 'Perso-<utilisateur>', pas 'perso-<utilisateur>')."""
    perso_alice_id = "99999999-9999-9999-9999-999999999999"
    rsx = respx.mock
    rsx.post(f"{API}/api/v1/auth/register").mock(return_value=httpx.Response(200, json={}))

    def _login(request):
        corps = _json.loads(request.content)
        email = corps["email"]
        if email == main.EMAIL:
            return httpx.Response(200, json={"access_token": "jwt-service"})
        utilisateur = email.split("@")[0]
        return httpx.Response(200, json={"access_token": f"jwt-{utilisateur}"})

    rsx.post(f"{API}/api/v1/auth/login").mock(side_effect=_login)

    def _list_spaces_perso(request):
        jwt = request.headers["authorization"].removeprefix("Bearer ")
        if jwt == "jwt-service":
            return httpx.Response(200, json=[{"id": SOLUTION_ID, "name": "Workplace"}])
        utilisateur = jwt.removeprefix("jwt-")
        if utilisateur == "alice":
            return httpx.Response(200, json=[
                {"id": SOLUTION_ID, "name": "Workplace"},
                {"id": perso_alice_id, "name": f"Perso-alice"}])
        return httpx.Response(200, json=[])

    rsx.get(f"{API}/api/v1/spaces").mock(side_effect=_list_spaces_perso)
    rsx.post(f"{API}/api/v1/spaces").mock(return_value=httpx.Response(201, json={
        "id": "new-space-id", "name": "new-space"}))
    rsx.post(f"{API}/api/v1/spaces/{SOLUTION_ID}/invite").mock(
        return_value=httpx.Response(200, json={"detail": "invited"}))
    route = rsx.post(f"{API}/api/v1/spaces/{perso_alice_id}/nodes").mock(
        return_value=httpx.Response(201, json={"id": "n5", "title": "t", "type": "input"}))
    r = await _appel("POST", "/retenir", json={"contenu": "préfère le bleu", "espace": "perso"},
                     headers=_entetes("alice"))
    assert r.status_code == 200
    assert route.called
