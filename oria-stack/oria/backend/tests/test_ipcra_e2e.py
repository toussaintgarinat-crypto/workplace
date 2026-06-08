"""
Tests end-to-end du système IPCRA.
Couvre : CRUD items · déplacement entre catégories · assist IA ·
         traces · recherche sémantique · isolation utilisateurs.
"""
import json
import pytest
import httpx
from unittest.mock import patch, AsyncMock, MagicMock

from database import SessionLocal
from models.agent import AgentDefinition


# ── Helpers ──────────────────────────────────────────────────────

def create_item(client, titre="Test item", categorie="input", contenu="", agent_id=None):
    body = {"titre": titre, "categorie": categorie, "contenu": contenu}
    if agent_id:
        body["agent_id"] = agent_id
    r = client.post("/api/ipcra/", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def create_agent(nom="Agent Test", forge_url="http://forge-test:3001", use_memory=False):
    db = SessionLocal()
    try:
        agent = AgentDefinition(
            nom=nom,
            world_id="world-test",
            owner_id="user-test-abc-123",
            forge_url=forge_url,
            forge_provider="anthropic",
            forge_model="claude-3-haiku",
            use_memory=use_memory,
            use_ipcra=True,
            is_active=True,
        )
        db.add(agent)
        db.commit()
        return agent.id
    finally:
        db.close()


def mock_forge_response(answer: str, steps: list = None):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"answer": answer, "steps": steps or []}
    mock_http = AsyncMock()
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=False)
    mock_http.post = AsyncMock(return_value=mock_resp)
    return mock_http


# ── CRUD Items ────────────────────────────────────────────────────

class TestItemCRUD:
    def test_create_item_retourne_201(self, client):
        r = client.post("/api/ipcra/", json={"titre": "Idée capture", "categorie": "input"})
        assert r.status_code == 201
        data = r.json()
        assert data["titre"] == "Idée capture"
        assert data["categorie"] == "input"
        assert "id" in data

    def test_create_item_categories_valides(self, client):
        for cat in ["input", "projet", "casquette", "ressource", "archive"]:
            r = client.post("/api/ipcra/", json={"titre": f"Item {cat}", "categorie": cat})
            assert r.status_code == 201, f"Catégorie {cat} rejetée : {r.text}"

    def test_create_item_categorie_invalide_retourne_400(self, client):
        r = client.post("/api/ipcra/", json={"titre": "X", "categorie": "inexistante"})
        assert r.status_code == 400

    def test_list_items_retourne_les_siens(self, client):
        create_item(client, "Item A")
        create_item(client, "Item B", "projet")
        r = client.get("/api/ipcra/")
        assert r.status_code == 200
        assert len(r.json()) == 2

    def test_list_items_filtre_par_categorie(self, client):
        create_item(client, "Input 1", "input")
        create_item(client, "Projet 1", "projet")
        create_item(client, "Input 2", "input")
        r = client.get("/api/ipcra/?categorie=input")
        assert r.status_code == 200
        items = r.json()
        assert len(items) == 2
        assert all(i["categorie"] == "input" for i in items)

    def test_get_item_existant(self, client):
        item = create_item(client, "Mon item")
        r = client.get(f"/api/ipcra/{item['id']}")
        assert r.status_code == 200
        assert r.json()["id"] == item["id"]

    def test_get_item_inexistant_retourne_404(self, client):
        r = client.get("/api/ipcra/item-qui-nexiste-pas")
        assert r.status_code == 404

    def test_update_item(self, client):
        item = create_item(client, "Titre initial")
        r = client.put(f"/api/ipcra/{item['id']}", json={"titre": "Titre modifié", "contenu": "Contenu ajouté"})
        assert r.status_code == 200
        data = r.json()
        assert data["titre"] == "Titre modifié"
        assert data["contenu"] == "Contenu ajouté"

    def test_delete_item(self, client):
        item = create_item(client)
        r = client.delete(f"/api/ipcra/{item['id']}")
        assert r.status_code == 204
        assert client.get(f"/api/ipcra/{item['id']}").status_code == 404

    def test_tags_sauvegardes_et_restitues(self, client):
        r = client.post("/api/ipcra/", json={
            "titre": "Avec tags",
            "categorie": "ressource",
            "tags": ["python", "fastapi", "memoire"],
        })
        assert r.status_code == 201
        assert r.json()["tags"] == ["python", "fastapi", "memoire"]


# ── Déplacement entre catégories ──────────────────────────────────

class TestMoveCategorieIPCRA:
    def test_move_input_vers_projet(self, client):
        item = create_item(client, "Idée à qualifier", "input")
        r = client.patch(f"/api/ipcra/{item['id']}/categorie?categorie=projet")
        assert r.status_code == 200
        assert r.json()["categorie"] == "projet"

    def test_move_projet_vers_archive(self, client):
        item = create_item(client, "Projet terminé", "projet")
        r = client.patch(f"/api/ipcra/{item['id']}/categorie?categorie=archive")
        assert r.status_code == 200
        assert r.json()["categorie"] == "archive"

    def test_move_categorie_invalide_retourne_400(self, client):
        item = create_item(client)
        r = client.patch(f"/api/ipcra/{item['id']}/categorie?categorie=inexistante")
        assert r.status_code == 400

    def test_move_item_inexistant_retourne_404(self, client):
        r = client.patch("/api/ipcra/item-fantome/categorie?categorie=archive")
        assert r.status_code == 404

    def test_move_declenche_sync_mempalace(self, client):
        item = create_item(client, "Ressource à déplacer", "input", "Contenu utile")
        with patch("mempalace_client.sync", return_value=True) as mock_sync:
            client.patch(f"/api/ipcra/{item['id']}/categorie?categorie=ressource")
        mock_sync.assert_called_once()


