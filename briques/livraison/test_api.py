from fastapi.testclient import TestClient
import main

c = TestClient(main.app)

def test_sante():
    r = c.get("/sante")
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] is True and d["brique"] == "livraison"

def test_sante_ne_fuit_aucun_secret():
    assert "key" not in c.get("/sante").text.lower()
