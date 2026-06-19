"""Mini App Telegram — auth souveraine par initData (S77).

Le point critique = la validation HMAC de l'`initData` : on prouve qu'un initData
correctement SIGNÉ passe, qu'un hash falsifié ou un horodatage périmé est REFUSÉ, et que
l'autorisation s'appuie sur le consentement (`correspondance`) + l'allowlist fail-closed.
On forge des initData signés avec un token connu (même algorithme que Telegram).

Pytest (conftest.py pose CONNEXION_DIR en tmp, tokens purgés). Autonome, aucun réseau.
"""
import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

from fastapi.testclient import TestClient

import main
import miniapp

# IDs Telegram HAUTS et uniques : la table correspondance est persistée pour toute la
# session pytest (un seul CONNEXION_DIR) et `resoudre` ne fixe le statut qu'à la création
# → on évite toute collision avec les ids d'autres fichiers de test (ex. 555 dans test_main).
TOKEN = "123456:AA-test-bot-token"
USER = {"id": 70000042, "first_name": "Toussaint", "username": "touss"}

client = TestClient(main.app)


def _signer(token=TOKEN, user=USER, auth_date=None, extra=None):
    """Construit un initData VALIDE (même calcul que Telegram)."""
    champs = {"auth_date": str(auth_date or int(time.time())),
              "user": json.dumps(user, separators=(",", ":"))}
    if extra:
        champs.update(extra)
    chaine = "\n".join(f"{k}={champs[k]}" for k in sorted(champs))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    champs["hash"] = hmac.new(secret, chaine.encode(), hashlib.sha256).hexdigest()
    return urlencode(champs)


# ── Validation de signature ──────────────────────────────────────────────────
def test_init_data_valide():
    d = miniapp.valider_init_data(_signer(), TOKEN)
    assert d is not None and d["user"]["id"] == 70000042


def test_hash_falsifie_refuse():
    forge = _signer()[:-3] + "000"          # on abîme le hash
    assert miniapp.valider_init_data(forge, TOKEN) is None


def test_mauvais_token_refuse():
    assert miniapp.valider_init_data(_signer(), "autre:token") is None


def test_horodatage_perime_refuse():
    vieux = _signer(auth_date=int(time.time()) - 999999)
    assert miniapp.valider_init_data(vieux, TOKEN, age_max_s=3600) is None
    # sans plafond d'âge, la signature reste valide.
    assert miniapp.valider_init_data(vieux, TOKEN, age_max_s=0) is not None


# ── Autorisation (consentement + allowlist) ──────────────────────────────────
def test_bot_non_configure(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    assert miniapp.autoriser(_signer())["raison"] == "bot_non_configure"


def test_consentement_requis_par_defaut(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("CONNEXION_OUVERT", "0")
    monkeypatch.delenv("TELEGRAM_MINIAPP_USERS", raising=False)
    res = miniapp.autoriser(_signer(user={"id": 70000777, "first_name": "Inconnu"}))
    assert res["ok"] is False and res["raison"] == "consentement_requis"
    assert res["code"]                                   # un code de liaison est proposé


def test_autorise_en_mode_ouvert(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("CONNEXION_OUVERT", "1")
    monkeypatch.setenv("CONNEXION_UTILISATEUR_DEFAUT", "perso")
    monkeypatch.delenv("TELEGRAM_MINIAPP_USERS", raising=False)
    res = miniapp.autoriser(_signer(user={"id": 70000555, "first_name": "Ami"}))
    assert res["ok"] is True and res["utilisateur"] == "perso" and res["nom"] == "Ami"


def test_allowlist_fail_closed(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("CONNEXION_OUVERT", "1")
    monkeypatch.setenv("TELEGRAM_MINIAPP_USERS", "111,222")     # 4242 absent
    res = miniapp.autoriser(_signer())
    assert res["ok"] is False and res["raison"] == "non_autorise_allowlist"


# ── Endpoint /miniapp/auth ────────────────────────────────────────────────────
def test_endpoint_auth_invalide(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    r = client.post("/miniapp/auth", json={"init_data": "user=%7B%7D&hash=deadbeef"})
    assert r.status_code == 200 and r.json()["ok"] is False


def test_endpoint_auth_ok(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("CONNEXION_OUVERT", "1")
    monkeypatch.setenv("CONNEXION_UTILISATEUR_DEFAUT", "perso")
    monkeypatch.delenv("TELEGRAM_MINIAPP_USERS", raising=False)
    r = client.post("/miniapp/auth", json={"init_data": _signer()})
    assert r.status_code == 200 and r.json()["ok"] is True


def test_chat_refuse_sans_auth(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    r = client.post("/miniapp/chat", json={"messages": [{"role": "user", "content": "hi"}],
                                           "init_data": "bidon"})
    assert r.status_code == 401


def test_page_servie():
    r = client.get("/miniapp")
    assert r.status_code == 200 and "telegram-web-app.js" in r.text
