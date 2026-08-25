"""Tests HTTP du routeur /federation (Sprint D) — même motif que les blocs
/spatial et /horloge de test_api.py (DB temporaire posée par conftest.py)."""
import importlib

from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


def test_federation_creer_et_lire():
    r = client.post("/federation", json={"nom": "F1"})
    assert r.status_code == 200
    fid = r.json()["id"]
    assert r.json()["nom"] == "F1"

    lu = client.get(f"/federation/{fid}")
    assert lu.status_code == 200
    assert lu.json()["pays"] == []
    assert lu.json()["adjacences"] == []


def test_federation_lire_introuvable_404():
    assert client.get("/federation/id-inconnu").status_code == 404


def test_federation_rattacher_puis_lire():
    fid = client.post("/federation", json={}).json()["id"]
    mid = client.post("/spatial/mondes", json={"nb_cellules": 10, "seed": 1}).json()["id"]

    r = client.post(f"/federation/{fid}/rattacher", json={"monde_id": mid, "nom": "France"})
    assert r.status_code == 200

    lu = client.get(f"/federation/{fid}").json()
    # Pas de `cle_api` dans la réponse HTTP (correctif revue finale, Critical) : c'est
    # la vraie clé d'authentification du propriétaire du pays — voir
    # main._federation_publique et le test multi-tenant en fin de fichier.
    assert lu["pays"] == [{"monde_id": mid, "nom": "France",
                            "rattache_le": lu["pays"][0]["rattache_le"]}]


def test_federation_rattacher_monde_introuvable_404():
    fid = client.post("/federation", json={}).json()["id"]
    assert client.post(f"/federation/{fid}/rattacher",
                        json={"monde_id": "inconnu"}).status_code == 404


def test_federation_rattacher_federation_introuvable_404():
    mid = client.post("/spatial/mondes", json={"nb_cellules": 10, "seed": 1}).json()["id"]
    assert client.post("/federation/id-inconnu/rattacher",
                        json={"monde_id": mid}).status_code == 404


def test_federation_detacher():
    fid = client.post("/federation", json={}).json()["id"]
    mid = client.post("/spatial/mondes", json={"nb_cellules": 10, "seed": 1}).json()["id"]
    client.post(f"/federation/{fid}/rattacher", json={"monde_id": mid})

    r = client.post(f"/federation/{fid}/detacher", json={"monde_id": mid})
    assert r.status_code == 200
    assert client.get(f"/federation/{fid}").json()["pays"] == []


def test_federation_adjacence():
    fid = client.post("/federation", json={}).json()["id"]
    m1 = client.post("/spatial/mondes", json={"nb_cellules": 10, "seed": 1}).json()["id"]
    m2 = client.post("/spatial/mondes", json={"nb_cellules": 10, "seed": 2}).json()["id"]
    client.post(f"/federation/{fid}/rattacher", json={"monde_id": m1})
    client.post(f"/federation/{fid}/rattacher", json={"monde_id": m2})

    r = client.post(f"/federation/{fid}/adjacence", json={"monde_id_a": m1, "monde_id_b": m2})
    assert r.status_code == 200

    lu = client.get(f"/federation/{fid}").json()
    assert len(lu["adjacences"]) == 1


def test_federation_adjacence_pays_non_membre_404():
    fid = client.post("/federation", json={}).json()["id"]
    m1 = client.post("/spatial/mondes", json={"nb_cellules": 10, "seed": 1}).json()["id"]
    client.post(f"/federation/{fid}/rattacher", json={"monde_id": m1})
    assert client.post(f"/federation/{fid}/adjacence",
                        json={"monde_id_a": m1, "monde_id_b": "inconnu"}).status_code == 404


def test_federation_adjacence_self_loop_rejetee_422():
    """Un pays adjacent à lui-même n'a pas de sens (défense en profondeur : le
    moteur de tick filtre déjà ce cas, mais autant le rejeter à la porte plutôt
    que de laisser une adjacence absurde entrer en base). 422 car c'est une
    requête malformée, pas une ressource absente/non autorisée — donc pas 404."""
    fid = client.post("/federation", json={}).json()["id"]
    m1 = client.post("/spatial/mondes", json={"nb_cellules": 10, "seed": 1}).json()["id"]
    client.post(f"/federation/{fid}/rattacher", json={"monde_id": m1})

    r = client.post(f"/federation/{fid}/adjacence", json={"monde_id_a": m1, "monde_id_b": m1})
    assert r.status_code == 422

    lu = client.get(f"/federation/{fid}").json()
    assert lu["adjacences"] == []


def test_federation_etat_population_agregee():
    fid = client.post("/federation", json={}).json()["id"]
    mid = client.post("/spatial/mondes", json={"nb_cellules": 10, "seed": 1}).json()["id"]
    client.post(f"/federation/{fid}/rattacher", json={"monde_id": mid})

    r = client.get(f"/federation/{fid}/etat")
    assert r.status_code == 200
    assert r.json() == {"federation_id": fid, "pays": [{"monde_id": mid, "population_vivante": 0}],
                         "population_totale": 0}


