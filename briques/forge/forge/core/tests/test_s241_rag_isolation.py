"""S241 — faille : `_qdrant_search` ne filtrait que pole_id, jamais user_id.

`GET /api/rag/search`, le chat et le ReAct renvoyaient donc les passages des documents de
TOUS les utilisateurs. Ces tests tournent sur un Qdrant réel : un mock n'aurait pas vu que
le filtre manquait."""
import inspect

import pytest

from app import memory
from tests.s241_outils import base, embedder_coupe, embedder_factice, integration  # noqa: F401

TEXTE = "Contrat de maintenance de la chaudière du client Durand, renouvelé chaque année."


def test_get_context_exige_l_utilisateur():
    parametre = inspect.signature(memory.get_context).parameters["user_id"]
    assert parametre.kind is inspect.Parameter.KEYWORD_ONLY
    assert parametre.default is inspect.Parameter.empty


@integration
async def test_get_context_ne_renvoie_que_les_passages_de_l_utilisateur(base, embedder_factice, monkeypatch):
    monkeypatch.setattr(memory, "mem_prefetch", lambda *a, **k: _vide())
    await memory.indexer_source(TEXTE, "11111111-1111-1111-1111-111111111111", "document", "alice", "Contrat")
    assert "chaudière" in await memory.get_context(TEXTE, "s", user_id="alice")
    assert await memory.get_context(TEXTE, "s", user_id="bob") == ""


@integration
async def test_chercher_fragments_filtre_par_utilisateur(base, embedder_factice):
    await memory.indexer_source(TEXTE, "11111111-1111-1111-1111-111111111111", "document", "alice", "Contrat")
    assert [f.source_id for f in await memory.chercher_fragments(TEXTE, "alice")] \
        == ["11111111-1111-1111-1111-111111111111"]
    assert await memory.chercher_fragments(TEXTE, "bob") == []


@integration
async def test_chercher_fragments_signale_la_panne(base, embedder_coupe):
    with pytest.raises(memory.RechercheVectorielleIndisponible):
        await memory.chercher_fragments(TEXTE, "alice")


@integration
async def test_indexer_source_remplace_les_anciens_fragments(base, embedder_factice):
    sid = "22222222-2222-2222-2222-222222222222"
    await memory.indexer_source(TEXTE, sid, "kb_article", "alice", "v1")
    await memory.indexer_source("Nouvelle version : contrat résilié en mars, plus aucune visite.", sid,
                                "kb_article", "alice", "v2")
    fragments = await memory.chercher_fragments("contrat résilié", "alice")
    assert {f.texte for f in fragments} == {"Nouvelle version : contrat résilié en mars, plus aucune visite."}


async def _vide():
    return []
