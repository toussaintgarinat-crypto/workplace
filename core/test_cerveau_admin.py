"""Garde des routes qui MODIFIENT le cerveau (S240, T1).

Avant S240, `assistant.router` n'était monté qu'avec `lire_contexte_tenant` (non bloquant) :
n'importe quel appareil du LAN/mesh pouvait poser une clé fournisseur ou changer le modèle
sans session. Ces tests verrouillent :
- la LISTE exacte des routes gardées (contrat : une route de modification ajoutée plus tard
  sans garde fait échouer `test_routes_gardees_exactement`) ;
- le comportement de `exiger_admin_cerveau` (401 sans session, 403 hors `CERVEAU_ADMINS`,
  cohérence avec `AUTH_ENABLED=false`).

$ cd core && python3 -m pytest test_cerveau_admin.py -v
"""
import os
import tempfile
import time

os.environ.setdefault("VAULT_SECRET", "test-secret-0123456789")
os.environ.setdefault("GATEWAY_KEY", "test")
os.environ.setdefault("AUTH_SESSION_SECRET", "test-session-secret-0123456789")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import auth  # noqa: E402
import main  # noqa: E402
import session_registre  # noqa: E402

client = TestClient(main.app)

# (méthode, chemin) des routes qui modifient le cerveau — rien de plus, rien de moins.
ROUTES_GARDEES = {
    ("POST", "/assistant/config"),
    ("PUT", "/assistant/config/organisation"),
    ("DELETE", "/assistant/config/organisation"),
    ("PUT", "/assistant/config/utilisateur"),
    ("DELETE", "/assistant/config/utilisateur"),
    ("POST", "/assistant/muscle"),
    ("POST", "/assistant/routage"),
    ("POST", "/assistant/persona"),
    ("POST", "/assistant/langue"),
    ("POST", "/assistant/voix"),
    ("POST", "/assistant/cle-openrouter"),
    ("POST", "/assistant/cle-fournisseur"),
    ("POST", "/assistant/modeles"),
    ("DELETE", "/assistant/modeles/{nom:path}"),
    ("POST", "/assistant/forge-modele"),
}


def _routes_avec_garde() -> set[tuple[str, str]]:
    trouvees = set()
    for r in main.app.routes:
        deps = getattr(r, "dependant", None)
        if deps is None:
            continue
        appels = {d.call for d in deps.dependencies}
        if auth.exiger_admin_cerveau in appels:
            for m in r.methods:
                trouvees.add((m, r.path))
    return trouvees


@pytest.fixture(autouse=True)
def _isoler(monkeypatch):
    """Registre de session neuf + cache de jetons vidé + aucun admin par défaut."""
    ancien = session_registre.DB
    session_registre.DB = os.path.join(tempfile.mkdtemp(), "session_registre.db")
    auth._cache_access_token.clear()
    monkeypatch.delenv("CERVEAU_ADMINS", raising=False)
    try:
        yield
    finally:
        session_registre.DB = ancien
        auth._cache_access_token.clear()


def _cookie(sub: str) -> dict:
    """Cookie de session valide pour `sub`, access token déjà en cache (pas d'appel Keycloak)."""
    auth._cache_access_token[sub] = ("at-cache", time.time() + 60)
    return {auth.COOKIE_SESSION: auth.chiffrer_cookie({"sub": sub, "refresh_token": "rt-1"})}


def test_routes_gardees_exactement():
    assert _routes_avec_garde() == ROUTES_GARDEES


def test_chat_et_lectures_restent_ouverts():
    """Telegram/Mini App/S2S passent par /assistant/chat et /assistant/historique_utilisateur
    sans session Keycloak : ils ne doivent JAMAIS hériter de la garde."""
    gardees = _routes_avec_garde()
    for libre in [("POST", "/assistant/chat"), ("GET", "/assistant/historique_utilisateur"),
                  ("GET", "/assistant/config"), ("GET", "/assistant/muscle")]:
        assert libre not in gardees


def test_sans_session_refuse_401_quand_auth_activee(monkeypatch):
    monkeypatch.setattr(auth, "AUTH_ENABLED", True)
    for methode, chemin in sorted(ROUTES_GARDEES):
        r = client.request(methode, chemin, json={}, follow_redirects=False)
        assert r.status_code == 401, (methode, chemin, r.status_code)


def test_session_valide_sans_liste_blanche_autorisee(monkeypatch):
    monkeypatch.setattr(auth, "AUTH_ENABLED", True)
    r = client.post("/assistant/persona", json={"persona": "default"}, cookies=_cookie("marina"))
    assert r.status_code == 200, r.text


def test_session_hors_liste_blanche_refusee_403(monkeypatch):
    monkeypatch.setattr(auth, "AUTH_ENABLED", True)
    monkeypatch.setenv("CERVEAU_ADMINS", "toussaint, autre")
    r = client.post("/assistant/persona", json={"persona": "default"}, cookies=_cookie("marina"))
    assert r.status_code == 403


def test_session_dans_liste_blanche_autorisee(monkeypatch):
    monkeypatch.setattr(auth, "AUTH_ENABLED", True)
    monkeypatch.setenv("CERVEAU_ADMINS", "autre,toussaint")
    r = client.post("/assistant/persona", json={"persona": "default"}, cookies=_cookie("toussaint"))
    assert r.status_code == 200, r.text


def test_auth_desactivee_sans_liste_blanche_comportement_historique():
    assert auth.AUTH_ENABLED is False
    r = client.post("/assistant/persona", json={"persona": "default"})
    assert r.status_code == 200


def test_auth_desactivee_avec_liste_blanche_refuse(monkeypatch):
    """Identité factice « anonymous » + liste blanche posée = configuration incohérente : on
    ferme plutôt que de laisser croire que la liste blanche protège quelque chose."""
    monkeypatch.setenv("CERVEAU_ADMINS", "toussaint")
    r = client.post("/assistant/persona", json={"persona": "default"})
    assert r.status_code == 403
    assert "AUTH_ENABLED" in r.json()["detail"]
