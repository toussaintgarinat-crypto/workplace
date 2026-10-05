import uuid

import pytest
from sqlalchemy import select

from app import database as db_module
from app.llm.embedder import Embedder, EmbeddingIndisponible
from app.models.node import Node
from app.services.embed_service import EmbedService
from tests.outils_embedder import activer_embedder_factice, couper_embedder, vecteur_factice

pytestmark = pytest.mark.asyncio


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
        assert appels["n"] == 2


class TestSemantique503:
    async def test_semantic_en_panne_repond_503(self, client, auth_headers, test_space):
        r = await client.post(
            f"/api/v1/spaces/{test_space['id']}/search/semantic",
            json={"query": "bonjour"},
            headers=auth_headers,
        )
        assert r.status_code == 503
        assert "indisponible" in r.json()["detail"]
