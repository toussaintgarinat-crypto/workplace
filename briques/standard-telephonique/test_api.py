"""Tests API (TestClient) : santé."""
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


def test_sante():
    r = client.get("/sante")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["brique"] == "standard-telephonique"


def test_messages_vide_par_defaut(tmp_path, monkeypatch):
    monkeypatch.setenv("MESSAGES_DB", str(tmp_path / "messages.db"))
    r = client.get("/messages")
    assert r.status_code == 200
    assert r.json() == {"messages": []}


def test_messages_liste_apres_enregistrement(tmp_path, monkeypatch):
    db_path = str(tmp_path / "messages.db")
    monkeypatch.setenv("MESSAGES_DB", db_path)
    import messages_store
    messages_store.enregistrer(db_path, option="1", audio_path="/data/audio/x.wav",
                               duree_s=3.0, texte="allo")

    r = client.get("/messages")
    assert r.status_code == 200
    data = r.json()["messages"]
    assert len(data) == 1
    assert data[0]["option"] == "1"
    assert data[0]["texte"] == "allo"


def test_messages_respecte_limite(tmp_path, monkeypatch):
    db_path = str(tmp_path / "messages.db")
    monkeypatch.setenv("MESSAGES_DB", db_path)
    import messages_store
    for i in range(5):
        messages_store.enregistrer(db_path, option=str(i), audio_path=f"/data/audio/{i}.wav",
                                   duree_s=1.0, texte=None)

    r = client.get("/messages", params={"limite": 2})
    assert len(r.json()["messages"]) == 2
