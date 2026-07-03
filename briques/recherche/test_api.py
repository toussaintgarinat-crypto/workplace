"""API de la brique browser : contrat compatible recherche + repli honnête."""
from fastapi.testclient import TestClient

import main
import providers
from search_providers import SearchResult


client = TestClient(main.app)


def test_sante_liste_les_neuf_moteurs():
    r = client.get("/sante")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert "duckduckgo" in data["fournisseurs"]
    assert "searxng" in data["fournisseurs"]
    # En test, aucun moteur n'est configuré (conftest neutralise tout).
    assert data["configures"] == []
    assert data["actif"] is None


def test_rechercher_sans_moteur_rend_note_honnete():
    r = client.post("/rechercher", json={"requete": "postgres"})
    assert r.status_code == 200
    data = r.json()
    assert data["resultats"] == []
    assert data["nb"] == 0
    assert "note" in data            # explique POURQUOI c'est vide, n'invente rien


def test_rechercher_requete_vide_422():
    assert client.post("/rechercher", json={"requete": "   "}).status_code == 422


def test_rechercher_fusionne_les_providers(monkeypatch):
    class Faux:
        def __init__(self, source, urls):
            self.source = source
            self.urls = urls
        async def search(self, query, max_results=10, topic="web", langue="fr"):
            return [SearchResult(title=f"T {u}", url=u, snippet="extrait", content="",
                                 source=self.source) for u in self.urls]

    monkeypatch.setattr(providers, "actifs", lambda: [
        ("duckduckgo", Faux("duckduckgo", ["https://a.test/1"])),
        ("brave", Faux("brave", ["https://a.test/1", "https://b.test/2"])),
    ])
    r = client.post("/rechercher", json={"requete": "x", "topic": "web"})
    data = r.json()
    assert data["nb"] == 2                                   # /1 (consensus) + /2
    assert data["resultats"][0]["url"] == "https://a.test/1"  # trouvé par 2 → en tête
    assert set(data["resultats"][0]["providers"]) == {"duckduckgo", "brave"}
    assert "duckduckgo" in data["moteurs"] and "brave" in data["moteurs"]


def test_rechercher_topic_invalide_retombe_sur_web(monkeypatch):
    monkeypatch.setattr(providers, "actifs", lambda: [])
    r = client.post("/rechercher", json={"requete": "x", "topic": "n_importe_quoi"})
    assert r.json()["topic"] == "web"


def test_synthetiser_sans_moteur_rend_note_honnete():
    """Sans moteur configuré → synthese=null + note honnête, pas d'erreur 500."""
    r = client.post("/synthétiser", json={"requete": "FastAPI"})
    assert r.status_code == 200
    data = r.json()
    assert data["synthese"] is None
    assert data["sources"] == []
    assert "note" in data


def test_synthetiser_gateway_indisponible(monkeypatch):
    """Si le gateway est down, retour gracieux avec synthese=null + sources brutes."""
    class Faux:
        async def search(self, query, max_results=10, topic="web", langue="fr"):
            return [SearchResult(title="T", url="https://d.test/1",
                                 snippet="extrait", content="", source="duckduckgo")]

    monkeypatch.setattr(providers, "actifs", lambda: [("duckduckgo", Faux())])

    import synthese as syn_mod

    async def _gateway_down(requete, resultats, instructions="", langue="fr", max_items=8):
        _, sources = syn_mod._formater_contexte(resultats, max_items)
        return None, sources

    monkeypatch.setattr(syn_mod, "synthetiser", _gateway_down)

    r = client.post("/synthétiser", json={"requete": "test gateway down"})
    assert r.status_code == 200
    data = r.json()
    assert data["synthese"] is None
    assert len(data["sources"]) == 1
    assert "note" in data


def test_lire_page_url_invalide_422():
    r = client.post("/lire-page", json={"url": "file:///etc/passwd"})
    assert r.status_code == 422


def test_cache_evite_double_appel(monkeypatch):
    """La 2e requête identique doit être servie depuis le cache (multi_search non rappelé)."""
    call_count = 0

    class Faux:
        async def search(self, query, max_results=10, topic="web", langue="fr"):
            nonlocal call_count
            call_count += 1
            return [SearchResult(title="T", url="https://c.test/1",
                                 snippet="s", content="", source="duckduckgo")]

    monkeypatch.setattr(providers, "actifs", lambda: [("duckduckgo", Faux())])

    from cache import recherche_cache
    recherche_cache.clear()

    payload = {"requete": "cache_test_unique_xyz", "topic": "web", "n": 3}
    r1 = client.post("/rechercher", json=payload)
    r2 = client.post("/rechercher", json=payload)

    assert r1.status_code == r2.status_code == 200
    assert r1.json() == r2.json()
    assert call_count == 1  # multi_search appelé UNE seule fois
