"""S133 — logique pure : sérialiseurs automation & pipelines + scoring risque."""

import datetime
import json
import types
import uuid

from app.routers.pipeline_templates import PIPELINE_TEMPLATES
from app.routers.risk_engine import score_action
from app.serde import (
    automation_rule,
    blackboard_event,
    decision_n0,
    degradation_episode,
    degradation_mode,
    governor_config,
    governor_usage,
    hitl_request,
    message,
    pipeline_template,
    repetition_config,
    risk_log,
    session,
    template,
)

DT = datetime.datetime(2026, 5, 30, 12, 0, 0)


def _ns(**kw):
    return types.SimpleNamespace(**kw)


# ── score_action : ordre des branches (parité Bun) ──────────────────────

def test_score_whitelist_fast_path():
    assert score_action("read_user") == (5, "faible")
    assert score_action("LIST items") == (5, "faible")
    assert score_action("export_csv") == (5, "faible")


def test_score_delete_before_purge():
    # "delete" matche avant "purge/drop/truncate" (ordre du Bun).
    assert score_action("delete_table") == (85, "eleve")
    assert score_action("supprimer compte") == (85, "eleve")


def test_score_deploy_stripe_email():
    assert score_action("deploy_app") == (70, "eleve")
    assert score_action("stripe_charge") == (70, "eleve")
    assert score_action("email_send") == (70, "eleve")


def test_score_create_update_moyen():
    assert score_action("create_invoice") == (35, "moyen")
    assert score_action("update_lead") == (35, "moyen")


def test_score_purge_critique_when_no_earlier_match():
    assert score_action("purge_cache") == (95, "critique")
    assert score_action("truncate logs") == (95, "critique")


def test_score_default():
    assert score_action("notify") == (20, "faible")


def test_score_fast_path_threshold():
    # fast_path = score <= 15 → seul le whitelist (5) qualifie.
    assert score_action("get")[0] <= 15
    assert score_action("notify")[0] > 15


# ── Sérialiseurs ────────────────────────────────────────────────────────

def test_pipeline_template_raw_json_text():
    r = _ns(id=uuid.uuid4(), user_id="u1", nom="P", description="d", icon="🔄",
            categorie="c", is_public=False, nodes='[{"id":"n1"}]', edges="[]",
            created_at=DT, updated_at=DT)
    out = pipeline_template(r)
    assert out["isPublic"] is False
    assert out["nodes"] == '[{"id":"n1"}]'  # TEXT JSON renvoyé brut
    assert out["createdAt"] == "2026-05-30T12:00:00.000Z"


def test_system_templates_shape():
    assert len(PIPELINE_TEMPLATES) == 3
    for t in PIPELINE_TEMPLATES:
        assert t["userId"] is None and t["isPublic"] is True
        # nodes/edges sont du JSON compact valide
        nodes = json.loads(t["nodes"])
        edges = json.loads(t["edges"])
        assert isinstance(nodes, list) and isinstance(edges, list)
        # JSON compact (parité JSON.stringify) : round-trip sans espace de séparateur
        assert t["nodes"] == json.dumps(nodes, separators=(",", ":"), ensure_ascii=False)
        assert t["edges"] == json.dumps(edges, separators=(",", ":"), ensure_ascii=False)


def test_automation_rule_serializer():
    r = _ns(id=uuid.uuid4(), user_id="u1", org_id=None, nom="A", description="",
            trigger="cron", conditions='{"x":1}', actions="[]", actif=True,
            executions=3, created_at=DT, updated_at=DT)
    out = automation_rule(r)
    assert out["trigger"] == "cron"
    assert out["conditions"] == '{"x":1}'  # brut
    assert out["executions"] == 3


def test_template_serializer():
    r = _ns(id=uuid.uuid4(), user_id="u1", org_id=None, nom="T", description="",
            type="email", contenu="hi", variables='["nom"]', public=True,
            created_at=DT, updated_at=DT)
    out = template(r)
    assert out["type"] == "email"
    assert out["variables"] == '["nom"]'
    assert out["public"] is True


