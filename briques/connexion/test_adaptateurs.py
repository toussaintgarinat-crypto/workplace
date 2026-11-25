"""Tests des adaptateurs réseaux : ordre/disponibilité, parsing, signatures (hors réseau)."""
import pytest

import adaptateurs as A


# ── Registre / ordre / disponibilité ───────────────────────────────────────────
def test_registre_quatre_reseaux():
    assert set(A.REGISTRE) == {"telegram", "whatsapp", "discord", "email_sms", "webpush"}


def test_disponibles_vide_par_defaut():
    # conftest a purgé tous les tokens → aucun réseau configuré (repli honnête).
    assert A.disponibles() == []


def test_ordre_defaut():
    assert A.ordre() == ["telegram", "whatsapp", "discord", "email_sms", "webpush"]


def test_ordre_env(monkeypatch):
    monkeypatch.setenv("CONNEXION_RESEAUX", "discord, telegram")
    assert A.ordre()[:2] == ["discord", "telegram"]
    assert set(A.ordre()) == set(A.REGISTRE)          # complété par le reste


# ── Telegram ────────────────────────────────────────────────────────────────────
def test_telegram_configure(monkeypatch):
    assert A.REGISTRE["telegram"].configure() is False
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    assert A.REGISTRE["telegram"].configure() is True


def test_telegram_parser():
    upd = {"update_id": 7, "message": {"chat": {"id": 42}, "text": " Bonjour ",
                                       "from": {"first_name": "Garina"}}}
    [e] = A.Telegram().parser_entrant(upd)
    assert e.reseau == "telegram" and e.id_externe == "42"
    assert e.texte == "Bonjour" and e.nom == "Garina"


def test_telegram_parser_sans_texte():
    assert A.Telegram().parser_entrant({"message": {"chat": {"id": 1}}}) == []


def test_telegram_parser_vocal():
    """Un message `voice` (sans texte) est porté comme média audio → transcription par le pont."""
    upd = {"update_id": 8, "message": {
        "chat": {"id": 42}, "from": {"first_name": "Garina"},
        "voice": {"file_id": "AwAC123", "duration": 3, "mime_type": "audio/ogg"}}}
    [e] = A.Telegram().parser_entrant(upd)
    assert e.id_externe == "42" and e.nom == "Garina"
    assert e.texte == "" and e.media_type == "audio"
    assert e.media_id == "AwAC123" and e.media_nom == "voix.ogg"


def test_telegram_parser_audio_fichier():
    """Un fichier `audio` garde son extension d'origine (utile au moteur STT)."""
    upd = {"message": {"chat": {"id": 7},
                       "audio": {"file_id": "Aud9", "file_name": "memo.m4a"}}}
    [e] = A.Telegram().parser_entrant(upd)
    assert e.media_id == "Aud9" and e.media_type == "audio" and e.media_nom == "voix.m4a"


def test_telegram_webhook_secret(monkeypatch):
    ad = A.Telegram()
    assert ad.verifier_webhook({}, b"") is True            # pas de secret → on n'exige rien
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "s3cr3t")
    assert ad.verifier_webhook({"X-Telegram-Bot-Api-Secret-Token": "s3cr3t"}, b"") is True
    assert ad.verifier_webhook({"X-Telegram-Bot-Api-Secret-Token": "non"}, b"") is False


# ── WhatsApp ─────────────────────────────────────────────────────────────────────
def test_whatsapp_configure(monkeypatch):
    assert A.REGISTRE["whatsapp"].configure() is False
    monkeypatch.setenv("WHATSAPP_TOKEN", "tok")
    monkeypatch.setenv("WHATSAPP_PHONE_ID", "111")
    assert A.REGISTRE["whatsapp"].configure() is True


def test_whatsapp_verifier_get(monkeypatch):
    monkeypatch.setenv("WHATSAPP_VERIFY_TOKEN", "vt")
    ad = A.WhatsApp()
    assert ad.verifier_get({"hub.mode": "subscribe", "hub.verify_token": "vt",
                            "hub.challenge": "1234"}) == "1234"
    assert ad.verifier_get({"hub.mode": "subscribe", "hub.verify_token": "NON"}) is None


def test_whatsapp_signature_hmac(monkeypatch):
    import hashlib
    import hmac
    monkeypatch.setenv("WHATSAPP_APP_SECRET", "shh")
    corps = b'{"hello":"world"}'
    bonne = "sha256=" + hmac.new(b"shh", corps, hashlib.sha256).hexdigest()
    ad = A.WhatsApp()
    assert ad.verifier_webhook({"X-Hub-Signature-256": bonne}, corps) is True
    assert ad.verifier_webhook({"X-Hub-Signature-256": "sha256=faux"}, corps) is False


def test_whatsapp_parser():
    payload = {"entry": [{"changes": [{"value": {
        "contacts": [{"wa_id": "33600", "profile": {"name": "Léa"}}],
        "messages": [{"from": "33600", "type": "text", "text": {"body": "Salut"}}]}}]}]}
    [e] = A.WhatsApp().parser_entrant(payload)
    assert e.id_externe == "33600" and e.texte == "Salut" and e.nom == "Léa"


# ── Discord (Ed25519) ────────────────────────────────────────────────────────────
def test_discord_signature_ed25519(monkeypatch):
    pytest.importorskip("cryptography")
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
    monkeypatch.setenv("DISCORD_PUBLIC_KEY", pub)

    ts, corps = "1700000000", b'{"type":1}'
    sig = priv.sign(ts.encode() + corps).hex()
    ad = A.Discord()
    bons = {"X-Signature-Ed25519": sig, "X-Signature-Timestamp": ts}
    assert ad.verifier_webhook(bons, corps) is True
    assert ad.verifier_webhook(bons, b'{"type":2}') is False         # corps altéré
    assert ad.verifier_webhook({}, corps) is False                   # en-têtes absents