def test_federation_lister():
    fid = client.post("/federation", json={"nom": "Listee"}).json()["id"]
    noms = [f["nom"] for f in client.get("/federation").json()]
    assert "Listee" in noms


def test_federation_supprimer_ne_touche_pas_le_monde():
    fid = client.post("/federation", json={}).json()["id"]
    mid = client.post("/spatial/mondes", json={"nb_cellules": 10, "seed": 1}).json()["id"]
    client.post(f"/federation/{fid}/rattacher", json={"monde_id": mid})

    r = client.delete(f"/federation/{fid}")
    assert r.status_code == 204
    assert client.get(f"/federation/{fid}").status_code == 404
    assert client.get(f"/spatial/mondes/{mid}").status_code == 200


def test_supprimer_un_monde_le_retire_de_sa_federation():
    """Correctif revue finale (Important) : `DELETE /spatial/mondes/{id}` cascadait
    sur l'horloge mais pas sur `federation_pays`/`federation_adjacences` — un monde
    supprimé continuait d'apparaître comme pays membre, à jamais, avec ses
    adjacences (et les ticks le proposaient encore en destination)."""
    fid = client.post("/federation", json={}).json()["id"]
    m1 = client.post("/spatial/mondes", json={"nb_cellules": 10, "seed": 1}).json()["id"]
    m2 = client.post("/spatial/mondes", json={"nb_cellules": 10, "seed": 2}).json()["id"]
    client.post(f"/federation/{fid}/rattacher", json={"monde_id": m1})
    client.post(f"/federation/{fid}/rattacher", json={"monde_id": m2})
    client.post(f"/federation/{fid}/adjacence", json={"monde_id_a": m1, "monde_id_b": m2})

    assert client.delete(f"/spatial/mondes/{m1}").status_code == 204

    lu = client.get(f"/federation/{fid}").json()
    assert [p["monde_id"] for p in lu["pays"]] == [m2]
    assert lu["adjacences"] == []
    # l'autre pays, lui, est intact
    assert client.get(f"/spatial/mondes/{m2}").status_code == 200


def test_federation_supprimer_introuvable_404():
    assert client.delete("/federation/id-inconnu").status_code == 404


def test_federation_cloisonnement_rattacher_exige_proprietaire_du_pays(monkeypatch):
    monkeypatch.setenv("API_KEYS", "cle-x,cle-y")
    importlib.reload(main)
    c = TestClient(main.app)
    fid = c.post("/federation", json={}, headers={"X-API-Key": "cle-x"}).json()["id"]
    mid = c.post("/spatial/mondes", json={"nb_cellules": 10, "seed": 1},
                 headers={"X-API-Key": "cle-y"}).json()["id"]
    # cle-x (créatrice de la fédération) essaie de rattacher un pays de cle-y : refusé
    r = c.post(f"/federation/{fid}/rattacher", json={"monde_id": mid},
               headers={"X-API-Key": "cle-x"})
    assert r.status_code == 404
    # cle-y (propriétaire du pays) peut le rattacher elle-même
    r2 = c.post(f"/federation/{fid}/rattacher", json={"monde_id": mid},
                headers={"X-API-Key": "cle-y"})
    assert r2.status_code == 200
    monkeypatch.delenv("API_KEYS", raising=False)
    importlib.reload(main)
    global client
    client = TestClient(main.app)  # resynchronise, même motif que test_api.py


def test_federation_multi_cle_api_visible_par_les_membres(monkeypatch):
    """Une fédération peut mélanger des cle_api différentes (voir design) : le
    créateur ET tout propriétaire d'un pays membre peuvent la voir, un tiers non
    plante en 404."""
    monkeypatch.setenv("API_KEYS", "cle-x,cle-y,cle-z")
    importlib.reload(main)
    c = TestClient(main.app)
    fid = c.post("/federation", json={}, headers={"X-API-Key": "cle-x"}).json()["id"]
    mid = c.post("/spatial/mondes", json={"nb_cellules": 10, "seed": 1},
                 headers={"X-API-Key": "cle-y"}).json()["id"]
    c.post(f"/federation/{fid}/rattacher", json={"monde_id": mid}, headers={"X-API-Key": "cle-y"})

    assert c.get(f"/federation/{fid}", headers={"X-API-Key": "cle-x"}).status_code == 200  # créatrice
    assert c.get(f"/federation/{fid}", headers={"X-API-Key": "cle-y"}).status_code == 200  # membre
    assert c.get(f"/federation/{fid}", headers={"X-API-Key": "cle-z"}).status_code == 404  # tiers
    monkeypatch.delenv("API_KEYS", raising=False)
    importlib.reload(main)
    global client
    client = TestClient(main.app)


