"""Tests API (TestClient) : santé, liste, sonde/pret, réveil, keepalive, recharge, auth,
inscription et suppression dynamique de nœuds.

Le parc de test (conftest) pointe des ports loopback FERMÉS → les sondes échouent vite
et hors-ligne. Les sondes des tests d'inscription sont monkeypatché pour rester 100% offline.
"""
import importlib
import json as json_mod

from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


def test_sante():
    r = client.get("/sante")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True and data["service"] == "calcul"
    assert data["noeuds"] == 2
    assert set(data["etats"]) == {"muscle", "fixe"}


def test_lister_noeuds():
    r = client.get("/noeuds")
    assert r.status_code == 200
    noeuds = {n["id"]: n for n in r.json()["noeuds"]}
    assert noeuds["muscle"]["reveillable"] is True       # wakeping
    assert noeuds["fixe"]["reveillable"] is False         # aucun
    assert noeuds["fixe"]["endpoint"] == "http://127.0.0.1:59998"   # slash retiré


def test_pret_injoignable_mais_endormi():
    r = client.get("/noeuds/muscle/pret")
    assert r.status_code == 200
    data = r.json()
    assert data["pret"] is False and data["etat"] == "endormi"   # réveillable → endormi


def test_pret_noeud_fige_injoignable():
    r = client.get("/noeuds/fixe/pret")
    assert r.json()["etat"] == "injoignable"             # pas de réveil → injoignable


def test_pret_noeud_inconnu_404():
    assert client.get("/noeuds/fantome/pret").status_code == 404


def test_reveiller_echec_rapide():
    # methode_reveil=wakeping, timeout 0 → verdict négatif honnête sans boucler.
    r = client.post("/noeuds/muscle/reveiller")
    assert r.status_code == 200
    data = r.json()
    assert data["reveille"] is False and data["methode"] == "wakeping"
    assert data["id"] == "muscle"


def test_sonder_tous():
    r = client.post("/noeuds/sonder")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert set(data["sondes"]) == {"muscle", "fixe"}
    assert all(v is False for v in data["sondes"].values())


def test_lister_noeuds_ordre_priorite():
    # /noeuds reflète le parc ; muscle (priorité 10) avant fixe (50) à l'élection.
    noeuds = {n["id"]: n for n in client.get("/noeuds").json()["noeuds"]}
    assert noeuds["muscle"]["priorite"] == 10
    assert noeuds["muscle"]["modele_gateway"] == "ollama/llama3.3"


def test_muscle_aucun_dispo_hors_ligne():
    # Les deux nœuds pointent des ports fermés → aucun muscle, repli honnête.
    r = client.get("/muscle")
    assert r.status_code == 200
    data = r.json()
    assert data["disponible"] is False
    # Le pool reste listé, trié par priorité (muscle avant fixe).
    assert [n["id"] for n in data["noeuds"]] == ["muscle", "fixe"]


def test_recharger():
    r = client.post("/noeuds/recharger")
    assert r.status_code == 200 and r.json()["noeuds"] == 2


def test_auth_exigee_si_cle_configuree(monkeypatch):
    monkeypatch.setenv("API_KEYS", "secret-1")
    m = importlib.reload(main)
    c = TestClient(m.app)
    assert c.get("/sante").status_code == 200            # santé reste ouverte
    assert c.get("/noeuds").status_code == 401            # protégé sans clé
    assert c.get("/noeuds", headers={"X-API-Key": "secret-1"}).status_code == 200
    monkeypatch.setenv("API_KEYS", "")
    importlib.reload(main)                                # restaure pour les autres tests


# ── Tests inscription / suppression dynamique (S131 Étape 2) ──────────────────

def test_inscrire_sans_cle_401(monkeypatch):
    """POST /noeuds exige une clé quand API_KEYS est configuré → 401 sans clé."""
    monkeypatch.setenv("API_KEYS", "muscle-key")
    m = importlib.reload(main)
    c = TestClient(m.app)
    r = c.post("/noeuds", json={"id": "nouveau", "endpoint": "http://127.0.0.1:59997"})
    assert r.status_code == 401
    monkeypatch.setenv("API_KEYS", "")
    importlib.reload(main)


