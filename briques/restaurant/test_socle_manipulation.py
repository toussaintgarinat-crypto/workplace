"""S102 — manipulation directe : la brique sert le socle (menu contextuel + modale) et
le back-office le branche sur les cartes de plats (clic droit / appui long)."""
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


def test_socle_servi():
    """GET /manipulation_directe.js renvoie le socle en JavaScript, avec ses helpers."""
    r = client.get("/manipulation_directe.js")
    assert r.status_code == 200
    assert "javascript" in r.headers["content-type"]
    assert "attacherMenu" in r.text
    assert "function sortable" in r.text


def test_back_office_branche_le_menu():
    """Le back-office charge le socle et câble le menu contextuel sur les plats, sans
    prompt()/alert() natifs pour éditer (remplacés par la modale du socle)."""
    html = client.get("/").text
    assert '<script src="/manipulation_directe.js"></script>' in html
    assert "brancherMenusPlats" in html
    assert "menuPlat" in html
    # Actions S102 du menu plat.
    assert "dupliquerPlat" in html
    assert "basculerRupture" in html
    # Le data-id requis par le socle est posé sur chaque carte.
    assert 'class="plat ${(p.disponible && !p.epuise)?\'\':\'indispo\'}" data-id="${p.id}"' in html


def test_back_office_branche_le_cliquer_deposer():
    """S104 : le back-office câble le cliquer-déposer (sortable) pour réordonner les plats."""
    html = client.get("/").text
    assert "brancherDndPlats" in html
    assert "window.sortable" in html
    assert "/plats/reordonner" in html


def _resto():
    import uuid
    email = f"dnd-{uuid.uuid4().hex[:8]}@exemple.fr"
    r = client.post("/auth/inscription", json={
        "email": email, "mot_de_passe": "motdepasse1", "nom_restaurant": "Chez Drag"}).json()
    return {"Authorization": f"Bearer {r['session']}"}, r["restaurant"]["id"]


def test_reordonner_plats_persiste_l_ordre():
    """S104 — POST /plats/reordonner fixe `ordre` ; lister_plats reflète la nouvelle suite."""
    auth, resto = _resto()
    ids = []
    for nom in ("Alpha", "Bravo", "Charlie"):
        ids.append(client.post(f"/restaurants/{resto}/plats", headers=auth,
                               json={"nom": nom, "prix_cents": 500}).json()["id"])
    # Ordre initial = ordre de création.
    avant = [p["id"] for p in client.get(f"/restaurants/{resto}/plats", headers=auth).json()["plats"]]
    assert avant == ids
    # On inverse.
    nouvel_ordre = list(reversed(ids))
    r = client.post(f"/restaurants/{resto}/plats/reordonner", headers=auth, json={"ids": nouvel_ordre})
    assert r.status_code == 200
    apres = [p["id"] for p in client.get(f"/restaurants/{resto}/plats", headers=auth).json()["plats"]]
    assert apres == nouvel_ordre
