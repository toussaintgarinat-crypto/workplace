"""Tests — composition de veille-info (sources RSS) par l'atelier-veille.

L'atelier ne stocke rien : il relaie tel quel vers veille-info et relaie les en-têtes
d'identité reçus du navigateur (pass-through pur, jamais fabriqués)."""
from fastapi.testclient import TestClient

import main as M

client = TestClient(M.app)


def _client_json(rep_json, status=200, boom=False, json_boom=False, content=None, headers=None):
    _contenu = content if content is not None else b""
    _entetes_rep = headers or {}

    class FauxRep:
        status_code = status
        content = _contenu
        headers = _entetes_rep
        def json(self):
            if json_boom:
                raise ValueError("réponse non-JSON (flux tronqué)")
            return rep_json

    class FauxClient:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url, headers=None, **k):
            if boom:
                raise RuntimeError("connection refused")
            FauxClient.dernier_appel = ("GET", url, headers)
            return FauxRep()
        async def post(self, url, headers=None, json=None, **k):
            if boom:
                raise RuntimeError("connection refused")
            FauxClient.dernier_appel = ("POST", url, headers, json)
            return FauxRep()
        async def delete(self, url, headers=None, **k):
            if boom:
                raise RuntimeError("connection refused")
            FauxClient.dernier_appel = ("DELETE", url, headers)
            return FauxRep()
        async def patch(self, url, headers=None, json=None, **k):
            if boom:
                raise RuntimeError("connection refused")
            FauxClient.dernier_appel = ("PATCH", url, headers, json)
            return FauxRep()
    return FauxClient


def test_lister_sources_proxifie_vers_veille_info(monkeypatch):
    monkeypatch.setattr(M.httpx, "AsyncClient",
                        _client_json([{"id": 1, "nom": "Flux A", "url": "https://a.example/rss"}]))
    r = client.get("/veille/sources", headers={"X-User-Id": "claire"})
    assert r.status_code == 200
    assert r.json() == [{"id": 1, "nom": "Flux A", "url": "https://a.example/rss"}]


def test_lister_sources_relaie_lidentite_recue(monkeypatch):
    Faux = _client_json([])
    monkeypatch.setattr(M.httpx, "AsyncClient", Faux)
    client.get("/veille/sources", headers={"X-User-Id": "claire", "X-API-Key": "cle-coeur"})
    _, url, headers = Faux.dernier_appel
    assert url == f"{M.VEILLE_INFO_URL}/sources"
    assert headers == {"X-User-Id": "claire", "X-API-Key": "cle-coeur"}


def test_lister_sources_sans_identite_ne_fabrique_rien(monkeypatch):
    Faux = _client_json([])
    monkeypatch.setattr(M.httpx, "AsyncClient", Faux)
    client.get("/veille/sources")
    _, _, headers = Faux.dernier_appel
    assert headers == {}


def test_lister_sources_injoignable_renvoie_502(monkeypatch):
    monkeypatch.setattr(M.httpx, "AsyncClient", _client_json({}, boom=True))
    r = client.get("/veille/sources")
    assert r.status_code == 502
    assert "veille-info" in r.json()["detail"]


def test_creer_source_proxifie_le_corps(monkeypatch):
    Faux = _client_json({"id": 2, "nom": "Flux B", "url": "https://b.example/rss"}, status=201)
    monkeypatch.setattr(M.httpx, "AsyncClient", Faux)
    r = client.post("/veille/sources", json={"nom": "Flux B", "url": "https://b.example/rss"})
    assert r.status_code == 201
    _, _, _, corps = Faux.dernier_appel
    # `thematique` a un défaut vide ("") dans le modèle CreerSource depuis S199 : le proxy
    # le relaie toujours, même quand l'appelant ne l'a pas fourni.
    assert corps == {"nom": "Flux B", "url": "https://b.example/rss", "thematique": ""}


