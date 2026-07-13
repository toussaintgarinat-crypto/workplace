"""Chemin de SERVICE : la carte pilotée par le Cœur (capacités MCP), clé de service.

Prouve que le Cœur (clé RESTAURANT_KEY) peut lire/écrire la carte d'un restaurant SANS le
mot de passe du restaurateur, que c'est fail-closed (sans clé / mauvaise clé → refus), et
que le résultat est cohérent avec la vue restaurateur classique."""
import os
import uuid

from fastapi.testclient import TestClient

os.environ["RESTAURANT_KEY"] = "cle-service-de-test"   # lu paresseusement par service_garde

import main

client = TestClient(main.app)
CLE = {"X-API-Key": "cle-service-de-test"}


def _resto():
    email = f"svc-{uuid.uuid4().hex[:8]}@exemple.fr"
    r = client.post("/auth/inscription", json={
        "email": email, "mot_de_passe": "motdepasse1", "nom_restaurant": "Chez Service"}).json()
    return r["session"], r["restaurant"]["id"]


def test_service_exige_la_cle():
    _, resto = _resto()
    # Sans clé → 401 ; mauvaise clé → 401 ; bonne clé → 200.
    assert client.get(f"/service/restaurants/{resto}/plats").status_code == 401
    assert client.get(f"/service/restaurants/{resto}/plats",
                      headers={"X-API-Key": "fausse"}).status_code == 401
    assert client.get(f"/service/restaurants/{resto}/plats", headers=CLE).status_code == 200


def test_service_lister_restaurants_decouverte():
    """S103 : l'assistant découvre les ids des restaurants sans qu'on les fournisse.
    Fail-closed (clé requise) et le resto créé apparaît bien dans la liste."""
    _, resto = _resto()
    assert client.get("/service/restaurants").status_code == 401
    assert client.get("/service/restaurants", headers={"X-API-Key": "fausse"}).status_code == 401
    r = client.get("/service/restaurants", headers=CLE)
    assert r.status_code == 200
    restos = r.json()["restaurants"]
    ids = {x["id"] for x in restos}
    assert resto in ids
    # Chaque entrée porte au moins l'id et le nom (contexte pour l'assistant).
    cible = next(x for x in restos if x["id"] == resto)
    assert cible["nom"] == "Chez Service"


def test_service_cycle_de_vie_d_un_plat():
    session, resto = _resto()
    # Le Cœur ajoute un plat (action).
    p = client.post(f"/service/restaurants/{resto}/plats", headers=CLE,
                    json={"nom": "Velouté", "prix_cents": 850, "categorie": "Entrées"})
    assert p.status_code == 200
    pid = p.json()["id"]

    # Il apparaît côté SERVICE et côté RESTAURATEUR (même donnée, deux portes).
    svc = client.get(f"/service/restaurants/{resto}/plats", headers=CLE).json()["plats"]
    resto_vue = client.get(f"/restaurants/{resto}/plats",
                           headers={"Authorization": f"Bearer {session}"}).json()["plats"]
    assert any(x["id"] == pid and x["nom"] == "Velouté" for x in svc)
    assert any(x["id"] == pid for x in resto_vue)

    # Modifier puis supprimer via le service.
    m = client.patch(f"/service/restaurants/{resto}/plats/{pid}", headers=CLE,
                     json={"prix_cents": 900, "disponible": False})
    assert m.status_code == 200 and m.json()["prix_cents"] == 900 and m.json()["disponible"] is False
    d = client.delete(f"/service/restaurants/{resto}/plats/{pid}", headers=CLE)
    assert d.status_code == 200 and d.json()["supprime"] is True
    restant = client.get(f"/service/restaurants/{resto}/plats", headers=CLE).json()["plats"]
    assert all(x["id"] != pid for x in restant)


def test_service_infos_resto():
    _, resto = _resto()
    r = client.get(f"/service/restaurants/{resto}", headers=CLE)
    assert r.status_code == 200 and r.json()["nom"] == "Chez Service"


def test_service_restaurant_inconnu_404():
    assert client.get(f"/service/restaurants/{uuid.uuid4().hex}/plats",
                      headers=CLE).status_code == 404
    assert client.post(f"/service/restaurants/{uuid.uuid4().hex}/plats", headers=CLE,
                       json={"nom": "fantôme"}).status_code == 404


def test_service_eteint_si_pas_de_cle(monkeypatch):
    # RESTAURANT_KEY absent ⇒ chemin de service ÉTEINT (503), jamais ouvert par défaut.
    monkeypatch.delenv("RESTAURANT_KEY", raising=False)
    _, resto = _resto()
    assert client.get(f"/service/restaurants/{resto}/plats", headers=CLE).status_code == 503


