import uuid

import pytest
from sqlalchemy import select
from sqlalchemy import text as text_sql

from app import database as db_module
from app.llm.client import LLMClient as _LLMClient
from app.llm.embedder import Embedder, EmbeddingIndisponible
from app.models.node import Node
from app.services.embed_service import EmbedService
from tests.outils_embedder import activer_embedder_factice, couper_embedder, vecteur_factice

pytestmark = pytest.mark.asyncio

_EMBED_ORIGINAL = _LLMClient.embed  # capturé à l'import, avant le monkeypatch autouse


async def _embedding(node_id: str):
    async with db_module.async_session_factory() as db:
        r = await db.execute(select(Node.embedding).where(Node.id == uuid.UUID(node_id)))
        return r.scalar_one()


async def _creer(client, headers, space_id, titre, contenu=""):
    r = await client.post(
        f"/api/v1/spaces/{space_id}/nodes",
        json={"type": "input", "title": titre, "content_md": contenu},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


class TestEmbedder:
    async def test_panne_leve_au_lieu_d_inventer(self):
        with pytest.raises(EmbeddingIndisponible):
            await Embedder().embed_text("bonjour")

    async def test_texte_vide_renvoie_none(self, embedder_factice):
        assert await Embedder().embed_text("   ") is None

    async def test_factice_renvoie_le_vecteur(self, embedder_factice):
        assert await Embedder().embed_text("bonjour") == vecteur_factice("bonjour")


class TestEmbeddingDiffere:
    async def test_creation_en_panne_enregistre_sans_vecteur(self, client, auth_headers, test_space):
        nid = await _creer(client, auth_headers, test_space["id"], "Note en panne", "contenu")
        assert await _embedding(nid) is None

    async def test_creation_titre_seul_est_vectorisee(self, client, auth_headers, test_space, embedder_factice):
        nid = await _creer(client, auth_headers, test_space["id"], "Titre seul")
        assert await _embedding(nid) is not None

    async def test_modification_en_panne_efface_le_vecteur_perime(self, client, auth_headers, test_space, monkeypatch):
        activer_embedder_factice(monkeypatch)
        nid = await _creer(client, auth_headers, test_space["id"], "Avant", "ancien contenu")
        assert await _embedding(nid) is not None
        couper_embedder(monkeypatch)
        r = await client.put(
            f"/api/v1/spaces/{test_space['id']}/nodes/{nid}",
            json={"content_md": "nouveau contenu"},
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text
        assert await _embedding(nid) is None


class TestRevectorisation:
    async def test_revectorise_les_manquants(self, client, auth_headers, test_space, monkeypatch):
        nid = await _creer(client, auth_headers, test_space["id"], "Différé", "à vectoriser")
        activer_embedder_factice(monkeypatch)
        async with db_module.async_session_factory() as db:
            faits = await EmbedService(db).revectoriser_manquants(limite=500)
        assert faits >= 1
        assert await _embedding(nid) is not None

    async def test_s_arrete_au_premier_echec(self, client, auth_headers, test_space, monkeypatch):
        await _creer(client, auth_headers, test_space["id"], "Un", "a")
        await _creer(client, auth_headers, test_space["id"], "Deux", "b")
        appels = {"n": 0}

        async def _une_seule_reussite(self, text):
            appels["n"] += 1
            if appels["n"] > 1:
                raise ConnectionError("panne au 2e appel")
            return vecteur_factice(text)

        from app.llm.client import LLMClient
        monkeypatch.setattr(LLMClient, "embed", _une_seule_reussite)
        async with db_module.async_session_factory() as db:
            faits = await EmbedService(db).revectoriser_manquants(limite=500)
        assert faits == 1
        assert appels["n"] == 3  # 1 réussite, 1 échec, 1 sonde en échec

    async def test_saute_un_souvenir_empoisonne(self, client, auth_headers, test_space, monkeypatch):
        pid = await _creer(client, auth_headers, test_space["id"], "POISON", "x")
        nid = await _creer(client, auth_headers, test_space["id"], "Normal", "sain")

        async def _embed(self, text):
            if "POISON" in text:
                raise ConnectionError("texte rejeté")
            return vecteur_factice(text)

        from app.llm.client import LLMClient
        monkeypatch.setattr(LLMClient, "embed", _embed)
        async with db_module.async_session_factory() as db:
            await EmbedService(db).revectoriser_manquants(limite=500)
        assert await _embedding(pid) is None
        assert await _embedding(nid) is not None

    async def test_ne_ecrase_pas_une_modification_concurrente(self, client, auth_headers, test_space, monkeypatch):
        nid = await _creer(client, auth_headers, test_space["id"], "Course", "ancien texte")
        concurrent = vecteur_factice("texte concurrent")

        async def _embed(self, text):
            if "ancien texte" in text:
                async with db_module.async_session_factory() as autre:
                    await autre.execute(
                        text_sql("UPDATE nodes SET embedding = CAST(:e AS vector), updated_at = now() WHERE id = :id"),
                        {"e": "[" + ",".join(repr(x) for x in concurrent) + "]", "id": uuid.UUID(nid)},
                    )
                    await autre.commit()
            return vecteur_factice(text)

        from app.llm.client import LLMClient
        monkeypatch.setattr(LLMClient, "embed", _embed)
        async with db_module.async_session_factory() as db:
            await EmbedService(db).revectoriser_manquants(limite=500)
        final = await _embedding(nid)
        assert list(final) == pytest.approx(concurrent, abs=1e-5)


class TestSemantique503:
    async def test_semantic_en_panne_repond_503(self, client, auth_headers, test_space):
        r = await client.post(
            f"/api/v1/spaces/{test_space['id']}/search/semantic",
            json={"query": "bonjour"},
            headers=auth_headers,
        )
        assert r.status_code == 503
        assert "indisponible" in r.json()["detail"]


async def test_client_openai_se_construit():
    """Regression : openai < 1.55.3 + httpx 0.28 -> TypeError 'proxies' a la construction."""
    from app.config import settings
    from app.llm.client import LLMClient

    ancien = (settings.llm_provider, settings.llm_api_key, settings.llm_base_url)
    settings.llm_provider = "openai"
    settings.llm_api_key = "cle-factice"
    settings.llm_base_url = "http://127.0.0.1:9/v1"
    try:
        client = await LLMClient()._get_client()
        assert client is not None
    finally:
        settings.llm_provider, settings.llm_api_key, settings.llm_base_url = ancien



async def test_embed_delai_court_sans_reessai():
    """embed_node est sur le chemin des requêtes : un Gateway qui pend ne doit pas bloquer
    écritures et recherches 600 s (défaut openai) ni être réessayé 2 fois."""
    from types import SimpleNamespace

    from app.llm import client as module_client

    options = {}

    class _Embeddings:
        async def create(self, **kwargs):
            return SimpleNamespace(data=[SimpleNamespace(embedding=[0.5])])

    class _Client:
        def with_options(self, **kwargs):
            options.update(kwargs)
            return SimpleNamespace(embeddings=_Embeddings())

        @property
        def embeddings(self):
            raise AssertionError("embeddings appelé sans with_options")

    llm = module_client.LLMClient()
    llm._client = _Client()
    assert await _EMBED_ORIGINAL(llm, "bonjour") == [0.5]
    assert options == {"timeout": module_client.DELAI_EMBEDDING_S, "max_retries": 0}
    assert module_client.DELAI_EMBEDDING_S <= 15

