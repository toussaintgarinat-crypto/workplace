"""S207 — le Cœur répond à la convention de santé du parc.

Le Cœur ne servait que `/health`, alors que 35 briques sur 38 exposent `/sante`. Une sonde
écrite d'après la convention tombait donc à côté et concluait que le Cœur était muet — c'est
exactement ce qui s'est produit pendant l'audit du 2026-07-27. Les deux chemins doivent
répondre, et l'ancien ne doit JAMAIS disparaître : les healthchecks Docker et `oria-stack`
pointent dessus.
"""
import os

os.environ.setdefault("VAULT_SECRET", "test-secret-0123456789")
os.environ.setdefault("GATEWAY_KEY", "test")

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402

client = TestClient(main.app)


def test_sante_repond_comme_health():
    sante, health = client.get("/sante"), client.get("/health")
    assert sante.status_code == 200
    assert sante.json() == health.json(), "les deux chemins doivent servir la même réponse"


def test_health_reste_servi():
    """Retirer l'ancien chemin casserait les healthchecks Docker et oria-stack."""
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["statut"] == "ok"
