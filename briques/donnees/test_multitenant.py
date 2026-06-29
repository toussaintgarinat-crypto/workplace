"""S121 — scope par organisation de la brique donnees (prépa multi-tenant).

Vérifie l'isolation par `X-Org-ID`, le repli rétrocompatible « defaut » (sans en-tête),
et la migration d'une base d'avant S121 (table sans colonne org_id).

Auth désactivée (défaut) : le tenant vient de l'en-tête `X-Org-ID` (chemin S2S) ou de
« defaut ». Aucun Keycloak requis. Lancer : `python3 -m pytest test_multitenant.py`.
"""
import os
import sqlite3
import tempfile

import pytest
from fastapi.testclient import TestClient

import main


@pytest.fixture()
def client(tmp_path):
    """TestClient sur une base vierge et isolée par test."""
    db = tmp_path / "donnees.db"
    main.DB_PATH = str(db)
    main._init_db()
    with TestClient(main.app) as c:
        yield c


_BASE = "/apps/app1/entites/clients/enregistrements"


def test_isolation_par_org(client):
    # Org A crée un enregistrement.
    r = client.post(_BASE, json={"nom": "Alice"}, headers={"X-Org-ID": "orgA"})
    assert r.status_code == 201, r.text

    # Org B ne voit RIEN dans la même app/entité.
    r = client.get(_BASE, headers={"X-Org-ID": "orgB"})
    assert r.status_code == 200 and r.json() == []

    # Org A voit son enregistrement.
    r = client.get(_BASE, headers={"X-Org-ID": "orgA"})
    assert r.status_code == 200
    noms = [e["nom"] for e in r.json()]
    assert noms == ["Alice"]


def test_sans_entete_retombe_sur_defaut(client):
    # Écriture sans en-tête → tenant « defaut ».
    r = client.post(_BASE, json={"nom": "Sans-org"})
    assert r.status_code == 201
    # Relecture sans en-tête → visible (même tenant defaut).
    r = client.get(_BASE)
    assert [e["nom"] for e in r.json()] == ["Sans-org"]
    # … mais invisible pour une org nommée.
    r = client.get(_BASE, headers={"X-Org-ID": "orgA"})
    assert r.json() == []


def test_modifier_supprimer_scopes_par_org(client):
    rec = client.post(_BASE, json={"nom": "Bob"}, headers={"X-Org-ID": "orgA"}).json()
    rid = rec["_id"]

    # Une autre org ne peut NI modifier NI supprimer (404, pas de fuite).
    r = client.put(f"{_BASE}/{rid}", json={"nom": "Pirate"}, headers={"X-Org-ID": "orgB"})
    assert r.status_code == 404
    r = client.delete(f"{_BASE}/{rid}", headers={"X-Org-ID": "orgB"})
    assert r.status_code == 404

    # L'org propriétaire, si.
    r = client.put(f"{_BASE}/{rid}", json={"nom": "Bob2"}, headers={"X-Org-ID": "orgA"})
    assert r.status_code == 200 and r.json()["nom"] == "Bob2"
    r = client.delete(f"{_BASE}/{rid}", headers={"X-Org-ID": "orgA"})
    assert r.status_code == 204


def test_resume_et_export_scopes(client):
    client.post(_BASE, json={"nom": "A"}, headers={"X-Org-ID": "orgA"})
    client.post(_BASE, json={"nom": "B"}, headers={"X-Org-ID": "orgB"})
    # resume ne compte que l'org appelante.
    r = client.get("/apps/app1/resume", headers={"X-Org-ID": "orgA"})
    assert r.json()["entites"] == {"clients": 1}
    # export idem.
    r = client.get("/apps/app1/export", headers={"X-Org-ID": "orgB"})
    recs = r.json()["entites"]["clients"]
    assert [e["nom"] for e in recs] == ["B"]


def test_migration_base_pre_s121(tmp_path):
    """Une base d'avant S121 (table SANS org_id, avec des lignes) doit migrer : la
    colonne est ajoutée et les lignes existantes deviennent lisibles en tenant « defaut »."""
    db = tmp_path / "vieux.db"
    # Schéma pré-S121 (copie de l'ancien CREATE TABLE, sans org_id) + une ligne réelle.
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE enregistrements (id TEXT PRIMARY KEY, app_id TEXT NOT NULL, "
        "entite_id TEXT NOT NULL, donnees TEXT NOT NULL, date_creation TEXT NOT NULL, "
        "date_maj TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT INTO enregistrements VALUES ('r1','app1','clients','{\"nom\":\"Ancien\"}','t','t')"
    )
    conn.commit()
    conn.close()

    main.DB_PATH = str(db)
    main._init_db()  # migration : ALTER ADD COLUMN org_id DEFAULT 'defaut'

    cols = {r[1] for r in sqlite3.connect(str(db)).execute("PRAGMA table_info(enregistrements)")}
    assert "org_id" in cols

    with TestClient(main.app) as c:
        # La ligne pré-existante est servie au tenant « defaut » (sans en-tête).
        r = c.get(_BASE)
        assert [e["nom"] for e in r.json()] == ["Ancien"]
        # Et pas à une autre org.
        r = c.get(_BASE, headers={"X-Org-ID": "orgA"})
        assert r.json() == []


def test_init_db_idempotent(client):
    """Rejouer _init_db() (reconnexions, redémarrages) ne casse rien."""
    main._init_db()
    main._init_db()
    r = client.get(_BASE, headers={"X-Org-ID": "orgA"})
    assert r.status_code == 200
