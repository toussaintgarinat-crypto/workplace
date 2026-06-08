"""forge/core — point d'entrée FastAPI.

Migration strangler forge/core TS/Bun → Python/FastAPI (roadmap S126-S137).
S136 cutover TERMINÉ : le Bun (forge/core) est supprimé, plus de proxy strangler.
core est désormais l'UNIQUE backend forge. Routes montées aux DEUX préfixes
``/api/...`` (legacy, headers Deprecation S99) et ``/v1/api/...`` (canonique).
Domaine metrics non porté (code mort, 0 consommateur — supprimé avec le Bun).

Portés à ce stade :
- S126 : aucun (socle).
- S127 : auth (profil/RGPD), api-keys, audit-logs, injection-guard, slo, /api/health.
- S128 : llm-config, chat, agents, agents-factory, agent-autonomy, orchestrator, personalities.
- S129 : conseil, content/legal/seo-agent, kb, memory, search + module mémoire RAG (Qdrant
  + brique Mémoire Workplace /rappeler). Branche get_context réel (chat + react_executor).
- S130 : ventures, poles, audit (+rapport IA), pole-dev-bridge, rapport, brief, morning-brief,
  veille. Cœur produit. SMTP (suppression venture) + email.py.
- S131 : organizations (multi-tenant), team, crm, prospection (LLM), contrats, facturation
  (numérotation + totaux), stripe (mock checkout/webhook), budget, forecast, okr.
- S132 : servers (parc SSH), deploy (déploiement client durable + SSE), gitpack (analyse repo
  LLM), netbird (proxy VPN), task-dag (tri topologique + exécution), dev-team, sprints/tasks,
  staging. Services dag/deploy/cloudflare.
- S133 : sessions (scopes user/pole/venture), command-bridge (pilotage N0 + blackboard +
  kill-switch), pipeline-templates (canvas + import DAG + assistant), automation, templates,
  repetition (détection → HITL → Pôle Dev), hitl, governor (coûts), risk-engine, degradation.
- S134 : temps réel — ws (chat WebSocket streaming + ReAct), voice (STT/TTS proxy), voice-realtime
  (proxy OpenAI Realtime), push (Web Push VAPID), webhooks (sortants + test). 1res routes WS natives.
- S135 : comms & intégrations — keybindings, saved-filters, imap (configs chiffrées + emails),
  incidents (par pôle), calendar (événements), social (comptes + plateformes), mcp (serveurs MCP
  + tools/call JSON-RPC), documents (upload + analyse LLM + ingestion RAG), analytics (tableau
  de bord agrégé), sentinel-rgpd (checklist + audit LLM).
"""

import logging
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from agent_personnel_shared.fastapi_setup import setup_cors, setup_logging

