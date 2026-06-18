"""Tests — registre OCR provider-agnostique (cascade + parsing hébergés, sans réseau réel)."""
import asyncio

import fournisseurs


def _run(coro):
    return asyncio.run(coro)


# ── Fake httpx pour tester le parsing des moteurs hébergés sans réseau ──────────
class _FakeResp:
    def __init__(self, payload):
        self._p = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._p


class _FakeClient:
    def __init__(self, payload, sink):
        self._p, self._sink = payload, sink

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, headers=None, json=None):
        self._sink.update(url=url, headers=headers, json=json)
        return _FakeResp(self._p)


def _brancher(monkeypatch, payload):
    sink = {}
    monkeypatch.setattr(fournisseurs.httpx, "AsyncClient",
                        lambda **kw: _FakeClient(payload, sink))
    return sink


# ── Registre & ordre ───────────────────────────────────────────────────────────
def test_registre_contient_les_quatre_moteurs():
    assert set(fournisseurs.REGISTRE) == {"markitdown", "tesseract", "mistral", "google"}


def test_ordre_par_defaut_souverain_dabord():
    assert fournisseurs.ordre()[:2] == ["markitdown", "tesseract"]


def test_ordre_surchargeable_et_filtre_les_inconnus(monkeypatch):
    monkeypatch.setenv("VISION_PROVIDERS", "google, nexistepas ,mistral")
    assert fournisseurs.ordre() == ["google", "mistral"]


def test_aucun_moteur_configure_en_test():
    # conftest : VISION_LOCAL=0 + aucune clé → cascade vide, repli honnête garanti.
    assert fournisseurs.disponibles() == []


# ── Disponibilité ────────────────────────────────────────────────────────────────
def test_locaux_neutralises_par_kill_switch(monkeypatch):
    monkeypatch.setenv("VISION_LOCAL", "0")
    assert fournisseurs.MarkItDown().disponible() is False
    assert fournisseurs.Tesseract().disponible() is False


def test_mistral_disponible_avec_cle(monkeypatch):
    monkeypatch.setenv("MISTRAL_API_KEY", "sk-test")
    assert fournisseurs.Mistral().disponible() is True


def test_google_disponible_avec_cle(monkeypatch):
    monkeypatch.delenv("GOOGLE_VISION_API_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "g-test")     # repli sur la clé générique
    assert fournisseurs.Google().disponible() is True


# ── Parsing des réponses hébergées ──────────────────────────────────────────────
def test_mistral_concatene_le_markdown_des_pages(monkeypatch):
    monkeypatch.setenv("MISTRAL_API_KEY", "sk-test")
    sink = _brancher(monkeypatch, {"pages": [{"markdown": "# Titre"}, {"markdown": "corps"}]})
    texte = _run(fournisseurs.Mistral().extraire(b"%PDF-1.4", "f.pdf", "application/pdf"))
    assert texte == "# Titre\n\ncorps"
    assert sink["json"]["document"]["type"] == "document_url"   # PDF → document_url


def test_mistral_image_passe_par_image_url(monkeypatch):
    monkeypatch.setenv("MISTRAL_API_KEY", "sk-test")
    sink = _brancher(monkeypatch, {"pages": [{"markdown": "ok"}]})
    _run(fournisseurs.Mistral().extraire(b"\x89PNG", "f.png", "image/png"))
    assert sink["json"]["document"]["type"] == "image_url"


def test_google_lit_full_text_annotation(monkeypatch):
    monkeypatch.setenv("GOOGLE_VISION_API_KEY", "g-test")
    _brancher(monkeypatch, {"responses": [{"fullTextAnnotation": {"text": "Bonjour"}}]})
    assert _run(fournisseurs.Google().extraire(b"img", "f.png", "image/png")) == "Bonjour"


def test_google_repli_sur_text_annotations(monkeypatch):
    monkeypatch.setenv("GOOGLE_VISION_API_KEY", "g-test")
    _brancher(monkeypatch, {"responses": [{"textAnnotations": [{"description": "Salut"}]}]})
    assert _run(fournisseurs.Google().extraire(b"img", "f.png", "image/png")) == "Salut"
