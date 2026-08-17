"""Tests — POST /series/{id}/audio avec `profil_id` (S231 P5).

Toute la chaîne réseau (Gateway pour la découpe en répliques, service voix pour le rendu)
est mockée — motif `test_images.py`/`test_langue.py`. On vérifie que `profil_id`, quand
fourni, adapte le script AVANT la découpe en répliques, et que son absence ne régresse pas
le chemin existant."""
import main
import studio as S


class _FauxClientVoix:
    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, *a, **k):
        class _Rep:
            def raise_for_status(self):
                pass

            def json(self):
                return {"url": "/fichiers/audio.mp3", "duree": 42}
        return _Rep()


def _mocker_chaine_production(monkeypatch, capture_adapter=None):
    """Mocke : découpe en répliques (Gateway), pool de voix, casting, rendu voix."""
    async def fake_repliques(*a, **k):
        return '[{"perso":"NARRATEUR","texte":"Il était une fois."}]'
    monkeypatch.setattr(main.agents, "_gateway_answer", fake_repliques)

    async def fake_pool(langue="fr"):
        return ["Thomas"]
    monkeypatch.setattr(S, "_voix_pool", fake_pool)

    import composition
    async def fake_caster(*a, **k):
        return None  # force le repli interne S._caster (aucun réseau)
    monkeypatch.setattr(composition, "caster", fake_caster)

    monkeypatch.setattr(S, "httpx", type("H", (), {"AsyncClient": _FauxClientVoix}))

    if capture_adapter is not None:
        async def fake_adapter(texte, cible):
            capture_adapter.append((texte, cible))
            return "Script adapté.", True
        monkeypatch.setattr(S, "_adapter_cible", fake_adapter)


def _serie_avec_episode():
    client = main.app
    from fastapi.testclient import TestClient
    c = TestClient(client)
    sid = c.post("/series", json={"titre": "Sonorisable"}).json()["id"]
    serie = S._load(sid)
    serie["episodes"] = [{"n": 1, "script_balise": "Il était une fois.",
                          "script_brut": "Il était une fois."}]
    S._save(serie)
    return c, sid


def test_audio_avec_profil_id_adapte_le_script_avant_les_repliques(monkeypatch):
    appels = []
    _mocker_chaine_production(monkeypatch, capture_adapter=appels)
    c, sid = _serie_avec_episode()
    pid = c.post("/profils", json={"nom": "Fille", "cible": "0-3"}).json()["id"]

    r = c.post(f"/series/{sid}/audio", json={"n": 1, "profil_id": pid})
    assert r.status_code == 200
    assert r.json()["profil_id"] == pid
    assert appels == [("Il était une fois.", "0-3")]


def test_audio_sans_profil_id_non_regression(monkeypatch):
    appels = []
    _mocker_chaine_production(monkeypatch, capture_adapter=appels)
    c, sid = _serie_avec_episode()

    r = c.post(f"/series/{sid}/audio", json={"n": 1})
    assert r.status_code == 200
    assert r.json()["profil_id"] is None
    assert appels == []  # _adapter_cible jamais appelé sans profil_id


def test_audio_profil_id_dautrui_404(monkeypatch):
    _mocker_chaine_production(monkeypatch)
    monkeypatch.setenv("STUDIO_KEY", "cle-coeur")
    from fastapi.testclient import TestClient
    c = TestClient(main.app)
    entetes_claire = {"X-API-Key": "cle-coeur", "X-User-Id": "claire"}
    entetes_marina = {"X-API-Key": "cle-coeur", "X-User-Id": "marina"}
    sid = c.post("/series", json={"titre": "SérieMarina"}, headers=entetes_marina).json()["id"]
    serie = S._load(sid)
    serie["episodes"] = [{"n": 1, "script_balise": "Texte.", "script_brut": "Texte."}]
    S._save(serie)
    pid = c.post("/profils", json={"nom": "DeClaire", "cible": "7-9"},
                 headers=entetes_claire).json()["id"]

    r = c.post(f"/series/{sid}/audio", json={"n": 1, "profil_id": pid}, headers=entetes_marina)
    assert r.status_code == 404
