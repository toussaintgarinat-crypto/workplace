"""Sérialiseurs — clés camelCase + format ISO Z (parité Drizzle/Bun)."""

import datetime
import types

from app.serde import audit_log, injection_log, iso, real, slo_entry, user_public


def test_real_short_repr():
    # float4 lu en binaire par asyncpg → repr courte façon driver pg (texte)
    assert real(99.9000015258789) == 99.9
    assert real(100.0) == 100.0
    assert real(None) is None


def test_iso_format_z():
    dt = datetime.datetime(2026, 5, 29, 19, 33, 19, 123000)
    assert iso(dt) == "2026-05-29T19:33:19.123Z"
    assert iso(None) is None


def test_iso_converts_aware_to_utc():
    tz = datetime.timezone(datetime.timedelta(hours=2))
    dt = datetime.datetime(2026, 5, 29, 21, 33, 19, 0, tzinfo=tz)
    assert iso(dt) == "2026-05-29T19:33:19.000Z"


def test_user_public_camel():
    u = types.SimpleNamespace(id="11111111-1111-1111-1111-111111111111", nom="Bob", avatar_emoji="🦊")
    assert user_public(u) == {"id": "11111111-1111-1111-1111-111111111111", "nom": "Bob", "avatarEmoji": "🦊"}


def test_audit_log_keys():
    r = types.SimpleNamespace(
        id="a", org_id=None, user_id="u1", user_nom="Bob", action="create",
        entite="venture", entite_id="v1", pole="dev", details="{}",
        created_at=datetime.datetime(2026, 1, 1),
    )
    out = audit_log(r)
    assert set(out) == {"id", "orgId", "userId", "userNom", "action", "entite", "entiteId", "pole", "details", "createdAt"}
    assert out["orgId"] is None and out["details"] == "{}"


def test_s128_serializers_keys():
    from app.serde import (agent_definition, agent_run, autonomy_rule, llm_preset,
                           orchestrator_session, personality)

    p = types.SimpleNamespace(id="p", scope_type="pole", scope_id="x", venture_id=None,
        provider="ollama", base_url="", api_key="", model="llama3.2", max_tokens=2048,
        budget_daily=None, budget_monthly=None, updated_at=None, updated_by="u")
    assert set(llm_preset(p)) == {"id", "scopeType", "scopeId", "ventureId", "provider", "baseUrl",
        "apiKey", "model", "maxTokens", "budgetDaily", "budgetMonthly", "updatedAt", "updatedBy"}

    a = types.SimpleNamespace(id="a", user_id="u", pole_id=None, personality_id=None, nom="X",
        description="", instructions="", niveau="medium", statut="draft", llm_preset="",
        created_at=None, updated_at=None)
    assert agent_definition(a)["niveau"] == "medium" and agent_definition(a)["poleId"] is None

    per = types.SimpleNamespace(id="x", label="L", emoji="🤖", description="", system_prompt="",
        is_builtin=0, position=0, created_at=None)
    assert set(personality(per)) == {"id", "label", "emoji", "description", "systemPrompt", "isBuiltin", "position", "createdAt"}

    r = types.SimpleNamespace(id="r", agent_id=None, user_id="u", niveau="N1", horaires="{}", override_ok=False, updated_at=None)
    assert autonomy_rule(r)["overrideOk"] is False

    run = types.SimpleNamespace(id="x", agent_id=None, user_id="u", pole_id=None, statut="running",
        input="", output="", tokens_in=0, tokens_out=0, duree_ms=0, created_at=None, completed_at=None)
    assert agent_run(run)["dureeMs"] == 0

    os_ = types.SimpleNamespace(id="o", user_id="u", pole_id=None, titre="T", agents="[]",
        statut="actif", output="", created_at=None, updated_at=None)
    assert orchestrator_session(os_)["agents"] == "[]"


def test_injection_and_slo_keys():
    inj = types.SimpleNamespace(id="i", org_id=None, user_id="u", input="x", flagged=True, raison="r", created_at=None)
    assert set(injection_log(inj)) == {"id", "orgId", "userId", "input", "flagged", "raison", "createdAt"}
    slo = types.SimpleNamespace(
        id="s", org_id=None, module="chat", health_score=90,
        slo_target=99.9, slo_current=100.0, erreurs_24h=2, updated_at=None,
    )
    out = slo_entry(slo)
    assert set(out) == {"id", "orgId", "module", "healthScore", "sloTarget", "sloCurrent", "erreurs24h", "updatedAt"}
    assert out["healthScore"] == 90 and out["erreurs24h"] == 2