# ── Sync MemPalace ────────────────────────────────────────────────

class TestSyncMemPalace:
    def test_create_avec_contenu_declenche_sync(self, client):
        with patch("mempalace_client.sync", return_value=True) as mock_sync:
            create_item(client, "Item sync", "projet", "Contenu à indexer")
        mock_sync.assert_called_once()
        args = mock_sync.call_args[0]
        assert "Contenu à indexer" in args[0]
        assert args[2] == "projet"

    def test_create_sans_contenu_sync_titre_seulement(self, client):
        # _sync_item synce le titre même sans contenu — comportement normal
        with patch("mempalace_client.sync", return_value=True) as mock_sync:
            create_item(client, "Item titre seulement")
        mock_sync.assert_called_once()
        args = mock_sync.call_args[0]
        assert "Item titre seulement" in args[0]
        assert "##" in args[0]  # format "## Titre"


# ── Assist IA ────────────────────────────────────────────────────

class TestAssist:
    def test_assist_sans_agent_retourne_conseil_categorie(self, client):
        item = create_item(client, "Mon projet", "projet")
        r = client.post(f"/api/ipcra/{item['id']}/assist", json={"prompt": "Que faire ensuite ?"})
        assert r.status_code == 200
        data = r.json()
        assert len(data["answer"]) > 20
        assert data.get("steps") == []

    def test_assist_item_inexistant_retourne_404(self, client):
        r = client.post("/api/ipcra/item-fantome/assist", json={"prompt": "test"})
        assert r.status_code == 404

    def test_assist_avec_agent_forge_appelle_forge(self, client):
        agent_id = create_agent("Agent Forge Test")
        item = create_item(client, "Projet avec agent", "projet", agent_id=agent_id)
        with patch("httpx.AsyncClient", return_value=mock_forge_response("Voici mon analyse.", [{"step": 1}])):
            r = client.post(f"/api/ipcra/{item['id']}/assist", json={"prompt": "Analyse ce projet"})
        assert r.status_code == 200
        assert r.json()["answer"] == "Voici mon analyse."

    def test_assist_avec_agent_forge_down_degrade_gracieusement(self, client):
        agent_id = create_agent("Agent Forge Down", forge_url="http://forge-down:9999")
        item = create_item(client, "Item forge down", "input", agent_id=agent_id)
        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.post = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
        with patch("httpx.AsyncClient", return_value=mock_http):
            r = client.post(f"/api/ipcra/{item['id']}/assist", json={"prompt": "Test"})
        assert r.status_code == 200
        assert "non disponible" in r.json()["answer"]

    def test_assist_avec_mempalace_prefetch_appele(self, client):
        agent_id = create_agent("Agent Mémoire", use_memory=True)
        item = create_item(client, "Item avec mémoire", "ressource", agent_id=agent_id)
        with patch("mempalace_client.prefetch", return_value=[]) as mock_prefetch, \
             patch("httpx.AsyncClient", return_value=mock_forge_response("Réponse enrichie")):
            client.post(f"/api/ipcra/{item['id']}/assist", json={"prompt": "Test mémoire"})
        mock_prefetch.assert_called_once()

    def test_assist_persiste_trace(self, client):
        agent_id = create_agent("Agent Trace")
        item = create_item(client, "Item tracé", "casquette", agent_id=agent_id)
        with patch("httpx.AsyncClient", return_value=mock_forge_response("Réponse tracée")):
            client.post(f"/api/ipcra/{item['id']}/assist", json={"prompt": "Trace ce message"})
        traces = client.get(f"/api/ipcra/{item['id']}/traces").json()
        assert len(traces) == 1
        assert "Trace ce message" in traces[0]["prompt"]
        assert traces[0]["agent_nom"] == "Agent Trace"
        assert isinstance(traces[0]["duree_ms"], int)


# ── Traces ────────────────────────────────────────────────────────

class TestTraces:
    def test_traces_vides_initialement(self, client):
        item = create_item(client)
        r = client.get(f"/api/ipcra/{item['id']}/traces")
        assert r.status_code == 200
        assert r.json() == []

    def test_traces_item_inexistant_retourne_404(self, client):
        r = client.get("/api/ipcra/item-inexistant-xyz/traces")
        assert r.status_code == 404

    def test_traces_triees_par_date_asc(self, client):
        agent_id = create_agent("Agent Ordre")
        item = create_item(client, "Item multi-traces", "projet", agent_id=agent_id)
        for msg in ["Premier appel", "Deuxième appel"]:
            with patch("httpx.AsyncClient", return_value=mock_forge_response(f"Réponse: {msg}")):
                client.post(f"/api/ipcra/{item['id']}/assist", json={"prompt": msg})
        traces = client.get(f"/api/ipcra/{item['id']}/traces").json()
        assert len(traces) == 2
        assert "Premier" in traces[0]["prompt"]
        assert "Deuxième" in traces[1]["prompt"]