def test_repetition_config_serializer():
    r = _ns(id=uuid.uuid4(), pole_id=uuid.uuid4(), seuil_occurrences=3,
            periode_jours=7, silence_days=30, actif=True, updated_at=DT)
    out = repetition_config(r)
    assert out["seuilOccurrences"] == 3
    assert out["periodeJours"] == 7
    assert out["silenceDays"] == 30


def test_hitl_request_serializer():
    r = _ns(id=uuid.uuid4(), session_id=None, user_id="u1", niveau=2,
            action="confirm", payload='{"k":"v"}', statut="pending",
            decide_par=None, decide_at=None, created_at=DT)
    out = hitl_request(r)
    assert out["niveau"] == 2
    assert out["payload"] == '{"k":"v"}'
    assert out["decideAt"] is None


def test_decision_n0_serializer():
    r = _ns(id=uuid.uuid4(), pole_id=uuid.uuid4(), pole_nom="Fin", agent_nom="Bot",
            action="spend", niveau="N0", statut="en_attente", urgence="haute",
            created_at=DT, resolved_at=None, resolved_by=None)
    out = decision_n0(r)
    assert out["poleNom"] == "Fin"
    assert out["statut"] == "en_attente"
    assert out["resolvedAt"] is None


def test_blackboard_event_serializer():
    r = _ns(id=uuid.uuid4(), pole_id=None, pole_nom="X", pole_emoji="📌",
            agent_nom="Bot", type="decision_created", payload="[N0] go", niveau="N1",
            created_at=DT)
    out = blackboard_event(r)
    assert out["type"] == "decision_created"
    assert out["poleId"] is None


def test_session_serializer():
    r = _ns(id=uuid.uuid4(), user_id="u1", org_id=None, name="Chat",
            pole_id=None, venture_id=None, scope="user", created_at=DT, updated_at=DT)
    out = session(r)
    assert out["scope"] == "user"
    assert out["name"] == "Chat"


def test_message_serializer():
    r = _ns(id=uuid.uuid4(), session_id=uuid.uuid4(), role="user", content="hi", created_at=DT)
    out = message(r)
    assert out["role"] == "user" and out["content"] == "hi"


def test_governor_config_serializer():
    r = _ns(id=uuid.uuid4(), user_id="u1", org_id=None, budget_journalier=100000,
            budget_mensuel=2000000, alerte_seuil=80, blocage_seuil=95, actif=True, updated_at=DT)
    out = governor_config(r)
    assert out["budgetJournalier"] == 100000
    assert out["blocageSeuil"] == 95


def test_governor_usage_real_cost():
    r = _ns(id=uuid.uuid4(), user_id="u1", org_id=None, provider="openai", model="gpt",
            tokens_in=10, tokens_out=20, cout_usd=0.5, pole_id=None, venture_id=None, created_at=DT)
    out = governor_usage(r)
    assert out["tokensIn"] == 10 and out["tokensOut"] == 20
    assert out["coutUsd"] == 0.5


def test_risk_log_serializer():
    r = _ns(id=uuid.uuid4(), user_id="u1", org_id=None, pole_id=None, action="delete",
            score=85, niveau="eleve", fast_path=False, approuve=False, raison="", created_at=DT)
    out = risk_log(r)
    assert out["score"] == 85 and out["fastPath"] is False


def test_degradation_serializers():
    m = _ns(id=uuid.uuid4(), org_id=None, ressource="qdrant", actif=True, grace_mode=False, created_at=DT)
    out = degradation_mode(m)
    assert out["ressource"] == "qdrant" and out["graceMode"] is False

    e = _ns(id=uuid.uuid4(), mode_id=uuid.uuid4(), duree_minutes=15, raison="oom", created_at=DT)
    eout = degradation_episode(e)
    assert eout["dureeMinutes"] == 15 and eout["raison"] == "oom"
