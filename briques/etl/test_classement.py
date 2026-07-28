"""S212 — le rangement d'un document, de bout en bout.

Le backlog du sprint annonçait que `PATCH /documents/{id}/classement` et `GET /dossiers`
étaient « inaccessibles en conversation, faute de capacité au manifeste ». **C'est faux** :
le Cœur les câble depuis S6 en outils `classer_document` / `lister_dossiers`
(`core/outils.py`, dispatch dans `core/outils_domaines/documents.py`). Les déclarer AUSSI
au manifeste aurait donné deux outils jumeaux à l'assistant pour le même geste.

Ce qui manquait vraiment, c'est la preuve que le geste ABOUTIT. `core/test_etl_cle_service.py`
ne vérifie que le port de la clé ; côté brique, `test_etl.py` ne couvre que le 404. Personne
ne vérifiait qu'un document classé se retrouve ensuite dans son dossier — or c'est exactement
le genre d'écart muet que S210 a trouvé partout ailleurs : l'appel réussit, et rien ne range.
"""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    import stockage
    monkeypatch.setattr(stockage, "DB_CHEMIN", tmp_path / "etl.db")
    from main import app
    with TestClient(app) as c:
        yield c


def _document(client, nom="devis.pdf"):
    return client.post("/documents/import",
                       json={"nom": nom, "texte_extrait": "Devis toiture, 12 000 €."}).json()["id"]


def test_un_document_classe_se_retrouve_dans_son_dossier(client):
    """Le critère de sortie du sprint : « ranger un document dans un projet », prouvé."""
    doc_id = _document(client)

    r = client.patch(f"/documents/{doc_id}/classement",
                     json={"categorie": "devis", "projet": "Toiture Martin",
                           "tags": ["urgent"], "entreprise_id": "liv-42"})
    assert r.status_code == 200

    dossiers = client.get("/dossiers").json()
    assert dossiers["projets"].get("Toiture Martin") == 1
    assert dossiers["categories"].get("devis") == 1

    listes = client.get("/documents", params={"projet": "Toiture Martin"}).json()["documents"]
    assert [d["id"] for d in listes] == [doc_id]
    assert listes[0]["classement"]["tags"] == ["urgent"]


def test_les_filtres_filtrent_vraiment(client):
    """Un filtre qui laisse tout passer est le défaut que S210 a trouvé sur cette route même.

    FastAPI ignore les query params inconnus sans broncher : un filtre mal branché renvoie
    la liste entière et l'assistant croit avoir filtré. On vérifie donc les deux sens.
    """
    range_id = _document(client, "range.pdf")
    _document(client, "vrac.pdf")          # jamais classé

    client.patch(f"/documents/{range_id}/classement", json={"projet": "Toiture Martin"})

    assert len(client.get("/documents").json()["documents"]) == 2
    retenus = client.get("/documents", params={"projet": "Toiture Martin"}).json()["documents"]
    assert [d["id"] for d in retenus] == [range_id]
    assert client.get("/documents", params={"projet": "Projet Inexistant"}).json()["documents"] == []


def test_un_second_classement_complete_le_premier_sans_l_effacer(client):
    """L'assistant range en plusieurs fois (« mets-le dans le projet », puis « c'est un devis »)."""
    doc_id = _document(client)

    client.patch(f"/documents/{doc_id}/classement", json={"projet": "Toiture Martin"})
    client.patch(f"/documents/{doc_id}/classement", json={"categorie": "devis"})

    classement = client.get(f"/documents/{doc_id}").json()["metadonnees"]["classement"]
    assert classement == {"projet": "Toiture Martin", "categorie": "devis"}


def test_un_document_non_classe_ne_pollue_aucun_dossier(client):
    """Sinon le tick proactif « documents à classer » compterait à côté."""
    _document(client, "vrac.pdf")
    assert client.get("/dossiers").json() == {"projets": {}, "categories": {}}
