"""Tests — composition de veille-prospection/geo/forge/mail par l'atelier-veille (onglet
Prospection, S193). Fichier séparé de test_composition.py (dédié à veille-info) : cette
fonctionnalité forme un tout cohérent, plus simple à relire groupée — motif déjà appliqué
par test_front.py/test_main.py/test_composition.py qui se partagent le fichier par rôle."""
from fastapi.testclient import TestClient

import main as M
from test_composition import _client_json

client = TestClient(M.app)


def _client_multi(reponses, boom_pour=None):
    """reponses : {suffixe_url: (status, json)}. boom_pour : liste de suffixes qui lèvent
    une exception réseau au lieu de répondre — sert à PROUVER qu'une route n'a pas été
    appelée (si elle l'était, le test échouerait avec un 502, pas silencieusement)."""
    class FauxRep:
        def __init__(self, status, corps):
            self.status_code, self._corps = status, corps
        def json(self):
            return self._corps

    class FauxClient:
        dernier_appel = None
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url, headers=None, **k):
            for suffixe in (boom_pour or []):
                if url.endswith(suffixe):
                    raise RuntimeError("connection refused")
            for suffixe, (status, corps) in reponses.items():
                if url.endswith(suffixe):
                    return FauxRep(status, corps)
            raise AssertionError(f"URL non mockée : {url}")
        async def post(self, url, headers=None, json=None, **k):
            for suffixe in (boom_pour or []):
                if url.endswith(suffixe):
                    raise RuntimeError("connection refused")
            for suffixe, (status, corps) in reponses.items():
                if url.endswith(suffixe):
                    FauxClient.dernier_appel = ("POST", url, headers, json)
                    return FauxRep(status, corps)
            raise AssertionError(f"URL non mockée : {url}")
    return FauxClient


def test_prospects_campagne_filtre_par_zone_nom(monkeypatch):
    monkeypatch.setattr(M.httpx, "AsyncClient", _client_multi({
        "/campagnes": (200, [{"id": 1, "zone_id": "z1", "zone_nom": "Restos Castres", "type": "b2b"}]),
        "/crm": (200, {"prospects": [
            {"id": "a", "nom": "Chez Paul", "email": "p@a.fr",
             "notes": "NAF : 56.10A · Commune : Castres · Zone : Restos Castres"},
            {"id": "b", "nom": "Salon B", "email": "x@b.fr", "notes": "Zone : Coiffeurs Castres"},
        ]}),
    }))
    r = client.get("/prospection/prospects?campagne_id=1")
    assert r.status_code == 200
    data = r.json()
    assert data["zone_nom"] == "Restos Castres"
    assert [p["id"] for p in data["prospects"]] == ["a"]


def test_prospects_campagne_introuvable_404(monkeypatch):
    monkeypatch.setattr(M.httpx, "AsyncClient", _client_multi({"/campagnes": (200, [])}))
    r = client.get("/prospection/prospects?campagne_id=999")
    assert r.status_code == 404


def test_prospects_campagne_sans_zone_nom_rend_liste_vide_sans_appeler_forge(monkeypatch):
    Faux = _client_multi({
        "/campagnes": (200, [{"id": 2, "zone_id": "z2", "zone_nom": None, "type": "b2b"}]),
    }, boom_pour=["/crm"])
    monkeypatch.setattr(M.httpx, "AsyncClient", Faux)
    r = client.get("/prospection/prospects?campagne_id=2")
    assert r.status_code == 200
    assert r.json() == {"campagne_id": 2, "zone_nom": None, "prospects": []}


def test_lister_campagnes_prospection_proxifie(monkeypatch):
    monkeypatch.setattr(M.httpx, "AsyncClient", _client_json(
        [{"id": 1, "zone_id": "z1", "zone_nom": "Restos Castres", "type": "b2b"}]))
    r = client.get("/prospection/campagnes")
    assert r.status_code == 200
    assert r.json()[0]["zone_nom"] == "Restos Castres"


