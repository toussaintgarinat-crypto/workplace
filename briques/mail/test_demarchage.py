"""Démarchage B2B (S170) : brouillons en lot personnalisés + conformité + cadence/opt-out.

Aucun envoi (on prépare seulement) et aucun réseau. Chaque test a sa propre clé API →
son propre tenant → un registre de démarchage vierge, indépendant de l'ordre d'exécution.
"""
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


def _corps_du_brouillon(h, brouillon_id):
    for b in client.get("/brouillons", headers=h).json()["brouillons"]:
        if b["id"] == brouillon_id:
            return b["corps"]
    return None


def test_prepare_brouillons_personnalises_et_conformes():
    h = {"X-API-Key": "dem-perso"}
    r = client.post("/demarchage/preparer", headers=h, json={
        "prospects": [{"email": "a@boulangerie.fr", "nom": "Marie",
                       "entreprise": "Boulangerie Marie", "ville": "Castres"}],
        "sujet": "Une idée pour {entreprise}",
        "message": "Bonjour {nom}, je vous écris au sujet de votre activité à {ville}.",
        "expediteur": "Jean Dupont — Studio X",
    })
    assert r.status_code == 201
    d = r.json()
    assert d["prepares"] == 1 and d["envoye"] is False
    br = d["brouillons"][0]
    assert br["sujet"] == "Une idée pour Boulangerie Marie"     # variable substituée
    assert br["numero_contact"] == 1 and br["relance"] is False
    corps = _corps_du_brouillon(h, br["brouillon_id"])
    assert "Bonjour Marie," in corps and "à Castres." in corps  # personnalisation
    assert "Jean Dupont — Studio X" in corps                    # identité expéditeur (LCEN)
    assert "STOP" in corps                                      # mention de désinscription


def test_refuse_sans_identite_expediteur():
    h = {"X-API-Key": "dem-noexp"}
    r = client.post("/demarchage/preparer", headers=h, json={
        "prospects": [{"email": "x@y.fr"}], "sujet": "S", "message": "M", "expediteur": "  "})
    assert r.status_code == 422


def test_saute_les_prospects_sans_email():
    h = {"X-API-Key": "dem-noemail"}
    r = client.post("/demarchage/preparer", headers=h, json={
        "prospects": [{"nom": "Sans Email"}, {"email": "ok@y.fr", "nom": "Bon"}],
        "sujet": "S", "message": "M", "expediteur": "Moi"}).json()
    assert r["prepares"] == 1 and r["ignores"]["sans_email"] == 1


def test_cadence_plafond_atteint():
    h = {"X-API-Key": "dem-cadence"}
    base = {"prospects": [{"email": "cible@y.fr"}], "sujet": "S", "message": "M",
            "expediteur": "Moi", "max_contacts": 1, "cooldown_jours": 0}
    assert client.post("/demarchage/preparer", headers=h, json=base).json()["prepares"] == 1
    # 2e passe : plafond de 1 contact déjà atteint → sauté (pas un envoi de plus).
    r2 = client.post("/demarchage/preparer", headers=h, json=base).json()
    assert r2["prepares"] == 0 and r2["ignores"]["cadence_atteinte"] == 1


def test_cooldown_bloque_un_recontact_trop_rapide():
    h = {"X-API-Key": "dem-cooldown"}
    base = {"prospects": [{"email": "cible@y.fr"}], "sujet": "S", "message": "M",
            "expediteur": "Moi", "max_contacts": 3, "cooldown_jours": 7}
    assert client.post("/demarchage/preparer", headers=h, json=base).json()["prepares"] == 1
    r2 = client.post("/demarchage/preparer", headers=h, json=base).json()
    assert r2["prepares"] == 0 and r2["ignores"]["trop_recent"] == 1


def test_relance_quand_le_cooldown_est_ecoule():
    h = {"X-API-Key": "dem-relance"}
    base = {"prospects": [{"email": "cible@y.fr", "nom": "Cible"}], "sujet": "S",
            "message": "M", "expediteur": "Moi", "max_contacts": 3, "cooldown_jours": 0}
    client.post("/demarchage/preparer", headers=h, json=base)
    r2 = client.post("/demarchage/preparer", headers=h, json=base).json()
    assert r2["prepares"] == 1
    assert r2["brouillons"][0]["numero_contact"] == 2 and r2["brouillons"][0]["relance"] is True


def test_desinscrit_jamais_recontacte():
    h = {"X-API-Key": "dem-optout"}
    assert client.post("/demarchage/desinscrire", headers=h,
                       json={"email": "STOP@y.fr"}).json()["email"] == "stop@y.fr"
    r = client.post("/demarchage/preparer", headers=h, json={
        "prospects": [{"email": "stop@y.fr"}], "sujet": "S", "message": "M",
        "expediteur": "Moi", "cooldown_jours": 0}).json()
    assert r["prepares"] == 0 and r["ignores"]["desinscrit"] == 1


def test_registre_transparence_et_isolation():
    h = {"X-API-Key": "dem-registre"}
    client.post("/demarchage/preparer", headers=h, json={
        "prospects": [{"email": "vu@y.fr"}], "sujet": "S", "message": "M", "expediteur": "Moi"})
    reg = client.get("/demarchage/registre", headers=h).json()["registre"]
    assert len(reg) == 1 and reg[0]["email"] == "vu@y.fr" and reg[0]["nb_contacts"] == 1
    # Un autre tenant ne voit pas ce registre.
    autre = client.get("/demarchage/registre", headers={"X-API-Key": "dem-voisin"}).json()
    assert autre["registre"] == []
