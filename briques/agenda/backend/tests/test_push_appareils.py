"""Push web (S178) : `/push/cle_publique` (publique) + relais `/push/appareils`
vers le pont `connexion` (POST enregistrer / DELETE retirer). Le `sub` du token
Keycloak est TOUJOURS l'identité relayée, jamais un `utilisateur` fourni par le
corps de la requête (anti-usurpation).

On appelle les fonctions de route directement, comme test_calendars.py /
test_service_agenda.py — pas de TestClient, pas de JWT. Le mock du client HTTP
sortant suit le motif FakeClient de test_shopping_notifications.py.
"""
from __future__ import annotations

import pytest

from config import settings
from routers import push
from routers.push import AppareilEntree, RetraitEntree

USER = {"sub": "vraie-personne"}


class FakeClient:
    """Capture les appels sortants (POST/DELETE) sans réseau réel."""

    def __init__(self, *a, **k):
        self.appels: list[dict] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None, headers=None):
        self.appels.append({"methode": "POST", "url": url, "json": json, "headers": headers})
        class R: ...
        return R()

    async def request(self, methode, url, json=None, headers=None):
        self.appels.append({"methode": methode, "url": url, "json": json, "headers": headers})
        class R: ...
        return R()


class BoomClient:
    def __init__(self, *a, **k): ...
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
    async def post(self, *a, **k):
        raise RuntimeError("connexion injoignable")
    async def request(self, *a, **k):
        raise RuntimeError("connexion injoignable")


# ── GET /push/cle_publique ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cle_publique_sert_la_valeur_configuree(monkeypatch):
    monkeypatch.setattr(settings, "VAPID_PUBLIC_KEY", "pub-xyz", raising=False)
    out = await push.cle_publique()
    assert out == {"cle": "pub-xyz"}


@pytest.mark.asyncio
async def test_cle_publique_vide_par_defaut(monkeypatch):
    monkeypatch.setattr(settings, "VAPID_PUBLIC_KEY", "", raising=False)
    out = await push.cle_publique()
    assert out == {"cle": ""}


# ── POST /push/appareils ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_enregistrer_sans_connexion_url_repli_honnete(monkeypatch):
    monkeypatch.setattr(settings, "CONNEXION_URL", "", raising=False)
    out = await push.enregistrer(
        AppareilEntree(appareil={"endpoint": "https://p/AAA", "keys": {}}), user=USER)
    assert out == {"ok": False, "raison": "push non configuré"}


@pytest.mark.asyncio
async def test_enregistrer_force_le_sub_du_token(monkeypatch):
    monkeypatch.setattr(settings, "CONNEXION_URL", "http://connexion", raising=False)
    monkeypatch.setattr(settings, "CONNEXION_KEY", "k", raising=False)
    fake = FakeClient()
    monkeypatch.setattr(push.httpx, "AsyncClient", lambda *a, **k: fake)

    body = AppareilEntree(appareil={"endpoint": "https://p/AAA", "keys": {}})
    out = await push.enregistrer(body, user=USER)

    assert out == {"ok": True}
    assert len(fake.appels) == 1
    appel = fake.appels[0]
    assert appel["url"] == "http://connexion/push/appareils"
    assert appel["json"]["utilisateur"] == "vraie-personne"   # forcé au sub du token
    assert appel["json"]["appareil"] == {"endpoint": "https://p/AAA", "keys": {}}
    assert appel["headers"] == {"X-API-Key": "k"}


@pytest.mark.asyncio
async def test_enregistrer_ignore_lutilisateur_du_corps():
    """Le schéma d'entrée n'accepte même pas d'`utilisateur` dans le corps — un
    éventuel champ additionnel serait de toute façon écrasé côté relais."""
    body = AppareilEntree(appareil={"endpoint": "https://p/AAA", "keys": {}})
    assert not hasattr(body, "utilisateur")


@pytest.mark.asyncio
async def test_enregistrer_pont_injoignable_ne_leve_pas(monkeypatch):
    monkeypatch.setattr(settings, "CONNEXION_URL", "http://connexion", raising=False)
    monkeypatch.setattr(push.httpx, "AsyncClient", BoomClient)
    out = await push.enregistrer(
        AppareilEntree(appareil={"endpoint": "https://p/AAA", "keys": {}}), user=USER)
    assert out == {"ok": False, "raison": "pont injoignable"}


# ── DELETE /push/appareils ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_retirer_sans_connexion_url_repli_honnete(monkeypatch):
    monkeypatch.setattr(settings, "CONNEXION_URL", "", raising=False)
    out = await push.retirer(RetraitEntree(endpoint="https://p/AAA"), user=USER)
    assert out == {"ok": False}


@pytest.mark.asyncio
async def test_retirer_relaie_lendpoint(monkeypatch):
    monkeypatch.setattr(settings, "CONNEXION_URL", "http://connexion", raising=False)
    monkeypatch.setattr(settings, "CONNEXION_KEY", "", raising=False)
    fake = FakeClient()
    monkeypatch.setattr(push.httpx, "AsyncClient", lambda *a, **k: fake)

    out = await push.retirer(RetraitEntree(endpoint="https://p/AAA"), user=USER)

    assert out == {"ok": True}
    assert len(fake.appels) == 1
    appel = fake.appels[0]
    assert appel["methode"] == "DELETE"
    assert appel["url"] == "http://connexion/push/appareils"
    assert appel["json"] == {"endpoint": "https://p/AAA"}


@pytest.mark.asyncio
async def test_retirer_pont_injoignable_ne_leve_pas(monkeypatch):
    monkeypatch.setattr(settings, "CONNEXION_URL", "http://connexion", raising=False)
    monkeypatch.setattr(push.httpx, "AsyncClient", BoomClient)
    out = await push.retirer(RetraitEntree(endpoint="https://p/AAA"), user=USER)
    assert out == {"ok": False}
