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


# ── Pièces jointes (S196) : collecte des médias via `url_interne` ────────────

SSE_AVEC_IMAGE = (
    'data: {"type": "texte_delta", "contenu": "Voici ton image."}\n\n'
    'data: {"type": "resultat_outil", "nom": "image_generer", '
    '"resultat": "{\\"url\\": \\"/brique-fichiers/images/img-abc.png\\", '
    '\\"url_interne\\": \\"http://host.docker.internal:5950/fichiers/img-abc.png\\"}"}\n\n'
    'data: {"type": "fin"}\n\n'
)


def test_accumuler_sans_medias_ignore_resultat_outil():
    # Comportement historique inchangé : sans `medias=`, resultat_outil est ignoré.
    assert CA.accumuler(CA.lire_sse(SSE_AVEC_IMAGE)) == "Voici ton image."


def test_accumuler_avec_medias_collecte_url_interne():
    medias = []
    texte = CA.accumuler(CA.lire_sse(SSE_AVEC_IMAGE), medias=medias)
    assert texte == "Voici ton image."
    assert medias == [{"url": "http://host.docker.internal:5950/fichiers/img-abc.png",
                       "nom": "image_generer"}]


def test_accumuler_resultat_sans_url_interne_ignore():
    evts = CA.lire_sse(
        'data: {"type": "resultat_outil", "nom": "lister_entreprises", '
        '"resultat": "{\\"ok\\": true}"}\n\n')
    medias = []
    CA.accumuler(evts, medias=medias)
    assert medias == []
