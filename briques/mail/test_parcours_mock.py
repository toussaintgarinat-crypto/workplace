"""Parcours bout-en-bout en mode MOCK (boîte simulée, sans réseau ni LLM réel).

La Gateway est volontairement absente (GATEWAY_KEY retiré par conftest) : le résumé et le
brouillon doivent retomber sur le repli LOCAL honnête, jamais lever.
"""
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


def test_sante():
    r = client.get("/sante")
    assert r.status_code == 200 and r.json()["brique"] == "mail"


def test_config_mock_par_defaut():
    r = client.get("/config")
    assert r.status_code == 200
    j = r.json()
    assert j["configure"] is False and j["fournisseur"] == "mock"


def test_lister_trie_par_importance():
    r = client.get("/mail")
    assert r.status_code == 200
    j = r.json()
    assert j["total"] > 0 and j["non_lus"] > 0
    scores = [m["score"] for m in j["messages"]]
    assert scores == sorted(scores, reverse=True)  # déjà trié décroissant
    # Le client urgent doit primer la newsletter promo.
    sujets = [m["sujet"] for m in j["messages"]]
    assert sujets.index(next(s for s in sujets if "URGENT" in s)) < \
        sujets.index(next(s for s in sujets if "Soldes" in s or "-50%" in s))


def test_filtre_non_lus():
    total = client.get("/mail").json()["messages"]
    non_lus = client.get("/mail", params={"non_lus": True}).json()["messages"]
    assert 0 < len(non_lus) < len(total)
    assert all(not m["lu"] for m in non_lus)


def test_filtre_par_categorie_newsletter():
    r = client.get("/mail", params={"categorie": "newsletter"})
    assert r.status_code == 200
    j = r.json()
    assert j["categorie"] == "newsletter"
    assert len(j["messages"]) >= 1
    assert all(m["categorie"] == "newsletter" for m in j["messages"])


def test_filtre_categorie_synonyme_pub():
    # « pub » doit être compris comme la catégorie newsletter (pubs/promos).
    par_synonyme = client.get("/mail", params={"categorie": "pub"}).json()
    par_canon = client.get("/mail", params={"categorie": "newsletter"}).json()
    assert par_synonyme["categorie"] == "newsletter"
    assert len(par_synonyme["messages"]) == len(par_canon["messages"])


def test_filtre_categorie_inconnue_liste_tout():
    tout = client.get("/mail").json()["total"]
    bidon = client.get("/mail", params={"categorie": "n-importe-quoi"}).json()
    assert bidon["categorie"] is None and bidon["total"] == tout


def test_lire_message_complet():
    premier = client.get("/mail").json()["messages"][0]
    r = client.get(f"/mail/{premier['id']}")
    assert r.status_code == 200
    assert "corps" in r.json() and len(r.json()["corps"]) > 0


def test_lire_message_inexistant_404():
    assert client.get("/mail/inexistant").status_code == 404


def test_trier_par_categorie():
    r = client.post("/mail/trier")
    assert r.status_code == 200
    groupes = r.json()["groupes"]
    assert "facture" in groupes and "rendez_vous" in groupes
    assert "etiquette" in groupes["facture"]


def test_resumer_repli_local_honnete():
    # Gateway absente → genere_par doit être "local", sans lever.
    r = client.post("/mail/resumer", json={"lang": "fr"})
    assert r.status_code == 200
    j = r.json()
    assert j["genere_par"] == "local"
    assert "non lu" in j["texte"] or "message" in j["texte"]


def test_brouillon_prepare_mais_non_envoye():
    premier = client.get("/mail").json()["messages"][0]
    r = client.post("/mail/brouillon", json={"message_id": premier["id"]})
    assert r.status_code == 201
    j = r.json()
    assert j["envoye"] is False
    assert j["brouillon"]["sujet"].lower().startswith("re:")
    assert j["genere_par"] == "local"  # pas de LLM → repli
    # Le brouillon est rangé, consultable.
    assert any(b["id"] == j["brouillon"]["id"] for b in client.get("/brouillons").json()["brouillons"])


def test_connecter_compte_identifiants_faux_echoue_proprement():
    # Aucun vrai serveur : la connexion IMAP doit échouer en 400 et NE RIEN garder.
    r = client.post("/comptes", json={"host": "imap.invalide.test", "utilisateur": "x@y.fr",
                                      "mot_de_passe": "faux", "port": 993})
    assert r.status_code == 400
    assert client.get("/config").json()["fournisseur"] == "mock"  # toujours mock
