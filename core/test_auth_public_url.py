"""S181 — la redirection navigateur /auth utilise KEYCLOAK_PUBLIC_URL ;
l'échange de code serveur reste sur KEYCLOAK_URL interne."""
import os

os.environ.setdefault("VAULT_SECRET", "test-secret-0123456789")
os.environ.setdefault("GATEWAY_KEY", "test")
os.environ.setdefault("AUTH_SESSION_SECRET", "test-session-secret-0123456789")

import main  # noqa: E402
import auth  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

client = TestClient(main.app)


def test_redirect_login_utilise_public_url():
    # `auth` est importé une seule fois par process (cache Python) : selon l'ordre de
    # collecte pytest, un autre fichier de test peut l'avoir importé avant nous et figé
    # KEYCLOAK_PUBLIC_URL sur sa valeur par défaut. On mute donc l'attribut du module
    # directement (même motif que test_auth.py pour AUTH_ENABLED), restauré après coup
    # pour ne pas polluer les tests suivants.
    ancien = auth.KEYCLOAK_PUBLIC_URL
    auth.KEYCLOAK_PUBLIC_URL = "https://public.example:18080"
    try:
        r = client.get("/auth/login", follow_redirects=False)
        assert r.status_code == 307
        loc = r.headers["location"]
        assert loc.startswith("https://public.example:18080/realms/forge/protocol/openid-connect/auth")
    finally:
        auth.KEYCLOAK_PUBLIC_URL = ancien


def test_token_endpoint_reste_interne():
    ancien = auth.KEYCLOAK_URL
    auth.KEYCLOAK_URL = "http://interne:8080"
    try:
        assert auth._token_endpoint() == "http://interne:8080/realms/forge/protocol/openid-connect/token"
    finally:
        auth.KEYCLOAK_URL = ancien
