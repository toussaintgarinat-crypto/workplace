"""Déploiement client durable — portage de ``services/deployService.ts`` (S132).

`run_deploy` exécute en 6 étapes : génération des fichiers (docker-compose/.env/
realm Keycloak/seed SQL), connexion SSH, upload rsync, `docker compose up`, seed
Postgres, DNS Cloudflare (mode auto). La progression est remontée via `on_progress`
(persistée en DB par le routeur, cf. pattern S124). Les générateurs sont purs
(testables sans I/O).
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import secrets
import shutil
import tempfile
import uuid as uuidlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.crypto import decrypt, encrypt
from app.services.cloudflare import create_cloudflare_record

# Re-exports : parité avec `export { encrypt as encryptKey, decrypt as decryptKey }`.
encrypt_key = encrypt
decrypt_key = decrypt

TOTAL_STEPS = 6

ProgressFn = Callable[[str, int, int], Awaitable[None]]


@dataclass
class MissionData:
    titre: str
    description: str = ""
    findings: list[dict] = field(default_factory=list)
    recos: list[dict] = field(default_factory=list)
    rapport: str = ""


@dataclass
class DeployOpts:
    instance_id: str
    server_ip: str
    ssh_key_encrypted: str
    ssh_user: str
    domain: str
    domain_mode: str  # 'cloudflare' | 'manual'
    admin_email: str
    admin_password: str
    mission_data: MissionData


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _bcrypt(password: str) -> str:
    import bcrypt  # import paresseux (dép. optionnelle au runtime du déploiement)

    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(10)).decode("ascii")


def _rand(n: int = 32) -> str:
    """Équivalent du `randomBytes(n).toString('base64').slice(0,n).replace(/[+/=]/g,'x')`."""
    raw = base64.b64encode(secrets.token_bytes(n)).decode("ascii")[:n]
    return raw.replace("+", "x").replace("/", "x").replace("=", "x")


# ── Générateurs (purs) ────────────────────────────────────────

def generate_env_vars(domain: str, admin_email: str, admin_hash: str) -> dict[str, str]:
    return {
        "NODE_ENV": "production",
        "FORGE_IMAGE": os.getenv("FORGE_IMAGE") or "ghcr.io/toussaintgarinat-crypto/forge-core:latest",
        "DOMAIN": domain or "localhost",
        "FRONTEND_URL": f"https://{domain}" if domain else "http://localhost:8600",
        "KEYCLOAK_URL": f"https://{domain}/auth" if domain else "http://keycloak:8080",
        "KEYCLOAK_REALM": "forge",
        "KEYCLOAK_CLIENT_ID": "forge-app",
        "KEYCLOAK_AUDIENCE": "forge-app",
        "JWT_SECRET": _rand(48),
        "ENCRYPTION_KEY": _rand(32),
        "POSTGRES_USER": "forge",
        "POSTGRES_PASSWORD": _rand(24),
        "POSTGRES_DB": "forge",
        "DATABASE_URL": "",  # calculé dans generate_dotenv
        "KC_DB_PASSWORD": _rand(24),
        "KEYCLOAK_ADMIN": "admin",
        "KEYCLOAK_ADMIN_PASSWORD": _rand(24),
        "ADMIN_EMAIL": admin_email,
        "LETSENCRYPT_EMAIL": admin_email,
    }


def generate_dotenv(env: dict[str, str]) -> str:
    e = dict(env)
    e["DATABASE_URL"] = f"postgresql+asyncpg://{e['POSTGRES_USER']}:{e['POSTGRES_PASSWORD']}@postgres:5432/{e['POSTGRES_DB']}"
    return "\n".join(f"{k}={v}" for k, v in e.items()) + "\n"


def generate_docker_compose(domain: str, domain_mode: str, env: dict[str, str]) -> str:
    with_traefik = domain_mode == "cloudflare" and bool(domain)

    traefik_service = """
  traefik:
    image: traefik:v3.0
    command:
      - --providers.docker=true
      - --providers.docker.exposedbydefault=false
      - --entrypoints.web.address=:80
      - --entrypoints.web.http.redirections.entrypoint.to=websecure
      - --entrypoints.websecure.address=:443
      - --certificatesresolvers.le.acme.httpchallenge=true
      - --certificatesresolvers.le.acme.httpchallenge.entrypoint=web
      - --certificatesresolvers.le.acme.email=${LETSENCRYPT_EMAIL}
      - --certificatesresolvers.le.acme.storage=/letsencrypt/acme.json
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - letsencrypt:/letsencrypt
    restart: unless-stopped""" if with_traefik else ""

    forge_labels = """
    labels:
      - traefik.enable=true
      - traefik.http.routers.forge.rule=Host(`${DOMAIN}`)
      - traefik.http.routers.forge.entrypoints=websecure
      - traefik.http.routers.forge.tls.certresolver=le
      - traefik.http.services.forge.loadbalancer.server.port=8600""" if with_traefik else """
    ports:
      - "8600:8600\""""

    kc_labels = """
    labels:
      - traefik.enable=true
      - traefik.http.routers.keycloak.rule=Host(`${DOMAIN}`) && PathPrefix(`/auth`)
      - traefik.http.routers.keycloak.entrypoints=websecure
      - traefik.http.routers.keycloak.tls.certresolver=le
      - traefik.http.services.keycloak.loadbalancer.server.port=8080""" if with_traefik else """
    ports:
      - "8080:8080\""""

    letsencrypt_vol = "\n  letsencrypt:" if with_traefik else ""

    return f"""version: '3.9'

services:

  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: ${{POSTGRES_USER}}
      POSTGRES_PASSWORD: ${{POSTGRES_PASSWORD}}
      POSTGRES_DB: ${{POSTGRES_DB}}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${{POSTGRES_USER}}"]
      interval: 5s
      timeout: 3s
      retries: 20
      start_period: 10s
    restart: unless-stopped

  keycloak-db:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: keycloak
      POSTGRES_PASSWORD: ${{KC_DB_PASSWORD}}
      POSTGRES_DB: keycloak
    volumes:
      - kc_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U keycloak"]
      interval: 5s
      timeout: 3s
      retries: 10
    restart: unless-stopped

  keycloak:
    image: quay.io/keycloak/keycloak:25.0
    command: start --import-realm
    environment:
      KC_DB: postgres
      KC_DB_URL: jdbc:postgresql://keycloak-db:5432/keycloak
      KC_DB_USERNAME: keycloak
      KC_DB_PASSWORD: ${{KC_DB_PASSWORD}}
      KC_HOSTNAME_STRICT: "false"
      KC_HTTP_ENABLED: "true"
      KC_HTTP_RELATIVE_PATH: /auth
      KEYCLOAK_ADMIN: ${{KEYCLOAK_ADMIN}}
      KEYCLOAK_ADMIN_PASSWORD: ${{KEYCLOAK_ADMIN_PASSWORD}}
    volumes:
      - ./forge-realm.json:/opt/keycloak/data/import/forge-realm.json:ro
    depends_on:
      keycloak-db:
        condition: service_healthy{kc_labels}
    restart: unless-stopped

  forge:
    image: ${{FORGE_IMAGE}}
    environment:
      NODE_ENV: ${{NODE_ENV}}
      DATABASE_URL: postgresql+asyncpg://${{POSTGRES_USER}}:${{POSTGRES_PASSWORD}}@postgres:5432/${{POSTGRES_DB}}
      KEYCLOAK_URL: ${{KEYCLOAK_URL}}
      KEYCLOAK_REALM: ${{KEYCLOAK_REALM}}
      KEYCLOAK_CLIENT_ID: ${{KEYCLOAK_CLIENT_ID}}
      KEYCLOAK_AUDIENCE: ${{KEYCLOAK_AUDIENCE}}
      JWT_SECRET: ${{JWT_SECRET}}
      ENCRYPTION_KEY: ${{ENCRYPTION_KEY}}
      FRONTEND_URL: ${{FRONTEND_URL}}
    depends_on:
      postgres:
        condition: service_healthy{forge_labels}
    restart: unless-stopped
{traefik_service}

volumes:
  postgres_data:
  kc_data:{letsencrypt_vol}
"""


