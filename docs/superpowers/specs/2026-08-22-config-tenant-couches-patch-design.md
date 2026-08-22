# Couches de patch déclaratif pour la config assistant — config_tenant.py

**Statut** : conçu, en attente d'implémentation (3e des 4 chantiers de la veille
[deepseek-harness/Cordis], après S234 audit gate Forge et l'invariant journal_modele).

## Contexte

La veille deepseek-harness (Cordis) documente un pattern de composition de config en
couches déclaratives : profil de base → bundles → patch de profil → patch de home →
overlay CLI, chaque couche remplaçant/insérant une entrée par id, sans forker le code.

Audit du Cœur (2026-08-22) : aucune couche de ce type n'existe aujourd'hui.
`core/contexte_tenant.py` fait de la pure propagation d'identité (3 `ContextVar`
posées par requête, relayées en en-têtes S2S vers les briques) — aucune config n'y
est attachée. `core/config_assistant.py::charger()` (modèle LLM, cascade, voix,
persona, langue) lit un **unique fichier JSON global** — un déploiement = une config,
pas de notion de tenant. Le seul mécanisme générique clé-valeur scopé par organisation
existant dans le dépôt est la brique `données` (`app_id`/`entite_id` → JSON, scopée par
`X-Org-ID`), déjà utilisée comme remplaçant du `localStorage` des apps générées.

C'est un chantier d'**anticipation architecture** (décision utilisateur explicite,
2026-08-22) : pas de client/organisation qui bute aujourd'hui sur la config globale
unique — le but est de préparer le terrain avant que le multi-org business
([[sprint-s227-entite-entreprise-unifiee]] → S230) ne le réclame.

## Décisions de portée (validées avec l'utilisateur)

1. **3 couches**, pas 5 comme dsh : `global` (fichier JSON existant, inchangé) →
   `organisation` (nouveau) → `utilisateur` (nouveau). Pas de couche CLI/overlay —
   aucun besoin identifié, cohérent avec la granularité mixte déjà actée en S121/S184.
2. **Tout le schéma actuel** de `charger()` est patchable (modèle, fallbacks, cascade,
   voix, persona, langue, routage, résumé, shadow, muscle, repli souverain) — pas un
   sous-ensemble arbitraire ; le mécanisme de fusion est générique par construction.
3. **Fusion façon JSON Merge Patch (RFC 7386)** : dicts fusionnés récursivement clé à
   clé ; toute valeur non-dict — **listes incluses** (`fallback_models`) — remplace
   entièrement la valeur de la couche du dessous, jamais de fusion élément par élément.
4. **Stockage via la brique `données`** (table en base, pas un JSON local par tenant) :
   réutilise le magasin générique déjà existant, pas de nouvelle table ni endpoint côté
   `données`.
5. **Cache en mémoire process avec TTL court**, invalidé activement à l'écriture : sans
   ça, chaque message assistant ferait 2 aller-retours réseau synchrones vers `données`
   à chaque tour, qui n'a aujourd'hui **aucun** appelant sur le chemin chaud d'une
   requête assistant (confirmé par audit — `core/config_assistant.py::charger()` est un
   simple read de fichier local, zéro latence réseau).

## Architecture

Nouveau module `core/config_tenant.py`, appelant `config_assistant.charger()` pour la
base plutôt que de complexifier ce fichier déjà dense (532 lignes, propriétaire du
pilotage Docker/clés Gateway — sujet sans rapport avec la résolution de couches).

### Stockage — clés dans la brique `données`

`app_id="_config_assistant"` (constante), scopé automatiquement par l'org courante via
l'en-tête `X-Org-ID` déjà généré par `contexte_tenant.entetes_donnees()` :
- couche organisation → `entite_id="_organisation"` (un enregistrement par org).
- couche utilisateur → `entite_id=<utilisateur>` (l'id posé par `_utilisateur` dans
  `contexte_tenant.py`) — scopé sous la MÊME org que la couche organisation, puisque
  les deux appels d'une même requête portent le même `X-Org-ID` sortant.

### Résolution

```python
async def resoudre(org_id: str | None, utilisateur: str | None) -> dict:
    base = config_assistant.charger()                       # global, sync, local
    patch_org = await _lire_couche("organisation", "_organisation", org_id)
    fusionne = _fusion_json_merge_patch(base, patch_org)
    patch_user = await _lire_couche("utilisateur", utilisateur, org_id) if utilisateur else {}
    return _fusion_json_merge_patch(fusionne, patch_user)
```

`_lire_couche(niveau, entite_id, org_id)` : vérifie le cache `(niveau, org_id, entite_id)`
(TTL ~90s) avant tout appel réseau ; sur hit cache expiré ET brique `données`
injoignable, sert quand même le cache expiré (mieux qu'un global nu) ; sans aucun
cache (premier appel, brique down), retombe sur `{}` (= couche absente, la résolution
continue avec les couches disponibles).

Point d'appel : le call-site actuel de `config_assistant.charger()` dans le chemin de
traitement du chat (`core/assistant.py`/`core/llm_pipeline.py`, à localiser précisément
en phase d'implémentation) devient `config_tenant.resoudre(org_actuel(), utilisateur_actuel())`
— lit les `ContextVar` déjà posées par `lire_contexte_tenant()`, aucune nouvelle
plomberie d'identité à ajouter.

### Écriture

```python
async def ecrire_couche(niveau: str, entite_id: str, org_id: str, patch: dict) -> dict
```

Valide le `patch` contre la **liste blanche** des clés connues de `config_assistant.charger()`
(les clés du dict `base` retourné) — toute clé inconnue est rejetée (erreur 400, pas
silencieusement ignorée). Écrit l'enregistrement dans `données` (upsert : lit
l'existant pour cette `(app_id, entite_id)`, fusionne le patch dessus — un `PUT` de
couche est lui-même un patch, pas un remplacement total — puis persiste). Invalide
immédiatement l'entrée de cache correspondante (write-through, pas d'attente du TTL).

