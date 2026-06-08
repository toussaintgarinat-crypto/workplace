"""Tests de l'endpoint /health natif (backend forge unique, Bun supprimé S136)."""


async def test_health_native(client):
    """/health est servi par Python et expose le schéma commun en mode natif."""
    r = await client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["service"] == "forge-core"
    assert body["metadata"]["mode"] == "native"
    # postgres injoignable en test → dépendance "down" présente, plus aucun bun_upstream
    dep_names = {d["name"] for d in body["dependencies"]}
    assert "postgres" in dep_names
    assert "bun_upstream" not in dep_names
