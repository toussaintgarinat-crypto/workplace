"""S18 (Chantier 2) — RGPD exécutable : inventaire d'effacement, sérialisation, routes.

Sans DB : on prouve la logique (introspection, ordre FK-safe, JSON-sérialisation) et le
montage protégé. L'effacement/export réel se valide sur stack live (DB + Qdrant).
"""

from __future__ import annotations

import datetime
import decimal
import uuid as uuidlib

import pytest
from httpx import ASGITransport, AsyncClient

from app import rgpd as rgpd_svc
from app.models import Base


def test_inventaire_tables_user_id_non_vide_et_coherent():
    tables = rgpd_svc.tables_with_user_id()
    names = [t.name for t in tables]
    # Quelques tables data-bearing connues doivent y figurer.
    # (memory_entries retiré : la mémoire est passée à la brique Mémoire — cf. S-memoire.)
    for expected in ("sessions", "rapports", "audit_logs"):
        assert expected in names, f"{expected} manquant de l'inventaire d'effacement"
    # Toutes ont bien une colonne user_id.
    assert all("user_id" in t.c for t in tables)
    # `users` n'a pas de colonne user_id (sa PK est `id`) → exclue de l'inventaire.
    assert "users" not in names


def test_ordre_fk_safe_enfants_avant_parents():
    """L'inventaire d'effacement est l'ordre de création **inversé** (enfants d'abord)."""
    tables = rgpd_svc.tables_with_user_id()
    creation_order = [t.name for t in Base.metadata.sorted_tables if "user_id" in t.c]
    assert [t.name for t in tables] == list(reversed(creation_order))


def test_jsonable_serialise_types_non_json():
    uid = uuidlib.uuid4()
    now = datetime.datetime(2026, 6, 7, 12, 0, 0)
    row = {
        "id": uid,
        "created_at": now,
        "montant": decimal.Decimal("12.50"),
        "nom": "Test",
        "actif": True,
        "n": 3,
    }
    out = rgpd_svc._jsonable(row)
    assert out["id"] == str(uid)
    assert out["created_at"] == "2026-06-07T12:00:00"
    assert out["montant"] == 12.5 and isinstance(out["montant"], float)
    assert out["nom"] == "Test" and out["actif"] is True and out["n"] == 3


def test_as_uuid_accepte_str_et_uuid():
    u = uuidlib.uuid4()
    assert rgpd_svc._as_uuid(str(u)) == u
    assert rgpd_svc._as_uuid(u) == u


@pytest.mark.asyncio
async def test_routes_rgpd_protegees_sans_token():
    from app.main import app as fastapi_app

    transport = ASGITransport(app=fastapi_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        assert (await c.get("/api/rgpd/apercu")).status_code == 401
        assert (await c.get("/api/rgpd/export")).status_code == 401
        assert (await c.post("/api/rgpd/effacer", json={"confirmation": "EFFACER"})).status_code == 401
        # Alias canonique monté aussi.
        assert (await c.get("/v1/api/rgpd/export")).status_code == 401
        # S18-8 — surface de capacités réelles, protégée.
        assert (await c.get("/api/sentinel-rgpd/capacites-forge")).status_code == 401


@pytest.mark.asyncio
async def test_capacites_forge_reflete_capacite_prouvee():
    """S18-8 — les 4 droits applicables par le code sont marqués prouvés (≠ déclaratif)."""
    from app.routers.sentinel_rgpd import capacites_forge

    out = await capacites_forge()
    assert out["prouves"] == 4  # acces, effacement, conservation, minimisation
    proven_ids = {p["id"] for p in out["points"] if p.get("prouve")}
    assert proven_ids == {"droit_acces", "droit_effacement", "duree_conservation", "minimisation"}
    # Les points organisationnels restent non prouvés par le système.
    assert not any(p.get("prouve") for p in out["points"] if p["id"] in ("dpo", "registre", "consentement"))