def test_supprimer_source_proxifie(monkeypatch):
    monkeypatch.setattr(M.httpx, "AsyncClient", _client_json({"ok": True}))
    r = client.delete("/veille/sources/2")
    assert r.status_code == 200


def test_supprimer_source_introuvable_relaie_404(monkeypatch):
    monkeypatch.setattr(M.httpx, "AsyncClient",
                        _client_json({"detail": "Source introuvable."}, status=404))
    r = client.delete("/veille/sources/999")
    assert r.status_code == 404


def test_lister_sources_json_malforme_renvoie_502(monkeypatch):
    monkeypatch.setattr(M.httpx, "AsyncClient", _client_json(None, json_boom=True))
    r = client.get("/veille/sources")
    assert r.status_code == 502
    assert "veille-info" in r.json()["detail"]


def test_creer_source_relaie_422_au_lieu_de_201(monkeypatch):
    monkeypatch.setattr(M.httpx, "AsyncClient",
                        _client_json({"detail": "URL invalide"}, status=422))
    r = client.post("/veille/sources", json={"nom": "Flux C", "url": "pas-une-url"})
    assert r.status_code == 422
    assert r.json()["detail"] == "URL invalide"


def test_lister_sources_relaie_500_au_lieu_de_200(monkeypatch):
    monkeypatch.setattr(M.httpx, "AsyncClient",
                        _client_json({"detail": "erreur interne veille-info"}, status=500))
    r = client.get("/veille/sources")
    assert r.status_code == 500


def test_lister_digests_proxifie_vers_veille_info(monkeypatch):
    monkeypatch.setattr(M.httpx, "AsyncClient",
                        _client_json([{"id": 1, "date": "2026-07-21", "texte_resume": "…",
                                       "nb_articles": 3, "audio_url": None, "audio_duree": None}]))
    r = client.get("/veille/digests", headers={"X-User-Id": "claire"})
    assert r.status_code == 200
    assert r.json()[0]["nb_articles"] == 3


def test_executer_digest_utilise_le_jeton_de_service_pas_lidentite_navigateur(monkeypatch):
    monkeypatch.setenv("VEILLE_INFO_KEY", "jeton-horloge")
    import importlib
    importlib.reload(M)
    Faux = _client_json({"utilisateurs_traites": 2, "digests_crees": 2})
    monkeypatch.setattr(M.httpx, "AsyncClient", Faux)
    r = TestClient(M.app).post("/veille/digest/executer", headers={"X-User-Id": "claire"})
    assert r.status_code == 200
    _, _, headers, _ = Faux.dernier_appel
    assert headers == {"Authorization": "Bearer jeton-horloge"}


def test_executer_digest_sans_cle_configuree_envoie_bearer_vide(monkeypatch):
    monkeypatch.delenv("VEILLE_INFO_KEY", raising=False)
    import importlib
    importlib.reload(M)
    Faux = _client_json({"utilisateurs_traites": 0, "digests_crees": 0})
    monkeypatch.setattr(M.httpx, "AsyncClient", Faux)
    r = TestClient(M.app).post("/veille/digest/executer")
    assert r.status_code == 200
    _, _, headers, _ = Faux.dernier_appel
    assert headers == {"Authorization": "Bearer "}


def test_executer_digest_refuse_relaie_lerreur(monkeypatch):
    monkeypatch.setattr(M.httpx, "AsyncClient",
                        _client_json({"detail": "Jeton horloge invalide."}, status=401))
    r = client.post("/veille/digest/executer")
    assert r.status_code == 401


# --- retagger_source (PATCH /veille/sources/{id}/thematique) — S199 ---

def test_retagger_source_relaie_lidentite_recue(monkeypatch):
    Faux = _client_json({"id": 2, "thematique": "tech"})
    monkeypatch.setattr(M.httpx, "AsyncClient", Faux)
    client.patch("/veille/sources/2/thematique", json={"thematique": "tech"},
                 headers={"X-User-Id": "claire", "X-API-Key": "cle-coeur"})
    _, url, headers, _ = Faux.dernier_appel
    assert url == f"{M.VEILLE_INFO_URL}/sources/2/thematique"
    assert headers == {"X-User-Id": "claire", "X-API-Key": "cle-coeur"}


