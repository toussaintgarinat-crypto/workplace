# Sprint S141 — Forge DB : activer le mot de passe dans .env.example et le .env

> **But du sprint** : sortir `FORGE_DB_PASSWORD` de l'état "commenté dans .env.example"
> pour qu'il ne soit plus jamais laissé à sa valeur par défaut `forge_secret_change_this`.
> Sprint court (< 30 min) mais important avant tout déploiement sur le HP.

- **Sprint** : S141
- **Catégorie** : Configuration / sécurité
- **Statut** : À planifier
- **Date de planification** : 2026-07-03
- **Brique concernée** : `briques/forge/`

---

## Contexte

Dans `briques/forge/docker-compose.yml` :

```yaml
forge-db:
  image: postgres:16.14
  environment:
    POSTGRES_PASSWORD: ${FORGE_DB_PASSWORD:-forge_secret_change_this}
```

Dans `.env.example` racine (ligne 77) :
```
#FORGE_DB_PASSWORD=
```

La ligne est **commentée** → `FORGE_DB_PASSWORD` n'est pas définie → le compose utilise
le fallback `forge_secret_change_this`. Ce mot de passe est dans le code source, connu
de quiconque lit ce dépôt.

La brique Forge est la plus critique du projet : elle contient les agents IA, les documents
clients et la base vectorielle RAG (~28 400 lignes de code).

---

## Chantiers

### C0 — Générer et définir FORGE_DB_PASSWORD dans `.env` racine

```bash
# Sur le Mac (dev) et sur le HP (prod), faire :
echo "FORGE_DB_PASSWORD=$(openssl rand -hex 24)" >> ~/Desktop/Workplace/.env
```

Vérifier qu'elle n'est pas déjà définie avant d'ajouter.

### C1 — Décommenter et documenter dans `.env.example`

```diff
# .env.example (ligne 77)
- #FORGE_DB_PASSWORD=
+ FORGE_DB_PASSWORD=GENERER_openssl_rand_-hex_24
```

Ajouter un commentaire au-dessus :
```
# Mot de passe PostgreSQL de la brique Forge. OBLIGATOIRE en production.
# Générer : openssl rand -hex 24
```

### C2 — Vérifier la propagation dans le compose

S'assurer que `FORGE_DB_PASSWORD` est bien transmis à tous les services qui en ont besoin
dans `briques/forge/docker-compose.yml` :

```bash
grep -n "FORGE_DB_PASSWORD\|forge_secret" /Users/garinat_t/Desktop/Workplace/briques/forge/docker-compose.yml
```

La variable doit apparaître dans `forge-db` (✓ déjà présent) et potentiellement dans le
service `forge` lui-même si sa `DATABASE_URL` en dépend.

### C3 — Idem pour FORGE_SERVICE_SECRET

Vérifier que `FORGE_SERVICE_SECRET` (déjà dans `.env` racine — valeur réelle trouvée lors
de l'audit) est aussi dans `.env.example` avec un placeholder clair, pas une valeur vide.

```bash
grep "FORGE_SERVICE_SECRET" /Users/garinat_t/Desktop/Workplace/.env.example
```

---

## Critère d'acceptation

- `FORGE_DB_PASSWORD` défini dans `.env` racine (valeur forte, pas le fallback)
- `.env.example` montre un exemple clair avec la commande de génération
- `docker compose up` dans `briques/forge/` démarre sans utiliser `forge_secret_change_this`

---

## Effort estimé

**20 minutes.** Uniquement de la configuration.

## Note

Si un volume Postgres Forge existe déjà avec l'ancien mot de passe, il faut soit :
1. Changer le mot de passe via `ALTER USER forge PASSWORD 'nouveau';` dans psql
2. Ou supprimer le volume et recréer (si les données ne sont pas critiques)

```bash
docker volume ls | grep forge
docker exec -it <forge-db-container> psql -U forge -c "ALTER USER forge PASSWORD 'nouveau_mdp';"
```
