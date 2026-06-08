"""S134 — logique pure : sérialiseurs push/webhook + prompt système WS."""

import datetime
import types
import uuid

from app.routers.ws import _build_system_prompt
from app.serde import push_subscription, push_subscription_min, webhook

DT = datetime.datetime(2026, 5, 30, 12, 0, 0)


def _ns(**kw):
    return types.SimpleNamespace(**kw)


# ── push subscription ───────────────────────────────────────────────────

def test_push_subscription_min_three_fields():
    uid = uuid.uuid4()
    r = _ns(id=uid, user_id="u1", endpoint="https://push/x", p256dh="p", auth="a", created_at=DT)
    out = push_subscription_min(r)
    assert out == {"id": str(uid), "endpoint": "https://push/x", "createdAt": "2026-05-30T12:00:00.000Z"}
    # parité GET : ne fuit pas user_id/p256dh/auth
    assert "userId" not in out and "p256dh" not in out and "auth" not in out


def test_push_subscription_full_row():
    uid = uuid.uuid4()
    r = _ns(id=uid, user_id="u1", endpoint="https://push/x", p256dh="p", auth="a", created_at=DT)
    out = push_subscription(r)
    assert out["userId"] == "u1" and out["p256dh"] == "p" and out["auth"] == "a"
    assert out["createdAt"] == "2026-05-30T12:00:00.000Z"


# ── webhook : quirk events parsé (GET/POST) vs brut (PATCH) ──────────────

def test_webhook_parse_events_array():
    uid = uuid.uuid4()
    r = _ns(id=uid, user_id="u1", nom="wh", url="https://h", events='["a","b"]',
            enabled=True, secret="s", org_id=None, created_at=DT)
    out = webhook(r)
    assert out["events"] == ["a", "b"]
    assert out["nom"] == "wh" and out["enabled"] is True and out["orgId"] is None


def test_webhook_patch_keeps_events_string():
    """Quirk Bun : PATCH renvoie la ligne brute → events reste une chaîne JSON."""
    uid = uuid.uuid4()
    r = _ns(id=uid, user_id="u1", nom="wh", url="https://h", events='["x"]',
            enabled=False, secret="", org_id=uid, created_at=DT)
    out = webhook(r, parse_events=False)
    assert out["events"] == '["x"]'
    assert out["orgId"] == str(uid)


def test_webhook_null_events_defaults_empty():
    r = _ns(id=uuid.uuid4(), user_id="u1", nom="wh", url="https://h", events=None,
            enabled=True, secret="", org_id=None, created_at=DT)
    assert webhook(r)["events"] == []


# ── prompt système WS (réplique buildSystemPrompt d'ws.ts) ──────────────

def test_ws_prompt_default_no_context():
    p = _build_system_prompt("", None, None, None)
    assert "Swarm-Sentinel platform" in p
    assert "Be concise, technical, and precise" in p
    assert "## Project Context" not in p


def test_ws_prompt_personality_takes_precedence():
    p = _build_system_prompt("", {"nom": "Finance", "type": "finance"}, None, "Tu es Aria.")
    assert p.startswith("Tu es Aria.")
    assert 'operating within the "Finance" pole' in p


def test_ws_prompt_pole_without_personality():
    p = _build_system_prompt("", {"nom": "Ops", "type": "ops"}, None, None)
    assert 'Forge, an expert AI assistant operating within the "Ops" pole' in p


def test_ws_prompt_venture_and_rag():
    p = _build_system_prompt("doc context", None, {"nom": "Acme"}, None)
    assert 'venture "Acme"' in p
    assert "## Project Context\ndoc context" in p
