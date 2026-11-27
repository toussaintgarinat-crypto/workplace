import json
import os
import sys

import pytest
from fastapi.testclient import TestClient

import contrat_donnees as C
import main
import stockage_pont
import studio as S
import support as SUP

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
try:  # absent dans l'image Docker (pas de racine du dépôt) : seuls les tests du harnais sautent
    from shared.conformite_contrat import Refus, verifier_conformite  # noqa: E402
except ImportError:
    Refus = verifier_conformite = None
harnais = pytest.mark.skipif(verifier_conformite is None, reason="hors monorepo (image Docker)")

CLE = "cle-support-test"
client = TestClient(main.app)
H = {"X-Support-Key": CLE}


@pytest.fixture(autouse=True)
def volume_jetable(tmp_path, monkeypatch):
    r = str(tmp_path)
    for sous in ("profils", "comptes", "pont"):
        os.makedirs(os.path.join(r, sous))
    monkeypatch.setattr(S, "ATELIERS_DIR", r)
    monkeypatch.setattr(S, "PROFILS_DIR", os.path.join(r, "profils"))
    monkeypatch.setattr(S, "COMPTES_DIR", os.path.join(r, "comptes"))
    monkeypatch.setattr(stockage_pont, "ATELIERS_DIR", r)
    monkeypatch.setattr(stockage_pont, "PONT_DIR", os.path.join(r, "pont"))
    monkeypatch.setenv("STUDIO_SUPPORT_KEY", CLE)
    monkeypatch.delenv("STUDIO_KEY", raising=False)


def peupler(u):
    sid, pid = f"serie-{u}", f"profil-{u}"
    S._save({"id": sid, "titre": f"Série de {u}", "cree_par": u, "episodes": []})
    S._save_profil({"id": pid, "nom": f"Enfant de {u}", "cible": "6-8", "cree_par": u})
    S._ajouter_evenement(pid, {"type": "ecoute", "serie_id": sid})
    S._save_compte(u, {"nom_famille": f"Famille {u}"})
    stockage_pont.fixer_monde(sid, f"monde-{u}")


# ── Authentification dédiée ─────────────────────────────────────
def test_support_desactive_sans_cle_configuree(monkeypatch):
    monkeypatch.delenv("STUDIO_SUPPORT_KEY")
    r = client.post("/support/exporter", json={"utilisateur": "claire"}, headers=H)
    assert r.status_code == 503


def test_cle_fausse_ou_absente_401():
    assert client.post("/support/exporter", json={"utilisateur": "c"}).status_code == 401
    assert client.post("/support/exporter", json={"utilisateur": "c"},
                       headers={"X-Support-Key": "fausse"}).status_code == 401


def test_la_cle_studio_et_les_api_keys_n_ouvrent_pas_le_support(monkeypatch):
    monkeypatch.setenv("STUDIO_KEY", "cle-coeur")
    monkeypatch.setattr(main, "API_KEYS", {"cle-byo"})
    for k in ("cle-coeur", "cle-byo"):
        r = client.post("/support/exporter", json={"utilisateur": "claire"},
                        headers={"X-API-Key": k, "X-Support-Key": k})
        assert r.status_code == 401


@pytest.mark.parametrize("u", [" claire", "claire ", "claire\n"])
def test_utilisateur_avec_espaces_422_partout(u):
    assert client.post("/support/exporter", json={"utilisateur": u}, headers=H).status_code == 422
    assert client.post("/support/reinitialiser", json={"utilisateur": u, "empreinte": "e"},
                       headers=H).status_code == 422
    for route in ("verifier", "importer"):
        r = client.post(f"/support/{route}", content=b"x", headers={**H, "X-Utilisateur": u})
        assert r.status_code == 422 and r.json()["detail"] == "utilisateur invalide"


def test_utilisateur_vide_422():
    assert client.post("/support/exporter", json={"utilisateur": "  "}, headers=H).status_code == 422