from app.config import settings
from app.db import dispose as db_dispose
from app.routers.agent_autonomy import router as agent_autonomy_router
from app.routers.agents import router as agents_router
from app.routers.agents_factory import router as agents_factory_router
from app.routers.api_keys import router as api_keys_router
from app.routers.audit import router as audit_router
from app.routers.audit_logs import router as audit_logs_router
from app.routers.auth import router as auth_router
from app.routers.brief import router as brief_router
from app.routers.budget import router as budget_router
from app.routers.chat import router as chat_router
from app.routers.conseil import router as conseil_router
from app.routers.rag import router as rag_router  # Workplace S17 — récupération RAG
from app.routers.content_agent import router as content_agent_router
from app.routers.contrats import router as contrats_router
from app.routers.crm import router as crm_router
from app.routers.facturation import router as facturation_router
from app.routers.forecast import router as forecast_router
from app.routers.forge_health import router as forge_health_router
from app.routers.health import router as health_router
from app.routers.injection_guard import router as injection_guard_router
from app.routers.kb import router as kb_router
from app.routers.legal_agent import router as legal_agent_router
from app.routers.llm_config import router as llm_config_router
from app.routers.memory_palace import router as memory_palace_router
from app.routers.morning_brief import router as morning_brief_router
from app.routers.okr import router as okr_router
from app.routers.orchestrator import router as orchestrator_router
from app.routers.organizations import router as organizations_router
from app.routers.personalities import router as personalities_router
from app.routers.pole_dev_bridge import router as pole_dev_bridge_router
from app.routers.poles import router as poles_router
from app.routers.prospection import router as prospection_router
from app.routers.rapport import router as rapport_router
from app.routers.search import router as search_router
from app.routers.seo_agent import router as seo_agent_router
from app.routers.slo import router as slo_router
from app.routers.stripe import router as stripe_router
from app.routers.team import router as team_router
from app.routers.veille import router as veille_router
from app.routers.ventures import router as ventures_router
# S132 — devops & déploiement
from app.routers.deploy import router as deploy_router
from app.routers.dev_team import router as dev_team_router
from app.routers.gitpack import router as gitpack_router
from app.routers.netbird import router as netbird_router
from app.routers.servers import router as servers_router
from app.routers.sprints import router as sprints_router
from app.routers.staging import router as staging_router
from app.routers.task_dag import router as task_dag_router
# S133 — automation & pipelines
from app.routers.automation import router as automation_router
from app.routers.command_bridge import router as command_bridge_router
from app.routers.degradation import router as degradation_router
from app.routers.governor import router as governor_router
from app.routers.hitl import router as hitl_router
from app.routers.pipeline_templates import router as pipeline_templates_router
from app.routers.repetition import router as repetition_router
from app.routers.risk_engine import router as risk_engine_router
from app.routers.sessions import router as sessions_router
from app.routers.templates import router as templates_router
# S134 — temps réel
from app.routers.push import router as push_router
from app.routers.voice import router as voice_router
from app.routers.voice_realtime import router as voice_realtime_router
from app.routers.webhooks import router as webhooks_router
from app.routers.ws import router as ws_router
# S135 — comms & intégrations
from app.routers.analytics import router as analytics_router
from app.routers.calendar import router as calendar_router
from app.routers.documents import router as documents_router
from app.routers.imap import router as imap_router
from app.routers.incidents import router as incidents_router
from app.routers.keybindings import router as keybindings_router
from app.routers.mcp import router as mcp_router
from app.routers.saved_filters import router as saved_filters_router
from app.routers.sentinel_rgpd import router as sentinel_rgpd_router
from app.routers.rgpd import router as rgpd_router
from app.routers.skills import router as skills_router
from app.routers.social import router as social_router

logger = logging.getLogger(__name__)

# S99 — sunset des alias /api/* (legacy) ~ 6 mois après livraison.
DEPRECATION_SUNSET = "Mon, 23 Nov 2026 00:00:00 GMT"


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "[forge:core] up — backend forge UNIQUE (Bun supprimé S136), port=%s",
        settings.CORE_PY_PORT,
    )
    yield
    await db_dispose()


app = FastAPI(title="forge/core", version=settings.VERSION, lifespan=lifespan)

setup_logging()
setup_cors(app, settings.CORS_ORIGINS, default=["http://localhost:3000"])


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """Contrat d'erreur du Bun : ``{"error": <message>}`` (vs {detail} de FastAPI)."""
    return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})


@app.middleware("http")
async def deprecation_headers(request: Request, call_next):
    """Ajoute les headers RFC 8594 sur les alias legacy /api/* servis NATIVEMENT.

    Les réponses proxifiées vers le Bun portent déjà ces headers (le Bun applique
    son propre middleware) → on n'ajoute que s'ils sont absents, ce qui évite les
    doublons. Les routes canoniques /v1/api/* n'en reçoivent pas.
    """
    response = await call_next(request)
    path = request.url.path
    if path.startswith("/api/") and "deprecation" not in (h.lower() for h in response.headers):
        response.headers["Deprecation"] = "true"
        response.headers["Sunset"] = DEPRECATION_SUNSET
        response.headers["Link"] = f"</v1{path}>; rel=\"successor-version\""
    return response


# ── Service health interne (HealthBuilder) — distinct du health forge ───
app.include_router(health_router)


# ── Montage double (legacy /api + canonique /v1/api) ────────────────────
def mount_both(router: APIRouter, api_path: str) -> None:
    app.include_router(router, prefix=api_path)
    app.include_router(router, prefix=f"/v1{api_path}")


# Public (sans auth) — /api/health façon Bun.
mount_both(forge_health_router, "/api/health")

