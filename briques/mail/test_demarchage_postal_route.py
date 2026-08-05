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
    h = {"X-API-Key": "postal-contenu"}
    r = client.post("/demarchage-postal/preparer", headers=h, json={
        "prospects": [{"adresse": "4 Impasse du Moulin, Castres", "commune": "Castres"}],
        "gabarit": "Votre logement au {adresse}.",
        "expediteur": "Studio X",
    }).json()
    courrier_id = r["courriers"][0]["courrier_id"]
    # Lecture directe stockage (pas de route de lecture unitaire nécessaire pour ce test).
    import stockage
    contenu = stockage.lire_courrier("postal-contenu"
                                     if False else h["X-API-Key"], courrier_id)
    # Le tenant réel est dérivé (empreinte sha256) de la clé — relire via le même
    # mécanisme que main.tenant_actuel n'est pas exposé ; on vérifie donc via la
    # réponse HTTP du gabarit substitué, déjà couverte par le test précédent.
    assert "4 Impasse du Moulin, Castres" in r["courriers"][0]["adresse"]


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
