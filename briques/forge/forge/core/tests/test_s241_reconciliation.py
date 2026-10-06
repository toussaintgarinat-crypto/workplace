"""S241 — réconciliation : PostgreSQL fait foi, Qdrant se reconstruit."""
from sqlalchemy import text

from app import memory, recherche_reindexer
from app.reconciliation import reconcilier_index
from tests.s241_outils import (  # noqa: F401
    ajouter_article, ajouter_document, base, embedder_coupe, embedder_factice, integration,
)

pytestmark = integration
TEXTE = "Procès-verbal de réception des travaux de toiture, signé sans réserve."


async def _ids(user_id, q=TEXTE):
    return {f.source_id for f in await memory.chercher_fragments(q, user_id)}


async def test_rattrape_un_document_jamais_vectorise(base, embedder_factice):
    doc = await ajouter_document("alice", "PV", TEXTE)
    assert await _ids("alice") == set()
    bilan = await reconcilier_index()
    assert bilan["revectorises"] == 1 and bilan["restants"] == 0 and not bilan["arret_sur_echec"]
    assert await _ids("alice") == {str(doc)}


async def test_supprime_les_orphelins(base, embedder_factice):
    await memory.indexer_source(TEXTE, "33333333-3333-3333-3333-333333333333", "document", "alice", "fantôme")
    bilan = await reconcilier_index()
    assert bilan["orphelins_supprimes"] == 1
    assert await _ids("alice") == set()


async def test_bilan_honnete_si_la_suppression_d_un_orphelin_echoue(base, embedder_factice, monkeypatch):
    await memory.indexer_source(TEXTE, "44444444-4444-4444-4444-444444444444", "document", "alice", "fantôme")

    async def _echec(*a, **k):
        raise RuntimeError("qdrant en panne")

    monkeypatch.setattr(memory._client(), "delete", _echec)
    bilan = await reconcilier_index()
    assert bilan["orphelins_supprimes"] == 0 and bilan["arret_sur_echec"] is True


async def test_nettoie_les_fragments_d_une_source_devenue_trop_courte(base, embedder_factice):
    doc = await ajouter_document("alice", "PV", TEXTE)
    await memory.indexer_source(TEXTE, str(doc), "document", "alice", "PV")
    assert await _ids("alice") == {str(doc)}
    from app.db import SessionLocal
    async with SessionLocal() as s:
        await s.execute(text("UPDATE documents SET contenu = 'ok' WHERE id = :i"), {"i": doc})
        await s.commit()
    bilan = await reconcilier_index()
    assert bilan["perimes_supprimes"] == 1 and bilan["revectorises"] == 0
    assert await _ids("alice") == set()


async def test_corrige_un_fragment_mal_attribue(base, embedder_factice):
    doc = await ajouter_article("alice", "PV", TEXTE)
    await memory.indexer_source(TEXTE, str(doc), "kb_article", "bob", "PV")
    await reconcilier_index()
    assert await _ids("bob") == set() and await _ids("alice") == {str(doc)}


async def test_texte_trop_court_jamais_retente(base, embedder_factice):
    await ajouter_document("alice", "court", "ok")  # aucun fragment (< 20 caractères)
    assert (await reconcilier_index())["revectorises"] == 0


async def test_s_arrete_au_premier_echec(base, embedder_coupe):
    await ajouter_document("alice", "A", TEXTE)
    await ajouter_document("alice", "B", TEXTE + " Copie.")
    bilan = await reconcilier_index()
    assert bilan["arret_sur_echec"] is True and bilan["revectorises"] == 0 and bilan["restants"] == 2


async def test_respecte_la_taille_du_lot(base, embedder_factice):
    for i in range(3):
        await ajouter_document("alice", f"D{i}", f"{TEXTE} Exemplaire numéro {i}.")
    bilan = await reconcilier_index(lot=2)
    assert bilan["revectorises"] == 2 and bilan["restants"] == 1


async def test_reindexer_reconstruit_tout(base, embedder_factice):
    from app.db import engine
    doc = await ajouter_document("alice", "PV", TEXTE)
    await reconcilier_index()
    client = memory._client()
    await client.delete_collection("forge_local")
    assert await recherche_reindexer.principal() == 0
    assert await _ids("alice") == {str(doc)}
    async with engine.connect() as conn:  # rien n'a touché PostgreSQL
        assert (await conn.execute(text("SELECT count(*) FROM documents"))).scalar_one() == 1