def generate_realm_json(domain: str, admin_user_id: str, admin_email: str, admin_password: str) -> str:
    base_url = f"https://{domain}" if domain else "http://localhost:8600"
    realm = {
        "realm": "forge",
        "displayName": "Forge Client",
        "enabled": True,
        "sslRequired": "external" if domain else "none",
        "registrationAllowed": False,
        "loginWithEmailAllowed": True,
        "duplicateEmailsAllowed": False,
        "resetPasswordAllowed": True,
        "bruteForceProtected": True,
        "accessTokenLifespan": 300,
        "ssoSessionMaxLifespan": 36000,
        "clients": [
            {
                "clientId": "forge-app",
                "name": "Forge Application",
                "enabled": True,
                "publicClient": True,
                "standardFlowEnabled": True,
                "directAccessGrantsEnabled": False,
                "redirectUris": [f"{base_url}/*"],
                "webOrigins": [base_url],
                "attributes": {
                    "pkce.code.challenge.method": "S256",
                    "post.logout.redirect.uris": f"{base_url}/*",
                },
                "protocolMappers": [
                    {
                        "name": "audience",
                        "protocol": "openid-connect",
                        "protocolMapper": "oidc-audience-mapper",
                        "consentRequired": False,
                        "config": {
                            "included.client.audience": "forge-app",
                            "id.token.claim": "false",
                            "access.token.claim": "true",
                        },
                    },
                ],
            },
        ],
        "roles": {
            "realm": [
                {"name": "admin", "description": "Forge administrator"},
                {"name": "member", "description": "Forge member"},
            ],
        },
        "defaultRoles": ["member"],
        "users": [
            {
                "id": admin_user_id,
                "username": admin_email,
                "email": admin_email,
                "enabled": True,
                "emailVerified": True,
                "credentials": [{"type": "password", "value": admin_password, "temporary": False}],
                "realmRoles": ["admin", "member"],
            },
        ],
    }
    return json.dumps(realm, indent=2)


