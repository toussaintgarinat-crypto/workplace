import pathlib
import re

BASE = pathlib.Path(__file__).resolve().parent.parent
FILES = [p for r in ("dokploy", "forgejo", "docker_user_guard") for p in (BASE / "roles" / r).rglob("*") if p.is_file()]
FILES.append(BASE / "playbooks" / "livraison.yml")


def text():
    return "\n".join(p.read_text() for p in FILES)


def test_playbook_references_roles():
    pb = (BASE / "playbooks" / "livraison.yml").read_text()
    for role in ("dokploy", "docker_user_guard", "forgejo"):
        assert role in pb


def test_no_floating_tags():
    t = text()
    assert not re.search(r":latest\b", t)
    assert "dokploy_version: v" in t and re.search(r'forgejo_version: "\d+\.\d+\.\d+"', t)


def test_no_literal_secret():
    assert not re.search(r"(?i)(password|secret_key|token)\s*[:=]\s*[\"']?[A-Za-z0-9]{12,}", text())


def test_published_ports_guarded_and_forgejo_off_3000():
    t = text()
    assert "--ctstate DNAT -j DROP" in t
    assert "forgejo_http_port: 3001" in t

def test_forgejo_reachable_from_docker_networks():
    assert "ufw allow from 172.16.0.0/12" in text()

def test_forgejo_registry_declared_insecure_for_rollback():
    assert "insecure-registries" in text()
