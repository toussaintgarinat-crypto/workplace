"""Tests des routes /auth/* du Cœur (S171).

$ cd core && python3 -m pytest test_auth_routes.py -v
"""
import os
import tempfile

os.environ.setdefault("VAULT_SECRET", "test-secret-0123456789")
os.environ.setdefault("GATEWAY_KEY", "test")
os.environ.setdefault("AUTH_SESSION_SECRET", "test-session-secret-0123456789")

import main  # noqa: E402
import auth  # noqa: E402
import session_registre  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
import pytest  # noqa: E402

client = TestClient(main.app)


@pytest.fixture(autouse=True)
def _registre_isole():
    """Repointe `session_registre.DB` vers un fichier neuf à CHAQUE test (Task 4).

    Depuis que `exiger_session` consulte `session_registre.generation_actuelle` (Task 4),
    des tests de ce fichier sans rapport entre eux mais réutilisant le même sub factice
    (`marina`, motif hérité de S171) se contaminent : un test qui passe par le vrai
    `/auth/callback` (p. ex. `test_callback_ok_pose_session_et_redirige_dashboard`) inscrit
    une génération réelle pour `marina` au registre PARTAGÉ ; un test plus loin qui fabrique
    à la main un cookie « valide » sans champ `generation` pour ce même sub se fait alors
    évincer par erreur — pas un bug d'`exiger_session`, un couplage d'ordre entre tests.
    Repartir d'un registre neuf à chaque test (attribut relu dynamiquement par `_conn()`,
    jamais figé dans une closure) élimine ce couplage sans toucher au sub de chaque test."""
    ancien = session_registre.DB
    session_registre.DB = os.path.join(tempfile.mkdtemp(), "session_registre.db")
    try:
        yield
    finally:
        session_registre.DB = ancien


def test_login_redirige_vers_keycloak_avec_pkce():
    r = client.get("/auth/login", follow_redirects=False)
    assert r.status_code == 307
    location = r.headers["location"]
    assert location.startswith(f"{auth.KEYCLOAK_URL}/realms/{auth.KEYCLOAK_REALM}/protocol/openid-connect/auth?")
    assert "code_challenge=" in location
    assert "code_challenge_method=S256" in location
    assert f"client_id={auth.KEYCLOAK_CLIENT_ID}" in location
    assert auth.COOKIE_PENDING in r.cookies


def test_callback_state_invalide_renvoie_400():
    r = client.get("/auth/login", follow_redirects=False)
    pending_cookie = r.cookies[auth.COOKIE_PENDING]
    r2 = client.get(
        "/auth/callback",
        params={"code": "code-abc", "state": "state-different"},
        cookies={auth.COOKIE_PENDING: pending_cookie},
        follow_redirects=False,
    )
    assert r2.status_code == 400


def test_callback_ok_pose_session_et_redirige_dashboard(monkeypatch):
    r = client.get("/auth/login", follow_redirects=False)
    pending_cookie = r.cookies[auth.COOKIE_PENDING]
    pending = auth.dechiffrer_cookie(pending_cookie)

    async def _echanger_fake(code, code_verifier, redirect_uri):
        assert code == "code-abc"
        assert code_verifier == pending["code_verifier"]
        return {"access_token": "at-1", "refresh_token": "rt-1", "expires_in": 300}

    async def _verify_fake(token, kc):
        return {"sub": "marina", "nom": "Marina", "avatarEmoji": "🌙"}

    monkeypatch.setattr(auth, "echanger_code", _echanger_fake)
    monkeypatch.setattr(auth, "verify_token", _verify_fake)

    r2 = client.get(
        "/auth/callback",
        params={"code": "code-abc", "state": pending["state"]},
        cookies={auth.COOKIE_PENDING: pending_cookie},
        follow_redirects=False,
    )
    assert r2.status_code == 307
    assert r2.headers["location"] == "/dashboard"
    session = auth.dechiffrer_cookie(r2.cookies[auth.COOKIE_SESSION])
    assert session["sub"] == "marina"
    assert session["refresh_token"] == "rt-1"


