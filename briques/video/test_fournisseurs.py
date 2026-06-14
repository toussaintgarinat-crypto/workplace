"""Tests — registre des fournisseurs vidéo (formes de requête + extraction, SANS réseau).

On ne touche jamais le réseau : on vérifie la requête que CHAQUE fournisseur construirait
(URL, en-tête d'auth, corps), l'extraction de vidéo quelle que soit la forme de réponse,
le polling (URL de statut) et la sélection (ordre/disponibilité). Les appels live se
prouvent ailleurs (clés réelles)."""
import asyncio
import base64

import fournisseurs as F


# ── _cherche_video : robuste aux conventions de chaque fournisseur ──
def test_extraction_fal_video():
    assert F._cherche_video({"video": {"url": "http://x/y.mp4"}}) == ("url", "http://x/y.mp4")


def test_extraction_replicate_url_simple():
    assert F._cherche_video({"output": "http://x/z.webm"}) == ("url", "http://x/z.webm")


def test_extraction_replicate_liste():
    assert F._cherche_video({"output": ["http://x/a.mp4", "http://x/b.mp4"]})[1] == "http://x/a.mp4"


def test_extraction_luma_assets():
    assert F._cherche_video({"assets": {"video": "http://x/c.mp4"}}) == ("url", "http://x/c.mp4")


def test_extraction_runway_output():
    assert F._cherche_video({"status": "SUCCEEDED", "output": ["http://x/d.mp4"]})[1] == "http://x/d.mp4"


def test_extraction_data_uri_video():
    assert F._cherche_video("data:video/mp4;base64,QUJD") == ("b64", "data:video/mp4;base64,QUJD")


def test_ne_confond_pas_une_vignette_image():
    # une URL d'image (vignette) ne doit JAMAIS être prise pour la vidéo
    assert F._cherche_video({"thumbnail_url": "http://x/thumb.png"}) is None
    assert F._cherche_video({"url": "http://x/preview.jpg"}) is None


def test_extraction_rien():
    assert F._cherche_video({"error": "quota"}) is None
    assert F._cherche_video(None) is None


def test_resoudre_b64_decode():
    data = asyncio.run(F._resoudre(None, ("b64", base64.b64encode(b"hello").decode())))
    assert data == b"hello"


# ── formes de requête (on ne POST pas : on lit ce qui SERAIT envoyé) ──
def test_requete_fal(monkeypatch):
    monkeypatch.setenv("FAL_KEY", "fk")
    monkeypatch.setenv("FAL_VIDEO_MODEL", "fal-ai/kling-video/v2/master/text-to-video")
    f = F.Fal()
    assert f.disponible() is True
    url, headers, body = f._requete("un dragon qui vole", "", 5, 7)
    assert url == "https://queue.fal.run/fal-ai/kling-video/v2/master/text-to-video"
    assert headers["Authorization"] == "Key fk"
    assert body["prompt"] == "un dragon qui vole" and body["seed"] == 7
    # image→vidéo : l'image de départ est transmise
    _, _, body2 = f._requete("anime ce perso", "http://b/img.png", 5, None)
    assert body2["image_url"] == "http://b/img.png"


def test_fal_statut_url_depuis_la_soumission():
    assert F.Fal()._statut_url({"response_url": "http://q/req/1"}) == "http://q/req/1"
    assert F.Fal()._statut_url({"status_url": "http://q/st/1"}) == "http://q/st/1"


def test_requete_replicate_synchrone(monkeypatch):
    monkeypatch.setenv("REPLICATE_API_TOKEN", "rt")
    url, headers, body = F.Replicate()._requete("loup", "", 5, None)
    assert headers["Prefer"] == "wait"                 # synchrone, polling en repli
    assert headers["Authorization"] == "Bearer rt"
    assert body["input"]["prompt"] == "loup"
    assert F.Replicate()._statut_url({"urls": {"get": "http://r/p/1"}}) == "http://r/p/1"


def test_requete_luma(monkeypatch):
    monkeypatch.setenv("LUMAAI_API_KEY", "lk")
    f = F.Luma()
    assert f.disponible() is True
    url, headers, body = f._requete("une cité flottante", "", 5, None)
    assert url.endswith("/dream-machine/v1/generations")
    assert headers["Authorization"] == "Bearer lk"
    assert body["model"] == "ray-2"
    assert f._statut_url({"id": "abc"}).endswith("/generations/abc")
    # image→vidéo : keyframe d'entrée
    _, _, body2 = f._requete("anime", "http://b/p.png", 5, None)
    assert body2["keyframes"]["frame0"]["url"] == "http://b/p.png"


def test_requete_runway(monkeypatch):
    monkeypatch.setenv("RUNWAY_API_KEY", "rk")
    f = F.Runway()
    assert f.disponible() is True
    # text→vidéo
    url, headers, body = f._requete("tempête en mer", "", 5, None)
    assert url.endswith("/v1/text_to_video")
    assert headers["X-Runway-Version"]
    assert body["promptText"] == "tempête en mer"
    # image→vidéo : autre endpoint + image
    url2, _, body2 = f._requete("anime", "http://b/p.png", 5, None)
    assert url2.endswith("/v1/image_to_video") and body2["promptImage"] == "http://b/p.png"
    assert f._statut_url({"id": "t1"}).endswith("/v1/tasks/t1")


def test_requete_gateway(monkeypatch):
    monkeypatch.setenv("GATEWAY_KEY", "sk-wp")
    monkeypatch.setenv("GATEWAY_URL", "http://host.docker.internal:4001")
    f = F.Gateway()
    assert f.disponible() is True                       # GATEWAY_KEY suffit, rien d'autre
    url, headers, body = f._requete("un envol d'oiseaux", "", 5, None)
    assert url == "http://host.docker.internal:4001/v1/chat/completions"
    assert headers["Authorization"] == "Bearer sk-wp"
    assert body["modalities"] == ["video", "text"]      # on demande bien une vidéo
    assert body["messages"][0]["content"].startswith("un envol")


def test_gateway_indisponible_sans_cle(monkeypatch):
    monkeypatch.delenv("GATEWAY_KEY", raising=False)
    assert F.Gateway().disponible() is False


# ── disponibilité & ordre ────────────────────────────────────────
def test_indisponible_sans_cle(monkeypatch):
    for v in ("FAL_KEY", "REPLICATE_API_TOKEN", "LUMAAI_API_KEY", "RUNWAY_API_KEY",
              "GATEWAY_KEY"):
        monkeypatch.delenv(v, raising=False)
    assert F.disponibles() == []


def test_ordre_par_defaut(monkeypatch):
    monkeypatch.delenv("VIDEO_PROVIDERS", raising=False)
    assert F.ordre()[0] == "fal"                        # moteur vidéo natif d'abord


def test_ordre_surcharge(monkeypatch):
    monkeypatch.setenv("VIDEO_PROVIDERS", "gateway, replicate , inconnu")
    assert F.ordre() == ["gateway", "replicate"]        # « inconnu » filtré


def test_disponibles_suit_la_cle(monkeypatch):
    monkeypatch.setenv("VIDEO_PROVIDERS", "fal,runway")
    monkeypatch.setenv("FAL_KEY", "x")
    monkeypatch.delenv("RUNWAY_API_KEY", raising=False)
    assert F.disponibles() == ["fal"]                   # seul fal a sa clé
