"""Smoke de parité contre un Bun LIVE (optionnel).

Exécuté seulement si PARITY_BUN_URL est défini (Bun forge/core accessible) :

    PARITY_BUN_URL=http://localhost:3001 pytest tests/parity/test_parity_smoke.py

En CI sans Bun, ces tests sont skippés — la logique du harnais reste couverte par
``test_parity_harness.py``. Sert de gabarit aux sprints S127+ : chaque route
portée ajoutera ici (ou dans un fichier dédié) son test de parité avant cutover.
"""

import pytest

from tests.parity.harness import bun_url_or_skip, compare

BUN_URL = bun_url_or_skip()
pytestmark = [
    pytest.mark.parity,
    pytest.mark.skipif(BUN_URL is None, reason="PARITY_BUN_URL non défini — Bun live requis"),
]


async def test_health_smoke_against_bun(client):
    """Le Bun répond bien sur /health (sanity check de l'upstream de parité)."""
    result = await compare(
        client,
        BUN_URL,
        method="GET",
        path="/health",
        compare_body=False,  # schémas /health différents (Python = HealthBuilder)
    )
    # On ne compare pas les bodies (schémas distincts) mais le Bun doit être up.
    assert result.status_bun == 200
