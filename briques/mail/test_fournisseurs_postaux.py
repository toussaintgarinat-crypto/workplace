"""Routeur postal : mock honnête (aucun prestataire réel branché dans cette itération —
cf. Non-objectifs de la spec)."""
import fournisseurs_postaux as fp


def test_mock_ne_depose_rien_reellement():
    r = fp.MockRouteurPostal().deposer({"id": "c1", "adresse": "12 Rue X"})
    assert r["ok"] is True and r["reel"] is False


def test_routeur_postal_rend_toujours_le_mock():
    assert isinstance(fp.routeur_postal(), fp.MockRouteurPostal)
