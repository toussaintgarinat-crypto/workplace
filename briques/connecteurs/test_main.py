"""Les routes de la brique connecteurs (S214).

⚠ Leçon S212, appliquée ici : un test de non-blocage écrit avec `TestClient` passe au vert
sur du code bloquant — le client synchrone attend de toute façon la réponse, et la boucle
d'événements qu'il faudrait observer n'est pas celle de l'application. Le fait que la sync
soit non bloquante n'est donc PAS affirmé par ces tests-là : il est tenu par
`test_la_sync_rend_la_main_avant_la_fin_du_transfert`, qui mesure le temps de réponse
pendant qu'un exécuteur lent tourne encore. Voir aussi briques/ingestion/test_ocr_non_bloquant.py.
"""
import asyncio
import json
import stat
import sys
import time

import pytest
from fastapi.testclient import TestClient

import main
import pont
import stockage


@pytest.fixture(autouse=True)
def _base_vierge():
    stockage.DB_CHEMIN.unlink(missing_ok=True)
    stockage.initialiser()
    yield


@pytest.fixture
def client():
    with TestClient(main.app) as c:
        yield c


@pytest.fixture
def executeur(tmp_path, monkeypatch):
    def fabriquer(code: str):
        script = tmp_path / "faux.py"
        script.write_text(code, encoding="utf-8")
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
        monkeypatch.setattr(pont, "PYTHON_PYAIRBYTE", sys.executable)
        monkeypatch.setattr(pont, "EXECUTEUR", str(script))
    return fabriquer


SYNC_OK = (
    "import sys, json\n"
    "sys.stdin.read()\n"
    "print(json.dumps({'ok': True, 'nb_enregistrements': 120, 'flux': ['issues'],\n"
    "                  'etats': {'issues': {'updated_at': '2026-07-28T10:00:00Z'}}}))\n"
)


def _creer(client, nom="mon-github"):
    r = client.post("/sources", json={
        "nom": nom, "connecteur": "source-github",
        "config": {"credentials": {"personal_access_token": "ghp_x"}},
        "flux": ["issues"]})
    assert r.status_code == 201, r.text
    return r.json()


async def _attendre_fin(sync_id, tenant="public", limite=5.0):
    debut = time.monotonic()
    while time.monotonic() - debut < limite:
        if stockage.sync_get(tenant, sync_id)["statut"] != "en_cours":
            return stockage.sync_get(tenant, sync_id)
        await asyncio.sleep(0.02)
    raise AssertionError("la sync n'a jamais été close")


# ── Santé ────────────────────────────────────────────────────────────────────

def test_sante(client):
    corps = client.get("/sante").json()
    assert corps["statut"] == "ok"
    assert "pont_pyairbyte" in corps


# ── Sources ──────────────────────────────────────────────────────────────────

def test_creer_puis_lister_une_source(client):
    _creer(client)
    sources = client.get("/sources").json()
    assert [s["nom"] for s in sources] == ["mon-github"]


def test_la_reponse_ne_contient_jamais_le_jeton(client):
    """Aucune route ne réexpose un identifiant tiers — pas même celle qui vient de le
    recevoir (elle serait relue par l'atelier, journalisée, mise en cache)."""
    r = client.post("/sources", json={
        "nom": "s", "connecteur": "source-github",
        "config": {"token": "ghp_TRES_SECRET"}, "flux": []})
    assert "ghp_TRES_SECRET" not in r.text
    assert r.json()["config"] == {"token": "(renseigné)"}
    assert "ghp_TRES_SECRET" not in client.get("/sources").text
    assert "ghp_TRES_SECRET" not in client.get(f"/sources/{r.json()['id']}").text


def test_nom_en_double_rend_409(client):
    _creer(client)
    assert client.post("/sources", json={"nom": "mon-github", "connecteur": "source-github",
                                         "config": {}, "flux": []}).status_code == 409


def test_source_inconnue_rend_404(client):
    assert client.get("/sources/999").status_code == 404
    assert client.delete("/sources/999").status_code == 404
    assert client.post("/sources/999/sync").status_code == 404
    assert client.patch("/sources/999/actif", json={"active": False}).status_code == 404


