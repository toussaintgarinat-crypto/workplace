# Rapport — Revue de dépôts open-source pour Workplace

> **Date** : 2026-07-19
> **Auteur** : revue assistant
> **Objet** : 18 dépôts GitHub évalués au regard de l'architecture de Workplace
> (noyau + briques, objectif 1 = usine à applications, objectif 2 = Jarvis).
> **Méthode** : lecture du README + licence pour chacun, classement par
> pertinence, recommandation d'intégration par brique.

---

## 0. Synthèse exécutive

| Verdict | Dépôt | Brique Workplace ciblée |
|---|---|---|
| ⭐ Intégrer | **Nango** | Brique « Connexions » du registre (OAuth 800+ APIs) |
| ⭐ Intégrer | **Crawl4AI** | Cœur de l'ETL web (objectif 1) |
| ⭐ Intégrer | **agent-skills** (Addy Osmani) | Workflow dev (compatible OpenCode) |
| ⭐ Intégrer | **Scrapling** | Fallback anti-bot de l'ETL |
| 🟡 Étudier | **LibreChat** | Concurrent/inspiration Assistant+Cœur |
| 🟡 Étudier | **browser-use** | Audit interactif (login extranet) |
| 🟡 Réserve | **curl-impersonate** | Dépendance transitive (TLS finesse) |
| 🟡 Réserve | **Agentic Inbox** | Pattern auto-draft pour emails |
| 🟡 Réserve | **TradingAgents** | Future brique Finance |
| 🟡 Réserve | **VoxCPM** | Voix du Jarvis (plus tard) |
| ⚠️ Isoler | **Firecrawl** | AGPL contagieux — conteneur séparé only |
| ⚠️ Isoler | **FinceptTerminal** | AGPL + commercial lourd — inspiration only |
| ⚪ Skip | **HyperFrames** | Hors périmètre (vidéo marketing) |
| ⚪ Skip | **MoneyPrinterTurbo** | Hors périmètre (vidéo TikTok) |
| ⚪ Skip | **Flowsint** | Hors périmètre (OSINT) |
| ⚪ Skip | **crawlee** | Doublon TS de Crawl4AI |
| ⚪ Skip | **scrapy** | Trop bas niveau pour usage IA-driven |
| ⚪ Skip | **autoscraper** | Non maintenu depuis 2022 |

---

## 1. Briques existantes de Workplace (rappel)