def test_lister_campagnes_prospection_relaie_lidentite(monkeypatch):
    Faux = _client_json([])
    monkeypatch.setattr(M.httpx, "AsyncClient", Faux)
    client.get("/prospection/campagnes", headers={"X-User-Id": "claire", "X-API-Key": "k"})
    _, url, headers = Faux.dernier_appel
    assert url == f"{M.VEILLE_PROSPECTION_URL}/campagnes"
    assert headers == {"X-User-Id": "claire", "X-API-Key": "k"}


def test_creer_campagne_prospection_proxifie_le_corps(monkeypatch):
    Faux = _client_json({"id": 2, "zone_id": "z2", "type": "b2b", "zone_nom": None}, status=201)
    monkeypatch.setattr(M.httpx, "AsyncClient", Faux)
    r = client.post("/prospection/campagnes", json={"zone_id": "z2"})
    assert r.status_code == 201
    _, _, _, corps = Faux.dernier_appel
    assert corps == {"zone_id": "z2", "type": "b2b"}


def test_supprimer_campagne_prospection_proxifie(monkeypatch):
    monkeypatch.setattr(M.httpx, "AsyncClient", _client_json({"ok": True}))
    r = client.delete("/prospection/campagnes/2")
    assert r.status_code == 200


def test_supprimer_campagne_prospection_introuvable_relaie_404(monkeypatch):
    monkeypatch.setattr(M.httpx, "AsyncClient",
                        _client_json({"detail": "Campagne introuvable ou inactive."}, status=404))
    r = client.delete("/prospection/campagnes/999")
    assert r.status_code == 404


def test_executer_campagne_prospection_proxifie(monkeypatch):
    monkeypatch.setattr(M.httpx, "AsyncClient", _client_json(
        {"trouves": 3, "deja_connus": 1, "nouveaux_crm": 2, "erreur": None}))
    r = client.post("/prospection/campagnes/1/executer")
    assert r.status_code == 200
    assert r.json()["trouves"] == 3


def test_executer_campagne_prospection_introuvable_relaie_404(monkeypatch):
    monkeypatch.setattr(M.httpx, "AsyncClient",
                        _client_json({"detail": "Campagne introuvable ou inactive."}, status=404))
    r = client.post("/prospection/campagnes/999/executer")
    assert r.status_code == 404


def test_executer_campagne_prospection_injoignable_502(monkeypatch):
    monkeypatch.setattr(M.httpx, "AsyncClient", _client_json({}, boom=True))
    r = client.post("/prospection/campagnes/1/executer")
    assert r.status_code == 502
    assert "veille-prospection" in r.json()["detail"]


def test_lister_zones_prospection_proxifie(monkeypatch):
    monkeypatch.setattr(M.httpx, "AsyncClient", _client_json(
        {"zones": [{"id": "z1", "nom": "Restos Castres", "type": "entreprise"}]}))
    r = client.get("/prospection/zones")
    assert r.status_code == 200
    assert r.json()["zones"][0]["nom"] == "Restos Castres"


def test_preparer_demarchage_extrait_ville_et_filtre_par_campagne(monkeypatch):
    Faux = _client_multi({
        "/campagnes": (200, [{"id": 1, "zone_id": "z1", "zone_nom": "Restos Castres", "type": "b2b"}]),
        "/crm": (200, {"prospects": [
            {"id": "a", "nom": "Chez Paul", "entreprise": "Chez Paul SARL", "email": "p@a.fr",
             "notes": "NAF : 56.10A · Commune : Castres · Zone : Restos Castres"},
        ]}),
        "/demarchage/preparer": (201, {"ok": True, "prepares": 1, "ignores": {},
                                       "message": "1 brouillon(s) préparé(s)."}),
    })
    monkeypatch.setattr(M.httpx, "AsyncClient", Faux)
    r = client.post("/prospection/demarchage", json={
        "campagne_id": 1, "prospect_ids": ["a"], "expediteur": "Studio Web — 06 00 00 00 00",
        "sujet": "Bonjour {nom}", "message": "On a vu {entreprise} à {ville}."
    })
    assert r.status_code == 201
    _, _, _, corps_aval = Faux.dernier_appel
    assert corps_aval["prospects"] == [{"nom": "Chez Paul", "entreprise": "Chez Paul SARL",
                                        "email": "p@a.fr", "ville": "Castres"}]
    assert corps_aval["sujet"] == "Bonjour {nom}"
    assert corps_aval["expediteur"] == "Studio Web — 06 00 00 00 00"


