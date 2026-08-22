"""Endpoints /assistant/config/{organisation,utilisateur,resolue} (S234-veille chantier 3) :
traduction des erreurs de config_tenant en HTTPException.

Fonctions testées directement (pas de TestClient) — même philosophie que
test_assistant_routes.py : pas besoin de monter toute l'app pour prouver le câblage.
    $ cd core && python3 -m pytest test_config_tenant_routes.py -v
"""
import asyncio
import os

os.environ.setdefault("VAULT_SECRET", "test-secret-0123456789")
os.environ.setdefault("GATEWAY_KEY", "test")
os.environ.setdefault("AUTH_SESSION_SECRET", "test-session-secret-0123456789")

import httpx  # noqa: E402
import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

import config_tenant  # noqa: E402
import contexte_tenant  # noqa: E402
from routers.assistant import (  # noqa: E402
    assistant_config_organisation_put,
    assistant_config_utilisateur_put,
)


def test_organisation_put_cle_inconnue_leve_400():
    jetons = contexte_tenant.definir_contexte(org_id="acme", utilisateur="alice")
    async def faux_ecrire(org_id, patch, client=None):
        raise ValueError("clé(s) inconnue(s) : bidule")
    ancien = config_tenant.ecrire_couche_organisation
    config_tenant.ecrire_couche_organisation = faux_ecrire
    try:
        with pytest.raises(HTTPException) as exc:
            asyncio.run(assistant_config_organisation_put({"bidule": 1}))
        assert exc.value.status_code == 400
    finally:
        config_tenant.ecrire_couche_organisation = ancien
        contexte_tenant.reinitialiser(jetons)


def test_organisation_put_panne_reseau_leve_502():
    jetons = contexte_tenant.definir_contexte(org_id="acme", utilisateur="alice")
    async def faux_ecrire(org_id, patch, client=None):
        raise httpx.ConnectError("refused", request=httpx.Request("GET", "http://x"))
    ancien = config_tenant.ecrire_couche_organisation
    config_tenant.ecrire_couche_organisation = faux_ecrire
    try:
        with pytest.raises(HTTPException) as exc:
            asyncio.run(assistant_config_organisation_put({"persona": "pro"}))
        assert exc.value.status_code == 502
    finally:
        config_tenant.ecrire_couche_organisation = ancien
        contexte_tenant.reinitialiser(jetons)


def test_utilisateur_put_cle_inconnue_leve_400():
    jetons = contexte_tenant.definir_contexte(org_id="acme", utilisateur="alice")
    async def faux_ecrire(org_id, utilisateur, patch, client=None):
        raise ValueError("clé(s) inconnue(s) : bidule")
    ancien = config_tenant.ecrire_couche_utilisateur
    config_tenant.ecrire_couche_utilisateur = faux_ecrire
    try:
        with pytest.raises(HTTPException) as exc:
            asyncio.run(assistant_config_utilisateur_put({"bidule": 1}))
        assert exc.value.status_code == 400
    finally:
        config_tenant.ecrire_couche_utilisateur = ancien
        contexte_tenant.reinitialiser(jetons)
