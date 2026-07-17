import os, importlib
from unittest.mock import patch, MagicMock


def _setup(tmp_path):
    os.environ["CONNEXION_DIR"] = str(tmp_path)
    os.environ["VAPID_PRIVATE_KEY"] = "cle-privee-factice"
    os.environ["VAPID_SUBJECT"] = "mailto:admin@example.org"
    import stockage, appareils, adaptateurs
    importlib.reload(stockage); importlib.reload(appareils); importlib.reload(adaptateurs)
    return appareils, adaptateurs


def test_configure_selon_env(tmp_path):
    _, ad = _setup(tmp_path)
    assert ad.obtenir("webpush").configure() is True
    del os.environ["VAPID_PRIVATE_KEY"]
    importlib.reload(ad)
    assert ad.obtenir("webpush").configure() is False


def test_envoyer_appelle_pywebpush(tmp_path):
    ap, ad = _setup(tmp_path)
    ap.enregistrer("marina", {"endpoint": "https://push/AAA", "keys": {"p256dh": "p", "auth": "a"}})
    with patch("adaptateurs.webpush") as wp:
        import asyncio
        ok = asyncio.run(
            ad.obtenir("webpush").envoyer("https://push/AAA", "🔔 Titre\nCorps"))
    assert ok is True
    assert wp.called
    payload = wp.call_args.kwargs.get("data") or wp.call_args.args[1]
    assert "Titre" in payload and "Corps" in payload


def test_envoyer_410_purge_appareil(tmp_path):
    ap, ad = _setup(tmp_path)
    ap.enregistrer("marina", {"endpoint": "https://push/GONE", "keys": {"p256dh": "p", "auth": "a"}})
    import correspondance
    importlib.reload(correspondance)
    correspondance.lier("webpush", "https://push/GONE", "marina")
    from pywebpush import WebPushException
    resp = MagicMock(); resp.status_code = 410
    exc = WebPushException("gone"); exc.response = resp
    with patch("adaptateurs.webpush", side_effect=exc):
        import asyncio
        ok = asyncio.run(
            ad.obtenir("webpush").envoyer("https://push/GONE", "🔔 x\ny"))
    assert ok is False
    assert ap.par_endpoint("https://push/GONE") is None
    assert ("webpush", "https://push/GONE") not in correspondance.cibles_pour("marina")