def test_retagger_source_sans_identite_ne_fabrique_rien(monkeypatch):
    Faux = _client_json({"id": 2, "thematique": "tech"})
    monkeypatch.setattr(M.httpx, "AsyncClient", Faux)
    client.patch("/veille/sources/2/thematique", json={"thematique": "tech"})
    _, _, headers, _ = Faux.dernier_appel
    assert headers == {}


def test_retagger_source_proxifie_le_corps(monkeypatch):
    Faux = _client_json({"id": 2, "thematique": "tech"})
    monkeypatch.setattr(M.httpx, "AsyncClient", Faux)
    r = client.patch("/veille/sources/2/thematique", json={"thematique": "tech"})
    assert r.status_code == 200
    _, _, _, corps = Faux.dernier_appel
    assert corps == {"thematique": "tech"}


def test_retagger_source_injoignable_renvoie_502(monkeypatch):
    monkeypatch.setattr(M.httpx, "AsyncClient", _client_json({}, boom=True))
    r = client.patch("/veille/sources/2/thematique", json={"thematique": "tech"})
    assert r.status_code == 502
    assert "veille-info" in r.json()["detail"]


# --- generer_audio_global (POST /veille/audio-global/generer) — S199 ---

def test_generer_audio_global_relaie_lidentite_recue(monkeypatch):
    Faux = _client_json({"id": 5, "statut": "en_cours"}, status=201)
    monkeypatch.setattr(M.httpx, "AsyncClient", Faux)
    client.post("/veille/audio-global/generer", json={"ordre_thematiques": [1, 2]},
                headers={"X-User-Id": "claire", "X-API-Key": "cle-coeur"})
    _, url, headers, _ = Faux.dernier_appel
    assert url == f"{M.VEILLE_INFO_URL}/audio-global/generer"
    assert headers == {"X-User-Id": "claire", "X-API-Key": "cle-coeur"}


def test_generer_audio_global_sans_identite_ne_fabrique_rien(monkeypatch):
    Faux = _client_json({"id": 5, "statut": "en_cours"})
    monkeypatch.setattr(M.httpx, "AsyncClient", Faux)
    client.post("/veille/audio-global/generer", json={"ordre_thematiques": [1, 2]})
    _, _, headers, _ = Faux.dernier_appel
    assert headers == {}


def test_generer_audio_global_proxifie_le_corps(monkeypatch):
    Faux = _client_json({"id": 5, "statut": "en_cours"})
    monkeypatch.setattr(M.httpx, "AsyncClient", Faux)
    r = client.post("/veille/audio-global/generer", json={"ordre_thematiques": [3, 1, 2]})
    assert r.status_code == 200
    _, _, _, corps = Faux.dernier_appel
    assert corps == {"ordre_thematiques": [3, 1, 2]}


def test_generer_audio_global_injoignable_renvoie_502(monkeypatch):
    monkeypatch.setattr(M.httpx, "AsyncClient", _client_json({}, boom=True))
    r = client.post("/veille/audio-global/generer", json={"ordre_thematiques": [1]})
    assert r.status_code == 502
    assert "veille-info" in r.json()["detail"]


# --- lister_audio_global (GET /veille/audio-global) — S199 ---

def test_lister_audio_global_relaie_lidentite_recue(monkeypatch):
    Faux = _client_json([])
    monkeypatch.setattr(M.httpx, "AsyncClient", Faux)
    client.get("/veille/audio-global", headers={"X-User-Id": "claire", "X-API-Key": "cle-coeur"})
    _, url, headers = Faux.dernier_appel
    assert url == f"{M.VEILLE_INFO_URL}/audio-global"
    assert headers == {"X-User-Id": "claire", "X-API-Key": "cle-coeur"}