def test_sans_coffre_la_creation_rend_503_au_lieu_d_ecrire_en_clair(client, monkeypatch):
    monkeypatch.delenv("CONNECTEURS_ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("VAULT_SECRET", raising=False)
    r = client.post("/sources", json={"nom": "s", "connecteur": "source-github",
                                      "config": {"token": "x"}, "flux": []})
    assert r.status_code == 503
    assert "clair" in r.json()["detail"]


def test_basculer_actif(client):
    src = _creer(client)
    assert client.patch(f"/sources/{src['id']}/actif", json={"active": False}).json()["active"] is False
    assert stockage.sources_actives() == []


def test_lire_une_source_rend_ses_curseurs(client):
    src = _creer(client)
    stockage.enregistrer_etat(src["id"], "issues", {"updated_at": "2026-07-28T00:00:00Z"})
    detail = client.get(f"/sources/{src['id']}").json()
    assert detail["etats"] == [{"flux": "issues",
                                "curseur": {"updated_at": "2026-07-28T00:00:00Z"},
                                "maj_le": detail["etats"][0]["maj_le"]}]


def test_oublier_le_curseur_dit_ce_qu_il_ne_fait_pas(client):
    """Honnêteté : la route vide le miroir SQLite, pas le cache PyAirbyte. Elle doit le
    dire, sinon on croit avoir remis la source à zéro et la sync suivante détrompe."""
    src = _creer(client)
    stockage.enregistrer_etat(src["id"], "issues", {"n": 1})
    r = client.delete(f"/sources/{src['id']}/etat").json()
    assert r["curseurs_oublies"] == 1
    assert "complet=true" in r["note"]


# ── Syncs ────────────────────────────────────────────────────────────────────

def test_une_sync_va_au_bout_et_recopie_le_curseur(client, executeur):
    executeur(SYNC_OK)
    src = _creer(client)
    r = client.post(f"/sources/{src['id']}/sync")
    assert r.status_code == 202
    fini = asyncio.run(_attendre_fin(r.json()["id"]))
    assert (fini["statut"], fini["nb_enregistrements"]) == ("ok", 120)
    assert stockage.lire_etats(src["id"]) == {"issues": {"updated_at": "2026-07-28T10:00:00Z"}}


def test_un_echec_de_connecteur_est_range_dans_la_sync_pas_leve(client, executeur):
    executeur("import sys, json\n"
              "sys.stdin.read()\n"
              "print(json.dumps({'ok': False, 'erreur': 'ConnectorError: 401 Bad credentials'}))\n")
    src = _creer(client)
    sync_id = client.post(f"/sources/{src['id']}/sync").json()["id"]
    fini = asyncio.run(_attendre_fin(sync_id))
    assert fini["statut"] == "echec"
    assert "401 Bad credentials" in fini["erreur"]


def test_deux_demandes_de_sync_ne_font_pas_deux_syncs(client, executeur):
    """Idempotence (le manifeste l'annonce à l'horloge) : deux syncs concurrentes se
    battraient pour le même curseur."""
    executeur("import sys, time\nsys.stdin.read()\ntime.sleep(3)\n")
    src = _creer(client)
    premiere = client.post(f"/sources/{src['id']}/sync").json()
    seconde = client.post(f"/sources/{src['id']}/sync").json()
    assert seconde["id"] == premiere["id"]
    assert seconde["deja_en_cours"] is True


def test_la_sync_rend_la_main_avant_la_fin_du_transfert(client, executeur):
    """Non-blocage RÉELLEMENT mesuré : l'exécuteur dort 3 s, la route doit répondre bien
    avant. Le test échouerait si `_syncer` était attendu dans la route."""
    executeur("import sys, time\nsys.stdin.read()\ntime.sleep(3)\n")
    src = _creer(client)
    debut = time.monotonic()
    r = client.post(f"/sources/{src['id']}/sync")
    ecoule = time.monotonic() - debut
    assert r.status_code == 202
    assert ecoule < 1.0, f"la route a attendu le transfert ({ecoule:.1f} s)"
    assert r.json()["statut"] == "en_cours"


def test_le_drapeau_complet_est_transmis_au_connecteur(client, executeur, tmp_path):
    """`complet=true` doit arriver jusqu'à `force_full_refresh` — sinon la personne qui
    demande un plein obtient un delta, en silence."""
    trace = tmp_path / "job.json"
    executeur("import sys, json, pathlib\n"
              f"pathlib.Path({str(trace)!r}).write_text(sys.stdin.read())\n"
              "print(json.dumps({'ok': True, 'nb_enregistrements': 0, 'etats': {}}))\n")
    src = _creer(client)
    sync_id = client.post(f"/sources/{src['id']}/sync", json={"complet": True}).json()["id"]
    asyncio.run(_attendre_fin(sync_id))
    job = json.loads(trace.read_text())
    assert job["complet"] is True
    assert job["connecteur"] == "source-github"
    assert job["config"]["credentials"]["personal_access_token"] == "ghp_x"


def test_sync_inconnue_rend_404(client):
    assert client.get("/syncs/999").status_code == 404


def test_lister_les_syncs_accepte_ses_filtres(client):
    src = _creer(client)
    stockage.ouvrir_sync("public", src["id"])
    assert len(client.get("/syncs", params={"source_id": src["id"], "limite": 10}).json()) == 1
    assert client.get("/syncs", params={"source_id": 999}).json() == []


# ── Tâche horloge ────────────────────────────────────────────────────────────

def test_la_tache_horloge_lance_les_sources_actives_et_saute_les_eteintes(client, executeur):
    executeur(SYNC_OK)
    active = _creer(client, "actif")
    eteinte = _creer(client, "eteint")
    client.patch(f"/sources/{eteinte['id']}/actif", json={"active": False})
    rapport = client.post("/sync/executer").json()
    assert rapport["nb_sources_actives"] == 1
    assert rapport["syncs"][0]["source_id"] == active["id"]


def test_la_tache_horloge_ne_pretend_pas_que_les_syncs_ont_reussi(client, executeur):
    """Le Cœur coupe à 120 s : la route rend « j'ai lancé », pas « ça a marché ». Dire
    l'un pour l'autre installerait un faux vert quotidien dans le journal de l'horloge."""
    executeur("import sys, time\nsys.stdin.read()\ntime.sleep(3)\n")
    _creer(client)
    rapport = client.post("/sync/executer").json()
    assert rapport["syncs"][0]["statut"] == "en_cours"


def test_la_tache_horloge_ne_masque_pas_le_tenant_en_entier(client, executeur):
    """Le rapport part dans le journal de l'horloge, lisible au dashboard : on y met de
    quoi identifier une source, pas de quoi rejouer une identité."""
    executeur(SYNC_OK)
    _creer(client)
    rapport = client.post("/sync/executer").json()
    assert len(rapport["syncs"][0]["tenant_masque"]) <= 8


# ── Auth ─────────────────────────────────────────────────────────────────────

def test_fail_closed_quand_des_cles_sont_definies(client, monkeypatch):
    monkeypatch.setattr(main, "API_KEYS", {"bonne-cle"})
    assert client.get("/sources").status_code == 401
    assert client.get("/sources", headers={"X-API-Key": "mauvaise"}).status_code == 401
    assert client.get("/sources", headers={"X-API-Key": "bonne-cle"}).status_code == 200


def test_le_coeur_emprunte_l_identite_de_la_personne(client, monkeypatch):
    """Motif veille-info S185 : même clé pour tout le foyer, des sources séparées."""
    monkeypatch.setattr(main, "API_KEYS", {"cle-coeur"})
    monkeypatch.setenv("CONNECTEURS_KEY", "cle-coeur")
    entetes = {"X-API-Key": "cle-coeur"}
    client.post("/sources", headers={**entetes, "X-User-Id": "marina"},
                json={"nom": "s", "connecteur": "source-github", "config": {}, "flux": []})
    a_marina = client.get("/sources", headers={**entetes, "X-User-Id": "marina"}).json()
    a_toussaint = client.get("/sources", headers={**entetes, "X-User-Id": "toussaint"}).json()
    assert len(a_marina) == 1 and a_toussaint == []


def test_la_tache_horloge_est_fermee_par_son_jeton(client, monkeypatch):
    monkeypatch.setenv("CONNECTEURS_KEY", "jeton-horloge")
    assert client.post("/sync/executer").status_code == 401
    assert client.post("/sync/executer",
                       headers={"Authorization": "Bearer jeton-horloge"}).status_code == 200


# ── Démarrage ────────────────────────────────────────────────────────────────

def test_au_demarrage_les_syncs_orphelines_sont_declarees_interrompues():
    """Le `lifespan` doit vraiment appeler la reprise — pas seulement `stockage` la fournir."""
    stockage.initialiser()
    src = stockage.creer_source("public", "s", "source-github", {"t": "x"}, [])
    sid = stockage.ouvrir_sync("public", src["id"])
    with TestClient(main.app):
        pass
    assert stockage.sync_get("public", sid)["statut"] == "interrompue"


# ── venture_id (S230) ────────────────────────────────────────────────────────

def test_creer_source_avec_venture_id(client, executeur):
    r = client.post("/sources", json={
        "nom": "hubspot-client-a", "connecteur": "source-hubspot",
        "config": {"credentials": {"access_token": "x"}},
        "flux": ["contacts", "deals"], "venture_id": "vt-a"})
    assert r.status_code == 201
    assert r.json()["venture_id"] == "vt-a"


def test_creer_source_sans_venture_id_reste_optionnel(client, executeur):
    r = client.post("/sources", json={"nom": "sans-lien", "connecteur": "source-faker"})
    assert r.status_code == 201
    assert r.json()["venture_id"] is None


def test_patch_source_relie_a_une_venture(client, executeur):
    r = _creer(client)
    sid = r["id"]
    p = client.patch(f"/sources/{sid}", json={"venture_id": "vt-b"})
    assert p.status_code == 200
    assert p.json()["venture_id"] == "vt-b"


def test_venture_id_absent_des_capacites_du_manifeste():
    """`POST /sources`/`PATCH /sources/{id}` restent hors assistant — S230 ne change
    pas ce principe en ajoutant venture_id."""
    import json
    from pathlib import Path
    manifest = json.loads((Path(__file__).parent / "manifest.json").read_text())
    ecritures = {(c["methode"], c["chemin"]) for c in manifest.get("capacites", [])
                if c.get("action")}
    assert ("POST", "/sources") not in ecritures
    assert ("PATCH", "/sources/{source_id}") not in ecritures


def test_une_sync_reussie_declenche_le_mappeur_si_connecteur_mappable(client, executeur, monkeypatch):
    appele = []
    async def _faux_mapper(tenant, source_id, connecteur, sync_id, schema):
        appele.append((tenant, source_id, connecteur, sync_id, schema))
    monkeypatch.setattr(main.mappeurs, "mapper_apres_sync", _faux_mapper)

    executeur(SYNC_OK)
    r = client.post("/sources", json={
        "nom": "hubspot-a", "connecteur": "source-hubspot",
        "config": {"credentials": {"access_token": "x"}}, "flux": ["contacts", "deals"],
        "venture_id": "vt-a"})
    sid = r.json()["id"]
    sync = client.post(f"/sources/{sid}/sync").json()
    time.sleep(0.2)  # laisse `_syncer` (tâche de fond) se terminer
    assert len(appele) == 1
    assert appele[0][2] == "source-hubspot"


def test_une_sync_reussie_ne_declenche_rien_pour_un_connecteur_non_mappable(client, executeur, monkeypatch):
    # `_syncer` appelle `mapper_apres_sync` sans condition (Step 7) : c'est le
    # dispatcher lui-même (Step 3) qui filtre CRM/compta vs le reste. On laisse donc
    # le vrai `mapper_apres_sync` tourner et on vérifie qu'il ne descend jamais
    # jusqu'aux mappeurs concrets pour un connecteur hors périmètre (source-github) —
    # même test de fond que `test_mapper_apres_sync_connecteur_non_mappable_ne_fait_rien`
    # dans test_mappeurs.py, mais vérifié ici bout-en-bout via la vraie route HTTP.
    appele = []
    monkeypatch.setattr(main.mappeurs, "_mapper_crm", lambda *a: appele.append("crm"))
    monkeypatch.setattr(main.mappeurs, "_mapper_compta", lambda *a: appele.append("compta"))
    executeur(SYNC_OK)
    r = _creer(client)  # source-github, motif existant
    sid = r["id"]
    client.post(f"/sources/{sid}/sync")
    time.sleep(0.2)
    assert appele == []


def test_un_mappeur_qui_leve_ne_fait_pas_echouer_la_sync(client, executeur, monkeypatch):
    async def _casse(*a):
        raise RuntimeError("boom")
    monkeypatch.setattr(main.mappeurs, "mapper_apres_sync", _casse)
    executeur(SYNC_OK)
    r = client.post("/sources", json={
        "nom": "hubspot-b", "connecteur": "source-hubspot",
        "config": {}, "flux": ["contacts"], "venture_id": "vt-b"})
    sid = r.json()["id"]
    sync = client.post(f"/sources/{sid}/sync").json()
    time.sleep(0.2)
    fini = client.get(f"/syncs/{sync['id']}").json()
    assert fini["statut"] == "ok"  # la sync elle-même n'a jamais vu passer l'exception