def test_callback_echange_code_echoue_redirige_login_sans_500(monkeypatch):
    """Code expiré/déjà utilisé (retour arrière navigateur, double-soumission) ou Keycloak
    injoignable : `echanger_code` lève (HTTPStatusError, ConnectError…) — le callback doit
    rediriger proprement vers /auth/login (303), jamais laisser fuiter un 500 nu (spec S171)."""
    r = client.get("/auth/login", follow_redirects=False)
    pending_cookie = r.cookies[auth.COOKIE_PENDING]
    pending = auth.dechiffrer_cookie(pending_cookie)

    async def _echanger_qui_echoue(code, code_verifier, redirect_uri):
        raise Exception("code d'autorisation expiré ou déjà utilisé")

    monkeypatch.setattr(auth, "echanger_code", _echanger_qui_echoue)

    r2 = client.get(
        "/auth/callback",
        params={"code": "code-perime", "state": pending["state"]},
        cookies={auth.COOKIE_PENDING: pending_cookie},
        follow_redirects=False,
    )
    assert r2.status_code == 303
    assert r2.headers["location"] == "/auth/login"


def test_logout_supprime_le_cookie_et_termine_la_session_sso():
    r = client.get("/auth/logout", follow_redirects=False)
    assert r.status_code == 303
    # httpx TestClient expose la suppression via un cookie expiré (Max-Age=0) dans les headers.
    set_cookie = r.headers.get("set-cookie", "")
    assert auth.COOKIE_SESSION in set_cookie
    # Doit traverser le end-session Keycloak (sinon la session SSO encore active relogue
    # silencieusement à la prochaine visite de /auth/login — le bouton semblerait ne rien faire).
    location = r.headers["location"]
    assert location.startswith(f"{auth.KEYCLOAK_URL}/realms/{auth.KEYCLOAK_REALM}/protocol/openid-connect/logout?")
    assert f"client_id={auth.KEYCLOAK_CLIENT_ID}" in location
    assert "post_logout_redirect_uri=" in location


def test_logout_purge_le_registre_de_session():
    """Important 4 (revue finale whole-branch) : sans ça, un logout propre suivi d'une
    reconnexion normale déclenche quand même un checkpoint fantôme (le registre croit
    encore une session active pour ce compte)."""
    session_registre.nouvelle_session("marina-purge-logout", "iPhone")
    assert session_registre.generation_actuelle("marina-purge-logout") == 1

    cookie = auth.chiffrer_cookie({
        "sub": "marina-purge-logout", "refresh_token": "rt-1", "generation": 1,
        "registre_id": session_registre.identifiant_registre(),
    })
    r = client.get("/auth/logout", cookies={auth.COOKIE_SESSION: cookie}, follow_redirects=False)
    assert r.status_code == 303
    assert session_registre.generation_actuelle("marina-purge-logout") is None


def test_dashboard_accessible_sans_session_quand_auth_desactivee():
    """Non-régression : AUTH_ENABLED=false (défaut) — comportement historique inchangé,
    /dashboard reste accessible en accès direct (core/test_dashboard.py doit continuer
    de passer sans modification)."""
    assert auth.AUTH_ENABLED is False
    r = client.get("/dashboard")
    assert r.status_code == 200


