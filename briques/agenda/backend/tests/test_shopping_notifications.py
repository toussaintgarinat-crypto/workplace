"""notifier_membres : cible les autres membres, jamais l'acteur, no-op sans connexion, ne lève jamais."""
from __future__ import annotations

import pytest

from config import settings
from models.orm import ShoppingList, ShoppingListMember
from services import notifications


async def _liste_avec_membres(db):
    liste = ShoppingList(name="Maison", created_by="perso")
    db.add(liste)
    await db.commit()
    await db.refresh(liste)
    db.add(ShoppingListMember(list_id=liste.id, user_id="marina", role="editor"))
    db.add(ShoppingListMember(list_id=liste.id, user_id="perso", role="owner"))
    await db.commit()
    return liste


@pytest.mark.asyncio
async def test_noop_sans_connexion_url(db, monkeypatch):
    monkeypatch.setattr(settings, "CONNEXION_URL", "", raising=False)
    liste = await _liste_avec_membres(db)
    n = await notifications.notifier_membres(db, liste, acteur_id="perso", texte="🛒 test")
    assert n == 0


@pytest.mark.asyncio
async def test_cible_les_autres_membres(db, monkeypatch):
    monkeypatch.setattr(settings, "CONNEXION_URL", "http://connexion:5870", raising=False)
    monkeypatch.setattr(settings, "CONNEXION_KEY", "", raising=False)
    cibles = []

    class FakeClient:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, json=None, headers=None):
            cibles.append(json["utilisateur"])
            class R: ...
            return R()

    monkeypatch.setattr(notifications.httpx, "AsyncClient", FakeClient)
    liste = await _liste_avec_membres(db)
    n = await notifications.notifier_membres(db, liste, acteur_id="perso", texte="🛒 test")
    assert set(cibles) == {"marina"}  # perso (acteur) exclu
    assert n == 1


@pytest.mark.asyncio
async def test_ne_leve_jamais_si_connexion_injoignable(db, monkeypatch):
    monkeypatch.setattr(settings, "CONNEXION_URL", "http://connexion:5870", raising=False)

    class BoomClient:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, *a, **k):
            raise RuntimeError("connexion down")

    monkeypatch.setattr(notifications.httpx, "AsyncClient", BoomClient)
    liste = await _liste_avec_membres(db)
    # Ne doit pas lever malgré l'exception réseau.
    await notifications.notifier_membres(db, liste, acteur_id="perso", texte="🛒 test")
