"""Assistant carte : importer une ancienne carte (OCR → proposition → ajout en lot).

L'OCR (brique vision) et le LLM (Gateway) sont des dépendances RÉSEAU : on les remplace
ici par un faux `carte_ia.importer` pour tester la BRIQUE (auth, cloisonnement, validation,
ajout en lot), pas les services tiers. Le pipeline réel est prouvé LIVE séparément."""
import uuid

from fastapi.testclient import TestClient

import carte_ia
import main

client = TestClient(main.app)


def _resto():
    email = f"imp-{uuid.uuid4().hex[:8]}@exemple.fr"
    r = client.post("/auth/inscription", json={
        "email": email, "mot_de_passe": "motdepasse1", "nom_restaurant": "Le Bistrot"}).json()
    return r["session"], r["restaurant"]["id"]


def _h(session):
    return {"Authorization": f"Bearer {session}"}


def _faux_import(plats):
    async def _f(**_kwargs):
        return {"ocr": {"backend": "tesseract", "nb_caracteres": 42}, "plats": plats, "note": ""}
    return _f


def test_import_exige_la_session():
    _, resto = _resto()
    assert client.post(f"/restaurants/{resto}/carte/importer",
                       json={"contenu_base64": "x"}).status_code == 401


def test_import_exige_un_contenu(monkeypatch):
    session, resto = _resto()
    r = client.post(f"/restaurants/{resto}/carte/importer", headers=_h(session), json={})
    assert r.status_code == 422


def test_import_propose_sans_persister(monkeypatch):
    session, resto = _resto()
    monkeypatch.setattr(carte_ia, "importer",
                        _faux_import([{"nom": "Tartare", "prix_cents": 1650, "categorie": "Plats",
                                       "description": "boeuf"}]))
    r = client.post(f"/restaurants/{resto}/carte/importer", headers=_h(session),
                    json={"contenu_base64": "data:image/png;base64,AAAA", "nom_fichier": "carte.png"})
    assert r.status_code == 200
    data = r.json()
    assert data["plats"][0]["nom"] == "Tartare"
    # PROPOSITION seulement : rien n'a été écrit dans la carte.
    carte = client.get(f"/restaurants/{resto}/plats", headers=_h(session)).json()["plats"]
    assert carte == []


def test_import_resto_d_autrui_404(monkeypatch):
    sa, _ = _resto()
    _, resto_b = _resto()
    monkeypatch.setattr(carte_ia, "importer", _faux_import([]))
    r = client.post(f"/restaurants/{resto_b}/carte/importer", headers=_h(sa),
                    json={"contenu_base64": "AAAA"})
    assert r.status_code == 404


def test_generer_exige_concept():
    session, resto = _resto()
    r = client.post(f"/restaurants/{resto}/carte/generer", headers=_h(session), json={"concept": "  "})
    assert r.status_code == 422


def test_generer_propose_sans_persister(monkeypatch):
    session, resto = _resto()
    async def _gen(*_a, **_k):
        return {"plats": [{"nom": "Mojito", "prix_cents": 900, "categorie": "Cocktails",
                           "description": "rhum, menthe"}], "note": ""}
    monkeypatch.setattr(carte_ia, "generer", _gen)
    r = client.post(f"/restaurants/{resto}/carte/generer", headers=_h(session),
                    json={"concept": "bar à cocktails", "par_section": 4})
    assert r.status_code == 200 and r.json()["plats"][0]["nom"] == "Mojito"
    # Génération = proposition : rien n'est écrit avant validation.
    assert client.get(f"/restaurants/{resto}/plats", headers=_h(session)).json()["plats"] == []


def test_ajout_en_lot():
    session, resto = _resto()
    plats = [{"nom": "Soupe", "prix_cents": 700, "categorie": "Entrées"},
             {"nom": "", "prix_cents": 100},                       # ignoré (sans nom)
             {"nom": "Café", "prix_cents": 200, "categorie": "Boissons"}]
    r = client.post(f"/restaurants/{resto}/plats/lot", headers=_h(session), json={"plats": plats})
    assert r.status_code == 200 and r.json()["ajoutes"] == 2
    noms = {p["nom"] for p in client.get(f"/restaurants/{resto}/plats",
                                         headers=_h(session)).json()["plats"]}
    assert noms == {"Soupe", "Café"}


def test_ajout_en_lot_resto_d_autrui_404():
    sa, _ = _resto()
    _, resto_b = _resto()
    r = client.post(f"/restaurants/{resto_b}/plats/lot", headers=_h(sa),
                    json={"plats": [{"nom": "intrusion"}]})
    assert r.status_code == 404
