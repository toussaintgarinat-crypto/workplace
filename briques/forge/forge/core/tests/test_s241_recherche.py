"""S241 — recherche hybride Forge de bout en bout (Postgres + Qdrant réels, embedder factice)."""
import pytest_asyncio
from sqlalchemy import text

from app import memory
from app.auth import UserContext, get_current_user
from tests.s241_outils import (  # noqa: F401
    ajouter_article, ajouter_document, base, embedder_coupe, embedder_factice, integration,
)

pytestmark = integration


@pytest_asyncio.fixture
async def alice(app):
    app.dependency_overrides[get_current_user] = lambda: UserContext(
        sub="alice", nom="Alice", avatar_emoji="🦊", org_id=None)
    yield
    app.dependency_overrides.pop(get_current_user, None)


async def _chercher(client, q, **params):
    r = await client.get("/api/recherche/hybride", params={"q": q, **params})
    assert r.status_code == 200, r.text
    return r.json()


async def test_reference_exacte_en_tete(base, embedder_factice, alice, client):
    cible = await ajouter_document("alice", "Relance", "Rappel : la facture FAC-2026-0042 reste impayée.")
    await ajouter_document("alice", "Facture", "Facture de mars, réglée.")
    rep = await _chercher(client, "facture FAC-2026-0042")
    assert rep["resultats"][0]["id"] == str(cible) and rep["resultats"][0]["exact"] is True


async def test_faute_de_frappe(base, embedder_factice, alice, client):
    cible = await ajouter_article("alice", "Maintenance", "Contrat de maintenance annuelle de la chaudière.")
    rep = await _chercher(client, "maintenence")
    assert [r["id"] for r in rep["resultats"]] == [str(cible)]
    assert rep["resultats"][0]["source"] == "kb"


async def test_aucune_fuite_dans_aucune_branche(base, embedder_factice, alice, client):
    texte = "Plan de financement confidentiel FIN-77 pour le rachat."
    secret = await ajouter_document("bob", "Secret de Bob", texte)
    await memory.indexer_source(texte, str(secret), "document", "bob", "Secret de Bob")
    # Fragment de Bob volontairement mal attribué à Alice dans Qdrant : le recoupement
    # PostgreSQL (user_id) doit l'écarter.
    await memory.indexer_source(texte, str(secret), "document", "alice", "Secret de Bob")
    for q in ("financement confidentiel", "FIN-77", "finnancement"):
        assert (await _chercher(client, q))["resultats"] == [], q


async def test_document_supprime_introuvable_meme_si_qdrant_garde_ses_fragments(base, embedder_factice, alice, client):
    from app.db import engine
    texte = "Compte rendu de chantier, toiture terminée."
    doc = await ajouter_document("alice", "CR chantier", texte)
    await memory.indexer_source(texte, str(doc), "document", "alice", "CR chantier")
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM documents WHERE id = :i"), {"i": doc})
    assert (await _chercher(client, "compte rendu chantier"))["resultats"] == []


async def test_branche_vectorielle_regroupe_et_donne_l_extrait(base, alice, client, monkeypatch):
    doc = await ajouter_document("alice", "Note", "Aucun mot de la requête ici.")

    async def _fragments(question, user_id, limite=30):
        return [memory.Fragment("document", str(doc), "passage pertinent A", 0.9),
                memory.Fragment("document", str(doc), "passage B", 0.8)]

    monkeypatch.setattr(memory, "chercher_fragments", _fragments)
    rep = await _chercher(client, "question sémantique")
    assert rep["mode"] == "hybride"
    assert [(r["id"], r["extrait"]) for r in rep["resultats"]] == [(str(doc), "passage pertinent A")]


async def test_embedder_coupe_mode_lexical(base, embedder_coupe, alice, client):
    cible = await ajouter_document("alice", "Devis toiture", "Réfection complète.")
    rep = await _chercher(client, "toiture")
    assert rep["mode"] == "lexical" and [r["id"] for r in rep["resultats"]] == [str(cible)]


async def test_filtre_sources_et_requete_vide(base, embedder_factice, alice, client):
    await ajouter_document("alice", "Toiture", "doc")
    k = await ajouter_article("alice", "Toiture", "article")
    assert [r["id"] for r in (await _chercher(client, "toiture", sources="kb"))["resultats"]] == [str(k)]
    assert (await _chercher(client, "  "))["resultats"] == []


async def test_sans_authentification_refuse(base, client):
    r = await client.get("/api/recherche/hybride", params={"q": "x"})
    assert r.status_code in (401, 403)