def test_lister_audio_global_sans_identite_ne_fabrique_rien(monkeypatch):
    Faux = _client_json([])
    monkeypatch.setattr(M.httpx, "AsyncClient", Faux)
    client.get("/veille/audio-global")
    _, _, headers = Faux.dernier_appel
    assert headers == {}


def test_lister_audio_global_injoignable_renvoie_502(monkeypatch):
    monkeypatch.setattr(M.httpx, "AsyncClient", _client_json({}, boom=True))
    r = client.get("/veille/audio-global")
    assert r.status_code == 502
    assert "veille-info" in r.json()["detail"]


# --- envoyer_audio_global (POST /veille/audio-global/{id}/envoyer) — S199 ---

def test_envoyer_audio_global_relaie_lidentite_recue(monkeypatch):
    Faux = _client_json({"envoye": True})
    monkeypatch.setattr(M.httpx, "AsyncClient", Faux)
    client.post("/veille/audio-global/7/envoyer", json={"destinataires": ["claire@example.fr"]},
                headers={"X-User-Id": "claire", "X-API-Key": "cle-coeur"})
    _, url, headers, _ = Faux.dernier_appel
    assert url == f"{M.VEILLE_INFO_URL}/audio-global/7/envoyer"
    assert headers == {"X-User-Id": "claire", "X-API-Key": "cle-coeur"}


def test_envoyer_audio_global_sans_identite_ne_fabrique_rien(monkeypatch):
    Faux = _client_json({"envoye": True})
    monkeypatch.setattr(M.httpx, "AsyncClient", Faux)
    client.post("/veille/audio-global/7/envoyer", json={"destinataires": ["claire@example.fr"]})
    _, _, headers, _ = Faux.dernier_appel
    assert headers == {}


def test_envoyer_audio_global_proxifie_le_corps(monkeypatch):
    Faux = _client_json({"envoye": True})
    monkeypatch.setattr(M.httpx, "AsyncClient", Faux)
    r = client.post("/veille/audio-global/7/envoyer",
                    json={"destinataires": ["claire@example.fr"], "sujet": "Veille du jour",
                          "message": "Voici l'audio."})
    assert r.status_code == 200
    _, _, _, corps = Faux.dernier_appel
    assert corps == {"destinataires": ["claire@example.fr"], "sujet": "Veille du jour",
                     "message": "Voici l'audio."}


def test_envoyer_audio_global_injoignable_renvoie_502(monkeypatch):
    monkeypatch.setattr(M.httpx, "AsyncClient", _client_json({}, boom=True))
    r = client.post("/veille/audio-global/7/envoyer", json={"destinataires": ["claire@example.fr"]})
    assert r.status_code == 502
    assert "veille-info" in r.json()["detail"]


# --- fichier_audio_global (GET /veille/audio-global/{jeton}.mp3) — S199
# Proxy BINAIRE volontairement sans identité (le jeton EST le contrôle d'accès, cf.
# docstring de la route dans main.py) : pas de test de relai d'identité ici, ce serait
# tester une propriété que cette route n'a pas.

def test_fichier_audio_global_relaie_les_octets_bruts(monkeypatch):
    monkeypatch.setattr(M.httpx, "AsyncClient",
                        _client_json(None, content=b"\xff\xfbID3fauxmp3",
                                    headers={"content-type": "audio/mpeg"}))
    r = client.get("/veille/audio-global/jeton-abc.mp3")
    assert r.status_code == 200
    assert r.content == b"\xff\xfbID3fauxmp3"
    assert r.headers["content-type"] == "audio/mpeg"


def test_fichier_audio_global_injoignable_renvoie_502(monkeypatch):
    monkeypatch.setattr(M.httpx, "AsyncClient", _client_json({}, boom=True))
    r = client.get("/veille/audio-global/jeton-abc.mp3")
    assert r.status_code == 502
    assert "veille-info" in r.json()["detail"]
