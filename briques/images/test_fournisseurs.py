"""Tests — registre des fournisseurs (formes de requête + extraction d'image, SANS réseau).

On ne touche jamais le réseau : on vérifie la requête que CHAQUE fournisseur construirait
(URL, en-tête d'auth, corps), l'extraction d'image quelle que soit la forme de réponse, et
la sélection (ordre/disponibilité). Les appels live se prouvent ailleurs (clés réelles).
"""
import asyncio
import base64

import fournisseurs as F


# ── _cherche_image : robuste aux conventions de chaque fournisseur ──
def test_extraction_fal():
    assert F._cherche_image({"images": [{"url": "http://x/y.png"}]}) == ("url", "http://x/y.png")


def test_extraction_replicate_url_simple():
    assert F._cherche_image({"output": "http://x/z.webp"}) == ("url", "http://x/z.webp")


def test_extraction_replicate_liste():
    assert F._cherche_image({"output": ["http://x/a.png", "http://x/b.png"]})[1] == "http://x/a.png"


def test_extraction_openai_b64():
    assert F._cherche_image({"data": [{"b64_json": "QUJD"}]}) == ("b64", "QUJD")


def test_extraction_gemini_inline_data():
    rep = {"candidates": [{"content": {"parts": [
        {"text": "voici"}, {"inlineData": {"mimeType": "image/png", "data": "QUJD"}}]}}]}
    assert F._cherche_image(rep) == ("b64", "QUJD")


def test_extraction_openrouter_chat_image():
    # forme OpenRouter via la Gateway : image dans choices[].message.images[].image_url.url
    rep = {"choices": [{"message": {"role": "assistant", "content": "voilà",
        "images": [{"type": "image_url", "image_url": {"url": "data:image/png;base64,QUJD"}}]}}]}
    assert F._cherche_image(rep) == ("b64", "data:image/png;base64,QUJD")


def test_extraction_rien():
    assert F._cherche_image({"error": "quota"}) is None
    assert F._cherche_image(None) is None


def test_resoudre_b64_decode():
    data = asyncio.run(F._resoudre(None, ("b64", base64.b64encode(b"hello").decode())))
    assert data == b"hello"


# ── formes de requête (on ne POST pas : on lit ce qui SERAIT envoyé) ──
def test_requete_gateway(monkeypatch):
    monkeypatch.setenv("GATEWAY_KEY", "sk-wp")
    monkeypatch.setenv("GATEWAY_URL", "http://host.docker.internal:4001")
    f = F.Gateway()
    assert f.disponible() is True                       # GATEWAY_KEY suffit, rien d'autre
    url, headers, body = f._requete("un dragon", "flou", 1024, 1024, None)
    assert url == "http://host.docker.internal:4001/v1/chat/completions"
    assert headers["Authorization"] == "Bearer sk-wp"
    assert body["modalities"] == ["image", "text"]      # on demande bien une image
    assert body["model"] == "google/gemini-2.5-flash-image"   # Nano Banana par défaut
    assert body["messages"][0]["content"].startswith("un dragon")


def test_gateway_indisponible_sans_cle(monkeypatch):
    monkeypatch.delenv("GATEWAY_KEY", raising=False)
    assert F.Gateway().disponible() is False


def test_gateway_modele_surchargeable(monkeypatch):
    monkeypatch.setenv("GATEWAY_KEY", "k")
    monkeypatch.setenv("IMAGE_GATEWAY_MODEL", "black-forest-labs/flux-1.1-pro")
    _, _, body = F.Gateway()._requete("x", "", 1024, 1024, None)
    assert body["model"] == "black-forest-labs/flux-1.1-pro"


def test_requete_nanobanana(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k-test")
    f = F.NanoBanana()
    assert f.disponible() is True
    url, headers, body = f._requete("un phare", "flou", 1024, 1024, None)
    assert "gemini" in url and "k-test" in url
    assert body["contents"][0]["parts"][0]["text"].startswith("un phare")


def test_requete_fal(monkeypatch):
    monkeypatch.setenv("FAL_KEY", "fk")
    monkeypatch.setenv("FAL_MODEL", "fal-ai/flux/dev")
    url, headers, body = F.Fal()._requete("chat", "", 512, 768, 7)
    assert url == "https://fal.run/fal-ai/flux/dev"
    assert headers["Authorization"] == "Key fk"
    assert body["image_size"] == {"width": 512, "height": 768} and body["seed"] == 7


def test_requete_replicate_synchrone(monkeypatch):
    monkeypatch.setenv("REPLICATE_API_TOKEN", "rt")
    url, headers, body = F.Replicate()._requete("loup", "", 1024, 1024, None)
    assert headers["Prefer"] == "wait"                 # synchrone, pas de polling
    assert headers["Authorization"] == "Bearer rt"
    assert body["input"]["prompt"] == "loup"


def test_requete_openai_taille_proche(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk")
    _, _, body = F.OpenAI()._requete("ville", "", 1600, 900, None)
    assert body["size"] == "1536x1024"                 # paysage → format large autorisé
    assert body["model"] == "gpt-image-1"


def test_taille_openai_mappe_les_formats():
    assert F._taille_openai(1024, 1024) == "1024x1024"
    assert F._taille_openai(768, 1024) == "1024x1536"   # portrait
    assert F._taille_openai(1024, 768) == "1536x1024"   # paysage


def test_requete_pruna(monkeypatch):
    monkeypatch.setenv("PRUNA_API_KEY", "pk")
    url, headers, body = F.Pruna()._requete("fleur", "laid", 1024, 1024, 3)
    assert headers["Authorization"] == "Bearer pk"
    assert body["negative_prompt"] == "laid" and body["seed"] == 3


# ── disponibilité & ordre ────────────────────────────────────────
def test_indisponible_sans_cle(monkeypatch):
    for v in ("FAL_KEY", "REPLICATE_API_TOKEN", "OPENAI_API_KEY", "PRUNA_API_KEY",
              "GEMINI_API_KEY", "GOOGLE_API_KEY", "COMFY_URL", "GATEWAY_KEY"):
        monkeypatch.delenv(v, raising=False)
    assert F.disponibles() == []


def test_ordre_par_defaut(monkeypatch):
    monkeypatch.delenv("IMAGE_PROVIDERS", raising=False)
    assert F.ordre()[0] == "comfyui"                    # souverain d'abord


def test_ordre_surcharge(monkeypatch):
    monkeypatch.setenv("IMAGE_PROVIDERS", "nanobanana, fal , inconnu")
    assert F.ordre() == ["nanobanana", "fal"]           # « inconnu » filtré


def test_disponibles_suit_la_cle(monkeypatch):
    monkeypatch.setenv("IMAGE_PROVIDERS", "fal,openai")
    monkeypatch.setenv("FAL_KEY", "x")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert F.disponibles() == ["fal"]                   # seul fal a sa clé


def test_comfy_urls_liste(monkeypatch):
    monkeypatch.setenv("COMFY_URL", "http://a:8188/ , http://b:8188")
    assert F.ComfyUI().urls() == ["http://a:8188", "http://b:8188"]
