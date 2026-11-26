# S247 (partie 2a) — Preuve LIVE de la sauvegarde vérifiée (2026-11-26)

App témoin : `calendrier-familial` (projet Dokploy `temoin`). Base témoin : Postgres `s247-pg` (42 lignes dans `evenements`).
Chaîne : brique `livraison` (HP) → Dokploy (sauvegarde vers le SeaweedFS du HP, S3 :9106) → exécuteur de restauration (VM 100, :8090) → comparaison des comptages → preuve enregistrée dans la brique.

## Déploiement
- VM 100 : rôle Ansible `executeur_restauration` appliqué SEUL (le playbook complet changerait `ROOT_URL` de Forgejo et réappliquerait `docker_user_guard` : dérive préexistante, non touchée). Secrets dans `/etc/executeur-restauration/env` (root 0600, créé à la main, jamais affiché). Bucket `dokploy-backups` créé. ufw : seul le HP atteint 8090 (le Mac expire).
- HP : images taguées `avant-s247` (Cœur et brique) AVANT reconstruction (construction sur le Mac puis `docker save | ssh docker load`, cf. piège DNS pip). `briques/livraison/.env` (0600) porte `EXECUTEUR_URL`/`EXECUTEUR_KEY` ; l'inventaire est dans le volume `/data/inventaire.json`. Le `docker-compose.yml` de la brique est modifié à la main sur le HP (4 lignes, second `env_file`) : `git checkout briques/livraison/docker-compose.yml` avant tout `git pull` d'un main qui contient S247.

## Droits de la clé Dokploy limitée (utilisateur membre du projet `temoin`)
| Action | Résultat |
|---|---|
| `postgres.create`, `destination.*` | 401 (réservé à l'owner : fait une fois, en session) |
| accès à un service neuf | 401 tant qu'il n'est pas ajouté à `accessedServices` (`user.assignPermissions` avec l'identifiant utilisateur — pas l'identifiant de membre, qui répond 200 sans rien changer) |
| `backup.create`, `backup.manualBackupPostgres`, `backup.listBackupFilesByBackupId`, `postgres.one` | OK une fois le service accordé |
La brique n'utilise donc jamais la clé owner.

## Résultats
| Essai | Verdict constaté |
|---|---|
| Nominal | `valide`, comptages `{"evenements": 42}` = 42, nettoyage ok, aucun `restore_*` restant |
| Sabotage 1 : mauvais `prefixe_s3` (mon inventaire sans l'appName) | `invalide` : « téléchargement de la sauvegarde impossible » ; preuve non valide |
| Sabotage 2 : exécuteur arrêté | `invalide` : « Exécuteur de restauration injoignable » |
| Sabotage 3 : mauvaise `EXECUTEUR_KEY` | `invalide` : « L'exécuteur a refusé la clé » |
| Retour à la normale | `valide` de nouveau |
| Sauvegarde Forgejo ×8 | 94 Mo, 7 conservées (la plus ancienne supprimée), `zip` valide (107 entrées, dépôts inclus) |

Rôle jetable : la restauration et la relecture se font avec `restore_<hex>` (sans privilège) ; le compte de la base témoin est superutilisateur, donc ce correctif était nécessaire. La connexion par socket local sans mot de passe fonctionne sur l'image `postgres:16` de Dokploy.

## Pièges
- `prefixe_s3` de l'inventaire = préfixe COMPLET `<appName>/<préfixe Dokploy>` (l'objet est `<appName>/<prefix>/<horodatage>.sql.gz`).
- Les routes de sauvegarde Forgejo écrivent sous `forgejo/` dans le même bucket.
- **Le Cœur lit les manifestes dans `/briques`, monté depuis la copie git du HP** (pas dans son image) : reconstruire le Cœur ne suffit pas, il faut mettre à jour `briques/livraison/manifest.json` sur le HP puis redémarrer le Cœur. Sans cela l'assistant répond « l'outil n'existe pas » et invente des chiffres (constaté : comptages et tailles fantaisistes dans sa 1ʳᵉ réponse — ne jamais se fier à un récit de l'assistant sans la preuve).
- Le HP porte deux écarts non commités : `docker-compose.yml` et `manifest.json` de `briques/livraison` (rustines S247). `git checkout` de ces deux fichiers avant le prochain `git pull`.

## Preuve côté Cœur (depuis le chat)
Demande explicite « utilise `livraison_verifier_sauvegarde` pour calendrier-familial » : verdict `valide`, preuve `4878d0a6506f00cc`, comptages `{"evenements": 42}`. Le Cœur a enregistré la preuve (table `preuves` de `approbations.db`) pour le compte de l'utilisateur sous les deux clés `calendrier-familial` et l'identifiant Dokploy, avec l'expiration de la brique. La 1ʳᵉ formulation vague (« vérifie la sauvegarde ») a fait choisir `/etat` à l'assistant : le routage d'outils reste à surveiller.

Reste : partie 2b (reset de l'app entière, bascule, retour arrière).
