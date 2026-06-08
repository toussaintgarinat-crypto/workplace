"""S132 — logique pure : tri topologique, sérialiseurs, générateurs de déploiement."""

import datetime
import json
import types
import uuid

from app.serde import (
    deployed_instance_public,
    dev_task,
    gitpack_job,
    managed_server,
    managed_server_public,
    sprint,
    staging_proposal,
    task,
    task_dag_item,
)
from app.services.dag import DagNode, topological_sort
from app.services.deploy import (
    generate_docker_compose,
    generate_dotenv,
    generate_env_vars,
    generate_realm_json,
    generate_seed_sql,
    MissionData,
)


def _ns(**kw):
    return types.SimpleNamespace(**kw)


# ── Tri topologique (Kahn) ───────────────────────────────────

def test_topo_linear_order():
    nodes = [
        DagNode("a", []),
        DagNode("b", ["a"]),
        DagNode("c", ["b"]),
    ]
    res = topological_sort(nodes)
    assert res.cycle is False
    assert res.order.index("a") < res.order.index("b") < res.order.index("c")


def test_topo_detects_cycle():
    nodes = [DagNode("a", ["b"]), DagNode("b", ["a"])]
    res = topological_sort(nodes)
    assert res.cycle is True
    assert len(res.order) < 2


def test_topo_ignores_unknown_deps():
    # Dépendance vers un nœud absent → ignorée (parité Bun).
    nodes = [DagNode("a", ["ghost"]), DagNode("b", ["a"])]
    res = topological_sort(nodes)
    assert res.cycle is False
    assert res.order == ["a", "b"]


# ── Sérialiseurs ─────────────────────────────────────────────

def test_managed_server_serializers():
    now = datetime.datetime(2026, 5, 30, 12, 0, 0)
    sid = uuid.uuid4()
    r = _ns(id=sid, user_id="u1", label="srv", ip="1.2.3.4", ssh_key="enc:cipher",
            ssh_user="root", region="eu", status="libre", instance_id=None, created_at=now)
    full = managed_server(r)
    assert full["id"] == str(sid)
    assert full["sshKey"] == "enc:cipher"  # masquage fait côté routeur
    assert full["createdAt"].endswith("Z")
    pub = managed_server_public(r)
    assert "sshKey" not in pub
    assert pub["status"] == "libre"


def test_deployed_instance_public_hides_secrets():
    now = datetime.datetime(2026, 5, 30, 12, 0, 0)
    r = _ns(id=uuid.uuid4(), mission_id=uuid.uuid4(), server_ip="1.2.3.4", domain="x.io",
            domain_mode="cloudflare", status="ready", admin_email="a@b.c", notes="",
            deployed_at=now, created_at=now)
    out = deployed_instance_public(r)
    assert "sshKey" not in out and "adminPasswordHash" not in out
    assert out["domainMode"] == "cloudflare"


def test_staging_and_dag_real_and_raw_json():
    now = datetime.datetime(2026, 5, 30, 12, 0, 0)
    sp = _ns(id=uuid.uuid4(), org_id=None, contenu="x", score_mea=0.5, statut="pending", created_at=now)
    assert staging_proposal(sp)["scoreMea"] == 0.5
    dag = _ns(id=uuid.uuid4(), pole_id=uuid.uuid4(), user_id="u", nom="n", description="",
              agent_owner="", dependances='["x"]', statut="pending", criticite="normale",
              node_type="agent", pos_x=1.5, pos_y=2.0, prompt_text="", created_at=now, updated_at=now)
    out = task_dag_item(dag)
    assert out["dependances"] == '["x"]'  # TEXT JSON brut (parité)
    assert out["posX"] == 1.5


def test_dev_task_sprint_task_gitpack_serializers():
    now = datetime.datetime(2026, 5, 30, 12, 0, 0)
    dt = _ns(id=uuid.uuid4(), pole_id=None, user_id="u", org_id=None, titre="t", description="",
             type="feature", statut="backlog", priorite="normale", agent_ia="", analyse_llm="",
             temps_estime=0, assigne_a="", deadline=None, created_at=now, updated_at=now)
    assert dev_task(dt)["type"] == "feature"
    sp = _ns(id=uuid.uuid4(), pole_id=uuid.uuid4(), user_id="u", nom="S1", objectif="",
             statut="actif", date_debut=now, date_fin=None, created_at=now)
    assert sprint(sp)["statut"] == "actif"
    tk = _ns(id=uuid.uuid4(), sprint_id=None, pole_id=uuid.uuid4(), user_id="u", titre="t",
             description="", statut="todo", priorite="normale", assigne_a=None,
             created_at=now, updated_at=now)
    assert task(tk)["statut"] == "todo"
    gj = _ns(id=uuid.uuid4(), user_id="u", org_id=None, github_url="https://gh/x/y", platform="macos",
             statut="running", language=None, framework=None, logs="[]", error=None,
             created_at=now, updated_at=now)
    assert gitpack_job(gj)["logs"] == "[]"


# ── Générateurs de déploiement (purs) ────────────────────────

def test_generate_dotenv_computes_database_url():
    env = generate_env_vars("x.io", "a@b.c", "$2b$hash")
    dotenv = generate_dotenv(env)
    assert "DATABASE_URL=postgresql+asyncpg://forge:" in dotenv  # core asyncpg (S137)
    assert "@postgres:5432/forge" in dotenv
    assert dotenv.endswith("\n")


def test_generate_docker_compose_manual_vs_cloudflare():
    env = generate_env_vars("", "a@b.c", "h")
    manual = generate_docker_compose("", "manual", env)
    assert "traefik" not in manual
    assert '"8600:8600"' in manual  # core FastAPI (S137)

    env2 = generate_env_vars("client.io", "a@b.c", "h")
    cf = generate_docker_compose("client.io", "cloudflare", env2)
    assert "traefik:" in cf
    assert "letsencrypt" in cf


def test_generate_realm_json_valid_and_ssl():
    raw = generate_realm_json("client.io", "uid-1", "a@b.c", "pw")
    realm = json.loads(raw)
    assert realm["realm"] == "forge"
    assert realm["sslRequired"] == "external"
    assert realm["users"][0]["email"] == "a@b.c"
    # Sans domaine → ssl 'none'
    realm2 = json.loads(generate_realm_json("", "uid-1", "a@b.c", "pw"))
    assert realm2["sslRequired"] == "none"


def test_generate_seed_sql_escapes_quotes():
    mission = MissionData(
        titre="L'audit",  # apostrophe à échapper
        description="desc",
        findings=[{"categorie": "c", "severite": "haute", "description": "d'oh", "source": "s"}],
        recos=[{"priorite": "haute", "action": "fix", "statut": "ouvert"}],
        rapport="rapport",
    )
    sql = generate_seed_sql("uid-1", "a@b.c", mission)
    assert "L''audit" in sql  # apostrophe doublée
    assert "d''oh" in sql
    assert "BEGIN;" in sql and "COMMIT;" in sql
    assert "audit_findings" in sql and "audit_recommendations" in sql


def test_generate_seed_sql_empty_findings():
    mission = MissionData(titre="t", findings=[], recos=[], rapport="")
    sql = generate_seed_sql("uid-1", "a@b.c", mission)
    assert "-- (aucun finding)" in sql
    assert "-- (aucune recommandation)" in sql