def test_inscrire_noeud_sonde_ok(monkeypatch, tmp_path):
    """POST /noeuds avec clé + sonde OK → 200, persisté, visible dans GET /noeuds."""
    parc_file = str(tmp_path / "parc.json")
    monkeypatch.setenv("API_KEYS", "muscle-key")
    monkeypatch.setenv("CALCUL_PARC_FILE", parc_file)
    m = importlib.reload(main)
    c = TestClient(m.app)

    async def sonde_ok(n, **kw):
        n.etat = "eveille"
        n.derniere_vue = "2026-01-01T00:00:00+00:00"
        return True

    monkeypatch.setattr(m.noeud_mod, "sonder", sonde_ok)

    r = c.post(
        "/noeuds",
        json={"id": "nouveau", "endpoint": "http://127.0.0.1:59997"},
        headers={"X-API-Key": "muscle-key"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["id"] == "nouveau"
    assert data["etat"] == "eveille"

    # Persisté dans le fichier
    saved = json_mod.loads((tmp_path / "parc.json").read_text())
    assert isinstance(saved, list)
    assert any(x.get("id") == "nouveau" for x in saved)

    # Visible dans GET /noeuds
    r2 = c.get("/noeuds", headers={"X-API-Key": "muscle-key"})
    assert r2.status_code == 200
    ids = [n["id"] for n in r2.json()["noeuds"]]
    assert "nouveau" in ids

    monkeypatch.setenv("API_KEYS", "")
    monkeypatch.setenv("CALCUL_PARC_FILE", "/tmp/calcul-test-parc-inexistant.json")
    importlib.reload(main)


def test_inscrire_noeud_injoignable_refuse(monkeypatch):
    """POST /noeuds avec nœud qui ne répond pas → refus honnête (422), non inscrit."""
    monkeypatch.setenv("API_KEYS", "muscle-key")
    m = importlib.reload(main)
    c = TestClient(m.app)

    async def sonde_echec(n, **kw):
        n.etat = "injoignable"
        return False

    monkeypatch.setattr(m.noeud_mod, "sonder", sonde_echec)

    r = c.post(
        "/noeuds",
        json={"id": "mort", "endpoint": "http://127.0.0.1:59997"},
        headers={"X-API-Key": "muscle-key"},
    )
    assert r.status_code == 422
    detail = r.json()["detail"].lower()
    # Message honnête : mentionne la sonde ou l'état
    assert any(mot in detail for mot in ("sonde", "répond", "injoignable", "refusé"))

    # Le nœud n'est PAS dans le parc
    r2 = c.get("/noeuds", headers={"X-API-Key": "muscle-key"})
    ids = [n["id"] for n in r2.json()["noeuds"]]
    assert "mort" not in ids

    monkeypatch.setenv("API_KEYS", "")
    importlib.reload(main)


def test_supprimer_noeud(monkeypatch, tmp_path):
    """DELETE /noeuds/{nid} après inscription → nœud retiré du parc et du fichier."""
    parc_file = str(tmp_path / "parc.json")
    monkeypatch.setenv("API_KEYS", "muscle-key")
    monkeypatch.setenv("CALCUL_PARC_FILE", parc_file)
    m = importlib.reload(main)
    c = TestClient(m.app)

    async def sonde_ok(n, **kw):
        n.etat = "eveille"
        return True

    monkeypatch.setattr(m.noeud_mod, "sonder", sonde_ok)

    # Inscrire d'abord
    rep = c.post(
        "/noeuds",
        json={"id": "temp", "endpoint": "http://127.0.0.1:59997"},
        headers={"X-API-Key": "muscle-key"},
    )
    assert rep.status_code == 200

    # Supprimer
    r = c.delete("/noeuds/temp", headers={"X-API-Key": "muscle-key"})
    assert r.status_code == 200
    assert r.json().get("retire") is True

    # Plus dans le parc
    r2 = c.get("/noeuds", headers={"X-API-Key": "muscle-key"})
    ids = [n["id"] for n in r2.json()["noeuds"]]
    assert "temp" not in ids

    monkeypatch.setenv("API_KEYS", "")
    monkeypatch.setenv("CALCUL_PARC_FILE", "/tmp/calcul-test-parc-inexistant.json")
    importlib.reload(main)


def test_supprimer_noeud_inconnu_404(monkeypatch):
    """DELETE /noeuds/fantome → 404 si nœud inconnu."""
    monkeypatch.setenv("API_KEYS", "muscle-key")
    m = importlib.reload(main)
    c = TestClient(m.app)
    r = c.delete("/noeuds/fantome", headers={"X-API-Key": "muscle-key"})
    assert r.status_code == 404
    monkeypatch.setenv("API_KEYS", "")
    importlib.reload(main)


def test_supprimer_sans_cle_401(monkeypatch):
    """DELETE /noeuds/{nid} sans clé API → 401 si API_KEYS configuré."""
    monkeypatch.setenv("API_KEYS", "muscle-key")
    m = importlib.reload(main)
    c = TestClient(m.app)
    # Essayer de supprimer sans clé (les endpoints du parc de base)
    r = c.delete("/noeuds/muscle")
    assert r.status_code == 401
    # Avec clé OK
    r_ok = c.delete("/noeuds/muscle", headers={"X-API-Key": "muscle-key"})
    assert r_ok.status_code in (200, 404)  # OK ou déjà retiré
    monkeypatch.setenv("API_KEYS", "")
    importlib.reload(main)


def test_reinscription_meme_id_idempotente(monkeypatch, tmp_path):
    """POST /noeuds avec le même id deux fois → idempotent, pas de doublon."""
    parc_file = str(tmp_path / "parc.json")
    monkeypatch.setenv("API_KEYS", "muscle-key")
    monkeypatch.setenv("CALCUL_PARC_FILE", parc_file)
    m = importlib.reload(main)
    c = TestClient(m.app)

    async def sonde_ok(n, **kw):
        n.etat = "eveille"
        n.derniere_vue = "2026-01-01T00:00:00+00:00"
        return True

    monkeypatch.setattr(m.noeud_mod, "sonder", sonde_ok)

    # Première inscription
    r1 = c.post(
        "/noeuds",
        json={"id": "test-id", "endpoint": "http://127.0.0.1:60001"},
        headers={"X-API-Key": "muscle-key"},
    )
    assert r1.status_code == 200
    data1 = r1.json()
    assert data1["id"] == "test-id"

    # Réinscription avec le même id (endpoint identique)
    r2 = c.post(
        "/noeuds",
        json={"id": "test-id", "endpoint": "http://127.0.0.1:60001"},
        headers={"X-API-Key": "muscle-key"},
    )
    assert r2.status_code == 200
    data2 = r2.json()
    assert data2["id"] == "test-id"

    # GET /noeuds : une seule entrée test-id (pas deux)
    r_list = c.get("/noeuds", headers={"X-API-Key": "muscle-key"})
    assert r_list.status_code == 200
    noeuds = r_list.json()["noeuds"]
    test_ids = [n["id"] for n in noeuds if n["id"] == "test-id"]
    assert len(test_ids) == 1, f"Doublon détecté : {test_ids}"

    # Fichier persisté : une seule entrée test-id
    saved = json_mod.loads((tmp_path / "parc.json").read_text())
    assert isinstance(saved, list)
    test_items = [x for x in saved if x.get("id") == "test-id"]
    assert len(test_items) == 1, f"Doublon dans fichier : {test_items}"

    monkeypatch.setenv("API_KEYS", "")
    monkeypatch.setenv("CALCUL_PARC_FILE", "/tmp/calcul-test-parc-inexistant.json")
    importlib.reload(main)


def test_supprimer_noeud_verifie_fichier(monkeypatch, tmp_path):
    """DELETE /noeuds/{nid} : vérifie que le nœud est retiré du fichier persisté."""
    parc_file = str(tmp_path / "parc.json")
    monkeypatch.setenv("API_KEYS", "muscle-key")
    monkeypatch.setenv("CALCUL_PARC_FILE", parc_file)
    m = importlib.reload(main)
    c = TestClient(m.app)

    async def sonde_ok(n, **kw):
        n.etat = "eveille"
        return True

    monkeypatch.setattr(m.noeud_mod, "sonder", sonde_ok)

    # Inscrire d'abord
    rep = c.post(
        "/noeuds",
        json={"id": "temp-file-test", "endpoint": "http://127.0.0.1:60002"},
        headers={"X-API-Key": "muscle-key"},
    )
    assert rep.status_code == 200

    # Vérifier dans le fichier avant suppression
    saved_before = json_mod.loads((tmp_path / "parc.json").read_text())
    assert any(x.get("id") == "temp-file-test" for x in saved_before)

    # Supprimer
    r = c.delete("/noeuds/temp-file-test", headers={"X-API-Key": "muscle-key"})
    assert r.status_code == 200
    assert r.json().get("retire") is True

    # Vérifier dans le fichier après suppression
    saved_after = json_mod.loads((tmp_path / "parc.json").read_text())
    assert not any(x.get("id") == "temp-file-test" for x in saved_after)

    # Plus dans GET /noeuds
    r2 = c.get("/noeuds", headers={"X-API-Key": "muscle-key"})
    ids = [n["id"] for n in r2.json()["noeuds"]]
    assert "temp-file-test" not in ids

    monkeypatch.setenv("API_KEYS", "")
    monkeypatch.setenv("CALCUL_PARC_FILE", "/tmp/calcul-test-parc-inexistant.json")
    importlib.reload(main)


def test_inscrire_sans_endpoint_422(monkeypatch):
    """POST /noeuds sans endpoint → 422 (validation échouée, nœud non inscrit)."""
    monkeypatch.setenv("API_KEYS", "muscle-key")
    m = importlib.reload(main)
    c = TestClient(m.app)

    async def sonde_ok(n, **kw):
        n.etat = "eveille"
        return True

    monkeypatch.setattr(m.noeud_mod, "sonder", sonde_ok)

    # POST sans endpoint
    r = c.post(
        "/noeuds",
        json={"id": "incomplete"},
        headers={"X-API-Key": "muscle-key"},
    )
    assert r.status_code == 422
    detail = r.json().get("detail", "").lower()
    # Le message doit mentionner le problème (endpoint manquant ou descripteur invalide)
    assert any(word in detail for word in ("endpoint", "incomplet", "invalide", "attendu"))

    # Le nœud ne devrait pas être dans le parc
    r2 = c.get("/noeuds", headers={"X-API-Key": "muscle-key"})
    ids = [n["id"] for n in r2.json()["noeuds"]]
    assert "incomplete" not in ids

    monkeypatch.setenv("API_KEYS", "")
    importlib.reload(main)


# ── Tests enregistrement Gateway (S131 Étape 3) ──────────────────────────────

def test_inscrire_avec_modele_gateway_ok(monkeypatch, tmp_path):
    """POST /noeuds avec `modele` + gateway OK → modele_gateway posé sur le nœud."""
    parc_file = str(tmp_path / "parc.json")
    monkeypatch.setenv("API_KEYS", "muscle-key")
    monkeypatch.setenv("CALCUL_PARC_FILE", parc_file)
    m = importlib.reload(main)
    c = TestClient(m.app)

    async def sonde_ok(n, **kw):
        n.etat = "eveille"
        n.derniere_vue = "2026-01-01T00:00:00+00:00"
        return True

    async def gateway_ok(model_name, api_base, **kw):
        return {"ok": True, "erreur": None, "model_id": "gw-id-123", "model_name": model_name}

    monkeypatch.setattr(m.noeud_mod, "sonder", sonde_ok)
    monkeypatch.setattr(m.gateway_admin_mod, "enregistrer_modele", gateway_ok)

    r = c.post(
        "/noeuds",
        json={"id": "muscle-gw", "endpoint": "http://127.0.0.1:11434", "modele": "llama3.3"},
        headers={"X-API-Key": "muscle-key"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["id"] == "muscle-gw"
    # modele_gateway doit être posé (contient llama3.3)
    assert data["modele_gateway"] is not None
    assert "llama3.3" in data["modele_gateway"]

    monkeypatch.setenv("API_KEYS", "")
    monkeypatch.setenv("CALCUL_PARC_FILE", "/tmp/calcul-test-parc-inexistant.json")
    importlib.reload(main)


def test_inscrire_avec_modele_gateway_erreur(monkeypatch, tmp_path):
    """POST /noeuds + gateway en erreur → nœud inscrit SANS modele_gateway (dégradé honnête)."""
    parc_file = str(tmp_path / "parc.json")
    monkeypatch.setenv("API_KEYS", "muscle-key")
    monkeypatch.setenv("CALCUL_PARC_FILE", parc_file)
    m = importlib.reload(main)
    c = TestClient(m.app)

    async def sonde_ok(n, **kw):
        n.etat = "eveille"
        n.derniere_vue = "2026-01-01T00:00:00+00:00"
        return True

    async def gateway_echec(model_name, api_base, **kw):
        return {"ok": False, "erreur": "LITELLM_URL non configuré", "model_id": None, "model_name": model_name}

    monkeypatch.setattr(m.noeud_mod, "sonder", sonde_ok)
    monkeypatch.setattr(m.gateway_admin_mod, "enregistrer_modele", gateway_echec)

    r = c.post(
        "/noeuds",
        json={"id": "muscle-sans-gw", "endpoint": "http://127.0.0.1:11434", "modele": "llama3.3"},
        headers={"X-API-Key": "muscle-key"},
    )
    # Le nœud doit être inscrit malgré l'erreur gateway (dégradé honnête)
    assert r.status_code == 200
    data = r.json()
    assert data["id"] == "muscle-sans-gw"
    assert data["modele_gateway"] is None
    # L'avertissement gateway doit figurer dans la réponse
    reponse_str = str(data).lower()
    assert "gateway" in reponse_str or "avertissement" in reponse_str

    monkeypatch.setenv("API_KEYS", "")
    monkeypatch.setenv("CALCUL_PARC_FILE", "/tmp/calcul-test-parc-inexistant.json")
    importlib.reload(main)


def test_republier_idempotent(monkeypatch, tmp_path):
    """POST /noeuds/republier re-pousse tous les modèles gateway — idempotent, pas de crash."""
    parc_file = str(tmp_path / "parc.json")
    monkeypatch.setenv("API_KEYS", "muscle-key")
    monkeypatch.setenv("CALCUL_PARC_FILE", parc_file)
    m = importlib.reload(main)
    c = TestClient(m.app)

    appels_gateway = []

    async def gateway_ok(model_name, api_base, **kw):
        appels_gateway.append(model_name)
        return {"ok": True, "erreur": None, "model_id": "x", "model_name": model_name}

    monkeypatch.setattr(m.gateway_admin_mod, "enregistrer_modele", gateway_ok)

    # Le parc de base (conftest) contient "muscle" avec modele_gateway="ollama/llama3.3"
    r = c.post("/noeuds/republier", headers={"X-API-Key": "muscle-key"})
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert isinstance(data.get("repousses"), int)
    # Au moins le nœud "muscle" (qui a un modele_gateway) a dû être republié
    assert data["repousses"] >= 1

    # Deuxième appel = idempotent (ne plante pas)
    r2 = c.post("/noeuds/republier", headers={"X-API-Key": "muscle-key"})
    assert r2.status_code == 200

    monkeypatch.setenv("API_KEYS", "")
    monkeypatch.setenv("CALCUL_PARC_FILE", "/tmp/calcul-test-parc-inexistant.json")
    importlib.reload(main)


def test_republier_sans_gateway_ne_plante_pas(monkeypatch):
    """POST /noeuds/republier sans LITELLM_URL → répond 200 quand même (best-effort)."""
    monkeypatch.delenv("LITELLM_URL", raising=False)
    m = importlib.reload(main)
    c = TestClient(m.app)

    r = c.post("/noeuds/republier")
    # En mode ouvert (API_KEYS=""), la route répond 200 même si gateway absent
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True

    importlib.reload(main)
