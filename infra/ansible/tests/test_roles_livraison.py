import pathlib
import re

BASE = pathlib.Path(__file__).resolve().parent.parent
FILES = [p for r in ("dokploy", "forgejo", "docker_user_guard", "executeur_restauration") for p in (BASE / "roles" / r).rglob("*") if p.is_file()]
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


def test_playbook_inclut_executeur():
    assert "executeur_restauration" in (BASE / "playbooks" / "livraison.yml").read_text()


def test_executeur_ecoute_sur_l_ip_lan_pas_sur_toutes_les_interfaces():
    t = text()
    assert "executeur_bind: \"{{ ansible_default_ipv4.address }}\"" in t
    assert "EXECUTEUR_BIND=0.0.0.0" not in t and "executeur_bind: \"0.0.0.0\"" not in t


def test_executeur_port_limite_a_l_ip_du_hp():
    t = text()
    assert "ufw allow from {{ executeur_client_ip }} to any port {{ executeur_port }}" in t
    assert "executeur_client_ip: 192.168.1.89" in t


def test_executeur_secrets_lus_dans_un_fichier_root_0600_cree_a_la_main():
    t = text()
    assert "EnvironmentFile=/etc/executeur-restauration/env" in t
    assert 'stat.mode == "0600"' in t and "ansible.builtin.stat" in t
    assert "EXECUTEUR_S3_SECRET=" not in t and "EXECUTEUR_KEY=" not in t


def test_executeur_unit_durcie():
    t = text()
    assert "NoNewPrivileges=true" in t and "ProtectHome=true" in t


def test_timer_forgejo_quotidien():
    assert "OnCalendar=*-*-* 03:15:00" in text()
