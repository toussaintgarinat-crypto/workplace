"""Parcours cagnotte universelle par ID (S166) en mode MOCK honnête : créer une cagnotte,
la remplir en ligne (via le rail) ET par la caisse (« client réfractaire »), voir le reste
descendre, anti-surpaiement, cloisonnement tenant, annulation."""
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)
H = {"X-API-Key": "solution-cagnotte"}
AUTRE = {"X-API-Key": "un-autre-tenant"}


def _compte_actif():
    """Un vendeur onboardé (peut encaisser) pour recevoir les contributions en ligne."""
    compte = client.post("/comptes-connectes", headers=H, json={"nom": "Chez Léa"}).json()
    client.get(f"/demo/onboarding/{compte['id']}")   # active le compte (mock)
    return compte


def _cagnotte(cible=5000, avec_compte=True, commission_bps=0):
    corps = {"montant_cible_cents": cible, "description": "Table 12",
             "commission_bps": commission_bps}
    if avec_compte:
        corps["compte_connecte_id"] = _compte_actif()["id"]
    return client.post("/cagnottes", headers=H, json=corps).json()


def test_creer_cagnotte_expose_cible_et_reste():
    cag = _cagnotte(cible=5000)
    assert cag["cible_cents"] == 5000 and cag["solde_cents"] == 0
    assert cag["reste_cents"] == 5000 and cag["statut"] == "ouverte"


def test_cible_invalide_refusee():
    r = client.post("/cagnottes", headers=H, json={"montant_cible_cents": 0})
    assert r.status_code == 400


def test_vue_publique_ne_fuite_pas_le_tenant():
    cag = _cagnotte()
    pub = client.get(f"/cagnottes/{cag['id']}/public").json()   # sans clé API
    assert pub["reste_cents"] == 5000
    assert "solution" not in pub and "contributions" not in pub and "compte_id" not in pub


def test_contribution_en_ligne_via_le_rail_fait_baisser_le_reste():
    cag = _cagnotte(cible=5000, commission_bps=250)
    rep = client.post(f"/cagnottes/{cag['id']}/contribuer",
                      json={"montant_cents": 2000, "nom": "Marc"}).json()
    assert rep["paiement"]["statut"] == "paye" and rep["paiement"]["mode"] == "mock"
    assert rep["paiement"]["commission_cents"] == 50          # 2,5 % de 20 €
    assert rep["cagnotte"]["solde_cents"] == 2000 and rep["cagnotte"]["reste_cents"] == 3000


def test_client_refractaire_pos_fait_baisser_le_reste_sans_flux():
    cag = _cagnotte(cible=5000)
    rep = client.post(f"/cagnottes/{cag['id']}/pos", headers=H,
                      json={"montant_cents": 1500, "source": "caisse"}).json()
    assert rep["contribution"]["sorte"] == "externe"
    assert rep["cagnotte"]["solde_cents"] == 1500 and rep["cagnotte"]["reste_cents"] == 3500
    assert "HORS rail" in rep["message"]


def test_melange_en_ligne_et_caisse_solde_la_cagnotte():
    cag = _cagnotte(cible=5000)
    client.post(f"/cagnottes/{cag['id']}/pos", headers=H, json={"montant_cents": 3000})
    client.post(f"/cagnottes/{cag['id']}/contribuer", json={"montant_cents": 2000})
    pub = client.get(f"/cagnottes/{cag['id']}/public").json()
    assert pub["solde_cents"] == 5000 and pub["reste_cents"] == 0
    assert pub["statut"] == "atteinte"


def test_anti_surpaiement_borne_au_reste():
    cag = _cagnotte(cible=5000)
    client.post(f"/cagnottes/{cag['id']}/pos", headers=H, json={"montant_cents": 4000})
    # On tente 3000 alors qu'il ne reste que 1000 en ligne → borné à 1000, pas plus.
    rep = client.post(f"/cagnottes/{cag['id']}/contribuer", json={"montant_cents": 3000}).json()
    assert rep["contribution"]["montant_cents"] == 1000
    assert rep["cagnotte"]["reste_cents"] == 0


def test_cagnotte_atteinte_refuse_toute_contribution():
    cag = _cagnotte(cible=2000)
    client.post(f"/cagnottes/{cag['id']}/pos", headers=H, json={"montant_cents": 2000})
    assert client.post(f"/cagnottes/{cag['id']}/pos", headers=H,
                       json={"montant_cents": 500}).status_code == 409
    assert client.post(f"/cagnottes/{cag['id']}/contribuer",
                       json={"montant_cents": 500}).status_code == 409


def test_cagnotte_sans_compte_accepte_pos_mais_pas_en_ligne():
    cag = _cagnotte(cible=5000, avec_compte=False)
    # Pas de compte vendeur → paiement en ligne impossible (409), mais la caisse marche.
    assert client.post(f"/cagnottes/{cag['id']}/contribuer",
                       json={"montant_cents": 1000}).status_code == 409
    r = client.post(f"/cagnottes/{cag['id']}/pos", headers=H, json={"montant_cents": 1000})
    assert r.status_code == 201 and r.json()["cagnotte"]["solde_cents"] == 1000


def test_annuler_ferme_les_contributions():
    cag = _cagnotte(cible=5000)
    assert client.post(f"/cagnottes/{cag['id']}/annuler", headers=H).json()["statut"] == "annulee"
    assert client.post(f"/cagnottes/{cag['id']}/pos", headers=H,
                       json={"montant_cents": 500}).status_code == 409


def test_cloisonnement_tenant():
    cag = _cagnotte()
    # Un autre tenant ne voit pas la cagnotte (404, on ne révèle pas son existence).
    assert client.get(f"/cagnottes/{cag['id']}", headers=AUTRE).status_code == 404
    assert client.post(f"/cagnottes/{cag['id']}/pos", headers=AUTRE,
                       json={"montant_cents": 100}).status_code == 404
    # …mais elle apparaît bien pour son propriétaire.
    assert any(c["id"] == cag["id"] for c in client.get("/cagnottes", headers=H).json()["cagnottes"])
