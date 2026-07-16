import os, tempfile, importlib


def _mod(tmp):
    os.environ["CONNEXION_DIR"] = tmp
    import appareils, stockage
    importlib.reload(stockage); importlib.reload(appareils)
    return appareils


def test_enregistrer_puis_resoudre(tmp_path):
    ap = _mod(str(tmp_path))
    appareil = {"endpoint": "https://push.example/AAA", "keys": {"p256dh": "k1", "auth": "k2"}, "ua": "Firefox"}
    ap.enregistrer("marina", appareil)
    trouve = ap.par_endpoint("https://push.example/AAA")
    assert trouve["utilisateur"] == "marina"
    assert trouve["keys"]["auth"] == "k2"
    assert ap.endpoints_de("marina") == ["https://push.example/AAA"]


def test_enregistrer_idempotent_et_retirer(tmp_path):
    ap = _mod(str(tmp_path))
    appareil = {"endpoint": "https://push.example/BBB", "keys": {"p256dh": "x", "auth": "y"}}
    ap.enregistrer("marina", appareil)
    ap.enregistrer("marina", appareil)  # 2e fois = pas de doublon
    assert ap.endpoints_de("marina") == ["https://push.example/BBB"]
    assert ap.retirer("https://push.example/BBB") is True
    assert ap.par_endpoint("https://push.example/BBB") is None
    assert ap.retirer("inconnu") is False
