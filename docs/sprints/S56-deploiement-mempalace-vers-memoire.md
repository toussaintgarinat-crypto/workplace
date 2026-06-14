# Sprint S56 — Déploiement de la migration MemPalace → brique `memoire`

> Suite directe de la migration du 2026-06-14 (cf. mémoire
> `migration-mempalace-vers-brique-memoire`). S54/S55 restent réservés au Studio
> (`plan-studio-brique-autonome` : S54 migration/décommission `atelier_router`,
> S55 vidéo). Le **code** de cette migration-ci est livré et prouvé
> (tests dans les images réelles + LIVE par exec direct contre la brique). Ce
> sprint **déploie** ce code dans les process qui tournent et **vérifie** le
> bout-en-bout à travers les services réels (Keycloak, navigateur).

## Pourquoi

La migration est codée, testée (brique 10 · Forge 180 · Oria 143+9) et prouvée
LIVE par exec direct. Mais **les conteneurs en service exécutent encore l'ancien
code** : `forge-forge-1` sert le router/front baked, `oria-backend-1` a été démarré
avant l'ajout de `MEMOIRE_URL`. Tant que ce n'est pas déployé + vérifié à travers
les vrais process, la migration n'est pas « finie » pour les utilisateurs.

## Périmètre (reliquat uniquement)

### 1. Déployer Forge core
- `docker compose build` + recreate du service `forge` (brique `briques/forge/forge`).
- Vérifier au démarrage : `/api/memory/taxonomy` répond (pas la table morte), aucun
  import résiduel `MemoryEntries` (les 180 tests le garantissent déjà).
- **DoD** : un appel authentifié réel (JWT Keycloak realm oria + `X-Org-ID`) sur
  `GET /v1/api/memory/taxonomy` renvoie `{total, wings}` depuis la brique.

### 2. Déployer le front Forge
- Le `dist` est déjà buildé (Vite OK). Rebuild image `forge-frontend` (ou publier le
  `dist`) + recreate.
- **DoD (Playwright)** : ouvrir la vue MemPalace dans le dashboard Forge → **plus
  d'écran de login `mp_token`** ; les onglets IPCRa affichent les comptes ; ajouter
  un souvenir, le rechercher, le supprimer ; tout passe par `/api/memory*` (vérifier
  l'onglet réseau : aucune requête vers `localhost:8100`).

### 3. Déployer Oria backend
- Recreate `oria-backend-1` pour charger `MEMOIRE_URL` (compose déjà à jour +
  `extra_hosts host-gateway`).
- **DoD** : `docker exec oria-backend-1 env | grep MEMOIRE_URL` non vide ;
  un tour de jardin réel (conversation) puis une recherche IPCRa retrouvent le
  souvenir via la brique (logs : appels à `/retenir` / `/rappeler`).

### 4. Vérification bout-en-bout inter-briques
- Écrire un souvenir **depuis Oria** (espace `oria-user-<id>`) et un **depuis Forge**
  (espace `forge-org-<id>`) ; confirmer l'**isolation** (l'un ne voit pas l'autre)
  et que chacun se relit dans sa propre surface.
- **DoD** : capture LIVE des deux côtés + isolation prouvée.

### 5. Nettoyage de dette (non bloquant)
- **Table orpheline `memory_entries`** (Forge DB) : plus de modèle ni d'écriture.
  Drop SQL manuel à jouer sur la base Forge (sauvegarde d'abord) :
  `DROP TABLE IF EXISTS memory_entries;`. Vérifier au préalable qu'elle ne contient
  pas de données client à exporter (sinon export RGPD avant drop).
- **Espaces de démo** laissés dans la DB Memory pendant les preuves :
  `forge-org-demo`, `forge-org-demo2`, `oria-user-u-oria-live`. À purger (suppression
  des nœuds, ou laisser — ils sont isolés et inoffensifs).
- **Shared lib `agent_personnel_shared`** : défaut `http://mempalace:8100` dans
  `http_client.py` / `health.py` (vendorisé Forge **et** agenda). Non invoqué par le
  `/health` de Forge core (qui ne checke que Postgres), mais à corriger pour ne plus
  référencer un service mort. ⚠️ Touche aussi la brique `agenda` → tester les deux.

## Ordre conseillé
3 (Oria, le moins risqué) → 1 (Forge core) → 2 (front Forge) → 4 (vérif croisée) → 5 (dette).

## Risques & rollback
- **Interruption de service** : recreate des conteneurs coupe brièvement Forge/Oria.
  Faire hors usage. Rollback = `docker compose up -d` sur l'image précédente (les
  images ne sont pas supprimées) ; la brique `memoire` n'est pas touchée.
- **Données** : aucune perte attendue — la DB Memory (volume `memoire_pgdata`) et la
  DB Forge persistent ; seul du code/process est remplacé. Le drop de `memory_entries`
  est la **seule** opération destructive → backup + vérif contenu d'abord.
- **`MEMOIRE_URL` injoignable** : dégradation gracieuse déjà codée (Forge → 503/502
  borné ; Oria → `[]`/`False`). Pas de plantage si la brique tombe.

## Définition de fin (sprint bouclé)
- [ ] Forge core + front + Oria backend tournent sur le nouveau code.
- [ ] MemPalace (vue Forge) fonctionne sans `mp_token`, 100 % via `/api/memory*` (Playwright).
- [ ] Aller-retour LIVE Oria et Forge à travers les **process déployés** (pas par exec).
- [ ] Isolation par espace vérifiée LIVE.
- [ ] Dette traitée ou explicitement reportée (table morte, espaces démo, shared lib).
