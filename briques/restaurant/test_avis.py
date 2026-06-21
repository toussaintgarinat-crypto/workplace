"""S84 — avis clients (note 1–5 + commentaire) laissés via le QR de table.

Couvre : la règle PURE (validation de note bornée 1–5, moyenne arrondie) ; le dépôt d'un
avis via le code de table ; le refus d'une note hors bornes ; l'UPSERT par visite (un convive
corrige le sien, jamais de doublon) ; la synthèse côté restaurateur (moyenne/nombre/derniers)
et son cloisonnement fail-closed (le resto d'un autre est invisible)."""
import uuid

from fastapi.testclient import TestClient

import domaine
import main

client = TestClient(main.app)


def _resto():
    email = f"avis-{uuid.uuid4().hex[:8]}@exemple.fr"
    r = client.post("/auth/inscription", json={
        "email": email, "mot_de_passe": "motdepasse1", "nom_restaurant": "Chez l'Avis"}).json()
    return r["session"], r["restaurant"]["id"]


def _h(s):
    return {"Authorization": f"Bearer {s}"}


def _table(h, resto, numero="1"):
    return client.post(f"/restaurants/{resto}/tables", headers=h, json={"numero": numero}).json()


# ── Domaine pur (sans I/O) ───────────────────────────────────────
def test_normaliser_note_borne_1_a_5():
    assert domaine.normaliser_note(1) == 1 and domaine.normaliser_note(5) == 5
    assert domaine.normaliser_note(4.0) == 4            # float toléré, tronqué
    assert domaine.normaliser_note(0) is None           # sous la borne
    assert domaine.normaliser_note(6) is None           # au-dessus
    assert domaine.normaliser_note("3") == 3
    assert domaine.normaliser_note("abc") is None
    assert domaine.normaliser_note(None) is None


def test_moyenne_notes_arrondie_et_vide():
    assert domaine.moyenne_notes([5, 4, 4]) == 4.3
    assert domaine.moyenne_notes([]) == 0.0
    assert domaine.moyenne_notes(None) == 0.0


# ── Bout-en-bout via l'API ───────────────────────────────────────
def test_client_laisse_un_avis_et_le_resto_le_voit():
    session, resto = _resto()
    h = _h(session)
    code = _table(h, resto)["code"]
    r = client.post(f"/t/{code}/avis", json={"convive": "Léa", "note": 5, "commentaire": "Parfait !"})
    assert r.status_code == 200 and r.json()["merci"] is True

    resume = client.get(f"/restaurants/{resto}/avis", headers=h).json()
    assert resume["nombre"] == 1 and resume["moyenne"] == 5.0
    assert resume["avis"][0]["convive"] == "Léa"
    assert resume["avis"][0]["commentaire"] == "Parfait !"


def test_note_hors_bornes_refusee():
    session, resto = _resto()
    code = _table(_h(session), resto)["code"]
    assert client.post(f"/t/{code}/avis", json={"convive": "X", "note": 0}).status_code == 400
    assert client.post(f"/t/{code}/avis", json={"convive": "X", "note": 9}).status_code == 400


def test_avis_upsert_par_visite_pas_de_doublon():
    session, resto = _resto()
    h = _h(session)
    code = _table(h, resto)["code"]
    client.post(f"/t/{code}/avis", json={"convive": "Léa", "note": 2, "commentaire": "bof"})
    # Le même convive corrige son avis sur la même visite → remplace, ne s'ajoute pas.
    client.post(f"/t/{code}/avis", json={"convive": "Léa", "note": 5, "commentaire": "finalement super"})
    resume = client.get(f"/restaurants/{resto}/avis", headers=h).json()
    assert resume["nombre"] == 1                        # un seul avis (upsert)
    assert resume["moyenne"] == 5.0
    assert resume["avis"][0]["commentaire"] == "finalement super"


def test_moyenne_sur_plusieurs_convives():
    session, resto = _resto()
    h = _h(session)
    code = _table(h, resto)["code"]
    client.post(f"/t/{code}/avis", json={"convive": "Léa", "note": 5})
    client.post(f"/t/{code}/avis", json={"convive": "Marc", "note": 4})
    client.post(f"/t/{code}/avis", json={"convive": "Sara", "note": 4})
    resume = client.get(f"/restaurants/{resto}/avis", headers=h).json()
    assert resume["nombre"] == 3 and resume["moyenne"] == 4.3


def test_avis_cloisonne_par_restaurateur():
    # Le resto B ne voit jamais les avis du resto A (fail-closed).
    sA, rA = _resto()
    code = _table(_h(sA), rA)["code"]
    client.post(f"/t/{code}/avis", json={"convive": "Léa", "note": 5})
    sB, _ = _resto()
    assert client.get(f"/restaurants/{rA}/avis", headers=_h(sB)).status_code == 404
