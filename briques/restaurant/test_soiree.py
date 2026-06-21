"""S85 — la soirée : surnom de tablée, « je paye ma tournée », résumé souvenir, annulation
de commande en cuisine.

Couvre les quatre évolutions de bout en bout via l'API :
  • RENOMMER la tablée (souvenir client, effacé à la clôture) ;
  • TOURNÉE : un convive règle TOUT le reste de la table d'un coup ;
  • RÉSUMÉ de soirée avec repli FACTUEL honnête quand l'assistant est hors ligne ;
  • ANNULER une commande déjà en cuisine (staff only, retrait simple de l'addition).
"""
import uuid

from fastapi.testclient import TestClient

import main
import souvenir

client = TestClient(main.app)


def _resto():
    email = f"soiree-{uuid.uuid4().hex[:8]}@exemple.fr"
    r = client.post("/auth/inscription", json={
        "email": email, "mot_de_passe": "motdepasse1", "nom_restaurant": "Le Festin"}).json()
    return r["session"], r["restaurant"]["id"]


def _h(s):
    return {"Authorization": f"Bearer {s}"}


def _plat(h, resto, **kw):
    return client.post(f"/restaurants/{resto}/plats", headers=h, json=kw).json()


def _table(h, resto, numero="1"):
    return client.post(f"/restaurants/{resto}/tables", headers=h, json={"numero": numero}).json()


# ── Renommer la tablée ───────────────────────────────────────────
def test_nommer_tablee_visible_cote_client():
    session, resto = _resto()
    h = _h(session)
    code = _table(h, resto)["code"]
    r = client.post(f"/t/{code}/nommer", json={"nom": "Les Gloutons"})
    assert r.status_code == 200 and r.json()["nom_session"] == "Les Gloutons"
    # Vu par le smartphone (vue client) ET dans l'état d'addition.
    assert client.get(f"/t/{code}").json()["nom_session"] == "Les Gloutons"
    assert client.get(f"/t/{code}/addition").json()["nom_session"] == "Les Gloutons"


def test_nom_vide_retire_le_surnom():
    session, resto = _resto()
    code = _table(_h(session), resto)["code"]
    client.post(f"/t/{code}/nommer", json={"nom": "La Joyeuse Marmite"})
    assert client.post(f"/t/{code}/nommer", json={"nom": "  "}).json()["nom_session"] == ""
    assert client.get(f"/t/{code}").json()["nom_session"] == ""


def test_cloture_efface_le_surnom():
    session, resto = _resto()
    h = _h(session)
    tbl = _table(h, resto)
    code, table_id = tbl["code"], tbl["id"]
    client.post(f"/t/{code}/nommer", json={"nom": "Les Affamés"})
    # Une table vide se clôture (rien à payer) → nouvelle session vierge, sans surnom.
    plat = _plat(h, resto, nom="Eau", prix_cents=0)
    client.post(f"/t/{code}/commander", json={"convive": "Léa", "plats": [{"plat_id": plat["id"], "quantite": 1}]})
    client.post(f"/restaurants/{resto}/tables/{table_id}/cloturer", headers=h, json={})
    assert client.get(f"/t/{code}").json()["nom_session"] == ""


# ── Je paye ma tournée ───────────────────────────────────────────
def test_tournee_solde_toute_la_table():
    session, resto = _resto()
    h = _h(session)
    code = _table(h, resto)["code"]
    p = _plat(h, resto, nom="Plat", prix_cents=1000)
    # Deux convives, 2000 au total.
    client.post(f"/t/{code}/commander", json={"convive": "Léa", "plats": [{"plat_id": p["id"], "quantite": 1}]})
    client.post(f"/t/{code}/commander", json={"convive": "Max", "plats": [{"plat_id": p["id"], "quantite": 1}]})
    r = client.post(f"/t/{code}/payer", json={"convive": "Léa", "mode": "tournee"})
    assert r.status_code == 200 and r.json()["paiement"]["montant_cents"] == 2000
    assert client.get(f"/t/{code}/addition").json()["reste_cents"] == 0
    # Plus rien à régaler → idempotent (400).
    assert client.post(f"/t/{code}/payer", json={"convive": "Léa", "mode": "tournee"}).status_code == 400