def generate_seed_sql(admin_user_id: str, admin_email: str, mission: MissionData) -> str:
    def esc(s: str) -> str:
        return (s or "").replace("'", "''")

    m_id = str(uuidlib.uuid4())
    venture_id = str(uuidlib.uuid4())
    pole_id = str(uuidlib.uuid4())
    now = _now_iso()

    finding_rows = ",\n  ".join(
        f"('{uuidlib.uuid4()}','{m_id}','{admin_user_id}','{esc(f.get('categorie', ''))}',"
        f"'{f.get('severite', 'faible')}','{esc(f.get('description', ''))}','{esc(f.get('source', ''))}','{now}')"
        for f in mission.findings
    )
    reco_rows = ",\n  ".join(
        f"('{uuidlib.uuid4()}','{m_id}','{admin_user_id}','{r.get('priorite', 'moyenne')}',"
        f"'{esc(r.get('action', ''))}','{r.get('statut', 'ouvert')}','{now}')"
        for r in mission.recos
    )
    rapport_contenu = esc(mission.rapport) if mission.rapport else ""

    findings_block = (
        "INSERT INTO audit_findings (id, mission_id, user_id, categorie, severite, description, source, created_at)\n"
        f"VALUES\n  {finding_rows};"
        if mission.findings else "-- (aucun finding)"
    )
    recos_block = (
        "INSERT INTO audit_recommendations (id, mission_id, user_id, priorite, action, statut, created_at)\n"
        f"VALUES\n  {reco_rows};"
        if mission.recos else "-- (aucune recommandation)"
    )
    rapport_block = (
        "-- Rapport\n"
        "INSERT INTO rapports (id, user_id, mission_id, titre, contenu, type, periode, created_at)\n"
        f"VALUES ('{uuidlib.uuid4()}','{admin_user_id}','{m_id}','Rapport d''audit — {esc(mission.titre)}',"
        f"'{rapport_contenu}','audit','{now}','{now}');"
        if rapport_contenu else ""
    )

    return f"""-- Forge Client Seed — généré automatiquement
BEGIN;

-- Utilisateur admin
INSERT INTO users (id, email, nom, avatar_emoji, keycloak_sub, created_at)
VALUES ('{admin_user_id}','{esc(admin_email)}','Admin','👤','{admin_user_id}','{now}')
ON CONFLICT (email) DO NOTHING;

-- Venture + pôle Finance
INSERT INTO organizations (id, name, slug, created_at)
VALUES ('{venture_id}','{esc(mission.titre)}','audit-client','{now}')
ON CONFLICT DO NOTHING;

INSERT INTO poles (id, nom, description, emoji, couleur, type, owner_id, created_at)
VALUES ('{pole_id}','Audit','Mission d''audit importée','🔍','#6366f1','finance','{admin_user_id}','{now}');

-- Mission d'audit
INSERT INTO audit_missions (id, pole_id, user_id, titre, description, statut, created_at, updated_at)
VALUES ('{m_id}','{pole_id}','{admin_user_id}','{esc(mission.titre)}','{esc(mission.description)}','termine','{now}','{now}');

-- Findings
{findings_block}

-- Recommandations
{recos_block}

{rapport_block}

COMMIT;
"""