def test_discord_parser_ping():
    assert A.Discord().parser_entrant({"type": 1}) == []


def test_discord_parser_commande():
    payload = {"type": 2, "channel_id": "999",
               "data": {"options": [{"name": "message", "value": "coucou"}]},
               "member": {"user": {"id": "u1", "username": "Max"}}}
    [e] = A.Discord().parser_entrant(payload)
    assert e.id_externe == "999" and e.texte == "coucou" and e.nom == "Max"


# ── Email/SMS (squelette honnête) ────────────────────────────────────────────────
def test_emailsms_non_configure():
    assert A.REGISTRE["email_sms"].configure() is False


# ── S245 : boutons inline + callback_query Telegram ──────────────────────────────
import asyncio
import json as _json

import httpx


class _R:
    def __init__(self, data=None):
        self._d = data or {"ok": True, "result": {}}

    def raise_for_status(self):
        pass

    def json(self):
        return self._d


def _faux_tg(monkeypatch, reponse=None):
    """Remplace httpx.AsyncClient de l'adaptateur ; consigne (méthode HTTP, url, kwargs)."""
    appels = []

    class _C:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, **kw):
            appels.append(("POST", url, kw))
            return _R(reponse)

        async def get(self, url, **kw):
            appels.append(("GET", url, kw))
            return _R(reponse)

    monkeypatch.setattr(A.httpx, "AsyncClient", _C)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    return appels


def _payload_cb(data="ap:" + "a" * 32 + ":ok"):
    return {"update_id": 1, "callback_query": {
        "id": "cb1", "from": {"id": 42},
        "message": {"message_id": 7, "chat": {"id": 42, "type": "private"}},
        "data": data}}


def test_parser_callback_extrait_les_champs():
    cb = A.Telegram().parser_callback(_payload_cb())
    assert (cb.from_id, cb.chat_id, cb.chat_type, cb.message_id, cb.callback_id) == (
        "42", "42", "private", 7, "cb1")
    assert cb.reseau == "telegram" and cb.data == "ap:" + "a" * 32 + ":ok"


def test_parser_callback_ignore_un_message_normal():
    upd = {"update_id": 2, "message": {"chat": {"id": 42}, "text": "salut"}}
    assert A.Telegram().parser_callback(upd) is None
    assert A.Telegram().parser_callback({}) is None
    assert A.Telegram().parser_callback({"callback_query": {"id": "x"}}) is None  # incomplet


def test_parser_entrant_ignore_un_callback_query():
    assert A.Telegram().parser_entrant(_payload_cb()) == []


def test_recuperer_demande_les_callback_query_et_rend_les_deux(monkeypatch, tmp_path):
    msg = {"update_id": 10, "message": {"chat": {"id": 42}, "text": "coucou",
                                        "from": {"first_name": "G"}}}
    cb = _payload_cb()
    cb["update_id"] = 11
    appels = _faux_tg(monkeypatch, {"ok": True, "result": [msg, cb]})
    sortie = asyncio.run(A.Telegram().recuperer())
    _, url, kw = appels[0]
    assert url.endswith("/getUpdates")
    assert _json.loads(kw["params"]["allowed_updates"]) == ["message", "callback_query"]
    assert [type(x).__name__ for x in sortie] == ["Entrant", "Callback"]


def test_envoyer_boutons_poste_un_inline_keyboard(monkeypatch):
    appels = _faux_tg(monkeypatch, {"ok": True, "result": {"message_id": 99,
                                                           "chat": {"id": 42}}})
    clavier = [[{"text": "OK", "callback_data": "ap:x:ok"}]]
    r = asyncio.run(A.Telegram().envoyer_boutons("42", "Texte", clavier))
    _, url, kw = appels[0]
    assert url.endswith("/sendMessage")
    assert kw["json"]["reply_markup"] == {"inline_keyboard": clavier}
    assert kw["json"]["chat_id"] == "42" and kw["json"]["text"] == "Texte"
    assert r == {"chat_id": "42", "message_id": 99}


def test_envoyer_boutons_sans_clavier_n_a_pas_de_reply_markup(monkeypatch):
    appels = _faux_tg(monkeypatch, {"ok": True, "result": {"message_id": 5,
                                                           "chat": {"id": 42}}})
    asyncio.run(A.Telegram().envoyer_boutons("42", "Texte", []))
    assert "reply_markup" not in appels[0][2]["json"]


def test_editer_message_retire_le_clavier(monkeypatch):
    appels = _faux_tg(monkeypatch)
    asyncio.run(A.Telegram().editer_message("42", 7, "Fait"))
    _, url, kw = appels[0]
    assert url.endswith("/editMessageText")
    assert kw["json"] == {"chat_id": "42", "message_id": 7, "text": "Fait",
                          "reply_markup": {"inline_keyboard": []}}


def test_repondre_callback_appelle_answerCallbackQuery(monkeypatch):
    appels = _faux_tg(monkeypatch)
    asyncio.run(A.Telegram().repondre_callback("cb1", "Décision enregistrée"))
    _, url, kw = appels[0]
    assert url.endswith("/answerCallbackQuery")
    assert kw["json"] == {"callback_query_id": "cb1", "text": "Décision enregistrée"}


def test_parser_callback_message_id_malforme_rend_none():
    p = _payload_cb()
    p["callback_query"]["message"]["message_id"] = "pas-un-entier"
    assert A.Telegram().parser_callback(p) is None
