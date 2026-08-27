"""Tests — routes du pont Studio↔world-engine : entrée (fonder) + éligibles après
chapitre. Monkeypatch de httpx.AsyncClient (même motif que test_world_engine.py)."""
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
    def __init__(self, reponses=None, leve=None):
        self._reponses = list(reponses or []); self._leve = leve
    def __call__(self, *a, **k): return self
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
    async def request(self, methode, url, json=None):
        if self._leve:
            raise self._leve
        return _FauxRep(self._reponses.pop(0))


def _serie_avec_personnage_caste(nom="Elara", description="Une aventurière rusée."):
    sid = client.post("/series", json={"titre": "T"}).json()["id"]
    serie = S._load(sid)
    serie["personnages"] = [{"nom": nom, "role": "héroïne", "description": description}]
    S._save(serie)
    return sid


def test_fonder_personnage_non_eligible_422():
    sid = client.post("/series", json={"titre": "T"}).json()["id"]
    r = client.post(f"/series/{sid}/pont/fonder", json={"nom": "Inconnu"})
    assert r.status_code == 422


def test_fonder_cree_le_monde_puis_lie_habitant(monkeypatch):
    sid = _serie_avec_personnage_caste()
    monkeypatch.setattr(S.httpx, "AsyncClient",
                         _FauxClient(reponses=[{"id": "monde-1", "nb_cellules": 10},
                                                {"eid": "eid-1", "cellule_id": 3, "theme": {}}]))
    r = client.post(f"/series/{sid}/pont/fonder", json={"nom": "Elara"})
    assert r.status_code == 200
    pont = r.json()
    assert pont["monde_id"] == "monde-1"
    assert pont["habitants"]["ELARA"]["eid"] == "eid-1"
    assert P.lire_pont(sid)["monde_id"] == "monde-1"


def test_fonder_reutilise_le_monde_deja_cree(monkeypatch):
    sid = _serie_avec_personnage_caste("Elara")
    P.fixer_monde(sid, "monde-existant")
    monkeypatch.setattr(S.httpx, "AsyncClient",
                         _FauxClient(reponses=[{"eid": "eid-2", "cellule_id": 1, "theme": {}}]))
    r = client.post(f"/series/{sid}/pont/fonder", json={"nom": "Elara"})
    assert r.status_code == 200
    assert r.json()["monde_id"] == "monde-existant"


def test_fonder_world_engine_injoignable_502(monkeypatch):
    sid = _serie_avec_personnage_caste()
    monkeypatch.setattr(S.httpx, "AsyncClient", _FauxClient(leve=RuntimeError("down")))
    r = client.post(f"/series/{sid}/pont/fonder", json={"nom": "Elara"})
    assert r.status_code == 502


def test_pont_apres_chapitre_liste_les_eligibles_sans_tick_si_pas_de_monde():
    sid = _serie_avec_personnage_caste()
    serie = S._load(sid)
    import asyncio
    eligibles = asyncio.run(S._pont_apres_chapitre(sid, serie))
    assert eligibles == ["Elara"]


def test_pont_apres_chapitre_tick_si_monde_existant(monkeypatch):
    sid = _serie_avec_personnage_caste()
    P.fixer_monde(sid, "monde-1")
    appels = []

    class _ClientTraceur(_FauxClient):
        async def request(self, methode, url, json=None):
            appels.append((methode, url))
            return _FauxRep({})
    monkeypatch.setattr(S.httpx, "AsyncClient", _ClientTraceur())
    import asyncio
    serie = S._load(sid)
    asyncio.run(S._pont_apres_chapitre(sid, serie))
    assert ("POST", f"{S.WORLD_ENGINE_URL}/horloge/monde-1/tick") in appels
