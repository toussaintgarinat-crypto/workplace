# Brique `dev` — l'auto-atelier souverain (port 5950)

Modifier les briques de Workplace et **ajouter des features depuis l'assistant**, avec le
**filet git** comme garantie « on ne casse pas la prod ».

> ⚠️ **Atelier PERSO SOUVERAIN.** Mono-user, local / self-host, **jamais exposé à un client**
> (comme la brique `paiements` est cloisonnée exprès). Un agent de code = exécution de code
> arbitraire ; le filet git + le gate humain sont ce qui rend ça sûr.

## Le principe (le filet)

L'agent ne travaille **jamais** dans le dépôt vivant. Pour chaque chantier :

1. `git worktree add -b dev/<intention> <chemin> <base>` — une copie isolée, branche neuve,
   **jamais `main`**. La prod continue de tourner.
2. L'agent (**Claude Code** ou **OpenCode**, sinon **mock honnête**) code dans le worktree et
   commite sur sa branche.
3. On relit le **diff** (`base...branche`) — le gate humain.
4. Soit on **fusionne** (gate humain, S87), soit on **jette** : `git worktree remove` →
   chantier effacé, prod intacte. Aucun `git push`, aucun déploiement automatique.

## La task trace (S89 — apprendre en regardant)

Interrupteur **on/off** par chantier (`trace:true`). Quand c'est ON, l'agent **raconte chaque pas
en français** — le factice narre ses pas ; **Claude Code** délègue la narration fine de ses outils
à un **hook `PreToolUse`** (`trace_hook.py`) qui les traduit (« je lis le fichier… », « je lance la
commande… »). La narration est **archivée** (`chantier.journal`, durable dans un JSONL par chantier)
ET **diffusée en direct** :

```
GET /chantiers/{id}/trace        # flux SSE de la narration en temps réel
GET /chantiers/{id}/trace?suivre=false   # relire l'archive puis clore
```

Trace OFF → l'agent bosse en silence, on ne montre que le diff final.

## Le flux BMAD léger (S88 — le plan d'abord, opt-in)

Reprend 3 idées de **BMAD** sans l'installer : un agent **« Architect »** par phase, le **plan
AVANT le code**, et la **story qui porte le contexte**. Opt-in par chantier (`plan_requis:true`) ;
sinon le flux direct de S86 reste intact.

1. `POST /chantiers/{id}/planifier` — l'Architect conçoit un plan en **trois sections imposées** :
   `## Mini-PRD` · `## Stories` · `## Domaine (DDD)` (le domaine pur d'abord). LLM Gateway, **repli
   honnête local** si pas de LLM (`genere_par` dit toujours la vérité).
2. `POST /chantiers/{id}/plan/valider` (`confirme=true`) — **1er gate** du double gate : valider
   le plan **débloque** le codage. Tant que ce n'est pas fait, `lancer` répond `409`.
3. Le plan validé est **injecté** à l'agent codeur (la story porte le contexte), puis on relit le
   diff — **2e gate** — et on fusionne (S87).

## La fusion contrôlée (S87 — le seul geste qui touche `main`)

Une fois le diff relu, on **confirme** : la branche est fusionnée dans `main` (`git merge
--no-ff`, donc un commit de merge **relisible / `git revert`-able**), puis on rebuild **la
seule brique modifiée**, puis on jette le worktree. Garde-fous, par construction :

- **Gate explicite** : `confirme=true` requis (sinon `428`) — la fusion modifie `main`.
- **Briques sensibles** : `paiements` / `connexion` / `auth` sont **refusées** (`403`) sauf
  déblocage explicite via `DEV_BRIQUES_DEBLOQUEES`.
- **Jamais forcé** : un conflit (ou un arbre sale) → `merge --abort` + `409`, dépôt laissé propre.
- **Rebuild ciblé** : **simulé honnête** par défaut (commande `docker compose` journalisée, non
  exécutée) ; réel seulement si `DEV_REBUILD=1`.

## API (v0.4.0)

| Méthode | Chemin | Rôle |
|---|---|---|
| `GET`  | `/sante` | Vivant + filet présent + agents disponibles |
| `POST` | `/chantiers` | Ouvre un worktree + branche neuve (`intention`, `brique_cible`, `agent`, `trace`, `sprint`, `plan_requis`) |
| `POST` | `/chantiers/{id}/planifier` | **BMAD** : l'Architect conçoit le plan (mini-PRD + stories + DDD) |
| `POST` | `/chantiers/{id}/plan/valider` | **Gate de plan** (`confirme=true`) → débloque le codage |
| `POST` | `/chantiers/{id}/lancer` | L'agent code dans le worktree, commite (verrouillé si plan requis non validé) |
| `GET`  | `/chantiers/{id}/trace` | **Task trace** SSE : la narration FR en direct (`suivre=false` = archive) |
| `GET`  | `/chantiers/{id}/diff` | Le diff à relire (jamais déployé) |
| `POST` | `/chantiers/{id}/fusionner` | **Gate** (`confirme=true`) → merge dans `main` + rebuild ciblé → jette |
| `GET`  | `/chantiers` · `/chantiers/{id}` | Liste / détail |
| `DELETE` | `/chantiers/{id}` | Jette le worktree (chantier + trace effacés) |

`agent` ∈ `claude_code` | `opencode` | `factice` | `""` (auto : Claude Code → OpenCode →
mock honnête). Si `DEV_KEY` est défini, l'en-tête `X-API-Key` est exigé.

## Réglages (env)

- `DEV_REPO` — dépôt cible (défaut : la racine Workplace)
- `DEV_ATELIERS` — dossier des worktrees jetables (hors du dépôt)
- `DEV_DB` — fichier JSON des chantiers
- `DEV_KEY` — clé d'accès optionnelle (vide = atelier local ouvert)
- `DEV_REBUILD` — `1` pour rebuild RÉELLEMENT la brique fusionnée (défaut : simulé honnête)
- `DEV_BRIQUES_DEBLOQUEES` — CSV de briques sensibles autorisées à la fusion (au cas par cas)
- `GATEWAY_URL` / `GATEWAY_KEY` / `GATEWAY_MODEL` — LLM du plan BMAD (repli honnête local si absent)
- `DEV_TRACES` — dossier des journaux de trace (un JSONL par chantier)

## Tests

```bash
python3 -m pytest -q   # 42 tests : domaine + filet + fusion + BMAD + task trace + parcours mock
```

## Feuille de route (sprints — détail dans `SPRINTS.md`)

- **S86** ✅ Socle git (worktree + branche + diff, prouvé sans déploiement)
- **S87** ✅ Fusion contrôlée + rebuild ciblé (ferme la boucle ; seul sprint qui touche `main`)
- **S88** ✅ Flux **BMAD** léger : plan d'abord (mini-PRD + stories + DDD) + gate de plan
- **S89** ✅ **Task trace** activable (narration pas-à-pas FR, SSE direct + archive)
- **S90** La **porte** à divulgation progressive (skills/MCP) + **prompt caching** (préfixe stable)
- **S91** **Création de skills** + accroche **MCP** par la brique
- **S92** **IDE `code-server`** en iframe + outil Cœur `dev_demander` (gate dans le chat)