# ── Exécution SSH/rsync/docker ────────────────────────────────

async def _run(cmd: str, timeout: float = 120.0) -> None:
    """Exécute une commande shell ; lève RuntimeError sur code retour non nul."""
    proc = await asyncio.create_subprocess_shell(
        cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError as exc:
        proc.kill()
        raise RuntimeError(f"Commande expirée ({timeout}s): {cmd[:80]}") from exc
    if proc.returncode != 0:
        raise RuntimeError((err or out or b"").decode("utf-8", "replace").strip() or "commande échouée")


async def run_deploy(opts: DeployOpts, on_progress: ProgressFn) -> None:
    deploy_id = str(uuidlib.uuid4())
    tmp_dir = os.path.join(tempfile.gettempdir(), f"forge-deploy-{deploy_id}")
    key_path = os.path.join(tempfile.gettempdir(), f"forge-ssh-{deploy_id}")
    admin_user_id = str(uuidlib.uuid4())

    ssh_key = decrypt(opts.ssh_key_encrypted)

    def _ssh_quote(cmd: str) -> str:
        return cmd.replace("'", "'\\''")

    def ssh_cmd(cmd: str) -> str:
        return (
            f"ssh -i \"{key_path}\" -o StrictHostKeyChecking=no -o ConnectTimeout=15 "
            f"{opts.ssh_user}@{opts.server_ip} '{_ssh_quote(cmd)}'"
        )

    try:
        # 1. Génération des fichiers
        await on_progress("Génération des fichiers de configuration…", 1, TOTAL_STEPS)
        os.makedirs(tmp_dir, exist_ok=True)
        with open(key_path, "w") as f:
            f.write(ssh_key)
        os.chmod(key_path, 0o600)

        admin_hash = _bcrypt(opts.admin_password)
        env_vars = generate_env_vars(opts.domain, opts.admin_email, admin_hash)

        with open(os.path.join(tmp_dir, "docker-compose.yml"), "w") as f:
            f.write(generate_docker_compose(opts.domain, opts.domain_mode, env_vars))
        with open(os.path.join(tmp_dir, ".env"), "w") as f:
            f.write(generate_dotenv(env_vars))
        with open(os.path.join(tmp_dir, "forge-realm.json"), "w") as f:
            f.write(generate_realm_json(opts.domain, admin_user_id, opts.admin_email, opts.admin_password))
        with open(os.path.join(tmp_dir, "seed.sql"), "w") as f:
            f.write(generate_seed_sql(admin_user_id, opts.admin_email, opts.mission_data))

        # 2. Connexion SSH
        await on_progress("Connexion au serveur…", 2, TOTAL_STEPS)
        await _run(ssh_cmd("echo connected"))

        # 3. Upload rsync
        await on_progress("Upload des fichiers vers le serveur…", 3, TOTAL_STEPS)
        await _run(ssh_cmd("mkdir -p /opt/forge-client"))
        await _run(
            f"rsync -az -e \"ssh -i '{key_path}' -o StrictHostKeyChecking=no\" "
            f"\"{tmp_dir}/\" {opts.ssh_user}@{opts.server_ip}:/opt/forge-client/"
        )

        # 4. Démarrage des conteneurs
        await on_progress("Démarrage des conteneurs Docker…", 4, TOTAL_STEPS)
        await _run(ssh_cmd("cd /opt/forge-client && docker compose pull --quiet 2>/dev/null || true"))
        await _run(ssh_cmd("cd /opt/forge-client && docker compose up -d --remove-orphans"))

        # 5. Seed base de données
        await on_progress("Injection des données d'audit…", 5, TOTAL_STEPS)
        await _run(ssh_cmd(
            "for i in $(seq 1 12); do docker compose -f /opt/forge-client/docker-compose.yml "
            "exec -T postgres pg_isready -U forge && break || sleep 5; done"
        ))
        await _run(ssh_cmd(
            "cd /opt/forge-client && docker compose exec -T postgres psql -U forge forge < /opt/forge-client/seed.sql"
        ))

        # 5b. DNS Cloudflare si mode auto
        if opts.domain_mode == "cloudflare" and opts.domain:
            await create_cloudflare_record(opts.domain, opts.server_ip)

        await on_progress("Déploiement terminé.", 6, TOTAL_STEPS)
    finally:
        try:
            os.unlink(key_path)
        except OSError:
            pass
        shutil.rmtree(tmp_dir, ignore_errors=True)