# ── S167 : socle rôle admin / isolation tenant (T1) ──────────────
import pytest
import stockage
from fastapi import HTTPException


def test_ensure_admin_idempotent_et_role():
    """ensure_admin crée un compte d'id déterministe en role='admin', et reste idempotent
    (deux appels ⇒ un seul compte, toujours admin)."""
    stockage.ensure_admin("admin")
    stockage.ensure_admin("admin")  # 2e appel : ne doit pas planter ni dupliquer
    assert stockage.role_du_compte("admin") == "admin"
    c = stockage.compte_par_id("admin")
    assert c and c["role"] == "admin"


def test_service_garde_admin_vs_tenant():
    """service_garde : la clé valide PUIS l'identité X-Compte-Id → rôle en base."""
    stockage.ensure_admin("admin")
    # Un restaurateur normal = tenant.
    _, resto = _resto()
    proprio = stockage.compte_du_restaurant(resto)

    admin_ctx = main.service_garde(x_api_key="cle-service-de-test", x_compte_id="admin")
    assert admin_ctx.est_admin is True

    tenant_ctx = main.service_garde(x_api_key="cle-service-de-test", x_compte_id=proprio)
    assert tenant_ctx.est_admin is False and tenant_ctx.role == "tenant"


def test_service_garde_fail_closed():
    """Clé fausse → 401 ; compte appelant inconnu → 403."""
    stockage.ensure_admin("admin")
    with pytest.raises(HTTPException) as e1:
        main.service_garde(x_api_key="fausse", x_compte_id="admin")
    assert e1.value.status_code == 401
    with pytest.raises(HTTPException) as e2:
        main.service_garde(x_api_key="cle-service-de-test", x_compte_id="compte-fantome")
    assert e2.value.status_code == 403


def test_service_garde_repli_deprecie_sans_compte():
    """Repli de rollout : X-Compte-Id absent ⇒ admin (à retirer avant le multi-user)."""
    ctx = main.service_garde(x_api_key="cle-service-de-test", x_compte_id=None)
    assert ctx.est_admin is True


def test_resoudre_compte_resto_bypass_et_isolation():
    """Le cœur du modèle : admin vise n'importe quel resto ; un tenant ne voit QUE le sien
    (resto d'autrui → 404, on ne divulgue pas son existence)."""
    stockage.ensure_admin("admin")
    _, resto_a = _resto()
    _, resto_b = _resto()
    proprio_a = stockage.compte_du_restaurant(resto_a)

    admin_ctx = main.ContexteService("admin", "admin")
    # Admin agit sur A ET B (bypass), au nom de leurs propriétaires respectifs.
    assert main.resoudre_compte_resto(admin_ctx, resto_a) == proprio_a
    assert main.resoudre_compte_resto(admin_ctx, resto_b) == stockage.compte_du_restaurant(resto_b)

    # Le propriétaire de A (tenant) accède à A…
    tenant_a = main.ContexteService(proprio_a, "tenant")
    assert main.resoudre_compte_resto(tenant_a, resto_a) == proprio_a
    # …mais PAS à B (404, indistingable d'un resto inexistant).
    with pytest.raises(HTTPException) as e:
        main.resoudre_compte_resto(tenant_a, resto_b)
    assert e.value.status_code == 404


# ── S167 T2 : jumeaux /service role-aware, bout en bout (HTTP) ────
def _svc(compte_id):
    """En-têtes d'un appel /service AU NOM d'un compte (clé de service + identité)."""
    return {"X-API-Key": "cle-service-de-test", "X-Compte-Id": compte_id}


def test_service_isolation_tenant_http():
    """Sur la vraie surface HTTP : un tenant ne voit/touche QUE ses restos ; l'admin, tous."""
    stockage.ensure_admin("admin")
    _, resto_a = _resto()
    _, resto_b = _resto()
    proprio_a = stockage.compte_du_restaurant(resto_a)

    # Le tenant A ne liste que A (pas B).
    liste = client.get("/service/restaurants", headers=_svc(proprio_a)).json()["restaurants"]
    ids = {x["id"] for x in liste}
    assert resto_a in ids and resto_b not in ids
    # Il lit la carte de A…
    assert client.get(f"/service/restaurants/{resto_a}/plats", headers=_svc(proprio_a)).status_code == 200
    # …mais B lui renvoie 404 (on ne divulgue pas le resto d'autrui).
    assert client.get(f"/service/restaurants/{resto_b}/plats", headers=_svc(proprio_a)).status_code == 404
    assert client.patch(f"/service/restaurants/{resto_b}", headers=_svc(proprio_a),
                        json={"nom": "pirate"}).status_code == 404
    # L'admin, lui, atteint A ET B.
    assert client.get(f"/service/restaurants/{resto_b}/plats", headers=_svc("admin")).status_code == 200


