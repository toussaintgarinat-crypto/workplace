"""Tests — synergies Studio (portrait/couverture/teaser/animer), proxy avec secret de
service (STUDIO_KEY) + identité relayée. Voir aussi test_galerie.py (même motif de
sécurité, dépendance _identite_service partagée)."""
from fastapi.testclient import TestClient

import main as M

client = TestClient(M.app)


def test_identite_service_mode_ouvert_honore_x_user_id_recu():
    """Sans ATELIER_IMAGES_VIDEO_KEY configurée (mode dev), l'en-tête X-User-Id reçu est
    honoré tel quel — il vient du routeur Cœur de confiance, jamais du navigateur direct
    en déploiement réel."""
    identite = M._identite_service(x_api_key=None, authorization=None, x_user_id="claire")
    assert identite == "claire"


def test_identite_service_mode_ouvert_replie_sur_perso():
    identite = M._identite_service(x_api_key=None, authorization=None, x_user_id=None)
    assert identite == "perso"


def test_identite_service_refuse_sans_bonne_cle(monkeypatch):
    monkeypatch.setenv("ATELIER_IMAGES_VIDEO_KEY", "cle-coeur")
    try:
        M._identite_service(x_api_key="mauvaise-cle", authorization=None, x_user_id="claire")
        assert False, "devait lever 401"
    except Exception as e:
        assert getattr(e, "status_code", None) == 401
    finally:
        monkeypatch.delenv("ATELIER_IMAGES_VIDEO_KEY", raising=False)


def test_identite_service_accepte_avec_la_bonne_cle(monkeypatch):
    monkeypatch.setenv("ATELIER_IMAGES_VIDEO_KEY", "cle-coeur")
    try:
        identite = M._identite_service(x_api_key="cle-coeur", authorization=None, x_user_id="claire")
        assert identite == "claire"
    finally:
        monkeypatch.delenv("ATELIER_IMAGES_VIDEO_KEY", raising=False)


def test_entetes_studio_porte_la_cle_et_lidentite(monkeypatch):
    monkeypatch.setenv("STUDIO_KEY", "cle-studio")
    assert M._entetes_studio("claire") == {"X-API-Key": "cle-studio", "X-User-Id": "claire"}


def test_entetes_memoire_porte_la_cle_et_lidentite(monkeypatch):
    monkeypatch.setenv("MEMOIRE_KEY", "cle-memoire")
    assert M._entetes_memoire("claire") == {"X-API-Key": "cle-memoire", "X-User-Id": "claire"}


def _client_json(rep_json, status=200, boom=False):
    class FauxReponse:
        status_code = status
        def json(self):
            return rep_json

    class FauxClient:
        dernier_appel = None
        def __init__(self, *a, **k):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False
        async def request(self, methode, url, headers=None, json=None, params=None, **k):
            if boom:
                raise RuntimeError("connection refused")
            FauxClient.dernier_appel = (methode, url, headers, json, params)
            return FauxReponse()
    return FauxClient


def test_studio_series_relaie_lidentite_recue(monkeypatch):
    monkeypatch.setenv("STUDIO_KEY", "cle-studio")
    Faux = _client_json([{"id": "s1", "titre": "Ma série"}])
    monkeypatch.setattr(M.httpx, "AsyncClient", Faux)
    r = client.get("/studio/series", headers={"X-User-Id": "claire"})
    assert r.status_code == 200
    _, url, entetes, _, _ = Faux.dernier_appel
    assert url == f"{M.STUDIO_URL}/series"
    assert entetes == {"X-API-Key": "cle-studio", "X-User-Id": "claire"}


def test_studio_serie_relaie_lidentite(monkeypatch):
    monkeypatch.setenv("STUDIO_KEY", "cle-studio")
    Faux = _client_json({"id": "s1", "titre": "Ma série", "personnages": [], "episodes": []})
    monkeypatch.setattr(M.httpx, "AsyncClient", Faux)
    r = client.get("/studio/series/s1", headers={"X-User-Id": "claire"})
    assert r.status_code == 200
    _, url, _, _, _ = Faux.dernier_appel
    assert url == f"{M.STUDIO_URL}/series/s1"


def test_studio_portrait_proxifie_sans_corps(monkeypatch):
    Faux = _client_json({"portrait_url": "/fichiers/p1.png", "place_holder": True,
                         "prompt_visuel": "…", "perso": {"id": "p1"}})
    monkeypatch.setattr(M.httpx, "AsyncClient", Faux)
    r = client.post("/studio/series/s1/personnages/p1/portrait")
    assert r.status_code == 200
    methode, url, _, corps, _ = Faux.dernier_appel
    assert methode == "POST"
    assert url == f"{M.STUDIO_URL}/series/s1/personnages/p1/portrait"
    assert corps is None


def test_studio_animer_proxifie(monkeypatch):
    Faux = _client_json({"clip_url": "/fichiers/c1.mp4", "place_holder": False,
                         "prompt_visuel": "…", "perso": {"id": "p1"}})
    monkeypatch.setattr(M.httpx, "AsyncClient", Faux)
    r = client.post("/studio/series/s1/personnages/p1/animer")
    assert r.status_code == 200
    assert r.json()["clip_url"] == "/fichiers/c1.mp4"


def test_studio_couverture_proxifie(monkeypatch):
    Faux = _client_json({"cover_url": "/fichiers/cov1.png", "place_holder": False, "n": 1})
    monkeypatch.setattr(M.httpx, "AsyncClient", Faux)
    r = client.post("/studio/series/s1/episode/1/couverture")
    assert r.status_code == 200
    _, url, _, _, _ = Faux.dernier_appel
    assert url == f"{M.STUDIO_URL}/series/s1/episode/1/couverture"


def test_studio_teaser_proxifie(monkeypatch):
    Faux = _client_json({"teaser_url": "/fichiers/t1.mp4", "place_holder": False, "n": 1})
    monkeypatch.setattr(M.httpx, "AsyncClient", Faux)
    r = client.post("/studio/series/s1/episode/1/teaser")
    assert r.status_code == 200
    assert r.json()["teaser_url"] == "/fichiers/t1.mp4"


def test_studio_injoignable_renvoie_502(monkeypatch):
    monkeypatch.setattr(M.httpx, "AsyncClient", _client_json({}, boom=True))
    r = client.get("/studio/series")
    assert r.status_code == 502
    assert "studio" in r.json()["detail"]


def test_studio_personnage_introuvable_relaie_404(monkeypatch):
    monkeypatch.setattr(M.httpx, "AsyncClient",
                        _client_json({"detail": "Personnage introuvable"}, status=404))
    r = client.post("/studio/series/s1/personnages/px/portrait")
    assert r.status_code == 404
