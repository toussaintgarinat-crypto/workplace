"""Tests du client assistant : parsing du flux SSE + accumulation du texte (hors réseau)."""
import pytest

import client_assistant as CA

SSE = (
    'data: {"type": "texte_delta", "contenu": "Il y"}\n\n'
    'data: {"type": "texte_delta", "contenu": " a 3"}\n\n'
    'data: {"type": "outil", "nom": "lister_entreprises"}\n\n'
    'data: {"type": "texte_delta", "contenu": " entreprises."}\n\n'
    'data: {"type": "fin"}\n\n'
)


def test_lire_sse():
    evts = CA.lire_sse(SSE)
    assert [e["type"] for e in evts] == ["texte_delta", "texte_delta", "outil",
                                         "texte_delta", "fin"]


def test_accumuler_texte():
    assert CA.accumuler(CA.lire_sse(SSE)) == "Il y a 3 entreprises."


def test_accumuler_verbeux_montre_outil():
    sortie = CA.accumuler(CA.lire_sse(SSE), verbeux=True)
    assert "lister_entreprises" in sortie


def test_accumuler_erreur_leve():
    evts = CA.lire_sse('data: {"type": "erreur", "contenu": "boum"}\n\n')
    with pytest.raises(RuntimeError, match="boum"):
        CA.accumuler(evts)


def test_lire_sse_ignore_lignes_non_data():
    assert CA.lire_sse(": commentaire\n\ndata: {\"type\":\"texte\",\"contenu\":\"ok\"}\n") \
        == [{"type": "texte", "contenu": "ok"}]