### Endpoints (Cœur, `core/routers/assistant.py` ou nouveau routeur dédié)

- `GET /assistant/config` — **change de sens** : renvoie désormais le résolu
  (global+organisation+utilisateur) au lieu du global seul. C'est ce que consomme déjà
  le front (panneau ⚙ Cerveau) et, après le changement de call-site ci-dessus, le
  chemin de chat.
- `GET|PUT /assistant/config/organisation` — lit/écrit la couche organisation seule
  (pas le résolu). `org_id` provient de la même résolution que `tenant_actuel` côté
  brique `données` (JWT sinon `X-Org-ID` sinon `"defaut"`) — `"defaut"` est une
  organisation légitime comme une autre, pas un cas rejeté : un déploiement mono-org
  peut ainsi patcher sa propre config org sans configurer Keycloak au préalable.
- `GET|PUT /assistant/config/utilisateur` — lit/écrit la couche utilisateur seule.
- `GET /assistant/config/resolue` — **debug/transparence** : renvoie le résolu +, pour
  chaque clé, quelle couche a eu le dernier mot (`global`|`organisation`|`utilisateur`).
  Cohérent avec l'invariant « visible du modèle = traçable » déjà posé côté
  [[sprint-journal-modele-invariant-journal-verite]]. Pas d'UI dédiée dans ce chantier
  (JSON brut, consultable via curl/devtools) — juste l'endpoint.

Les endpoints/fonctions `définir_*` existants (`definir_modele`, `definir_persona`,
`definir_voix`, `definir_cascade`, `definir_routage`, `definir_muscle`,
`definir_repli_souverain`, `definir_langue`) sont **inchangés** : ils continuent
d'écrire la couche globale via `config_assistant.py`. Le panneau ⚙ Cerveau existant
n'a besoin d'aucune modification pour ce chantier.

## Résilience

- **Lecture** (`resoudre()`, `_lire_couche()`) : `except` **ciblé** sur les erreurs
  réseau/HTTP httpx (`httpx.HTTPError`, `httpx.TransportError`) autour de l'appel à
  `données` — pas un `except Exception` fourre-tout qui masquerait un bug réel. Une
  erreur réseau dégrade vers le cache expiré puis vers `{}` (couche absente), ne casse
  jamais un tour de conversation. Leçon déjà tirée sur ce projet
  ([[sprint-journal-modele-invariant-journal-verite]], commit `de4b0ce` — un `except`
  aussi large que la promesse « ne lève jamais » est un bug, pas une robustesse).
- **Écriture** (`ecrire_couche()`) : **jamais silencieuse** — une erreur réseau vers
  `données` remonte une vraie erreur HTTP à l'appelant (pas de faux succès, pas de
  patch perdu sans le dire).

## Compatibilité

Sans aucun override org/user (déploiements existants, org `"defaut"` implicite), la
résolution est bit-à-bit identique au comportement actuel : patch absent/vide =
no-op sur chaque couche. Zéro migration de données, zéro régression attendue.

## Tests

`core/test_config_tenant.py` :
1. Fusion JSON Merge Patch : précédence global < organisation < utilisateur, clé
   imbriquée partiellement surchargée, liste (`fallback_models`) **remplacée**
   entièrement (pas fusionnée élément par élément).
2. `ecrire_couche()` rejette une clé hors liste blanche (400), accepte un patch partiel
   valide.
3. Cache : hit dans le TTL ne refait pas d'appel réseau (mock compté) ; écriture
   invalide immédiatement l'entrée avant expiration du TTL.
4. Panne simulée de la brique `données` en lecture → repli cache expiré puis `{}`,
   aucune exception ne remonte. En écriture → l'erreur remonte à l'appelant.
5. Non-régression : sans aucune couche org/user présente, `resoudre()` retourne
   exactement `config_assistant.charger()`.

## Hors périmètre (différé)

- Pas de couche CLI/overlay (5e couche dsh) — aucun besoin identifié.
- Aucun changement à la gestion des clés API/Gateway (`recreer_gateway`,
  `FOURNISSEURS_CLES`) — infra globale au déploiement, sans rapport avec des
  préférences de tenant.
- Pas de routage Gateway par tenant au niveau infra — la couche organisation/utilisateur
  choisit juste une valeur de `model`/`cascade` différente, servie par la Gateway
  multi-fournisseurs déjà en place (S93/S94) ; aucune évolution de la Gateway requise.
- Pas d'UI dédiée à la gestion des couches org/utilisateur (formulaire ⚙ Cerveau par
  tenant) — les endpoints existent, le front reste à construire séparément le jour où
  un cas d'usage concret l'exige.
- Le 4e chantier de la veille (seams 3 rôles pour dev-auto-atelier/5955) reste non
  entamé.
