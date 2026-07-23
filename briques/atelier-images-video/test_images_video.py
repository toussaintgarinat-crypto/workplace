"""Tests — génération libre (images/video), proxy sans auth vers les briques 5950/5970."""
from fastapi.testclient import TestClient

import main as M

client = TestClient(M.app)


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


def test_images_generer_proxifie_le_corps(monkeypatch):
    Faux = _client_json({"url": "/fichiers/img-1.png", "prompt": "un chat",
                         "backend": "fal", "place_holder": False})
    monkeypatch.setattr(M.httpx, "AsyncClient", Faux)
    r = client.post("/images/generer", json={"prompt": "un chat"})
    assert r.status_code == 200
    assert r.json()["backend"] == "fal"
    methode, url, _, corps, _ = Faux.dernier_appel
    assert methode == "POST"
    assert url == f"{M.IMAGES_URL}/generer"
    assert corps["prompt"] == "un chat"


def test_images_generer_reecrit_lurl_en_chemin_local(monkeypatch):
    """Le chemin renvoyé par la brique images (/fichiers/img-1.png) n'est résoluble que
    depuis IMAGES_URL (souvent host.docker.internal, injoignable par le navigateur) — on
    doit le réécrire vers /fichiers/images/… servi par CETTE brique."""
    Faux = _client_json({"url": "/fichiers/img-1.png", "backend": "fal", "place_holder": False})
    monkeypatch.setattr(M.httpx, "AsyncClient", Faux)
    r = client.post("/images/generer", json={"prompt": "un chat"})
    assert r.json()["url"] == "/fichiers/images/img-1.png"


def test_images_generer_injoignable_renvoie_502(monkeypatch):
    monkeypatch.setattr(M.httpx, "AsyncClient", _client_json({}, boom=True))
    r = client.post("/images/generer", json={"prompt": "un chat"})
    assert r.status_code == 502
    assert "images" in r.json()["detail"]


def test_images_fournisseurs_relaie_le_catalogue(monkeypatch):
    monkeypatch.setattr(M.httpx, "AsyncClient",
                        _client_json({"fournisseurs": [{"nom": "fal", "configure": True}],
                                     "ordre": ["comfyui", "gateway", "fal"]}))
    r = client.get("/images/fournisseurs")
    assert r.status_code == 200
    assert r.json()["fournisseurs"][0]["nom"] == "fal"


def test_video_generer_proxifie_le_corps(monkeypatch):
    Faux = _client_json({"url": "/fichiers/vid-1.mp4", "backend": "luma", "place_holder": False})
    monkeypatch.setattr(M.httpx, "AsyncClient", Faux)
    r = client.post("/video/generer", json={"prompt": "un chat qui court", "secondes": 4})
    assert r.status_code == 200
    methode, url, _, corps, _ = Faux.dernier_appel
    assert url == f"{M.VIDEO_URL}/generer"
    assert corps["secondes"] == 4


def test_video_generer_reecrit_lurl_en_chemin_local(monkeypatch):
    Faux = _client_json({"url": "/fichiers/vid-1.mp4", "backend": "luma", "place_holder": False})
    monkeypatch.setattr(M.httpx, "AsyncClient", Faux)
    r = client.post("/video/generer", json={"prompt": "un chat qui court", "secondes": 4})
    assert r.json()["url"] == "/fichiers/video/vid-1.mp4"


def test_video_generer_prompt_vide_rejete_par_pydantic():
    r = client.post("/video/generer", json={"secondes": 4})
    assert r.status_code == 422


def test_video_fournisseurs_relaie_le_catalogue(monkeypatch):
    monkeypatch.setattr(M.httpx, "AsyncClient",
                        _client_json({"fournisseurs": [{"nom": "luma", "configure": False}],
                                     "ordre": ["fal", "replicate", "luma"]}))
    r = client.get("/video/fournisseurs")
    assert r.status_code == 200
    assert r.json()["fournisseurs"][0]["nom"] == "luma"


def _client_binaire(contenu: bytes, content_type: str, status=200, boom=False):
    class FauxReponse:
        status_code = status
        content = contenu
        headers = {"content-type": content_type}

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
            FauxClient.dernier_appel = (methode, url)
            return FauxReponse()
    return FauxClient


def test_fichier_image_rapatrie_les_octets(monkeypatch):
    monkeypatch.setattr(M.httpx, "AsyncClient", _client_binaire(b"\x89PNG...", "image/png"))
    r = client.get("/fichiers/images/img-1.png")
    assert r.status_code == 200
    assert r.content == b"\x89PNG..."
    assert r.headers["content-type"] == "image/png"


def test_fichier_image_interroge_la_bonne_brique(monkeypatch):
    Faux = _client_binaire(b"data", "image/svg+xml")
    monkeypatch.setattr(M.httpx, "AsyncClient", Faux)
    client.get("/fichiers/images/ph-1.svg")
    methode, url = Faux.dernier_appel
    assert methode == "GET"
    assert url == f"{M.IMAGES_URL}/fichiers/ph-1.svg"


def test_fichier_video_rapatrie_les_octets(monkeypatch):
    monkeypatch.setattr(M.httpx, "AsyncClient", _client_binaire(b"\x00\x00\x00ftyp", "video/mp4"))
    r = client.get("/fichiers/video/vid-1.mp4")
    assert r.status_code == 200
    assert r.content == b"\x00\x00\x00ftyp"


def test_fichier_video_interroge_la_bonne_brique(monkeypatch):
    Faux = _client_binaire(b"data", "video/mp4")
    monkeypatch.setattr(M.httpx, "AsyncClient", Faux)
    client.get("/fichiers/video/vid-1.mp4")
    _, url = Faux.dernier_appel
    assert url == f"{M.VIDEO_URL}/fichiers/vid-1.mp4"


def test_fichier_image_introuvable_renvoie_404(monkeypatch):
    monkeypatch.setattr(M.httpx, "AsyncClient", _client_binaire(b"", "text/plain", status=404))
    r = client.get("/fichiers/images/absent.png")
    assert r.status_code == 404


def test_fichier_image_brique_injoignable_renvoie_502(monkeypatch):
    monkeypatch.setattr(M.httpx, "AsyncClient", _client_binaire(b"", "text/plain", boom=True))
    r = client.get("/fichiers/images/img-1.png")
    assert r.status_code == 502
    assert "images" in r.json()["detail"]


def test_relayer_guard_204_no_content(monkeypatch):
    """_relayer() doit retourner {} sans appeler r.json() si status==204, plutôt que
    de laisser r.json() lever une exception sur un corps vide."""
    Faux = _client_json({}, status=204)  # corps ignoré pour 204
    monkeypatch.setattr(M.httpx, "AsyncClient", Faux)
    # galerie_supprimer appelle _relayer avec DELETE, qui doit gérer le 204 proprement
    r = client.delete("/galerie/souvenir-123")
    assert r.status_code == 200  # La relayer renvoie {} pour 204 (traité comme succès)
    assert r.json() == {}
