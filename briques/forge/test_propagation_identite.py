"""S36 / dette S20 — propagation du token utilisateur par l'adaptateur Forge.

Sans token utilisateur → repli sur le token de **service** (comportement S17 inchangé).
Avec un token utilisateur (capté du ContextVar) → c'est LUI qui part en Bearer, et le
token de service n'est même pas demandé.

Aucun réseau : `client.request` est faux et capture les en-têtes.
Lancer : `python3 test_propagation_identite.py`.
"""

import asyncio

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


def run():
    ok = 0

    # ── 1. Repli service : pas de token utilisateur → token de service en Bearer ──
    main._JETON_UTILISATEUR.set(None)

    class _AuthOK:
        configure = True
        async def token(self, client):
            return "SERVICE-TOKEN"
    orig_auth = main._auth
    main._auth = _AuthOK()
    client = _FakeClient()
    asyncio.run(main._appel_protege(client, "GET", "/api/agents"))
    main._auth = orig_auth
    assert client.dernier_headers["Authorization"] == "Bearer SERVICE-TOKEN", client.dernier_headers
    print("✅ 1. repli : sans token utilisateur → token de service propagé (S17 inchangé)")
    ok += 1

    # ── 2. Propagation : token utilisateur présent → c'est lui, service non sollicité ──
    jeton = main._JETON_UTILISATEUR.set("USER-JWT-123")

    class _AuthExplose:
        configure = True
        async def token(self, client):
            raise AssertionError("le token de service ne doit PAS être demandé")
    main._auth = _AuthExplose()
    client2 = _FakeClient()
    asyncio.run(main._appel_protege(client2, "GET", "/api/poles/p1/crm"))
    main._auth = orig_auth
    main._JETON_UTILISATEUR.reset(jeton)
    assert client2.dernier_headers["Authorization"] == "Bearer USER-JWT-123", client2.dernier_headers
    print("✅ 2. propagation : token utilisateur présent → propagé, service non sollicité")
    ok += 1

    # ── 3. Middleware : X-Forge-User-Token (avec ou sans préfixe Bearer) → ContextVar ──
    captures = {}

    class _Req:
        def __init__(self, val):
            self.headers = {"X-Forge-User-Token": val} if val is not None else {}

    async def _next(_req):
        captures["token"] = main._JETON_UTILISATEUR.get()
        return _FakeResponse()

    asyncio.run(main._capter_jeton_utilisateur(_Req("Bearer ABC"), _next))
    assert captures["token"] == "ABC", captures
    asyncio.run(main._capter_jeton_utilisateur(_Req("XYZ"), _next))
    assert captures["token"] == "XYZ", captures
    asyncio.run(main._capter_jeton_utilisateur(_Req(None), _next))
    assert captures["token"] is None, captures
    # Le ContextVar est bien remis à zéro après chaque requête (pas de fuite).
    assert main._JETON_UTILISATEUR.get() is None, "fuite de token entre requêtes"
    print("✅ 3. middleware : X-Forge-User-Token capté (Bearer toléré), reset après requête")
    ok += 1

    print(f"\n{ok}/3 scénarios OK")
    return ok


if __name__ == "__main__":
    import sys
    sys.exit(0 if run() == 3 else 1)
