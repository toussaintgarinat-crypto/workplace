"""Tests notifier : appel HTTP vers briques/connexion (/pousser), mocké."""
import httpx
import pytest

import notifier


@pytest.mark.asyncio
async def test_notifier_appelle_pousser_avec_le_bon_corps(monkeypatch):
    appels = []

    def handler(request: httpx.Request) -> httpx.Response:
        appels.append(request)
        return httpx.Response(200, json={"ok": True, "envoyes": 1})

    monkeypatch.setattr(notifier, "_client", lambda: httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://connexion.test"))
    monkeypatch.setenv("STANDARD_TEL_NOTIF_UTILISATEUR", "perso")

    await notifier.notifier("Nouveau message vocal (option 3) : bonjour...")

    assert len(appels) == 1
    assert appels[0].url.path == "/pousser"
    import json
    corps_envoye = json.loads(appels[0].content)
    assert corps_envoye["utilisateur"] == "perso"
    assert "option 3" in corps_envoye["texte"]


@pytest.mark.asyncio
async def test_notifier_ne_leve_jamais_si_brique_injoignable(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("brique absente")

    monkeypatch.setattr(notifier, "_client", lambda: httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://connexion.test"))

    await notifier.notifier("texte")  # ne doit pas lever
