"""Priorité d'identité du chat de l'assistant (S173) : `utilisateur` explicite du corps
(Telegram/S2S) prime toujours sur la session web ; la session ne sert que de repli.

Fonction pure, testée directement — pas besoin de TestClient ni de mocker le flux SSE
(le reste du handler `assistant_chat` est inchangé par ce sprint).

$ cd core && python3 -m pytest test_assistant_routes.py -v
"""
import os

os.environ.setdefault("VAULT_SECRET", "test-secret-0123456789")
os.environ.setdefault("GATEWAY_KEY", "test")
os.environ.setdefault("AUTH_SESSION_SECRET", "test-session-secret-0123456789")

import auth  # noqa: E402
from routers.assistant import _resoudre_utilisateur  # noqa: E402
from test_auth import _fake_request  # noqa: E402


def test_utilisateur_explicite_du_corps_garde_la_priorite():
    cookie = auth.chiffrer_cookie({"sub": "marina", "refresh_token": "rt-1"})
    corps = {"utilisateur": "telegram-perso"}
    r = _resoudre_utilisateur(corps, _fake_request({auth.COOKIE_SESSION: cookie}))
    assert r == "telegram-perso"


def test_pas_de_corps_mais_session_valide_utilise_le_sub():
    cookie = auth.chiffrer_cookie({"sub": "marina", "refresh_token": "rt-1"})
    r = _resoudre_utilisateur({}, _fake_request({auth.COOKIE_SESSION: cookie}))
    assert r == "marina"


def test_ni_corps_ni_session_renvoie_none():
    r = _resoudre_utilisateur({}, _fake_request({}))
    assert r is None