# Protégés (auth via Depends(get_current_user) dans chaque handler).
# S127 — auth & cross-cutting
mount_both(auth_router, "/api/auth")
mount_both(api_keys_router, "/api/settings/api-keys")
mount_both(audit_logs_router, "/api")
mount_both(injection_guard_router, "/api")
mount_both(slo_router, "/api")
# S128 — cœur agents/LLM
mount_both(llm_config_router, "/api/llm-config")
mount_both(chat_router, "/api/chat")
mount_both(agents_router, "/api/agents")
mount_both(agents_factory_router, "/api")
mount_both(agent_autonomy_router, "/api")
mount_both(orchestrator_router, "/api")
mount_both(personalities_router, "/api")
# S129 — agents spécialisés + mémoire (RAG)
mount_both(conseil_router, "/api/conseil")
mount_both(content_agent_router, "/api")
mount_both(legal_agent_router, "/api")
mount_both(seo_agent_router, "/api")
mount_both(kb_router, "/api")
mount_both(memory_palace_router, "/api")
mount_both(search_router, "/api")
mount_both(rag_router, "/api")  # Workplace S17 — récupération RAG en lecture seule
# S130 — ventures & audit (cœur produit)
mount_both(ventures_router, "/api")
mount_both(poles_router, "/api/poles")
mount_both(audit_router, "/api")
mount_both(pole_dev_bridge_router, "/api")
mount_both(rapport_router, "/api")
mount_both(brief_router, "/api")
mount_both(morning_brief_router, "/api")
mount_both(veille_router, "/api")
# S131 — business & finance
mount_both(organizations_router, "/api/orgs")
mount_both(team_router, "/api")
mount_both(crm_router, "/api")
mount_both(prospection_router, "/api")
mount_both(contrats_router, "/api")
mount_both(facturation_router, "/api")
mount_both(stripe_router, "/api")
mount_both(budget_router, "/api")
mount_both(forecast_router, "/api")
mount_both(okr_router, "/api")
# S132 — devops & déploiement
mount_both(servers_router, "/api")
mount_both(deploy_router, "/api")
mount_both(gitpack_router, "/api")
mount_both(netbird_router, "/api/netbird")
mount_both(task_dag_router, "/api")
mount_both(dev_team_router, "/api")
mount_both(sprints_router, "/api")
mount_both(staging_router, "/api")
# S133 — automation & pipelines
mount_both(sessions_router, "/api/sessions")
mount_both(command_bridge_router, "/api/command-bridge")
mount_both(pipeline_templates_router, "/api")
mount_both(automation_router, "/api")
mount_both(templates_router, "/api")
mount_both(repetition_router, "/api")
mount_both(hitl_router, "/api")
mount_both(governor_router, "/api")
mount_both(risk_engine_router, "/api")
mount_both(degradation_router, "/api")
# S134 — temps réel (HTTP : push, webhooks, voice STT/TTS)
mount_both(push_router, "/api")
mount_both(webhooks_router, "/api")
mount_both(voice_router, "/api/voice")
# S135 — comms & intégrations
mount_both(keybindings_router, "/api")
mount_both(saved_filters_router, "/api")
mount_both(imap_router, "/api")
mount_both(incidents_router, "/api")
mount_both(calendar_router, "/api")
mount_both(social_router, "/api")
mount_both(mcp_router, "/api")
mount_both(documents_router, "/api")
mount_both(analytics_router, "/api")
mount_both(sentinel_rgpd_router, "/api")
mount_both(rgpd_router, "/api")  # S18 Chantier 2 — droits RGPD exécutables (effacement/export)
mount_both(skills_router, "/api")

# WebSockets natifs (S134) — hors mount_both : le proxy strangler est HTTP-only et
# le middleware Deprecation ne s'applique pas au scope websocket. Montés aux deux
# préfixes pour cohérence avec les routes HTTP (le frontend vise /api/...).
#  - /api/ws/:sessionId        chat streaming + ReAct
#  - /api/voice/realtime       proxy OpenAI Realtime
for _prefix in ("/api/ws", "/v1/api/ws"):
    app.include_router(ws_router, prefix=_prefix)
for _prefix in ("/api/voice", "/v1/api/voice"):
    app.include_router(voice_realtime_router, prefix=_prefix)


# S136 cutover : le catch-all strangler (proxy → Bun) a été retiré. Toute route
# non déclarée ci-dessus renvoie un 404 natif FastAPI (contrat {"error": ...} via
# http_exception_handler). Le Bun (forge/core) est supprimé.