# ── Recherche sémantique ──────────────────────────────────────────

class TestSemanticSearch:
    def test_search_sans_resultats_retourne_vide(self, client):
        with patch("mempalace_client.prefetch", return_value=[]) as mock_prefetch:
            r = client.get("/api/ipcra/search/semantic?q=optimisation+cloud")
        assert r.status_code == 200
        assert r.json()["results"] == []
        mock_prefetch.assert_called_once()

    def test_search_retourne_hits_mempalace(self, client):
        hits = [{"text": "Migration AWS", "wing": "wing_user", "room": "ipcra-sessions", "similarity": 0.85}]
        with patch("mempalace_client.prefetch", return_value=hits):
            r = client.get("/api/ipcra/search/semantic?q=migration+cloud")
        assert r.status_code == 200
        assert len(r.json()["results"]) == 1
        assert r.json()["results"][0]["similarity"] == 0.85


# ── Isolation utilisateurs ────────────────────────────────────────

class TestIsolationUtilisateurs:
    def test_item_invisible_autre_utilisateur(self, client):
        from main import app
        from routers.auth import get_current_user as gcu

        item = create_item(client, "Item privé user A")

        app.dependency_overrides[gcu] = lambda: {
            "id": "user-autre-xyz",
            "email": "autre@test.com",
        }
        r = client.get(f"/api/ipcra/{item['id']}")
        app.dependency_overrides[gcu] = lambda: {
            "id": "user-test-abc-123",
            "email": "test@oria-test.com",
            "nom": "Test User",
            "avatar_emoji": "👤",
        }
        assert r.status_code == 404

    def test_list_ne_retourne_que_ses_items(self, client):
        from main import app
        from routers.auth import get_current_user as gcu

        create_item(client, "Item user A")

        app.dependency_overrides[gcu] = lambda: {"id": "user-autre-xyz", "email": "autre@test.com"}
        r = client.get("/api/ipcra/")
        app.dependency_overrides[gcu] = lambda: {
            "id": "user-test-abc-123",
            "email": "test@oria-test.com",
            "nom": "Test User",
            "avatar_emoji": "👤",
        }
        assert r.json() == []


# ── Flux complet end-to-end ───────────────────────────────────────

class TestFluxCompletIPCRA:
    def test_parcours_complet_input_vers_archive(self, client):
        """
        Simule le cycle de vie complet d'un élément IPCRA :
        capture (Input) → qualification → déplacement (Projet) →
        enrichissement → archivage.
        """
        # 1. Capture brute
        item = create_item(client, "Idée de feature voice search", "input",
                           "Permettre la recherche vocale dans l'app mobile")
        assert item["categorie"] == "input"

        # 2. Qualifier : déplacer vers Projet
        r = client.patch(f"/api/ipcra/{item['id']}/categorie?categorie=projet")
        assert r.status_code == 200
        assert r.json()["categorie"] == "projet"

        # 3. Enrichir avec du contenu
        r = client.put(f"/api/ipcra/{item['id']}", json={
            "contenu": "Objectif : intégrer Whisper API. Deadline Q3 2026.",
            "tags": ["voice", "whisper", "mobile"],
        })
        assert r.status_code == 200
        assert r.json()["tags"] == ["voice", "whisper", "mobile"]

        # 4. Demander conseil IA (sans agent → guide textuel)
        r = client.post(f"/api/ipcra/{item['id']}/assist",
                        json={"prompt": "Quelles sont les prochaines étapes ?"})
        assert r.status_code == 200
        assert len(r.json()["answer"]) > 20

        # 5. Archiver
        r = client.patch(f"/api/ipcra/{item['id']}/categorie?categorie=archive")
        assert r.status_code == 200
        final = r.json()
        assert final["categorie"] == "archive"
        assert final["contenu"] == "Objectif : intégrer Whisper API. Deadline Q3 2026."
        assert final["tags"] == ["voice", "whisper", "mobile"]

    def test_creation_5_categories_independantes(self, client):
        """Chaque catégorie IPCRA est indépendante — pas de séquence imposée."""
        items = {
            "input":     create_item(client, "Capture brute",         "input"),
            "projet":    create_item(client, "Projet actif",           "projet"),
            "casquette": create_item(client, "Rôle tech lead",         "casquette"),
            "ressource": create_item(client, "Template de réunion",    "ressource"),
            "archive":   create_item(client, "Projet terminé 2025",    "archive"),
        }
        # Toutes existent de façon indépendante
        for cat, item in items.items():
            r = client.get(f"/api/ipcra/{item['id']}")
            assert r.status_code == 200
            assert r.json()["categorie"] == cat

        # Le filtre retourne exactement les bons items
        r = client.get("/api/ipcra/")
        assert len(r.json()) == 5