def test_federation_adjacence_exige_etre_membre_pas_seulement_createur(monkeypatch):
    monkeypatch.setenv("API_KEYS", "cle-x,cle-y")
    importlib.reload(main)
    c = TestClient(main.app)
    fid = c.post("/federation", json={}, headers={"X-API-Key": "cle-x"}).json()["id"]
    m1 = c.post("/spatial/mondes", json={"nb_cellules": 10, "seed": 1},
                headers={"X-API-Key": "cle-y"}).json()["id"]
    m2 = c.post("/spatial/mondes", json={"nb_cellules": 10, "seed": 2},
                headers={"X-API-Key": "cle-y"}).json()["id"]
    c.post(f"/federation/{fid}/rattacher", json={"monde_id": m1}, headers={"X-API-Key": "cle-y"})
    c.post(f"/federation/{fid}/rattacher", json={"monde_id": m2}, headers={"X-API-Key": "cle-y"})

    # cle-x est créatrice mais possède 0 pays dans cette fédération → pas "membre"
    r = c.post(f"/federation/{fid}/adjacence", json={"monde_id_a": m1, "monde_id_b": m2},
               headers={"X-API-Key": "cle-x"})
    assert r.status_code == 404
    r2 = c.post(f"/federation/{fid}/adjacence", json={"monde_id_a": m1, "monde_id_b": m2},
                headers={"X-API-Key": "cle-y"})
    assert r2.status_code == 200
    monkeypatch.delenv("API_KEYS", raising=False)
    importlib.reload(main)
    global client
    client = TestClient(main.app)


def _cles_api_presentes(noeud) -> list[str]:
    """Récursif : tout nom de champ `cle_api`/`createur_cle_api` trouvé À N'IMPORTE
    QUEL niveau d'imbrication de la réponse JSON."""
    trouves = []
    if isinstance(noeud, dict):
        for k, v in noeud.items():
            if k in ("cle_api", "createur_cle_api"):
                trouves.append(k)
            trouves.extend(_cles_api_presentes(v))
    elif isinstance(noeud, list):
        for v in noeud:
            trouves.extend(_cles_api_presentes(v))
    return trouves


def test_federation_ne_renvoie_jamais_les_cles_api_brutes(monkeypatch):
    """Correctif revue finale (Critical) : `GET /federation/{id}` et `GET /federation`
    renvoyaient `createur_cle_api` et le `cle_api` de chaque pays — les VRAIES clés
    d'authentification (`X-API-Key`). Une fédération étant multi-tenant par
    construction, n'importe quel membre pouvait donc lire la clé du créateur ou d'un
    autre membre et usurper complètement ce tenant.

    Scénario réel à 2 tenants : `cle-x` crée la fédération, `cle-y` y rattache SON
    pays. Aucune des deux réponses, lue par l'un ou l'autre, ne doit contenir de
    champ `cle_api`/`createur_cle_api` — ni la valeur brute d'une clé."""
    monkeypatch.setenv("API_KEYS", "cle-x,cle-y")
    importlib.reload(main)
    c = TestClient(main.app)

    creation = c.post("/federation", json={"nom": "Fuite"}, headers={"X-API-Key": "cle-x"})
    assert creation.status_code == 200
    assert _cles_api_presentes(creation.json()) == [], creation.json()
    fid = creation.json()["id"]

    mid = c.post("/spatial/mondes", json={"nb_cellules": 10, "seed": 1},
                 headers={"X-API-Key": "cle-y"}).json()["id"]
    assert c.post(f"/federation/{fid}/rattacher", json={"monde_id": mid, "nom": "Pays Y"},
                  headers={"X-API-Key": "cle-y"}).status_code == 200

    for lecteur in ("cle-x", "cle-y"):
        lu = c.get(f"/federation/{fid}", headers={"X-API-Key": lecteur})
        assert lu.status_code == 200
        assert _cles_api_presentes(lu.json()) == [], (lecteur, lu.json())
        assert "cle-x" not in lu.text and "cle-y" not in lu.text, (lecteur, lu.text)
        # le contenu légitime, lui, est bien là
        assert [p["monde_id"] for p in lu.json()["pays"]] == [mid]

        liste = c.get("/federation", headers={"X-API-Key": lecteur})
        assert liste.status_code == 200
        assert _cles_api_presentes(liste.json()) == [], (lecteur, liste.json())
        assert "cle-x" not in liste.text and "cle-y" not in liste.text, (lecteur, liste.text)
        assert fid in [f["id"] for f in liste.json()]

    # l'agrégat consenti (`/etat`) n'en a jamais contenu — vérifié explicitement
    etat = c.get(f"/federation/{fid}/etat", headers={"X-API-Key": "cle-y"})
    assert etat.status_code == 200
    assert _cles_api_presentes(etat.json()) == [], etat.json()

    monkeypatch.delenv("API_KEYS", raising=False)
    importlib.reload(main)
    global client
    client = TestClient(main.app)


def test_federation_supprimer_exige_le_createur(monkeypatch):
    monkeypatch.setenv("API_KEYS", "cle-x,cle-y")
    importlib.reload(main)
    c = TestClient(main.app)
    fid = c.post("/federation", json={}, headers={"X-API-Key": "cle-x"}).json()["id"]
    assert c.delete(f"/federation/{fid}", headers={"X-API-Key": "cle-y"}).status_code == 404
    assert c.delete(f"/federation/{fid}", headers={"X-API-Key": "cle-x"}).status_code == 204
    monkeypatch.delenv("API_KEYS", raising=False)
    importlib.reload(main)
    global client
    client = TestClient(main.app)