def test_service_compte_inconnu_403_http():
    """Clé valide mais X-Compte-Id inconnu → 403 (fail-closed)."""
    _, resto = _resto()
    assert client.get(f"/service/restaurants/{resto}/plats",
                      headers=_svc("compte-fantome")).status_code == 403


def test_service_setup_complet_par_admin():
    """Le flux setup à la voix : créer un resto → carte en lot → table → éditer → consulter."""
    stockage.ensure_admin("admin")
    # Créer un restaurant (setup).
    cree = client.post("/service/restaurants", headers=_svc("admin"),
                       json={"nom": "Chez Voix", "tva_taux": 10.0})
    assert cree.status_code == 200
    rid = cree.json()["id"]

    # Importer une carte en lot (les entrées sans nom sont ignorées).
    lot = client.post(f"/service/restaurants/{rid}/plats/lot", headers=_svc("admin"),
                      json={"plats": [{"nom": "Margherita", "prix_cents": 1200, "categorie": "Pizzas"},
                                      {"nom": "", "prix_cents": 0}]})
    assert lot.status_code == 200 and lot.json()["ajoutes"] == 1

    # Créer une table, la retrouver dans la liste, puis la supprimer.
    t = client.post(f"/service/restaurants/{rid}/tables", headers=_svc("admin"), json={"numero": "12"})
    assert t.status_code == 200
    tid = t.json()["id"]
    tables = client.get(f"/service/restaurants/{rid}/tables", headers=_svc("admin")).json()["tables"]
    assert any(x["id"] == tid for x in tables)
    assert client.delete(f"/service/restaurants/{rid}/tables/{tid}",
                         headers=_svc("admin")).json()["supprime"] is True

    # Éditer le restaurant (TVA).
    e = client.patch(f"/service/restaurants/{rid}", headers=_svc("admin"), json={"tva_taux": 5.5})
    assert e.status_code == 200 and e.json()["tva_taux"] == 5.5

    # Consultations (vides mais 200) + état rail HONNÊTE (non configuré en test).
    assert client.get(f"/service/restaurants/{rid}/tickets", headers=_svc("admin")).status_code == 200
    assert client.get(f"/service/restaurants/{rid}/avis", headers=_svc("admin")).status_code == 200
    assert client.get(f"/service/restaurants/{rid}/cuisine", headers=_svc("admin")).json()["commandes"] == []
    rail_etat = client.get(f"/service/restaurants/{rid}/rail", headers=_svc("admin"))
    assert rail_etat.status_code == 200 and rail_etat.json()["configure"] is False


def test_service_rail_activer_non_configure_honnete():
    """Sans rail configuré (PAIEMENTS_URL absent), activer renvoie 503 — pas de fausse promesse."""
    stockage.ensure_admin("admin")
    rid = client.post("/service/restaurants", headers=_svc("admin"),
                      json={"nom": "Sans Rail"}).json()["id"]
    assert client.post(f"/service/restaurants/{rid}/rail/activer",
                       headers=_svc("admin")).status_code == 503


def test_service_cuisine_guard_commande_inconnue():
    """Statut/annulation sur une commande inconnue → 404 (wiring + garde de périmètre)."""
    stockage.ensure_admin("admin")
    rid = client.post("/service/restaurants", headers=_svc("admin"),
                      json={"nom": "Cuisine Test"}).json()["id"]
    assert client.post(f"/service/restaurants/{rid}/commandes/inexistante/statut",
                       headers=_svc("admin"), json={"statut": "prete"}).status_code == 404
    assert client.delete(f"/service/restaurants/{rid}/commandes/inexistante",
                         headers=_svc("admin")).status_code == 404


def test_service_generer_carte_valide_le_concept():
    """generer sans concept → 422 (garde d'entrée, sans appeler l'IA)."""
    stockage.ensure_admin("admin")
    rid = client.post("/service/restaurants", headers=_svc("admin"),
                      json={"nom": "Concept Vide"}).json()["id"]
    assert client.post(f"/service/restaurants/{rid}/carte/generer",
                       headers=_svc("admin"), json={"concept": "  "}).status_code == 422