# ── Résumé de soirée ─────────────────────────────────────────────
def _commander_pour_resume():
    session, resto = _resto()
    h = _h(session)
    code = _table(h, resto)["code"]
    p = _plat(h, resto, nom="Burger", prix_cents=1500)
    client.post(f"/t/{code}/commander", json={"convive": "Léa", "plats": [{"plat_id": p["id"], "quantite": 2}]})
    return code


def test_resume_repli_local_quand_assistant_hors_ligne(monkeypatch):
    async def _ko(*_a, **_k):
        raise RuntimeError("gateway down")
    monkeypatch.setattr(souvenir, "_completer", _ko)
    code = _commander_pour_resume()
    d = client.get(f"/t/{code}/resume").json()
    assert d["genere_par"] == "local"
    assert "Burger" in d["texte"] and "Total" in d["texte"]   # factuel, jamais inventé


def test_resume_ia_quand_assistant_disponible(monkeypatch):
    async def _ok(*_a, **_k):
        return "Quelle belle soirée entre amis autour de bons burgers ! À très vite."
    monkeypatch.setattr(souvenir, "_completer", _ok)
    code = _commander_pour_resume()
    d = client.get(f"/t/{code}/resume").json()
    assert d["genere_par"] == "ia" and "soirée" in d["texte"]


# ── Annuler une commande en cuisine (staff only) ─────────────────
def test_staff_annule_commande_la_sort_de_addition_et_cuisine():
    session, resto = _resto()
    h = _h(session)
    code = _table(h, resto)["code"]
    p = _plat(h, resto, nom="Frites", prix_cents=500)
    cmd = client.post(f"/t/{code}/commander",
                      json={"convive": "Léa", "plats": [{"plat_id": p["id"], "quantite": 2}]}).json()
    cmd_id = cmd["commandes"][0]["id"]
    assert client.get(f"/t/{code}/addition").json()["total_cents"] == 1000

    r = client.delete(f"/restaurants/{resto}/commandes/{cmd_id}", headers=h)
    assert r.status_code == 200 and r.json()["supprime"] is True
    # Sortie de l'addition…
    etat = client.get(f"/t/{code}/addition").json()
    assert etat["total_cents"] == 0 and etat["convives"] == []
    # …et de la file cuisine.
    cuisine = client.get(f"/restaurants/{resto}/cuisine", headers=h).json()["commandes"]
    assert all(c["id"] != cmd_id for c in cuisine)


def test_annuler_commande_exige_le_staff():
    session, resto = _resto()
    h = _h(session)
    code = _table(h, resto)["code"]
    p = _plat(h, resto, nom="Soupe", prix_cents=600)
    cmd = client.post(f"/t/{code}/commander",
                      json={"convive": "Léa", "plats": [{"plat_id": p["id"], "quantite": 1}]}).json()
    cmd_id = cmd["commandes"][0]["id"]
    # Sans session → 401 (le client ne peut pas annuler une commande en cuisine).
    assert client.delete(f"/restaurants/{resto}/commandes/{cmd_id}").status_code == 401


def test_annuler_commande_d_un_autre_resto_404():
    sa, resto_a = _resto()
    sb, _ = _resto()
    ha = _h(sa)
    code = _table(ha, resto_a)["code"]
    p = _plat(ha, resto_a, nom="Tarte", prix_cents=700)
    cmd = client.post(f"/t/{code}/commander",
                      json={"convive": "Léa", "plats": [{"plat_id": p["id"], "quantite": 1}]}).json()
    cmd_id = cmd["commandes"][0]["id"]
    # Le staff d'un AUTRE restaurant ne peut pas annuler (cloisonnement fail-closed).
    assert client.delete(f"/restaurants/{resto_a}/commandes/{cmd_id}", headers=_h(sb)).status_code == 404