# ── Routes ──────────────────────────────────────────────────────
def test_exporter_expose_les_metadonnees_en_entetes():
    peupler("claire")
    r = client.post("/support/exporter", json={"utilisateur": "claire"}, headers=H)
    assert r.status_code == 200
    assert json.loads(r.headers["x-comptages"])["series"] == 1
    meta, objets = C.lire_paquet(r.content, CLE.encode(), "studio", "claire", "1")
    assert r.headers["x-empreinte"] == meta["empreinte"] == C.empreinte(objets)


def test_verifier_route():
    peupler("claire")
    paquet = client.post("/support/exporter", json={"utilisateur": "claire"}, headers=H).content
    r = client.post("/support/verifier", content=paquet, headers={**H, "X-Utilisateur": "claire"})
    assert r.status_code == 200 and r.json()["ok"] is True


def test_verifier_paquet_falsifie_422_sans_donnee_perso():
    peupler("claire")
    paquet = client.post("/support/exporter", json={"utilisateur": "claire"}, headers=H).content
    mauvais = paquet[:20] + bytes([paquet[20] ^ 0xFF]) + paquet[21:]
    r = client.post("/support/verifier", content=mauvais, headers={**H, "X-Utilisateur": "claire"})
    assert r.status_code == 422 and r.json()["detail"] in {"illisible", "signature", "somme_controle"}


def test_reinitialiser_mauvaise_empreinte_409_et_rien_efface():
    peupler("claire")
    r = client.post("/support/reinitialiser",
                    json={"utilisateur": "claire", "empreinte": "faux"}, headers=H)
    assert r.status_code == 409
    assert os.path.exists(S._path("serie-claire"))


def test_importer_paquet_d_un_autre_utilisateur_422():
    peupler("claire")
    paquet = client.post("/support/exporter", json={"utilisateur": "claire"}, headers=H).content
    r = client.post("/support/importer", content=paquet, headers={**H, "X-Utilisateur": "marina"})
    assert r.status_code == 422 and r.json()["detail"] == "utilisateur"


def test_importer_conflit_409():
    peupler("marina")
    objets = {"series": [{"id": "serie-marina", "cree_par": "claire"}], "profils": [],
              "journaux": [], "comptes": [], "ponts": []}
    paquet = C.construire_paquet("studio", "claire", "1", objets, CLE.encode())
    r = client.post("/support/importer", content=paquet, headers={**H, "X-Utilisateur": "claire"})
    assert r.status_code == 409


def test_toutes_les_routes_refusent_cle_absente_fausse_ou_non_configuree(monkeypatch):
    appels = [
        lambda h: client.post("/support/exporter", json={"utilisateur": "c"}, headers=h),
        lambda h: client.post("/support/verifier", content=b"x", headers={**h, "X-Utilisateur": "c"}),
        lambda h: client.post("/support/reinitialiser",
                              json={"utilisateur": "c", "empreinte": "e"}, headers=h),
        lambda h: client.post("/support/importer", content=b"x", headers={**h, "X-Utilisateur": "c"}),
    ]
    for appel in appels:
        assert appel({}).status_code == 401
        assert appel({"X-Support-Key": "fausse"}).status_code == 401
    monkeypatch.delenv("STUDIO_SUPPORT_KEY")
    for appel in appels:
        assert appel(H).status_code == 503


# ── Conformité (harnais réutilisable) + mutation de l'isolation ─
class AdaptateurStudio:
    def peupler(self, u):
        peupler(u)

    def exporter(self, u):
        r = client.post("/support/exporter", json={"utilisateur": u}, headers=H)
        assert r.status_code == 200
        return r.content

    def etat(self, u):
        r = client.post("/support/exporter", json={"utilisateur": u}, headers=H)
        return json.loads(r.headers["x-comptages"]), r.headers["x-empreinte"]

    def reinitialiser(self, u, empreinte):
        r = client.post("/support/reinitialiser",
                        json={"utilisateur": u, "empreinte": empreinte}, headers=H)
        if r.status_code >= 400:
            raise Refus(r.json()["detail"])

    def importer(self, u, octets):
        r = client.post("/support/importer", content=octets, headers={**H, "X-Utilisateur": u})
        if r.status_code >= 400:
            raise Refus(r.json()["detail"])


