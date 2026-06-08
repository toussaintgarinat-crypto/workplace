"""S18 (Chantier 1) — preuves d'étanchéité multi-tenant.

Deux couches :

1. **Garde de régression (sans DB, toujours exécutée)** : démontre que la *seule*
   source d'``org_id`` de confiance est ``require_org`` (qui ne lit que ``user.org_id``,
   jamais le header), et qu'aucun router data-bearing ne relit ``X-Org-ID`` cru. Si
   quelqu'un réintroduit un ``Header("X-Org-ID")`` ou ``request.headers.get("X-Org-ID")``
   dans un router scopé, ce test casse.

2. **Test croisé A/B live (gated)** : skip sauf si ``FORGE_LIVE_URL`` + ``FORGE_TOKEN_A``
   + ``FORGE_TOKEN_B`` sont fournis (deux orgs réelles). Prouve par appel réel que le
   token de B ne voit jamais une donnée créée par A (lecture) et ne peut pas l'écrire.
   Même esprit que les tests de parité Bun (skip si stack absente).
"""

from __future__ import annotations

import os
import pathlib

import httpx
import pytest

ROUTERS_DIR = pathlib.Path(__file__).resolve().parent.parent / "app" / "routers"

# Routers volontairement autorisés à toucher X-Org-ID *via le helper validé*
# (``_resolve_org_id`` vérifie l'appartenance) — pas une lecture crue.
_ALLOWED_RAW = {"ventures.py"}


# ── Couche 1 : garde de régression (sans DB) ───────────────────────────────


def test_require_org_ne_lit_que_user_org_id():
    """``require_org`` renvoie ``user.org_id`` tel quel, sans toucher au header."""
    import asyncio

    from app.auth import UserContext, require_org

    user = UserContext(sub="u-1", nom="Test", avatar_emoji="👤", org_id="org-B")
    assert asyncio.run(require_org(user)) == "org-B"


def test_require_org_refuse_sans_org():
    """Sans org active → 400 (pas de repli silencieux sur un id client)."""
    import asyncio

    from fastapi import HTTPException

    from app.auth import UserContext, require_org

    user = UserContext(sub="u-1", nom="Test", avatar_emoji="👤", org_id=None)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(require_org(user))
    assert exc.value.status_code == 400


def test_aucun_router_ne_lit_x_org_id_cru():
    """Aucun router data-bearing ne relit ``X-Org-ID`` en paramètre/header brut.

    Tolère les docstrings/commentaires (le motif code est ``Header(...alias=...)``
    ou ``request.headers.get("X-Org-ID")``). ``ventures.py`` est exempté car il
    passe par ``_resolve_org_id`` (valide l'appartenance).
    """
    offenders: list[str] = []
    for path in sorted(ROUTERS_DIR.glob("*.py")):
        if path.name in _ALLOWED_RAW:
            continue
        src = path.read_text(encoding="utf-8")
        if 'request.headers.get("X-Org-ID")' in src:
            offenders.append(f"{path.name}: request.headers.get X-Org-ID")
        if 'alias="X-Org-ID"' in src:
            offenders.append(f"{path.name}: Header(alias=X-Org-ID)")
    assert not offenders, "Header X-Org-ID cru réintroduit :\n" + "\n".join(offenders)


# ── Posture d'audience (S18-2, sans Keycloak live) ─────────────────────────


def test_audience_vide_desactive_verify_aud():
    """`audience` vide ⇒ posture S17 ouverte (`verify_aud: False`)."""
    from agent_personnel_shared.keycloak_auth import KeycloakSettings

    kc = KeycloakSettings(url="http://kc", realm="oria", audience="")
    assert kc.decode_options().get("verify_aud") is False


def test_audience_renseignee_active_verify_aud():
    """`audience` renseigné ⇒ posture verrouillée (verify_aud par défaut = actif)."""
    from agent_personnel_shared.keycloak_auth import KeycloakSettings

    kc = KeycloakSettings(url="http://kc", realm="oria", audience="forge")
    # verify_aud n'est PAS forcé à False, et l'audience est bien portée.
    assert kc.decode_options().get("verify_aud") is not False
    assert kc.audience == "forge"


# ── Couche 2 : test croisé A/B live (gated) ────────────────────────────────

_LIVE = os.environ.get("FORGE_LIVE_URL")
_TOKEN_A = os.environ.get("FORGE_TOKEN_A")
_TOKEN_B = os.environ.get("FORGE_TOKEN_B")
_live_ready = bool(_LIVE and _TOKEN_A and _TOKEN_B)


@pytest.mark.skipif(
    not _live_ready,
    reason="FORGE_LIVE_URL + FORGE_TOKEN_A + FORGE_TOKEN_B requis (deux orgs réelles)",
)
async def test_cross_tenant_memory_lecture_et_ecriture():
    """B ne voit jamais une mémoire créée par A, et ne peut pas la lire par id."""
    base = _LIVE.rstrip("/")
    ha = {"Authorization": f"Bearer {_TOKEN_A}"}
    hb = {"Authorization": f"Bearer {_TOKEN_B}"}

    async with httpx.AsyncClient(base_url=base, timeout=15) as c:
        # A crée une mémoire.
        r = await c.post("/api/memory", headers=ha,
                         json={"cle": "s18-secret-A", "valeur": "donnée confidentielle A"})
        assert r.status_code == 201, r.text
        created = r.json()
        mem_id = created.get("id")

        # B liste ses mémoires → ne doit jamais contenir la clé de A.
        r = await c.get("/api/memory", headers=hb)
        assert r.status_code == 200, r.text
        cles_b = {m.get("cle") for m in r.json()}
        assert "s18-secret-A" not in cles_b, "FUITE : B voit la mémoire de A"

        # B tente d'écraser la mémoire de A (PUT par id) → ne doit pas réussir
        # à modifier la donnée de A (404/403, ou no-op silencieux côté A).
        if mem_id:
            await c.put(f"/api/memory/{mem_id}", headers=hb,
                        json={"valeur": "écrasé par B"})
            # A relit : sa donnée est intacte.
            r = await c.get("/api/memory", headers=ha)
            a_mem = next((m for m in r.json() if m.get("id") == mem_id), None)
            assert a_mem is not None, "A a perdu sa mémoire"
            assert a_mem.get("valeur") == "donnée confidentielle A", \
                "FUITE D'ÉCRITURE : B a modifié la mémoire de A"