def test_preparer_demarchage_ville_vide_si_absente_des_notes(monkeypatch):
    Faux = _client_multi({
        "/campagnes": (200, [{"id": 1, "zone_id": "z1", "zone_nom": "Restos Castres", "type": "b2b"}]),
        "/crm": (200, {"prospects": [
            {"id": "a", "nom": "Chez Paul", "email": "p@a.fr", "notes": "Zone : Restos Castres"}]}),
        "/demarchage/preparer": (201, {"ok": True, "prepares": 1, "ignores": {}}),
    })
    monkeypatch.setattr(M.httpx, "AsyncClient", Faux)
    client.post("/prospection/demarchage", json={
        "campagne_id": 1, "prospect_ids": ["a"], "expediteur": "X", "sujet": "S", "message": "M"})
    _, _, _, corps_aval = Faux.dernier_appel
    assert corps_aval["prospects"][0]["ville"] == ""


def test_preparer_demarchage_prospect_id_hors_campagne_est_ignore_422(monkeypatch):
    Faux = _client_multi({
        "/campagnes": (200, [{"id": 1, "zone_id": "z1", "zone_nom": "Restos Castres", "type": "b2b"}]),
        "/crm": (200, {"prospects": [
            {"id": "a", "nom": "Chez Paul", "email": "p@a.fr", "notes": "Zone : Restos Castres"}]}),
    })
    monkeypatch.setattr(M.httpx, "AsyncClient", Faux)
    r = client.post("/prospection/demarchage", json={
        "campagne_id": 1, "prospect_ids": ["id-inconnu"], "expediteur": "X",
        "sujet": "S", "message": "M"})
    assert r.status_code == 422


def test_preparer_demarchage_relaie_une_erreur_de_mail(monkeypatch):
    Faux = _client_multi({
        "/campagnes": (200, [{"id": 1, "zone_id": "z1", "zone_nom": "Restos Castres", "type": "b2b"}]),
        "/crm": (200, {"prospects": [
            {"id": "a", "nom": "Chez Paul", "email": "p@a.fr", "notes": "Zone : Restos Castres"}]}),
        "/demarchage/preparer": (404, {"detail": "Boîte « x@y.fr » non connectée."}),
    })
    monkeypatch.setattr(M.httpx, "AsyncClient", Faux)
    r = client.post("/prospection/demarchage", json={
        "campagne_id": 1, "prospect_ids": ["a"], "expediteur": "Studio Web",
        "sujet": "S", "message": "M", "compte": "x@y.fr"})
    assert r.status_code == 404
    assert "non connectée" in r.json()["detail"]


def test_preparer_demarchage_expediteur_vide_422_sans_appeler_mail(monkeypatch):
    Faux = _client_multi({
        "/campagnes": (200, [{"id": 1, "zone_id": "z1", "zone_nom": "Restos Castres", "type": "b2b"}]),
        "/crm": (200, {"prospects": [
            {"id": "a", "nom": "Chez Paul", "email": "p@a.fr", "notes": "Zone : Restos Castres"}]}),
    }, boom_pour=["/demarchage/preparer"])
    monkeypatch.setattr(M.httpx, "AsyncClient", Faux)
    r = client.post("/prospection/demarchage", json={
        "campagne_id": 1, "prospect_ids": ["a"], "expediteur": "", "sujet": "S", "message": "M"})
    assert r.status_code == 422
