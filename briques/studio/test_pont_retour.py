"""Tests — routes du pont Studio↔world-engine : retour (suggestions + acceptation)."""
from fastapi.testclient import TestClient

import main
import stockage_pont as P
import studio as S

client = TestClient(main.app)


class _FauxRep:
    def __init__(self, data): self._data = data
    def raise_for_status(self): pass
    def json(self): return self._data


class _FauxClient:
    def __init__(self, reponse=None, leve=None):
        self._reponse, self._leve = reponse, leve
    def __call__(self, *a, **k): return self
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
    async def request(self, methode, url, json=None):
        if self._leve:
            raise self._leve
        return _FauxRep(self._reponse)


def _serie_avec_habitant_lie(nom="Elara", eid="eid-1"):
    sid = client.post("/series", json={"titre": "T"}).json()["id"]
    serie = S._load(sid)
    serie["personnages"] = [{"nom": nom, "role": "héroïne", "description": "x"}]
    S._save(serie)
    P.lier_habitant(sid, S._cle_perso(nom), eid, nom, "2026-08-26T00:00:00+00:00")
    return sid


def test_suggestions_vide_sans_personnage_lie():
    sid = client.post("/series", json={"titre": "T"}).json()["id"]
    r = client.get(f"/series/{sid}/pont/suggestions")
    assert r.status_code == 200
    assert r.json() == {"suggestions": []}


def test_suggestions_vivant(monkeypatch):
    sid = _serie_avec_habitant_lie()
    sim = {"monde_id": "m1", "cellule_id": 2, "ne_au_tick": 0, "age_actuel_ticks": 4,
           "vivant": True, "mort_au_tick": None}
    monkeypatch.setattr(S.httpx, "AsyncClient", _FauxClient(reponse={"id": "eid-1", "simulation": sim}))
    r = client.get(f"/series/{sid}/pont/suggestions")
    assert r.status_code == 200
    (sug,) = r.json()["suggestions"]
    assert sug["nom_affiche"] == "Elara"
    assert sug["age_actuel_ticks"] == 4
    assert sug["vivant"] is True


def test_suggestions_silencieuses_si_world_engine_injoignable(monkeypatch):
    sid = _serie_avec_habitant_lie()
    monkeypatch.setattr(S.httpx, "AsyncClient", _FauxClient(leve=RuntimeError("down")))
    r = client.get(f"/series/{sid}/pont/suggestions")
    assert r.status_code == 200
    assert r.json() == {"suggestions": []}


def test_accepter_ajoute_un_fait_acquis(monkeypatch):
    sid = _serie_avec_habitant_lie()
    sim = {"monde_id": "m1", "cellule_id": 2, "ne_au_tick": 0, "age_actuel_ticks": 4,
           "vivant": True, "mort_au_tick": None}
    monkeypatch.setattr(S.httpx, "AsyncClient", _FauxClient(reponse={"id": "eid-1", "simulation": sim}))
    r = client.post(f"/series/{sid}/pont/accepter", json={"nom_cles": ["ELARA"]})
    assert r.status_code == 200
    assert any("Elara" in f and "4" in f for f in r.json()["acquis"])
    assert any("Elara" in f for f in S._load(sid)["canon"]["acquis"])


def test_accepter_mort_detache_l_habitant(monkeypatch):
    sid = _serie_avec_habitant_lie()
    sim = {"monde_id": "m1", "cellule_id": 2, "ne_au_tick": 0, "age_actuel_ticks": 9,
           "vivant": False, "mort_au_tick": 9}
    monkeypatch.setattr(S.httpx, "AsyncClient", _FauxClient(reponse={"id": "eid-1", "simulation": sim}))
    r = client.post(f"/series/{sid}/pont/accepter", json={"nom_cles": ["ELARA"]})
    assert r.status_code == 200
    assert "ELARA" not in P.lire_pont(sid)["habitants"]