@harnais
def test_studio_est_conforme_au_contrat():
    verifier_conformite(AdaptateurStudio())


@harnais
def test_mutation_filtre_utilisateur_neutralise_est_detecte(monkeypatch):
    """Si le filtre d'appartenance est neutralisé, le harnais DOIT échouer (sinon le test
    d'isolation ne protège rien)."""
    monkeypatch.setattr(SUP, "_appartient", lambda objet, utilisateur, serie: True)
    with pytest.raises(AssertionError) as exc:
        verifier_conformite(AdaptateurStudio())
    assert str(exc.value)


@harnais
def test_mutation_change_reellement_le_comportement(monkeypatch):
    """Avec le filtre neutralisé, l'export de claire CONTIENT la série de marina : la mutation
    agit vraiment, l'échec du harnais n'est pas accidentel."""
    peupler("claire")
    peupler("marina")
    monkeypatch.setattr(SUP, "_appartient", lambda objet, utilisateur, serie: True)
    paquet = client.post("/support/exporter", json={"utilisateur": "claire"}, headers=H).content
    _meta, objets = C.lire_paquet(paquet, CLE.encode(), "studio", "claire", "1")
    assert "serie-marina" in [s["id"] for s in objets["series"]]


def test_copie_de_la_bibliotheque_a_jour():
    source = os.path.join(os.path.dirname(__file__), "..", "..", "shared", "contrat_donnees.py")
    if not os.path.exists(source):
        pytest.skip("hors monorepo (image Docker)")
    with open(source, "rb") as a, open(C.__file__, "rb") as b:
        assert a.read() == b.read(), "relancer outils/sync_socle.sh"


def test_manifeste_declare_un_contrat_valide():
    chemin = os.path.join(os.path.dirname(__file__), "manifest.json")
    with open(chemin, encoding="utf-8") as f:
        bloc = json.load(f).get("contrat_donnees")
    assert C.valider_bloc_contrat(bloc) == []
    assert bloc["version_schema"] == SUP.VERSION_SCHEMA


def test_corps_trop_gros_413_sur_verifier_et_importer(monkeypatch):
    monkeypatch.setattr(main, "CORPS_SUPPORT_MAX", 100)
    for route in ("verifier", "importer"):
        r = client.post(f"/support/{route}", content=b"x" * 200, headers={**H, "X-Utilisateur": "claire"})
        assert r.status_code == 413, route
        assert r.json()["detail"] == "trop_gros"


def test_corps_borne_ne_masque_pas_le_401():
    r = client.post("/support/verifier", content=b"x" * 10, headers={"X-Utilisateur": "claire"})
    assert r.status_code == 401


@pytest.mark.parametrize("secret_env", ["STUDIO_KEY", "API_KEYS"])
def test_identite_egale_a_une_cle_secrete_refusee(monkeypatch, secret_env):
    monkeypatch.setenv(secret_env, "autre-cle-xyz, cle-secrete-123")
    cible = "cle-secrete-123" if secret_env == "API_KEYS" else "autre-cle-xyz, cle-secrete-123"
    r = client.post("/support/exporter", json={"utilisateur": cible}, headers=H)
    assert r.status_code == 422 and r.json()["detail"] == "identite_interdite"


def test_verifier_et_importer_exigent_l_entete_et_ignorent_la_query():
    for route in ("verifier", "importer"):
        r = client.post(f"/support/{route}?utilisateur=claire", content=b"x", headers=H)
        assert r.status_code == 422, route                       # la query ne suffit plus
        r = client.post(f"/support/{route}", content=b"x", headers={**H, "X-Utilisateur": "  "})
        assert r.status_code == 422, route


def test_importer_lit_l_utilisateur_dans_l_entete():
    peupler("claire")
    paquet = client.post("/support/exporter", json={"utilisateur": "claire"}, headers=H).content
    r = client.post("/support/verifier", content=paquet, headers={**H, "X-Utilisateur": "claire"})
    assert r.status_code == 200 and r.json()["ok"] is True
