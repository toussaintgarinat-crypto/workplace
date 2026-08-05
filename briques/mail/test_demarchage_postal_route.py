"""Démarchage POSTAL (parallèle à test_demarchage.py, email) : jamais de nom de
personne, registre par adresse, jamais d'envoi réel dans cette route."""
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


def test_prepare_courriers_personnalises_sans_nom():
    h = {"X-API-Key": "postal-perso"}
    r = client.post("/demarchage-postal/preparer", headers=h, json={
        "prospects": [{"adresse": "12 Rue des Lilas, Castres", "commune": "Castres",
                       "grade_dpe": "F"}],
        "gabarit": "Votre logement au {adresse} ({commune}) pourrait bénéficier de "
                   "panneaux solaires.",
        "expediteur": "Studio X — Solutions Solaires",
    })
    assert r.status_code == 201
    d = r.json()
    assert d["prepares"] == 1 and d["envoye"] is False
    c = d["courriers"][0]
    assert c["numero_contact"] == 1 and c["relance"] is False and c["token"]
    assert "{adresse}" not in c["adresse"]   # sanity : pas de gabarit non substitué


def test_contenu_du_courrier_ne_contient_jamais_nom():
    """Vérifie que le contenu du courrier généré ne contient JAMAIS de nom de personne.

    Le pipeline démarchage-postal ne substitue JAMAIS {nom} (aucune identité de propriétaire
    n'est accessible structurellement dans ce domaine légal). Ce test :
    1. Prépare un courrier avec un gabarit contenant {nom} en tant que PLACEHOLDER TEST,
    2. Récupère le contenu stocké via la brique storage,
    3. Vérifie que {nom} est resté INCHANGÉ dans le contenu (non remplacé),
    4. Vérifie aussi qu'aucun nom arbitraire (ex: "Jean Dupont") n'apparaît.
    """
    import hashlib
    import stockage

    api_key = "postal-contenu"
    h = {"X-API-Key": api_key}

    # Le tenant est dérivé via sha256 tronqué (même mécanisme que main.tenant_actuel)
    tenant = hashlib.sha256(api_key.encode()).hexdigest()[:16]

    # Préparer un courrier avec un gabarit contenant le placeholder {nom} comme TEST
    r = client.post("/demarchage-postal/preparer", headers=h, json={
        "prospects": [{
            "adresse": "4 Impasse du Moulin, Castres",
            "commune": "Castres"
        }],
        "gabarit": "Votre logement au {adresse} ({commune}) pourrait bénéficier d'aide. "
                   "Veuillez contacter {nom}.",
        "expediteur": "Studio X",
    }).json()

    assert r["prepares"] == 1, "Doit préparer exactement 1 courrier"
    courrier_id = r["courriers"][0]["courrier_id"]

    # Récupérer le contenu réel stocké (pas juste la réponse HTTP)
    courrier = stockage.lire_courrier(tenant, courrier_id)
    assert courrier is not None, f"Courrier {courrier_id} doit exister dans le stockage"

    contenu = courrier["contenu"]

    # Vérification 1 : {adresse} et {commune} ont été substitués
    assert "{adresse}" not in contenu, "Le placeholder {adresse} doit être substitué"
    assert "{commune}" not in contenu, "Le placeholder {commune} doit être substitué"
    assert "4 Impasse du Moulin, Castres" in contenu, "L'adresse doit apparaître substituée"
    assert "Castres" in contenu, "La commune doit apparaître substituée"

    # Vérification 2 : {nom} N'EST PAS substitué (reste tel quel)
    # Cela prouve structurellement qu'il n'existe aucun .replace("{nom}", ...) dans le pipeline
    assert "{nom}" in contenu, "Le placeholder {nom} doit rester INCHANGÉ (jamais substitué)"

    # Vérification 3 : aucun nom arbitraire n'apparaît (on n'aurait pas pu l'injecter)
    assert "Jean Dupont" not in contenu, "Aucun nom aléatoire ne doit apparaître"

    # Vérification bonus : le pied d'expéditeur (footer) doit être présent
    assert "Studio X" in contenu, "L'identité de l'expéditeur doit figurer en pied"


