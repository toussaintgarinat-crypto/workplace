# forge/core — migration Python du backend Forge

Service **FastAPI** qui remplace progressivement le backend `forge/core` (TS/Bun)
selon une stratégie **strangler**. Objectif : consolider tout le backend du projet
sur Python (langage unique), supprimer Bun.

> **Statut : S131.** Socle (S126) + auth & cross-cutting (S127) + cœur agents/LLM
> (S128) + agents spécialisés & mémoire RAG (S129) + ventures & audit (S130) +
> **business & finance** (S131 : organizations, team, crm, prospection, contrats,
> facturation, stripe, budget, forecast, okr). Vercel AI SDK retiré du chemin Python
> (tout via gateway). Tout le reste est encore proxy-fié vers le Bun. Le frontend
> vise toujours le Bun (:3001) jusqu'au cutover S136.

## Routes portées

| Sprint | Domaine | Routes |
|---|---|---|
| S127 | auth | `PATCH /api/auth/me`, `GET /api/auth/me/export`, `DELETE /api/auth/me` |
| S127 | api-keys | `GET/PUT/DELETE /api/settings/api-keys[/:provider]` (chiffrement AES-GCM compat Bun) |
| S127 | audit-logs | `GET /api/audit-logs` (+ helper `log_audit`) |
| S127 | injection-guard | `POST /api/injection-guard/check`, `GET /api/injection-guard/logs` |
| S127 | slo | `GET /api/slo`, `PUT /api/slo/:module` |
| S127 | health | `GET /api/health` (public, forme `forge:core`) |
| S128 | llm-config | providers, preset CRUD, global, venture, resolve, ollama/provider models |
| S128 | personalities | `GET/POST/PUT/DELETE /api/personalities` + reorder |
| S128 | agent-autonomy | rules / feedback / runs / scores (`/api/agents/:id/*`, `/api/agent-runs/:id`) |
| S128 | agents-factory | templates + CRUD `/api/agent-factory` + stats |
| S128 | agents | `GET /api/agents`, `POST /api/agents/run` (via ReAct) |
| S128 | orchestrator | `/api/orchestrator/sessions` CRUD |
| S128 | chat | `POST /api/chat`, `POST /api/chat/stream` (SSE) — exécution LLM via gateway |
| S129 | agents spécialisés | conseil, content/legal/seo-agent + kb, memory-palace, search + module RAG (Qdrant/MemPalace) |
| S130 | ventures & audit | ventures (+6 pôles), poles, audit (+rapport IA), pole-dev-bridge, rapport, brief, morning-brief, veille |
| S131 | organizations | `GET/POST /api/orgs`, détail+membres, invitation par email, suppression owner (`/api/orgs/:id[/members/:userId]`) |
| S131 | team | `GET/POST/PATCH/DELETE /api/team[/:id]` (scopé `X-Org-ID`) |
| S131 | crm | leads par pôle (`/api/poles/:poleId/crm`, `/api/crm/:id`) |
| S131 | prospection | `POST /api/prospection/analyze` + `/email` (LLM via gateway) |
| S131 | contrats | par pôle + signature (`/api/poles/:poleId/contrats`, `/api/contrats/:id[/signer]`) |
| S131 | facturation | factures/devis, numérotation auto, totaux HT/TVA/TTC, devis→facture (`/api/facturation[/:id[/transformer]]`) |
| S131 | stripe | plans, abonnement, checkout (mock), webhook, paiements (`/api/stripe/*`) |
| S131 | budget | entrées recette/dépense + agrégats (`/api/poles/:poleId/budget`, `/api/budget/:id`) |
| S131 | forecast | prévisions mensuelles (`/api/poles/:poleId/forecast`, `/api/forecast/:id`) |
| S131 | okr | OKR + key-results + progression (`/api/poles/:poleId/okrs`, `/api/okrs/:id`, `/api/kr/:id`) |