D'après `WORKPLACE.md` §4, l'inventaire vérifié est :
- **Memory** (Mémoire, pgvector, port 5600) — 🟢
- **Gateway** (LiteLLM, routeur LLM unique) — 🟢
- **Oria** (collaboration/messagerie) — 🟡
- **Forge** (agents + RAG, facturation, CRM, Stripe, emails) — 🟢
- **Donnees** (persistance FastAPI + SQLite, port 5500) — 🟢
- **Strategic App Builder** (générateur d'app, autonome) — 🟢
- **Assistant** (modèle de l'assistant du Cœur, S7)
- **ETL** (`briques/etl`, markitdown, Tesseract, pdf2image)

**Manquants identifiés** : le Cœur + registre de briques, l'ETL web réel, une
brique Connexions-API, une brique Finance, une brique Voix.

---

## 2. Catégorie « Crawling / Scraping / ETL web »

### 2.1 Crawl4AI — `unclecode/crawl4ai` ⭐⭐⭐

- **Licence** : Apache-2.0 ✅
- **Stack** : Python, Playwright, async, Docker, CLI `crwl`, MCP server intégré
- **Stars** : 73k
- **Points forts** :
  - Output **Markdown LLM-ready** avec `fit_markdown` (BM25 + Pruning)
  - Citations et référence des liens (utile pour RAG/AIDS)
  - Extraction structurée LLM **ou** CSS/XPath (sans LLM quand possible)
  - Deep-crawl BFS/DFS/Best-First avec **crash recovery** (`resume_state`,
    `on_state_change`) → longs crawls reprise possible
  - Mode `prefetch=True` 5-10× plus rapide pour découverte d'URLs
  - Shadow DOM flattening, sessions persistantes, proxy rotation, hooks
  - Dashboard Docker de monitoring, sécurisé par défaut depuis v0.9.0
- **Faiblesses** :
  - Dépendances Playwright lourdes (image Docker ~1 Go)
  - Quelques CVE historiques sur le Docker API (patchés en v0.8.7)
- **Rôle Workplace** : **cœur de l'ETL web** de la brique `etl`. Le Markdown
  RAG-ready se branche directement sur Forge/Qdrant sans étape de nettoyage.
- **Contrat proposé** : `crawl(url, schema?) -> {markdown, links, extracted}`.

### 2.2 Scrapling — `D4Vinci/Scrapling` ⭐⭐⭐

- **Licence** : BSD-3-Clause ✅
- **Stack** : Python, fetchers HTTP/Playwright, MCP server
- **Stars** : 70k
- **Points forts** :
  - Bypass **Cloudflare Turnstile** out-of-the-box (`StealthyFetcher`,
    `solve_cloudflare=True`)
  - Parser **adaptatif** : si le design d'un site change, il relocalise les
    éléments (`adaptive=True`, `auto_save=True`) — clé pour les sites
    d'entreprise qui évoluent
  - Spiders façon Scrapy avec `pause/resume` checkpointés
  - Multi-session (HTTP stealth + browser stealth) dans un même spider
  - Plus rapide que BS4 (≈1 ms/5k éléments vs 1,5 s)
  - CLI `scrapling extract` et shell interactive
- **Faiblesses** :
  - Setup browser lourd via `scrapling install`
  - Écosystème plus jeune que Crawl4AI
- **Rôle Workplace** : **fallback anti-bot** derrière Crawl4AI. Appelé
  uniquement quand Crawl4AI retourne 403/captcha. Pas en première intention
  (plus coûteux, ouvre un vrai Chrome).

### 2.3 curl-impersonate — `lwthiker/curl-impersonate` 🟡

- **Licence** : MIT ✅
- **Stars** : 6,6 k
- **Rôle** : build spécial de curl qui imite les Client Hello TLS et HTTP/2
  de Chrome/Edge/Safari/Firefox. Utilisé pour passer les fingerprints TLS.
- **Recommandation** : **dépendance transitive** — Crawl4AI et Scrapling
  l'utilisent déjà. Ne pas l'intégrer frontalement dans une brique.

### 2.4 Firecrawl — `firecrawl/firecrawl` ⚠️

- **Licence** : **AGPL-3.0** ⚠️ (contagieux : toute modification exposée doit
  être publiée)
- **Stars** : 153 k
- **Points forts** :
  - API très mature (search/scrape/map/crawl/agent/interact)
  - SDK officiels Python/Node/Go/Java/Rust/PHP/Ruby/.NET/Elixir
  - MCP server, skill agent, auto-hébergeable
- **Recommandation** : **ne pas intégrer dans le noyau Workplace** (AGPL).
  Si usage, **conteneur isolé**, API consommée via HTTP, sans modifier le
  code source. Alternative « hosted » à privilégier plutôt que fork.

### 2.5 browser-use — `browser-use/browser-use` 🟡

- **Licence** : MIT ✅
- **Stars** : 105 k
- **Rôle** : agent IA qui **pilote un navigateur comme un humain** (clic,
  formulaire, login, scroll). Modèle optimisé `bu-*` ou tout LLM.
- **Recommandation** : l'intégrer dans la phase **Audit interactif** de
  l'objectif 1 — quand l'ETL doit se connecter à un extranet client ou un
  backoffice (espace pro, SCIRA, etc.). Pas pour scrapper en masse.

### 2.6 crawlee — `apify/crawlee` ⚪

- **Licence** : Apache-2.0 ✅
- **Stars** : 24,8 k
- **Rôle** : équivalent JS/TS de Crawl4AI/Scrapy (Apify).
- **Recommandation** : **skip**. Doublon côté TypeScript. À ne reconsidérer
  que si une brique TS a strictement besoin d'un crawler embarqué.

### 2.7 scrapy — `scrapy/scrapy` ⚪

- **Licence** : BSD-3-Clause ✅
- **Stars** : 63,2 k
- **Rôle** : framework historique de crawling à grande échelle.
- **Recommandation** : **skip pour l'instant**. Trop bas-niveau pour de
  l'IA-driven. À garder en réserve si un jour tu dois aspirer 100k+ pages
  avec pipelines/storages custom.

### 2.8 autoscraper — `alirezamika/autoscraper` ⚪

- **Licence** : MIT ✅
- **Stars** : 7,6 k
- **Dernier release** : 2022 → **non maintenu**.
- **Recommandation** : **skip**. Dépassé par Scrapling (qui reprend l'idée
  d'éléments adaptatifs mais en actif).

---

## 3. Catégorie « Connexions API / Intégrations »

### 3.1 Nango — `NangoHQ/nango` ⭐⭐⭐

- **Licence** : Elastic License (auto-hébergeable gratuitement, ok pour usage
  interne)
- **Stars** : 11,2 k
- **Stack** : TypeScript, 800+ providers OAuth/API key, fonctions TS
  déployables, AI builder de fonctions, proxy auth, syncs, webhooks
- **Points forts** :
  - **OAuth géré pour 800+ APIs** (Gmail, Slack, HubSpot, Notion, Salesforce,
    GitHub, etc.) → la plus grosse douleur d'une brique « Connexions »
  - Multi-tenant (per-connection credentials)
  - Syncs one/two-way pour RAG, webhooks entrants, API unification
  - Compatible Cursor/Codex/Claude Code et MCP/LangChain
  - Self-host possible
- **Rôle Workplace** : **nouvelle brique « Connexions »** du registre. Donné
  aux apps générées (objectif 1) pour qu'elles accèdent aux API tierces sans
  que Workplace réécrive l'auth à chaque fois. Canal de branchement natif
  avec Forge (qui a déjà Stripe) et l'Audit (qui peut aspirer Gmail/Drive).
- **Contrat proposé** :
  `connect(provider, userId) -> connectionId ; proxy(connectionId, req) -> resp`.

---

## 4. Catégorie « Chat / Assistant / LLM Gateway »

### 4.1 LibreChat — `danny-avila/LibreChat` 🟡

- **Licence** : MIT ✅
- **Stars** : 40,9 k
- **Stack** : Node/TS, React, MCP, agents, skills, code interpreter, multi-user
- **Points forts** :
  - UI ChatGPT-like multi-provider (OpenRouter, Ollama, Azure, Anthropic, etc.)
  - **MCP natif** + Agents marketplace + Skills + Subagents
  - Admin panel multi-user/rôles, OAuth2/LDAP
  - Code interpreter sandboxé, Artifacts, RAG, voice
  - Docker one-command, Helm chart
- **Risque pour Workplace** :
  - **Chevauchement fort** avec **Gateway + Assistant** — il faut trancher :
    remplacer OU s'inspirer. À ne pas bricoler en parallèle.
- **Recommandation** : **étude approfondie avant décision**. Trois pistes :
  1. **Remplacer** le couple Gateway+Assistant par LibreChat (gain UI mûre,
     MCP, admin) — risque : aftermath d'identité (Workplace ≠ LibreChat).
  2. **Embarquer** comme sous-brique UI chat (conteneur isolé, SSO Keycloak)
     en gardant Gateway LiteLLM derrière.
  3. **S'inspirer seulement** (Skills/Subagents/MCP/Artifacts) sans intégrer.
- La décision mérite un brainstorming dédié car elle touche au Cœur.

### 4.2 agent-skills — `addyosmani/agent-skills` ⭐⭐⭐

- **Licence** : MIT ✅
- **Stars** : 79,1 k
- **Stack** : 24 skills Markdown (spec→plan→build→test→review→ship) + 4
  personas + 8 slash commands compatibles OpenCode
- **Points forts** :
  - Skills production-grade (Google-style : Hyrum's Law, Beyonce Rule, test
    pyramid, trunk-based, feature flags)
  - Compatibles OpenCode nativement (cf. `docs/opencode-setup.md`)
  - Anti-rationalization tables, gate de vérification
- **Recommandation** : **installer immédiatement** dans le workflow de dev
  Workplace (complémentaire de superpowers déjà utilisé). Pas une brique
  métier, mais un outillage de l'équipe.

---

## 5. Catégorie « Agents domain-spécifiques »

### 5.1 TradingAgents — `TauricResearch/TradingAgents` 🟡

- **Licence** : Apache-2.0 ✅
- **Stars** : 93,5 k
- **Stack** : Python, LangGraph, multi-provider
- **Rôle** : framework multi-agents (analystes fondamentaux/sentiment/news
  + chercheurs bull/bear + trader + risk + portfolio manager) qui débattent
  puis décident.
- **Recommandation** : **future brique Finance/Trésorerie** pour les
  entreprises auditées (objectif 1). Modèle d'organisation des agents
  (analystes opposés qui débattent) réutilisable pour d'autres domaines.

### 5.2 FinceptTerminal — `Fincept-Corporation/FinceptTerminal` ⚠️

- **Licence** : **AGPL-3.0 + Commercial License obligatoire pour usage
  business** ⚠️
- **Stars** : 28,6 k
- **Stack** : C++20/Qt6 + Python embarqué — binaire natif desktop
- **Recommandation** : **inspiration only**, pas d'intégration de code.
  Récupérer les idées : 37 agents IA finance (Buffett, Graham, Lynch…), 100+
  connecteurs de données, QuantLib embarqué. Licence trop restrictive pour
  un usage interne à une app livrée.

### 5.3 Flowsint — `reconurge/flowsint` ⚪

- **Licence** : Apache-2.0 ✅
- **Stars** : 7,4 k
- **Rôle** : OSINT graph-based pour cybersécurité (DNS, WHOIS, breaches,
  Neo4j).
- **Recommandation** : **skip**. Hors périmètre Workplace. À reconsidérer
  seulement si une brique « due diligence / audit externe entreprise »
  voit le jour dans l'Audit.

### 5.4 Agentic Inbox — `cloudflare/agentic-inbox` 🟡

- **Licence** : Apache-2.0 ✅
- **Stars** : 6,4 k
- **Stack** : TypeScript, Cloudflare Workers + Durable Objects + R2
- **Rôle** : client mail auto-hébergé avec agent IA qui lit, cherche, drafte.
  Auto-draft à la réception, confirmation explicite avant envoi.
- **Recommandation** : **emprunter le pattern auto-draft + confirm** pour
  enrichir la brique emails de Forge (relances S22). Pas d'intégration du
  code Cloudflare (forte dépendance à leur stack), mais inspiration UX.

---

## 6. Catégorie « Média / Voix / Vidéo » (secondaire)

### 6.1 VoxCPM — `OpenBMB/VoxCPM` 🟡

- **Licence** : Apache-2.0 ✅
- **Stars** : 33,7 k
- **Rôle** : TTS multilingue (30 langues, 48 kHz), voice design, cloning,
  controllable. Intègre vLLM-Omni et llama.cpp-omni pour edge.
- **Recommandation** : **réserve**. À intégrer au Jarvis (objectif 2) si la
  voix devient prioritaire. Connectable au tunnel LiveKit/Oria.

### 6.2 HyperFrames — `heygen-com/hyperframes` ⚪

- **Licence** : Apache-2.0 ✅
- **Stars** : 36,1 k
- **Rôle** : framework HTML → MP4 déterministe, conçu pour agents. 19
  skills, intégration Figma.
- **Recommandation** : **skip pour le noyau**. Future brique « Marketing
  /Contenu » dans l'app générée, si une entreprise cliente veut des vidéos
  de présentation produit auto.

### 6.3 MoneyPrinterTurbo — `harry0703/MoneyPrinterTurbo` ⚪

- **Licence** : MIT ✅
- **Stars** : 98 k
- **Rôle** : short-video TikTok/YouTube Shorts à partir d'un sujet.
- **Recommandation** : **skip**. Hors périmètre professionnel Workplace.
  Eventuelle brique « Marketing social », mais non prioritaire.

---

## 7. Plan d'intégration proposé (par sprint)

| Sprint | Brique | Dépôt intégré | Nature |
|---|---|---|---|
| ETL-1 | `briques/etl-web` | **Crawl4AI** | Cœur de crawl, Markdown RAG-ready |
| ETL-2 | `briques/etl-web` | **Scrapling** | Fallback Cloudflare + parser adaptatif |
| ETL-3 | `briques/etl-web` | **browser-use** | Audit interactif (login extranet) |
| CONN-1 | `briques/connexions` | **Nango** | OAuth 800+ APIs pour apps générées |
| DEV-1 | (workflow) | **agent-skills** | Skills installés sur OpenCode |
| ASST-1 | `Assistant/Cœur` | **LibreChat** (étude) | Décision : remplacer / embarquer / inspirer |
| VOIX-1 | `briques/voix` | **VoxCPM** | TTS multilingue du Jarvis (plus tard) |
| FIN-1 | `briques/finance` | **TradingAgents** | Future brique Finance pour Audit |
| MAIL-1 | Forge/emails | **Agentic Inbox** (pattern) | Auto-draft + confirm sur relances S22 |

**Sprints prioritaires** : ETL-1, CONN-1, DEV-1 (modifiables au prochain
point de synchro).

---

## 8. Risques transverses

- **Licences** : pour chaque intégration, vérifier avant de modifier le code
  source.
  - **OK** (MIT, Apache-2.0, BSD-3) : Crawl4AI, Scrapling, browser-use,
    curl-impersonate, LibreChat, agent-skills, TradingAgents, VoxCPM,
    HyperFrames, MoneyPrinterTurbo, Flowsint, Agentic Inbox, scrapy,
    autoscraper, crawlee.
  - **AGPL-3.0** (contagieux) : Firecrawl, FinceptTerminal → isoler en
    conteneur, ne pas modifier, ou inspiration seulement.
  - **Elastic** : Nango (auto-hébergement gratuit, restrictions sur offre
    cloud managée — pas un blocant pour self-host).
- **Identité** : respecter `WORKPLACE.md` §5 (pas de « Gungnir », pas de
  « Conscience »). Quand LibreChat/agent-skills sont intégrés, ne pas
  rebaptiser la solution.
- **Sémantique** : chaque brique garde son `manifest.json`, sa version
  SemVer et son CHANGELOG (`WORKPLACE.md` §3).

---

## 9. Prochaines actions possibles

1. Inspecter l'état réel de `briques/etl` et écrire un plan d'intégration
   Crawl4AI + Scrapling (contrats, routes, manifeste).
2. Lancer un atelier brainstorming sur la décision LibreChat vs
   Gateway+Assistant.
3. Définir le contrat de la nouvelle brique « Connexions » basée sur Nango.
4. Installer `agent-skills` dans le workflow OpenCode de l'équipe.

---

*Rapport fermé — source de vérité : `WORKPLACE.md`. Toute intégration
effective devra figurer en §4 (inventaire) et §5 (à construire).*