def test_dashboard_redirige_vers_login_quand_auth_activee():
    ancien = auth.AUTH_ENABLED
    auth.AUTH_ENABLED = True
    try:
        r = client.get("/dashboard", follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"] == "/auth/login"
    finally:
        auth.AUTH_ENABLED = ancien


def test_dashboard_accessible_avec_session_valide_quand_auth_activee():
    ancien = auth.AUTH_ENABLED
    auth.AUTH_ENABLED = True
    auth._cache_access_token.clear()
    try:
        cookie = auth.chiffrer_cookie({
            "sub": "marina", "refresh_token": "rt-1", "nom": "Marina", "avatarEmoji": "🌙",
        })
        import time
        auth._cache_access_token["marina"] = ("at-cache", time.time() + 60)
        r = client.get("/dashboard", cookies={auth.COOKIE_SESSION: cookie})
        assert r.status_code == 200
    finally:
        auth.AUTH_ENABLED = ancien
        auth._cache_access_token.clear()


def test_parcours_complet_login_callback_puis_dashboard_avec_refresh_a_froid(monkeypatch):
    """Bout-en-bout sur le vrai chemin d'un navigateur : un seul TestClient qui garde ses
    cookies d'une requête à l'autre (comme un navigateur réel), pas des appels isolés.
    (a) /auth/login pose le cookie pending ; (b) /auth/callback le consomme et pose le
    cookie de session ; (c) /dashboard, cache access-token FROID, déclenche un vrai
    rafraîchissement — referme le seam jamais exercé par les tests unitaires ci-dessus."""
    # base_url en https : les cookies posés ici sont `Secure` (AUTH_COOKIE_SECURE=true par
    # défaut) — un TestClient en http://testserver ne les réémettrait jamais sur les
    # requêtes suivantes (comportement réel des navigateurs), cassant l'enchaînement.
    parcours = TestClient(main.app, base_url="https://testserver")
    ancien = auth.AUTH_ENABLED

    try:
        # (a) login → cookie pending posé sur le client, cookies conservés automatiquement
        r_login = parcours.get("/auth/login", follow_redirects=False)
        assert r_login.status_code == 307
        pending = auth.dechiffrer_cookie(parcours.cookies[auth.COOKIE_PENDING])

        # (b) callback → mock des appels Keycloak, cookie de session posé
        async def _echanger_fake(code, code_verifier, redirect_uri):
            return {"access_token": "at-parcours", "refresh_token": "rt-parcours", "expires_in": 300}

        async def _verify_fake(token, kc):
            return {"sub": "marina", "nom": "Marina", "avatarEmoji": "🌙"}

        monkeypatch.setattr(auth, "echanger_code", _echanger_fake)
        monkeypatch.setattr(auth, "verify_token", _verify_fake)

        r_callback = parcours.get(
            "/auth/callback",
            params={"code": "code-parcours", "state": pending["state"]},
            follow_redirects=False,
        )
        assert r_callback.status_code == 307
        assert auth.COOKIE_SESSION in parcours.cookies

        # (c) dashboard, cache froid → rafraîchissement réel via rafraichir_access_token
        auth.AUTH_ENABLED = True
        auth._cache_access_token.clear()

        async def _rafraichir_fake(refresh_token):
            assert refresh_token == "rt-parcours"
            return {"access_token": "at-frais", "refresh_token": "rt-frais", "expires_in": 300}

        monkeypatch.setattr(auth, "rafraichir_access_token", _rafraichir_fake)

        r_dashboard = parcours.get("/dashboard")
        assert r_dashboard.status_code == 200
        assert "marina" in auth._cache_access_token
    finally:
        auth.AUTH_ENABLED = ancien
        auth._cache_access_token.clear()


import checkpoint_session  # noqa: E402


def test_callback_pose_une_generation_dans_le_cookie(monkeypatch):
    r = client.get("/auth/login", follow_redirects=False)
    pending_cookie = r.cookies[auth.COOKIE_PENDING]
    pending = auth.dechiffrer_cookie(pending_cookie)

    async def _echanger_fake(code, code_verifier, redirect_uri):
        return {"access_token": "at-1", "refresh_token": "rt-1", "expires_in": 300}

    async def _verify_fake(token, kc):
        return {"sub": "generation-test", "nom": "Test", "avatarEmoji": "🧪"}

    monkeypatch.setattr(auth, "echanger_code", _echanger_fake)
    monkeypatch.setattr(auth, "verify_token", _verify_fake)

    r2 = client.get(
        "/auth/callback",
        params={"code": "code-abc", "state": pending["state"]},
        cookies={auth.COOKIE_PENDING: pending_cookie},
        follow_redirects=False,
    )
    session = auth.dechiffrer_cookie(r2.cookies[auth.COOKIE_SESSION])
    assert session["generation"] == 1


def test_deuxieme_callback_incremente_la_generation_et_declenche_le_checkpoint(monkeypatch):
    appels_checkpoint = []
    monkeypatch.setattr(checkpoint_session, "declencher_checkpoint", appels_checkpoint.append)

    async def _echanger_fake(code, code_verifier, redirect_uri):
        return {"access_token": "at-1", "refresh_token": "rt-1", "expires_in": 300}

    async def _verify_fake(token, kc):
        return {"sub": "generation-relai", "nom": "Test", "avatarEmoji": "🧪"}

    monkeypatch.setattr(auth, "echanger_code", _echanger_fake)
    monkeypatch.setattr(auth, "verify_token", _verify_fake)

    def _callback():
        r = client.get("/auth/login", follow_redirects=False)
        pending_cookie = r.cookies[auth.COOKIE_PENDING]
        pending = auth.dechiffrer_cookie(pending_cookie)
        r2 = client.get(
            "/auth/callback",
            params={"code": "code-abc", "state": pending["state"]},
            cookies={auth.COOKIE_PENDING: pending_cookie},
            follow_redirects=False,
        )
        return auth.dechiffrer_cookie(r2.cookies[auth.COOKIE_SESSION])

    premiere = _callback()
    assert premiere["generation"] == 1
    assert appels_checkpoint == []  # pas d'ancienne session au tout premier login

    deuxieme = _callback()
    assert deuxieme["generation"] == 2
    assert appels_checkpoint == ["generation-relai"]  # checkpoint déclenché pour CE sub