**S128 — cœur agents/LLM (keystone).** Le Vercel AI SDK / VoltAgent sont retirés du
chemin Python : tout passe par la **LiteLLM Gateway** (OpenAI-compatible) via
`app/llm.py` + `app/react_executor.py` (ReAct function-calling, depth-guard,
fallback chain, traces, governor). Parité CRUD prouvée en live (14/14) ;
l'exécution LLM est non-déterministe (parité de protocole/erreur seulement).
Limites assumées : RAG retriever → S129, MCP tools (table absente) ignorés,
pricing governor → S133, `skills` laissé proxifié (table absente de l'instance).

Chaque route est montée aux deux préfixes `/api/...` (legacy, headers Deprecation
RFC 8594) et `/v1/api/...` (canonique). Auth = `Depends(get_current_user)`
(vérif JWKS Keycloak + provisioning user/org + résolution `X-Org-ID`), portage
fidèle de `middleware/auth.ts`.

## Stratégie strangler

```
            ┌─────────────────────────────────────────────┐
  client ──▶│  forge/core (FastAPI, :8600)             │
            │   ├─ routes portées (Python natif) ─────────┐│
            │   └─ catch-all  ──proxy──▶  forge/core (Bun)││
            └─────────────────────────────────────────────┘
                                          ▲ :3001
                          même Postgres + agent_personnel_shared
```

- Les routes **portées** en Python sont déclarées dans `app/routers/` et montées
  **avant** le catch-all (`app/main.py`) → elles court-circuitent le proxy.
- Tout le reste est **relayé tel quel** au Bun (`app/proxy.py`) : méthode, query,
  headers, body et streaming préservés. **Forge reste fonctionnel en continu.**
- Au **cutover (S136)**, la dernière route portée → on retire le proxy et on
  supprime `forge/core` (Bun). Le frontend bascule de `:3001` vers `:8600`.

## Arborescence

```
app/
  main.py            FastAPI + lifespan + catch-all proxy
  config.py          settings (env) — pydantic-settings
  db.py              SQLAlchemy 2.0 async (asyncpg) — pas de create_all
  proxy.py           proxy strangler → Bun
  routers/
    health.py        /health natif (HealthBuilder partagé)
  models/
    generated.py     AUTO-GÉNÉRÉ (sqlacodegen) — 77 tables reflétées
    __init__.py      re-export Base + modèles
tests/
  test_health.py     /health natif (non proxifié)
  test_proxy.py      proxy : méthode/body/query/502
  parity/
    harness.py       compare()/assert_parity() Python vs Bun
    test_parity_harness.py   tests unitaires du harnais
    test_parity_smoke.py     smoke contre Bun LIVE (skip si pas de PARITY_BUN_URL)
scripts/
  gen_models.sh      régénère app/models/generated.py
```

## Base de données

La DB est **partagée avec le Bun et ne bouge pas** pendant la migration. Les
modèles SQLAlchemy reflètent le schéma existant (source de vérité =
`../core/src/db/schema.ts`, Drizzle) → **zéro migration de données**.

77 tables sur 87 sont reflétées. 10 tables ne sont pas encore créées dans
l'instance courante (features jamais activées) ; elles seront ajoutées en
régénérant une fois présentes — cf. en-tête de `app/models/generated.py`.

Régénérer les modèles :

```bash
./scripts/gen_models.sh                              # via réseau docker forge_default
DBURL=postgresql+psycopg://u:p@host/db ./scripts/gen_models.sh   # DB explicite
```

## Tests de parité

Avant de débrancher une route Bun au profit de son portage Python, on **prouve la
parité** des réponses sur les mêmes entrées (`tests/parity/harness.py`) :

```python
from tests.parity.harness import assert_parity

@pytest.mark.parity
async def test_ventures_parity(client):
    await assert_parity(client, BUN_URL, method="GET", path="/api/ventures",
                        ignore_keys={"created_at", "updated_at"})
```

Les smokes de parité requièrent un Bun live (`PARITY_BUN_URL`) ; sinon ils sont
skippés (la logique du harnais reste couverte unitairement).

## Développement

```bash
python3.12 -m venv .venv && . .venv/bin/activate
pip install -e ../../shared -r requirements.txt -r requirements-dev.txt

# tests + gate couverture (≥30 %, monte au fil des sprints vers 60 %)
PYTHONPATH=. pytest --cov=app --cov-report=term-missing --cov-fail-under=30

# lancer en local (proxy vers un Bun sur :3001)
PYTHONPATH=. uvicorn app.main:app --port 8600 --reload

# parité contre un Bun live
PARITY_BUN_URL=http://localhost:3001 PYTHONPATH=. pytest -m parity
```

En Docker, le service est défini dans `forge/docker-compose.yml` (`core`,
port `8600`, build context = racine repo pour embarquer `shared/`).

## Roadmap

S126 (ce socle) → S137 (durcissement). Cf. mémoire projet
`roadmap_migration_forge_python`. Chaque sprint porte un domaine, prouve la
parité, débranche l'équivalent Bun, garde la couverture montante.
