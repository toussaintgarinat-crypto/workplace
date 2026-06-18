"""Tests des adaptateurs réseaux : ordre/disponibilité, parsing, signatures (hors réseau)."""
import pytest

import adaptateurs as A


# ── Registre / ordre / disponibilité ───────────────────────────────────────────
def test_registre_quatre_reseaux():
    assert set(A.REGISTRE) == {"telegram", "whatsapp", "discord", "email_sms"}


def test_disponibles_vide_par_defaut():
    # conftest a purgé tous les tokens → aucun réseau configuré (repli honnête).
    assert A.disponibles() == []


def test_ordre_defaut():
    assert A.ordre() == ["telegram", "whatsapp", "discord", "email_sms"]


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
