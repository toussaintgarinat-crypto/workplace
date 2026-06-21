"""S83 — répartition flexible de l'addition.

Couvre : la règle PURE de partage égal (`parts_egales` : somme exacte, résidu sur les
premières parts) et de plafonnement serveur (`montant_a_encaisser`), puis le flux client
bout-en-bout des trois modes (ma part / partage égal / montant libre) avec l'invariant
ANTI-SURPAIEMENT (on n'encaisse jamais plus que le reste global de la table). Le mode
historique « part » reste intact (rétrocompatibilité)."""
import uuid

from fastapi.testclient import TestClient

import domaine
import main

client = TestClient(main.app)


def _resto():
    email = f"repart-{uuid.uuid4().hex[:8]}@exemple.fr"
    r = client.post("/auth/inscription", json={
        "email": email, "mot_de_passe": "motdepasse1", "nom_restaurant": "Le Partage Juste"}).json()
    return r["session"], r["restaurant"]["id"]


def _h(s):
    return {"Authorization": f"Bearer {s}"}


def _plat(h, resto, **kw):
    return client.post(f"/restaurants/{resto}/plats", headers=h, json=kw).json()


def _table_a(total_cents):
    """Une table dont l'addition vaut exactement `total_cents` (un plat, un convive)."""
    session, resto = _resto()
    h = _h(session)
    plat = _plat(h, resto, nom="Menu", prix_cents=total_cents)
    code = client.post(f"/restaurants/{resto}/tables", headers=h, json={"numero": "1"}).json()["code"]
    client.post(f"/t/{code}/commander", json={"convive": "Léa", "plats": [
        {"plat_id": plat["id"], "quantite": 1}]})
    return code


# ── Domaine pur (sans I/O) ───────────────────────────────────────
def test_parts_egales_somme_exacte_et_residu_sur_les_premieres():
    assert domaine.parts_egales(1000, 3) == [334, 333, 333]
    assert sum(domaine.parts_egales(1000, 3)) == 1000           # jamais de centime orphelin
    assert domaine.parts_egales(4000, 4) == [1000, 1000, 1000, 1000]
    assert sum(domaine.parts_egales(997, 7)) == 997


def test_parts_egales_garde_fous():
    assert domaine.parts_egales(1000, 0) == [1000]              # 0 part → 1 part = le tout
    assert domaine.parts_egales(1000, -3) == [1000]
    assert domaine.parts_egales(-500, 3) == [0, 0, 0]           # total négatif borné à 0


def test_montant_a_encaisser_borne_au_reste_global():
    # « libre » : on demande plus que le reste → plafonné au reste.
    assert domaine.montant_a_encaisser(300, "libre", montant_cents=999) == 300
    assert domaine.montant_a_encaisser(300, "libre", montant_cents=100) == 100
    # « egal » : la plus grosse part, mais jamais au-delà du reste.
    assert domaine.montant_a_encaisser(332, "egal", total_cents=1000, parts=3) == 332
    assert domaine.montant_a_encaisser(1000, "egal", total_cents=1000, parts=3) == 334
    # « part » : le dû propre du convive, borné au reste.
    assert domaine.montant_a_encaisser(1000, "part", du_convive_cents=600) == 600
    # Table soldée → rien, quel que soit le mode.
    assert domaine.montant_a_encaisser(0, "libre", montant_cents=500) == 0


# ── Bout-en-bout : les trois modes via l'API client ──────────────
def test_partage_egal_tombe_juste_et_solde_la_table():
    code = _table_a(1000)
    montants = []
    for _ in range(3):
        r = client.post(f"/t/{code}/payer", json={"convive": "Léa", "mode": "egal", "parts": 3})
        assert r.status_code == 200
        montants.append(r.json()["paiement"]["montant_cents"])
    assert montants == [334, 334, 332]                          # le dernier absorbe le reliquat
    assert sum(montants) == 1000
    etat = client.get(f"/t/{code}/addition").json()
    assert etat["reste_cents"] == 0                             # table soldée pile

    # Plus rien à encaisser → 400 (idempotence).
    assert client.post(f"/t/{code}/payer",
                       json={"convive": "Léa", "mode": "egal", "parts": 3}).status_code == 400


def test_montant_libre_fait_descendre_le_reste():
    code = _table_a(1000)
    r = client.post(f"/t/{code}/payer", json={"convive": "Léa", "mode": "libre", "montant_cents": 700})
    assert r.json()["paiement"]["montant_cents"] == 700
    assert client.get(f"/t/{code}/addition").json()["reste_cents"] == 300


def test_anti_surpaiement_le_montant_libre_est_plafonne_au_reste():
    code = _table_a(1000)
    client.post(f"/t/{code}/payer", json={"convive": "Léa", "mode": "libre", "montant_cents": 700})
    # On tente de payer 999 alors qu'il ne reste que 300 → plafonné à 300.
    r = client.post(f"/t/{code}/payer", json={"convive": "Léa", "mode": "libre", "montant_cents": 999})
    assert r.json()["paiement"]["montant_cents"] == 300
    assert client.get(f"/t/{code}/addition").json()["reste_cents"] == 0


def test_contributeur_sans_consommation_est_regle_et_jamais_anonyme():
    # Le payeur ne donne pas de nom et n'a rien commandé : il CONTRIBUE au reste de la table.
    code = _table_a(1000)
    client.post(f"/t/{code}/payer", json={"convive": "", "mode": "libre", "montant_cents": 400})
    etat = client.get(f"/t/{code}/addition").json()
    contrib = next(c for c in etat["convives"] if c["paye_cents"] == 400 and c["du_cents"] == 0)
    assert contrib["convive"] == "Convive"        # normalisé, jamais une ligne vide
    assert contrib["regle"] is True               # a payé, ne doit rien → réglé, pas « en attente »
    assert etat["reste_cents"] == 600


def test_mode_part_reste_intact():
    code = _table_a(1500)
    # Sans mode → défaut « part » : règle tout le dû du convive.
    r = client.post(f"/t/{code}/payer", json={"convive": "Léa"})
    assert r.json()["paiement"]["montant_cents"] == 1500
    assert client.get(f"/t/{code}/addition").json()["reste_cents"] == 0
