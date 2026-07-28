"""S36 / dette S20 — propagation du token utilisateur par l'adaptateur Forge.

Sans token utilisateur → repli sur le token de **service** (comportement S17 inchangé).
Avec un token utilisateur (capté du ContextVar) → c'est LUI qui part en Bearer, et le
token de service n'est même pas demandé.

Aucun réseau : `client.request` est faux et capture les en-têtes.

Écrit à l'origine comme script autonome (`def run()` + `python3 test_propagation_identite.py`),
donc jamais exécuté par le filet. Converti en tests pytest le 2026-07-28 — les 3 scénarios
sont conservés à l'identique. Le remplacement de `main._auth` passe par `monkeypatch` : le
script restaurait à la main, et une assertion rouge laissait l'adaptateur mocké.
"""
import asyncio

import pytest

import main


class _FakeResponse:
    status_code = 200


class _FakeClient:
    """Capture les en-têtes du dernier appel ; ne touche pas le réseau."""

    def __init__(self):
        self.dernier_headers = None

    async def request(self, methode, url, headers=None, **kw):
        self.dernier_headers = headers or {}
        return _FakeResponse()


@pytest.fixture(autouse=True)
def _contextvar_propre():
    """Le ContextVar est global au processus : sans remise à zéro, un test en teinterait
    un autre (exactement la fuite que le scénario 3 cherche à interdire)."""
    jeton = main._JETON_UTILISATEUR.set(None)
    yield
    main._JETON_UTILISATEUR.reset(jeton)


def test_sans_token_utilisateur_le_token_de_service_est_propage(monkeypatch):
    class _AuthOK:
        configure = True

        async def token(self, client):
            return "SERVICE-TOKEN"

    monkeypatch.setattr(main, "_auth", _AuthOK())
    client = _FakeClient()
    asyncio.run(main._appel_protege(client, "GET", "/api/agents"))
    assert client.dernier_headers["Authorization"] == "Bearer SERVICE-TOKEN", \
        client.dernier_headers


def test_avec_token_utilisateur_le_service_n_est_pas_sollicite(monkeypatch):
    class _AuthExplose:
        configure = True

        async def token(self, client):
            raise AssertionError("le token de service ne doit PAS être demandé")

    main._JETON_UTILISATEUR.set("USER-JWT-123")
    monkeypatch.setattr(main, "_auth", _AuthExplose())
    client = _FakeClient()
    asyncio.run(main._appel_protege(client, "GET", "/api/poles/p1/crm"))
    assert client.dernier_headers["Authorization"] == "Bearer USER-JWT-123", \
        client.dernier_headers


class _Req:
    def __init__(self, valeur):
        self.headers = {"X-Forge-User-Token": valeur} if valeur is not None else {}


def _capter(valeur):
    """Fait passer une requête dans le middleware et rend le jeton vu par la suite."""
    vu = {}

    async def _suite(_req):
        vu["token"] = main._JETON_UTILISATEUR.get()
        return _FakeResponse()

    asyncio.run(main._capter_jeton_utilisateur(_Req(valeur), _suite))
    return vu["token"]


@pytest.mark.parametrize("entete,attendu", [
    ("Bearer ABC", "ABC"),   # préfixe Bearer toléré
    ("XYZ", "XYZ"),          # jeton nu accepté
    (None, None),            # en-tête absent → pas de jeton
])
def test_le_middleware_capte_l_entete_x_forge_user_token(entete, attendu):
    assert _capter(entete) == attendu


def test_le_contextvar_est_remis_a_zero_apres_chaque_requete():
    """Sans ce reset, le jeton d'une personne fuiterait sur la requête suivante."""
    _capter("Bearer ABC")
    assert main._JETON_UTILISATEUR.get() is None, "fuite de token entre requêtes"
