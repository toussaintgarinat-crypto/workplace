"""Parcours objets : R*Tree synchronisé (triggers), filtres, troncature — via l'API."""
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

import main
import stockage

client = TestClient(main.app)

# Castres et alentours : bbox de travail des tests.
BBOX_TARN = "43.55,2.10,43.70,2.35"
CASTRES = {"latitude": 43.606, "longitude": 2.24}


def _il_y_a(jours: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=jours)).isoformat()


def test_module_rtree_disponible():
    """Garde d'infra : le sqlite3 embarqué doit compiler le R*Tree (vrai sur macOS
    et sur python:3.12-slim ; si ça casse, la brique entière est à revoir)."""
    assert stockage.rtree_disponible()


def test_creer_puis_trouver_dans_la_bbox():
    r = client.post("/objets", json={**CASTRES, "date_reference": _il_y_a(5),
                                     "metadata": {"nom": "Boulangerie Test", "naf": "1071C"}})
    assert r.status_code == 201
    assert r.json()["source"] == "manuel"
    dedans = client.get("/objets", params={"bbox": BBOX_TARN}).json()
    assert any(o["metadata"].get("nom") == "Boulangerie Test" for o in dedans["objets"])
    ailleurs = client.get("/objets", params={"bbox": "48.8,2.2,48.9,2.5"}).json()  # Paris
    assert all(o["metadata"].get("nom") != "Boulangerie Test" for o in ailleurs["objets"])


def test_upsert_resynchronise_le_rtree_au_deplacement():
    tenant = "public"
    obj, nouveau = stockage.upsert_objet(tenant, type_="entreprise", ref_externe="123456789",
                                         latitude=43.606, longitude=2.24,
                                         metadata={"nom": "Mobile SARL"})
    assert nouveau
    # Le siège déménage à Paris : même SIREN → mise à jour, pas de doublon.
    maj, nouveau2 = stockage.upsert_objet(tenant, type_="entreprise", ref_externe="123456789",
                                          latitude=48.853, longitude=2.35,
                                          metadata={"nom": "Mobile SARL"})
    assert not nouveau2 and maj["id"] == obj["id"]
    tarn = stockage.chercher_bbox(tenant, (43.55, 2.10, 43.70, 2.35))
    assert all(o["id"] != obj["id"] for o in tarn["objets"])
    paris = stockage.chercher_bbox(tenant, (48.8, 2.2, 48.9, 2.5))
    assert any(o["id"] == obj["id"] for o in paris["objets"])


def test_filtres_type_naf_et_texte():
    client.post("/objets", json={**CASTRES, "type": "evenement",
                                 "metadata": {"nom": "Marché de nuit"}})
    client.post("/objets", json={**CASTRES, "metadata": {"nom": "Garage Dupont", "naf": "4520A"}})
    evenements = client.get("/objets", params={"bbox": BBOX_TARN, "type": "evenement"}).json()
    assert {o["type"] for o in evenements["objets"]} == {"evenement"}
    naf = client.get("/objets", params={"bbox": BBOX_TARN, "naf": "4520"}).json()
    assert all(o["metadata"]["naf"].startswith("4520") for o in naf["objets"])
    texte = client.get("/objets", params={"bbox": BBOX_TARN, "q": "dupont"}).json()
    assert any("Dupont" in o["metadata"].get("nom", "") for o in texte["objets"])


def test_filtre_fraicheur_rouge_ne_garde_que_les_recents():
    client.post("/objets", json={**CASTRES, "date_reference": _il_y_a(5),
                                 "metadata": {"nom": "Toute neuve"}})
    client.post("/objets", json={**CASTRES, "date_reference": _il_y_a(200),
                                 "metadata": {"nom": "Vieille maison"}})
    rouges = client.get("/objets", params={"bbox": BBOX_TARN, "fraicheur": "rouge"}).json()
    noms = [o["metadata"].get("nom") for o in rouges["objets"]]
    assert "Toute neuve" in noms and "Vieille maison" not in noms
    assert all(o["fraicheur"] == "rouge" for o in rouges["objets"])


def test_fraicheur_calculee_dans_chaque_reponse():
    client.post("/objets", json={**CASTRES, "date_reference": _il_y_a(45),
                                 "metadata": {"nom": "Quarante-cinq jours"}})
    res = client.get("/objets", params={"bbox": BBOX_TARN, "q": "Quarante-cinq"}).json()
    assert res["objets"] and res["objets"][0]["fraicheur"] == "orange"


def test_limite_et_troncature_annoncee():
    for i in range(5):
        client.post("/objets", json={"latitude": 43.60 + i * 0.001, "longitude": 2.24,
                                     "metadata": {"nom": f"Série {i}"}})
    res = client.get("/objets", params={"bbox": BBOX_TARN, "limite": 3}).json()
    assert len(res["objets"]) == 3
    assert res["nb_total"] >= 5 and res["tronque"] is True


def test_bbox_invalide_renvoie_400():
    assert client.get("/objets", params={"bbox": "n-importe-quoi"}).status_code == 400
    assert client.get("/objets", params={"bbox": "43.7,2.0,43.5,2.4"}).status_code == 400


def test_point_hors_bornes_renvoie_400():
    r = client.post("/objets", json={"latitude": 95.0, "longitude": 2.24})
    assert r.status_code == 400
