"""S230 : `crm/import-lot` peut cibler une venture précise via `venture_id` — sans quoi
le pipeline audit multi-client (S227→S230) mélangerait les prospects de deux clients
différents dans la même venture Forge (`_resoudre_pole_crm` prenait toujours la première
venture trouvée, mise en cache pour la durée de vie du process)."""
import main
from fastapi.testclient import TestClient

client = TestClient(main.app)


class _Resp:
    def __init__(self, corps, status=200):
        self.status_code, self._c, self.text = status, corps, ""

    def json(self):
        return self._c


def _install_faux_core(monkeypatch, poles_par_venture, existants=None):
    store = list(existants or [])
    appels = []

    async def faux_appel(_cl, methode, chemin, **kw):
        appels.append((methode, chemin))
        if methode == "GET" and chemin.endswith("/poles"):
            vid = chemin.split("/")[-2]
            return _Resp(poles_par_venture.get(vid, []))
        if methode == "GET" and chemin.endswith("/crm"):
            return _Resp(list(store))
        if methode == "POST" and chemin.endswith("/crm"):
            lead = dict(kw.get("json") or {})
            lead["id"] = f"lead-{len(store) + 1}"
            store.append(lead)
            return _Resp(lead)
        return _Resp({})

    monkeypatch.setattr(main, "_appel_protege", faux_appel)
    return store, appels


def test_import_lot_avec_venture_id_resout_le_pole_de_cette_venture(monkeypatch):
    store, appels = _install_faux_core(monkeypatch, {
        "vt-a": [{"id": "pole-a-sales", "type": "sales"}],
    })
    r = client.post("/crm/import-lot", json={
        "prospects": [{"nom": "Client A"}], "venture_id": "vt-a"})
    assert r.status_code == 200
    assert r.json()["crees"] == 1
    assert ("GET", "/api/ventures/vt-a/poles") in appels
    assert ("POST", "/api/poles/pole-a-sales/crm") in appels


def test_import_lot_deux_ventures_differentes_ne_se_melangent_pas(monkeypatch):
    store, appels = _install_faux_core(monkeypatch, {
        "vt-a": [{"id": "pole-a", "type": "sales"}],
        "vt-b": [{"id": "pole-b", "type": "sales"}],
    })
    client.post("/crm/import-lot", json={"prospects": [{"nom": "X"}], "venture_id": "vt-a"})
    client.post("/crm/import-lot", json={"prospects": [{"nom": "Y"}], "venture_id": "vt-b"})
    # Le magasin est partagé dans ce faux core (comme le vrai `/api/poles/{id}/crm`
    # scope par pole_id) — la preuve porte sur le POLE appelé, pas sur un store séparé.
    # Assertion réelle (S230 revue finale M1) : les deux appels ont bien résolu deux
    # URLs de lookup de pôle DIFFÉRENTES (une par venture), pas un fallback partagé.
    assert ("GET", "/api/ventures/vt-a/poles") in appels
    assert ("GET", "/api/ventures/vt-b/poles") in appels


def test_import_lot_venture_id_absent_le_id_absent_utilise_le_cache_global_existant(monkeypatch):
    """Non-régression S169 : sans venture_id, comportement inchangé."""
    appels_pole = []

    async def faux_resoudre(_cl, venture_id=None):
        appels_pole.append(venture_id)
        return "pole-legacy"

    async def faux_appel(_cl, methode, chemin, **kw):
        if methode == "GET" and chemin.endswith("/crm"):
            return _Resp([])
        if methode == "POST" and chemin.endswith("/crm"):
            return _Resp({**(kw.get("json") or {}), "id": "lead-1"})
        return _Resp({})

    monkeypatch.setattr(main, "_resoudre_pole_crm", faux_resoudre)
    monkeypatch.setattr(main, "_appel_protege", faux_appel)
    r = client.post("/crm/import-lot", json={"prospects": [{"nom": "Z"}]})
    assert r.status_code == 200
    assert appels_pole == [None]


def test_import_lot_venture_id_sans_pole_sales_prend_le_premier(monkeypatch):
    _install_faux_core(monkeypatch, {"vt-c": [{"id": "pole-c1", "type": "production"}]})
    r = client.post("/crm/import-lot", json={"prospects": [{"nom": "X"}], "venture_id": "vt-c"})
    assert r.status_code == 200


def test_import_lot_venture_id_sans_aucun_pole_erreur_502(monkeypatch):
    _install_faux_core(monkeypatch, {"vt-vide": []})
    r = client.post("/crm/import-lot", json={"prospects": [{"nom": "X"}], "venture_id": "vt-vide"})
    assert r.status_code == 502