def test_refuse_sans_identite_expediteur():
    h = {"X-API-Key": "postal-noexp"}
    r = client.post("/demarchage-postal/preparer", headers=h, json={
        "prospects": [{"adresse": "1 Rue X"}], "gabarit": "G", "expediteur": "  "})
    assert r.status_code == 422


def test_saute_les_prospects_sans_adresse():
    h = {"X-API-Key": "postal-noadresse"}
    r = client.post("/demarchage-postal/preparer", headers=h, json={
        "prospects": [{"commune": "Castres"}, {"adresse": "2 Rue Y"}],
        "gabarit": "G", "expediteur": "Moi"}).json()
    assert r["prepares"] == 1 and r["ignores"]["sans_adresse"] == 1


def test_cadence_plafond_atteint():
    h = {"X-API-Key": "postal-cadence"}
    base = {"prospects": [{"adresse": "3 Rue Z"}], "gabarit": "G", "expediteur": "Moi",
            "max_contacts": 1, "cooldown_jours": 0}
    assert client.post("/demarchage-postal/preparer", headers=h, json=base).json()["prepares"] == 1
    r2 = client.post("/demarchage-postal/preparer", headers=h, json=base).json()
    assert r2["prepares"] == 0 and r2["ignores"]["cadence_atteinte"] == 1


def test_desinscrit_jamais_recontacte():
    h = {"X-API-Key": "postal-optout"}
    stockage_module = __import__("stockage")
    # Désinscription directe via la route registre (Task ultérieure du plan n'ajoute
    # pas de route dédiée /demarchage-postal/desinscrire dans ce plan — hors
    # périmètre, cf. Non-objectifs : seule la capture de réponse qualifie/désinscrit
    # via /repondre. On teste donc le cas via stockage directement.)
    import hashlib
    tenant = hashlib.sha256(b"postal-optout").hexdigest()[:16]
    stockage_module.demarchage_postal_desinscrire(tenant, "5 Rue Opt-Out")
    r = client.post("/demarchage-postal/preparer", headers=h, json={
        "prospects": [{"adresse": "5 Rue Opt-Out"}], "gabarit": "G", "expediteur": "Moi",
        "cooldown_jours": 0}).json()
    assert r["prepares"] == 0 and r["ignores"]["desinscrit"] == 1


def test_envoyer_depose_simule_et_change_le_statut():
    h = {"X-API-Key": "postal-envoyer"}
    prep = client.post("/demarchage-postal/preparer", headers=h, json={
        "prospects": [{"adresse": "6 Rue Envoi"}], "gabarit": "G", "expediteur": "Moi"
    }).json()
    courrier_id = prep["courriers"][0]["courrier_id"]
    r = client.post(f"/demarchage-postal/envoyer/{courrier_id}", headers=h)
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] is True and d["reel"] is False   # simulé, honnête


def test_envoyer_courrier_introuvable_404():
    h = {"X-API-Key": "postal-404"}
    r = client.post("/demarchage-postal/envoyer/inexistant", headers=h)
    assert r.status_code == 404


def test_envoyer_deux_fois_refuse():
    h = {"X-API-Key": "postal-double"}
    prep = client.post("/demarchage-postal/preparer", headers=h, json={
        "prospects": [{"adresse": "8 Rue Double"}], "gabarit": "G", "expediteur": "Moi"
    }).json()
    courrier_id = prep["courriers"][0]["courrier_id"]
    client.post(f"/demarchage-postal/envoyer/{courrier_id}", headers=h)
    r2 = client.post(f"/demarchage-postal/envoyer/{courrier_id}", headers=h)
    assert r2.status_code == 409


def test_envoyer_cloisonne_par_tenant():
    h = {"X-API-Key": "postal-proprio"}
    prep = client.post("/demarchage-postal/preparer", headers=h, json={
        "prospects": [{"adresse": "10 Rue Prive"}], "gabarit": "G", "expediteur": "Moi"
    }).json()
    courrier_id = prep["courriers"][0]["courrier_id"]
    r = client.post(f"/demarchage-postal/envoyer/{courrier_id}",
                    headers={"X-API-Key": "postal-voisin"})
    assert r.status_code == 404
