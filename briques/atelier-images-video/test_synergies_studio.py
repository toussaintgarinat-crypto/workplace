"""Tests — synergies Studio (portrait/couverture/teaser/animer), proxy avec secret de
service (STUDIO_KEY) + identité relayée. Voir aussi test_galerie.py (même motif de
sécurité, dépendance _identite_service partagée)."""
from fastapi.testclient import TestClient

import main as M

client = TestClient(M.app)


def test_identite_service_mode_ouvert_honore_x_user_id_recu():
    """Sans ATELIER_IMAGES_VIDEO_KEY configurée (mode dev), l'en-tête X-User-Id reçu est
    honoré tel quel — il vient du routeur Cœur de confiance, jamais du navigateur direct
    en déploiement réel."""
    identite = M._identite_service(x_api_key=None, authorization=None, x_user_id="claire")
    assert identite == "claire"


def test_identite_service_mode_ouvert_replie_sur_perso():
    identite = M._identite_service(x_api_key=None, authorization=None, x_user_id=None)
    assert identite == "perso"


def test_identite_service_refuse_sans_bonne_cle(monkeypatch):
    monkeypatch.setenv("ATELIER_IMAGES_VIDEO_KEY", "cle-coeur")
    try:
        M._identite_service(x_api_key="mauvaise-cle", authorization=None, x_user_id="claire")
        assert False, "devait lever 401"
    except Exception as e:
        assert getattr(e, "status_code", None) == 401
    finally:
        monkeypatch.delenv("ATELIER_IMAGES_VIDEO_KEY", raising=False)


def test_identite_service_accepte_avec_la_bonne_cle(monkeypatch):
    monkeypatch.setenv("ATELIER_IMAGES_VIDEO_KEY", "cle-coeur")
    try:
        identite = M._identite_service(x_api_key="cle-coeur", authorization=None, x_user_id="claire")
        assert identite == "claire"
    finally:
        monkeypatch.delenv("ATELIER_IMAGES_VIDEO_KEY", raising=False)


def test_entetes_studio_porte_la_cle_et_lidentite(monkeypatch):
    monkeypatch.setenv("STUDIO_KEY", "cle-studio")
    assert M._entetes_studio("claire") == {"X-API-Key": "cle-studio", "X-User-Id": "claire"}


def test_entetes_memoire_porte_la_cle_et_lidentite(monkeypatch):
    monkeypatch.setenv("MEMOIRE_KEY", "cle-memoire")
    assert M._entetes_memoire("claire") == {"X-API-Key": "cle-memoire", "X-User-Id": "claire"}
