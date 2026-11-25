# S246 — VM 100 « dokploy » : journal d'installation (sans secret)

## Task 1 (2026-11-25)
- Méthode : image cloud Debian 13 (voie b, celle de `infra/ansible/exercise/create_vm.sh`), SHA512 vérifié.
- Choix non destructif : la définition de la VM 100 est conservée ; l'ISO est retirée, l'ancien disque
  vide (32 Go) reste détaché en `unused0` (`vm-100-disk-0.qcow2`), nouveau disque 60 Go importé.
- RAM 5824 Mo, 2 cœurs, démarrage auto au boot de l'hyperviseur (`onboot 1`), cloud-init `debian` + clé du Mac.
- IP LAN (DHCP) : 192.168.1.165 (à réserver côté routeur ou fixer avant d'exposer des services).
- Vérifié : Debian 13 (trixie), ~5,6 Go RAM, 59 Go disque, SSH par clé OK. RAM libre nœud avant démarrage : 8,4 Go.

## Task 2 (2026-11-25)
- NetBird 0.83.2 installé, enrôlé (setup key à usage unique, expirée sous 2 jours, non conservée) : FQDN `dokploy.netbird.cloud`, IP mesh `100.124.176.122`.
- Joignable depuis le HP par le mesh (ping 0 % de perte). Le Mac n'a pas répondu (pas dans le mesh ou hors ligne) : à vérifier.
- ufw : refus par défaut ; SSH depuis 192.168.1.0/24 et depuis `wt0` seulement.
- ⚠ Docker contourne ufw pour les ports publiés : au moment d'installer Dokploy/Forgejo, restreindre par la chaîne `DOCKER-USER` ou lier les ports à l'IP mesh, puis faire un test de refus réel (Task 3).

## Task 3 (2026-11-25)
- Rôles `dokploy`, `docker_user_guard`, `forgejo` + `playbooks/livraison.yml`, tests `tests/test_roles_livraison.py` (4 verts). Appliqué sur la VM 100 : ok=11, failed=0.
- Versions épinglées : Dokploy v0.31.4 (installateur officiel, `DOKPLOY_VERSION`), Forgejo 17.0.2, Traefik v3.7.19 et postgres:16 (choisis par l'installateur Dokploy, non épinglés par nous).
- Ports : Dokploy 3000, Traefik 80/443, Forgejo HTTP 3001 et SSH 2222. RAM après démarrage : ~1,3 Go utilisés / 5,6 Go.
- **Garde `DOCKER-USER`** (Docker contourne ufw) : tout port publié n'est joignable que depuis le LAN, le mesh et les réseaux Docker. **Test de refus réel** depuis une source simulée 203.0.113.2 (netns) : 3000 et 3001 refusés (compteur DROP à 8), LAN → 3001 = 200.
- Hors dépôt : comptes et clés dans `~/.workplace-secrets/s246-comptes.txt` (0600).

## Task 4 — spike d'API (contrats dans `docs/s246/contrats/`)
**Dokploy v0.31.4** (OpenAPI servie par `GET /api/settings.getOpenApiDocument`, session requise ; 659 routes)
- Auth machine : en-tête `x-api-key`. Clé créée par `POST /api/user.createApiKey` avec `metadata.organizationId` obligatoire.
- ⚠ **Écart n°1 : limite par défaut de 10 requêtes / 24 h par clé** (429 constaté à la 5ᵉ requête sur une clé de test déjà entamée). Créer la clé avec `rateLimitEnabled:false`. Vérifié : 14 appels de suite en 200.
- Routes utiles : `application.search|one|deploy|redeploy|reload|start|stop|readLogs`, `deployment.all?applicationId=`, `deployment.readLogs?deploymentId=`, `rollback.rollback {rollbackId}`, `project.all`, `backup.*` (S247).
- Écart n°2 : le **rollback se fait par `rollbackId`** (pas par applicationId) : il faut d'abord lister les rollbacks de l'app ; à relever dans la Task 5.
- Écart n°3 : `application.reload` exige `appName` ET `applicationId` ; mutations en `POST` JSON, lectures en `GET`.
- Premier compte créé par `POST /api/auth/sign-up/email` → rôle `owner`, organisation créée automatiquement.
- Une clé de test (`spike-s246`, limitée à 10/jour) reste à supprimer dans l'interface.

**Forgejo 17.0.2** (swagger `GET /swagger.v1.json`, base API Gitea 1.22) : jetons personnels à portée limitée, création de dépôt `POST /user/repos`, miroirs `POST /repos/migrate`.

## Task 5 — app témoin Calendrier Familial (2026-11-25)
- Dépôt poussé dans Forgejo (`wp-admin/calendrier-familial`, public, branche `main`) ; projet Dokploy `temoin`, application `calendrier-familial` (source git personnalisée, build Dockerfile). Service Swarm 1/1, healthcheck interne 200. RAM VM : ~1,5 Go / 5,6 Go.
- **Écart n°4** : 1er déploiement en erreur — les conteneurs de build ne joignaient pas Forgejo (ufw bloque les réseaux Docker vers l'hôte). Règle `ufw allow from 172.16.0.0/12 to port 3001` ajoutée au rôle `forgejo` (+ test) et réappliquée ; 2ᵉ déploiement `done`. Les logs d'échec sont lisibles via `deployment.readLogs` (le client devra les filtrer, S249).
- Prouvé par l'API : `deploy`, `redeploy`, `reload` (exige `appName`+`applicationId`), `stop` (service 0/0, statut `idle`), `start` (1/1, `done`), `deployment.all`, `deployment.readLogs`.
- **Écart n°5** : `start`/`stop` renvoient **tout l'objet application** (≈ 5 Ko, dont `refreshToken`) → la brique doit en extraire quelques champs, jamais le renvoyer au LLM.
- **Écart n°6 (ROLLBACK, non résolu)** : `application.update {rollbackActive:true}` n'a produit aucun `rollbackId` visible après un redéploiement ; aucune route de liste des rollbacks n'existe (seulement `rollback.rollback` et `rollback.delete`). Dokploy lie le rollback à un **registre d'images** (`rollbackRegistryId`, routes `registry.*`). Piste : utiliser le registre de conteneurs de Forgejo, ce qui impose de déclarer `192.168.1.165:3001` comme registre non sécurisé (HTTP) dans le démon Docker de la VM 100. **Décision à prendre avant la Partie 2.**

## Suite Task 5 (2026-11-25) — écarts résolus
- **Limite 10 requêtes/jour : résolue.** Clé créée avec `rateLimitEnabled:false` (14 appels de suite en 200). Clé de test `spike-s246` supprimée (`user.deleteApiKey {apiKeyId}`, l'id vient de `user.get`).
- **Rollback par le registre Forgejo : prouvé.** Rôle `forgejo` : `/etc/docker/daemon.json` `insecure-registries` (HTTP, LAN/mesh uniquement ; Docker redémarré, garde `DOCKER-USER` toujours en place). Dokploy : `registry.create` (`registryType:"cloud"`, jeton Forgejo `write:package`), puis `application.update {rollbackActive:true, rollbackRegistryId, registryId}`. Chaque déploiement suivant pousse `:vN` + `:latest` dans Forgejo et porte un `rollbackId` (champ `deployments[].rollbackId` de `application.one`). `rollback.rollback {rollbackId}` : image `:latest` → `:v1`, conteneur sain.
- ⚠ `registry.create` renvoie le mot de passe/jeton en clair : la brique ne doit jamais relayer cette réponse.
- **Miroir GitHub → Forgejo** : dépôt Forgejo recréé en *pull mirror* (`POST /repos/migrate`, `mirror:true`, `mirror_interval:"10m0s"`), lecture seule côté Forgejo ; on pousse sur GitHub, Forgejo suit en ≤ 10 min (`POST /repos/{o}/{r}/mirror-sync` pour forcer). Un dépôt privé exigerait un jeton GitHub. Dokploy ne redéploie pas tout seul à la synchro (déploiement toujours demandé via la brique).
