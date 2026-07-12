"""Tests de la phase « yeux » du ciblage (S165 phase 2) — capture de zone → OCR vision.

Offline : la brique vision (5960) est simulée en remplaçant le client HTTP du module.
    $ cd core && python3 -m pytest test_yeux.py -q
"""
import asyncio
import contextlib
import os
import tempfile

os.environ.setdefault("ASSISTANT_CONFIG_PATH", os.path.join(tempfile.mkdtemp(), "cfg.json"))
os.environ.setdefault("GATEWAY_KEY", "sk-test-local")
os.environ.pop("VISION_URL", None)   # pas d'override d'URL : on teste via le registre

import httpx  # noqa: E402

import ciblage  # noqa: E402


class _FauxRegistre:
    def __init__(self, briques):
        self.briques = briques


REGISTRE = _FauxRegistre({"vision": {"nom": "vision", "port": 5960}})
SANS_VISION = _FauxRegistre({})
CAPTURE = {"data": "aGVsbG8=", "nom_fichier": "capture-zone.jpg"}


class _FauxReponse:
    def __init__(self, corps, statut=200):
        self._corps = corps
        self.status_code = statut

    def json(self):
        if isinstance(self._corps, Exception):
            raise self._corps
        return self._corps


@contextlib.contextmanager
def _vision(corps=None, statut=200, exc=None):
    """La brique vision simulée : POST /lire → `corps` (ou lève `exc`)."""

    class _FauxClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None):
            assert url.endswith("/lire")
            if exc is not None:
                raise exc
            return _FauxReponse(corps, statut)

    origine = ciblage.httpx.AsyncClient
    ciblage.httpx.AsyncClient = _FauxClient
    try:
        yield
    finally:
        ciblage.httpx.AsyncClient = origine


def test_sans_capture_rien_ne_change():
    # Pas de capture (ou data vide) → '' et instructions strictement inchangées,
    # sans le moindre appel HTTP (aucun faux client posé : un appel planterait).
    assert asyncio.run(ciblage.contexte_capture(None, REGISTRE)) == ""
    assert asyncio.run(ciblage.contexte_capture({"data": "  "}, REGISTRE)) == ""
    assert asyncio.run(ciblage.fusionner_capture(None, None, REGISTRE)) is None
    assert asyncio.run(ciblage.fusionner_capture("projet X", None, REGISTRE)) == "projet X"


def test_capture_lue_injectee():
    with _vision({"texte": "Agenda : 3 rendez-vous jeudi", "backend": "tesseract"}):
        ctx = asyncio.run(ciblage.contexte_capture(CAPTURE, REGISTRE))
    assert ctx.startswith("Yeux")
    assert "Agenda : 3 rendez-vous jeudi" in ctx
    assert "erreurs" in ctx          # l'OCR est présenté comme faillible, pas comme la vérité


def test_texte_ocr_plafonne():
    long_texte = "x" * (ciblage.MAX_TEXTE_CAPTURE + 500)
    with _vision({"texte": long_texte}):
        ctx = asyncio.run(ciblage.contexte_capture(CAPTURE, REGISTRE))
    assert "…[tronqué]" in ctx
    assert len(ctx) < ciblage.MAX_TEXTE_CAPTURE + 200   # coût LLM borné (S138)


def test_vision_absente_note_honnete():
    # Brique hors registre → on LE DIT, sans tenter d'appel (aucun faux client posé).
    ctx = asyncio.run(ciblage.contexte_capture(CAPTURE, SANS_VISION))
    assert "PAS pu la lire" in ctx
    assert "absente du registre" in ctx


def test_vision_injoignable_note_honnete():
    with _vision(exc=httpx.ConnectError("boom")):
        ctx = asyncio.run(ciblage.contexte_capture(CAPTURE, REGISTRE))
    assert "PAS pu la lire" in ctx and "pas répondu" in ctx


def test_vision_refuse_note_honnete():
    with _vision({"detail": "clé invalide"}, statut=403):
        ctx = asyncio.run(ciblage.contexte_capture(CAPTURE, REGISTRE))
    assert "PAS pu la lire" in ctx


def test_ocr_ne_lit_rien_note_honnete():
    # Repli placeholder de la brique (aucun moteur OCR) : la note remonte telle quelle.
    with _vision({"texte": "", "place_holder": True, "note": "Aucun moteur OCR configuré"}):
        ctx = asyncio.run(ciblage.contexte_capture(CAPTURE, REGISTRE))
    assert "rien lu" in ctx
    assert "Aucun moteur OCR configuré" in ctx


def test_fusion_projet_ciblage_yeux():
    # Les trois étages s'empilent : projet, puis ciblage, puis yeux.
    instructions = ciblage.fusionner_instructions("projet X", None, REGISTRE)
    with _vision({"texte": "Zone visible"}):
        tout = asyncio.run(ciblage.fusionner_capture(instructions, CAPTURE, REGISTRE))
    assert tout.startswith("projet X")
    assert "Yeux" in tout and "Zone visible" in tout
    # Capture seule (sans projet ni cible) → le contexte des yeux, tel quel.
    with _vision({"texte": "Zone visible"}):
        seul = asyncio.run(ciblage.fusionner_capture(None, CAPTURE, REGISTRE))
    assert seul.startswith("Yeux")


if __name__ == "__main__":
    for nom, fn in list(globals().items()):
        if nom.startswith("test_") and callable(fn):
            fn()
            print(f"  ✓ {nom}")
    print("\n✅ TOUS LES TESTS PASSENT")
