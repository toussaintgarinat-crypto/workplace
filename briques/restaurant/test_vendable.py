"""Capacités « vendable » (v0.2.0) : clôture/réutilisation de table, TVA & ticket,
révocation de session, changement de mot de passe, anti-brute-force, catégories, pourboire."""
import uuid

from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


def _resto(tva=10.0):
    email = f"vend-{uuid.uuid4().hex[:8]}@exemple.fr"
    r = client.post("/auth/inscription", json={
        "email": email, "mot_de_passe": "motdepasse1", "nom_restaurant": "Vendable"}).json()
    s = r["session"]
    resto = r["restaurant"]["id"]
    if tva != 10.0:
        client.patch(f"/restaurants/{resto}", headers={"Authorization": "Bearer " + s},
                     json={"tva_taux": tva})
    return s, resto, email


def _h(s):
    return {"Authorization": "Bearer " + s}


def _table(s, resto, num="1"):
    return client.post(f"/restaurants/{resto}/tables", headers=_h(s), json={"numero": num}).json()


def _plat(s, resto, nom, prix, **kw):
    return client.post(f"/restaurants/{resto}/plats", headers=_h(s),
                       json={"nom": nom, "prix_cents": prix, **kw}).json()


# ── Clôture / réutilisation de table ─────────────────────────────
def test_cloture_remet_la_table_a_zero_pour_le_groupe_suivant():
    s, resto, _ = _resto()
    t = _table(s, resto, "4")
    p = _plat(s, resto, "Plat", 1000)
    client.post(f"/t/{t['code']}/commander", json={"convive": "Groupe1", "plats": [{"plat_id": p["id"], "quantite": 1}]})
    client.post(f"/t/{t['code']}/payer", json={"convive": "Groupe1"})

    # Clôture autorisée (tout payé) → ticket + table vierge
    r = client.post(f"/restaurants/{resto}/tables/{t['id']}/cloturer", headers=_h(s), json={})
    assert r.status_code == 200
    assert r.json()["ticket"]["etat"]["total_cents"] == 1000
    assert r.json()["etat"]["convives"] == []          # repartie de zéro

    # Le groupe suivant ne voit PAS l'addition du précédent
    etat = client.get(f"/t/{t['code']}/addition").json()
    assert etat["convives"] == [] and etat["reste_cents"] == 0

    # Nouvelle commande → nouvelle session propre
    client.post(f"/t/{t['code']}/commander", json={"convive": "Groupe2", "plats": [{"plat_id": p["id"], "quantite": 2}]})
    etat2 = client.get(f"/t/{t['code']}/addition").json()
    assert etat2["total_cents"] == 2000
    assert [c["convive"] for c in etat2["convives"]] == ["Groupe2"]

    # Le ticket du 1er groupe reste dans l'historique
    tickets = client.get(f"/restaurants/{resto}/tickets", headers=_h(s)).json()["tickets"]
    assert len(tickets) == 1 and tickets[0]["table_numero"] == "4"


def test_cloture_refusee_si_reste_a_payer_sauf_force():
    s, resto, _ = _resto()
    t = _table(s, resto)
    p = _plat(s, resto, "Plat", 1500)
    client.post(f"/t/{t['code']}/commander", json={"convive": "X", "plats": [{"plat_id": p["id"], "quantite": 1}]})
    # Reste dû → 409
    assert client.post(f"/restaurants/{resto}/tables/{t['id']}/cloturer", headers=_h(s), json={}).status_code == 409
    # force → autorisé (départ assumé)
    assert client.post(f"/restaurants/{resto}/tables/{t['id']}/cloturer", headers=_h(s),
                       json={"force": True}).status_code == 200


# ── TVA & ticket ─────────────────────────────────────────────────
def test_tva_ventilee_sur_l_addition():
    s, resto, _ = _resto(tva=10.0)
    t = _table(s, resto)
    p = _plat(s, resto, "Menu", 2100)
    client.post(f"/t/{t['code']}/commander", json={"convive": "A", "plats": [{"plat_id": p["id"], "quantite": 1}]})
    etat = client.get(f"/t/{t['code']}/addition").json()
    assert etat["tva"]["tva_taux"] == 10.0
    assert etat["tva"]["ht_cents"] == 1909       # 2100 / 1.10
    assert etat["tva"]["tva_cents"] == 191        # TTC - HT


# ── Catégories de carte ──────────────────────────────────────────
def test_categorie_portee_sur_la_carte_client():
    s, resto, _ = _resto()
    t = _table(s, resto)
    _plat(s, resto, "Tiramisu", 600, categorie="Desserts")
    carte = client.get(f"/t/{t['code']}").json()["carte"]
    assert carte[0]["categorie"] == "Desserts"


# ── Pourboire ────────────────────────────────────────────────────
def test_pourboire_enregistre_sans_fausser_le_du():
    s, resto, _ = _resto()
    t = _table(s, resto)
    p = _plat(s, resto, "Plat", 1000)
    client.post(f"/t/{t['code']}/commander", json={"convive": "A", "plats": [{"plat_id": p["id"], "quantite": 1}]})
    client.post(f"/t/{t['code']}/payer", json={"convive": "A", "pourboire_cents": 150})
    etat = client.get(f"/t/{t['code']}/addition").json()
    assert etat["pourboire_cents"] == 150
    assert etat["reste_cents"] == 0               # le pourboire n'est pas un dû


# ── Sécurité : révocation de session ─────────────────────────────
def test_changement_mot_de_passe_revoque_les_anciennes_sessions():
    s, resto, email = _resto()
    # Une 2e session (autre appareil)
    s2 = client.post("/auth/connexion", json={"email": email, "mot_de_passe": "motdepasse1"}).json()["session"]
    assert client.get("/auth/moi", headers=_h(s2)).status_code == 200
    # Changement de mdp depuis la 1re session → la 2e doit tomber
    r = client.post("/auth/mot-de-passe", headers=_h(s), json={"ancien": "motdepasse1", "nouveau": "nouveaumdp1"})
    assert r.status_code == 200
    assert client.get("/auth/moi", headers=_h(s2)).status_code == 401       # ancienne session révoquée
    assert client.get("/auth/moi", headers=_h(r.json()["session"])).status_code == 200  # nouvelle OK


def test_mauvais_ancien_mot_de_passe_refuse():
    s, _, _ = _resto()
    assert client.post("/auth/mot-de-passe", headers=_h(s),
                       json={"ancien": "FAUX", "nouveau": "nouveaumdp1"}).status_code == 403


def test_deconnexion_partout_invalide_les_sessions():
    s, _, email = _resto()
    s2 = client.post("/auth/connexion", json={"email": email, "mot_de_passe": "motdepasse1"}).json()["session"]
    client.post("/auth/deconnexion-partout", headers=_h(s))
    assert client.get("/auth/moi", headers=_h(s2)).status_code == 401


# ── Sécurité : anti-brute-force ──────────────────────────────────
def test_anti_brute_force_sur_connexion():
    email = f"brute-{uuid.uuid4().hex[:8]}@exemple.fr"
    client.post("/auth/inscription", json={"email": email, "mot_de_passe": "motdepasse1"})
    # 10 essais ratés autorisés, le 11e est bloqué (429)
    codes = [client.post("/auth/connexion", json={"email": email, "mot_de_passe": "faux"}).status_code
             for _ in range(12)]
    assert 429 in codes
