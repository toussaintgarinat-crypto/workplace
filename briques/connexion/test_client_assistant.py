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


# ── S245 : appels d'approbation vers le Cœur (clé partagée, fail closed) ─────────
import asyncio

import httpx


class _Rep:
    def __init__(self, data):
        self._d = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._d


def _faux_httpx(monkeypatch, appels):
    class _C:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None):
            appels.append((url, json, headers))
            return _Rep({"ok": True})

    monkeypatch.setattr(CA.httpx, "AsyncClient", _C)


def test_approbation_envoie_la_cle_partagee(monkeypatch):
    monkeypatch.setenv("APPROBATIONS_CLE", "cle-secrete")
    monkeypatch.setenv("NOYAU_ASSISTANT_URL", "http://coeur:5100")
    appels = []
    _faux_httpx(monkeypatch, appels)
    asyncio.run(CA.decider_approbation("a" * 32, "ok", "telegram:42", "alice"))
    asyncio.run(CA.armer_code("a" * 32, "telegram:42", "alice"))
    asyncio.run(CA.soumettre_code("telegram:42", "123456", "alice"))
    assert [a[0] for a in appels] == [
        f"http://coeur:5100/approbations/{'a' * 32}/decision",
        f"http://coeur:5100/approbations/{'a' * 32}/code/armer",
        "http://coeur:5100/approbations/code"]
    assert all(a[2] == {"X-Approbations-Cle": "cle-secrete"} for a in appels)
    assert appels[0][1] == {"decision": "ok", "par": "telegram:42", "utilisateur": "alice",
                           "canal": "telegram"}
    assert appels[1][1] == {"par": "telegram:42", "utilisateur": "alice"}
    assert appels[2][1] == {"par": "telegram:42", "code": "123456", "utilisateur": "alice"}


@pytest.mark.parametrize("valeur", [None, "", "   "])
def test_approbation_sans_cle_leve_et_n_envoie_rien(monkeypatch, valeur):
    if valeur is None:
        monkeypatch.delenv("APPROBATIONS_CLE", raising=False)
    else:
        monkeypatch.setenv("APPROBATIONS_CLE", valeur)
    appels = []
    _faux_httpx(monkeypatch, appels)
    for coro in (CA.decider_approbation("a" * 32, "ok", "telegram:1", "alice"),
                 CA.armer_code("a" * 32, "telegram:1", "alice"),
                 CA.soumettre_code("telegram:1", "123456", "alice")):
        with pytest.raises(RuntimeError):
            asyncio.run(coro)
    assert appels == []
