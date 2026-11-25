# S246 — Forgejo + Dokploy + brique `livraison` : plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal :** Poser la chaîne dépôt → déploiement en interne (Forgejo + Dokploy sur la VM Proxmox 100) et donner à l'assistant ses premiers outils d'exploitation (lire état/logs, redémarrer, rollback, déployer), chaque action au-delà de la lecture validée par l'humain sur Telegram (socle S245/S245b).

**Architecture :** Forgejo et Dokploy tournent sur la VM 100, joignables seulement par le mesh NetBird. Une brique `livraison` (client HTTP des API Dokploy et Forgejo) expose ses capacités à l'assistant par `manifest.json` ; les capacités non-lecture déclarent `sensibilite` et passent par `approbations`. L'assistant n'a jamais le socket Docker : il n'appelle que des API HTTP.

**Tech Stack :** Proxmox (`qm`), Debian 13, Docker, Dokploy, Forgejo, Ansible (`infra/ansible/`), Python 3 / FastAPI / httpx / pytest (brique), faux serveur HTTP local pour les tests de contrat.

## Découpage honnête en deux parties

L'API de Dokploy et la forme de ses clés **ne sont pas connues** (aucune installation n'existe) et la spec interdit de coder le client « de mémoire ». Ce plan est donc en deux parties :

- **Partie 1 (rédigée ici, exécutable maintenant)** : mettre la VM 100 en service, installer Forgejo et Dokploy, **faire le spike d'API** et en tirer le contrat figé. Dépend de l'utilisateur à deux endroits (installation Debian à la console, création des comptes admin).
- **Partie 2 (squelette ci-dessous, à détailler en plan complet APRÈS le spike)** : la brique `livraison` (code + tests de contrat). Ses tâches sont listées, mais les corps d'appel HTTP viennent des fichiers `docs/s246/contrat-dokploy.md` et `contrat-forgejo.md` produits par la tâche 4. Relancer `writing-plans` pour la Partie 2 avec ces deux fichiers.

## Global Constraints

Décisions du 2026-11-25 (fichier S246) :
- **RAM** : VM 103 déjà réduite à 20 Go (fait). La VM 100 garde **5824 Mo**, 2 cœurs, disque 32 Go. Ne jamais redémarrer ni modifier la VM 103/104 sans accord explicite de l'utilisateur.
- **Forgejo sur la même VM que Dokploy** ; sauvegarde des dépôts Forgejo à prévoir (S247) ; GitHub reste miroir public.
- **App témoin : Calendrier Familial** (`/Users/garinat_t/Desktop/calendrier-familial`, dépôt local existant, avec base de données). Pas de rollback destructif sur des données réelles.
- Dokploy possède son Docker et son Traefik : **zéro conflit avec Caddy**, zéro accès au socket Docker de Workplace.
- Interfaces Dokploy/Forgejo **non exposées publiquement** (mesh NetBird seulement).
- Clé API Dokploy / jeton Forgejo : **variables d'environnement**, jamais littérales dans un compose (piège env-shadow : pas de `VAR=${VAR:-}`), portée minimale.
- Nom de brique : **`livraison`** (pas « forge »). Port : à vérifier libre dans les `manifest.json` avant de le figer (6240 proposé).
- **Ne pas poser** `APPROBATIONS_CLE`, `CONNEXION_KEY`, `CONNEXION_API_KEYS`, `API_KEYS`, `TELEGRAM_WEBHOOK_SECRET` sur le HP avant la fin d'S246 ; ne jamais remplir `API_KEYS`.
- Prérequis avant toute capacité Forge sensible : voir le fichier S246 (jeton utilisateur / repli compte de service).
- Aucune modification de la VM sans validation de l'utilisateur ; aucun secret en clair dans le dépôt ni dans les commits ; pas de `rm -rf` (utiliser `trash`).
- Code, commentaires, messages en **français**. Commits : fin de message = `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>` puis `Claude-Session: https://claude.ai/code/session_01HhWGGaLbPBnwM9KTfyyUQp`.
- Accès Proxmox : `ssh -o BatchMode=yes root@192.168.1.222` (voir mémoire `acces-ssh-proxmox-hyperviseur`).

---

# PARTIE 1 — Infrastructure et spike d'API

### Task 1 : Installer Debian 13 sur la VM 100 (avec l'utilisateur)

**Files:**
- Create: `docs/s246/vm100-installation.md` (journal d'installation, sans secret)

**Interfaces:**
- Produces : VM 100 démarrée, Debian 13 installé, SSH par clé pour `debian@<ip VM 100>`, IP relevée.

- [ ] **Step 1 : Contrôles préalables (lecture seule)**

```bash
ssh -o BatchMode=yes root@192.168.1.222 'free -m | sed -n 2p; qm status 100; qm config 100 | grep -E "^(memory|cores|ide2|scsi0|net0|boot)"'
```
Expected : `Mem` avec ≥ 8000 libres ; `status: stopped` ; `memory: 5824`. Si la RAM libre est < 7000 Mo, **s'arrêter** et prévenir l'utilisateur.

- [ ] **Step 2 : Choisir la méthode d'installation avec l'utilisateur**
  Deux voies : (a) installation interactive depuis l'ISO déjà branchée (console Proxmox, l'utilisateur déroule l'installateur) ; (b) image cloud Debian comme `infra/ansible/exercise/create_vm.sh` (reproductible, recommandé pour un rôle Ansible). Si (b), recréer la VM 100 est une **opération destructive sur une VM vide** : demander l'accord explicite avant de la supprimer/recréer.

- [ ] **Step 3 : Démarrer la VM et installer** (accord explicite requis avant `qm start 100`)

```bash
ssh -o BatchMode=yes root@192.168.1.222 'qm start 100 && qm status 100'
```
Voie (a) : l'utilisateur installe Debian (partitionnement guidé, serveur SSH, utilisateur `debian`). Voie (b) : `create_vm.sh` + `provision.yml`.

- [ ] **Step 4 : Poser la clé SSH et relever l'IP** — noter l'IP de la VM 100 dans `docs/s246/vm100-installation.md` (aucun mot de passe).

- [ ] **Step 5 : Vérifier**

```bash
ssh -o BatchMode=yes debian@<IP_VM100> 'lsb_release -d; free -m | sed -n 2p; df -h / | tail -1; nproc'
```
Expected : Debian 13, ~5,7 Go de RAM, 2 cœurs.

- [ ] **Step 6 : Commit** `docs(s246): installation VM 100` (fichier sans secret).

### Task 2 : Enrôler la VM 100 dans le mesh NetBird et verrouiller l'accès

**Files:**
- Modify: `docs/s246/vm100-installation.md`

- [ ] **Step 1 :** Installer le client NetBird selon `GUIDE-mesh-netbird.md` (lire la section « enrôler une machine »), l'utilisateur fournit/valide la clé d'enrôlement (secret : jamais dans le dépôt).
- [ ] **Step 2 :** Pare-feu de la VM 100 (`nftables`/`ufw`) : n'autoriser en entrée que SSH et les ports Dokploy/Forgejo **depuis le mesh et le LAN d'administration**. Vérifier depuis le Mac et depuis le HP.
- [ ] **Step 3 :** Vérifier qu'un port Dokploy/Forgejo n'est **pas** joignable depuis une adresse hors mesh/LAN (test de refus réel, pas seulement la règle).
- [ ] **Step 4 :** Commit `docs(s246): VM 100 dans le mesh, accès verrouillé`.

### Task 3 : Installer Forgejo et Dokploy (rôle Ansible reproductible)

**Files:**
- Create: `infra/ansible/roles/dokploy/` (tasks, defaults, README) ; `infra/ansible/roles/forgejo/` (idem) ; `infra/ansible/playbooks/livraison.yml`
- Create: `infra/ansible/tests/test_roles_livraison.py`

**Interfaces:**
- Produces : Dokploy et Forgejo en service sur la VM 100 ; versions **épinglées** (aucun tag flottant) ; ports effectifs relevés dans `docs/s246/vm100-installation.md`.

- [ ] **Step 1 : Relever les versions à épingler** (lecture de la doc officielle de chaque projet — ne pas deviner un numéro) et lire un rôle existant (`infra/ansible/roles/compose/`) pour suivre ses conventions.
- [ ] **Step 2 : Écrire le test qui échoue** — `test_roles_livraison.py` : le playbook référence les deux rôles ; aucun tag d'image `latest` ; aucun secret littéral ; aucun port publié sur `0.0.0.0` hors liste blanche. Lancer : `cd infra/ansible && python3 -m pytest -q tests/test_roles_livraison.py` → FAIL.
- [ ] **Step 3 : Écrire les rôles** : Dokploy via son installateur officiel **dans le rôle** (version épinglée, vérifier ce que l'installateur modifie sur l'hôte : Docker Swarm, ports 80/443/3000), Forgejo en conteneur (compose épinglé, volume dédié, SQLite ou Postgres selon la RAM). Forgejo sur un port distinct de ceux de Traefik.
- [ ] **Step 4 :** Les tests passent (`pytest` ci-dessus), puis `ansible-playbook --check` sur la VM 100.
- [ ] **Step 5 : Appliquer** (accord de l'utilisateur) et relever : `docker ps`, RAM utilisée (`free -m` après démarrage), ports en écoute.
- [ ] **Step 6 : Commit** `feat(s246): rôles Ansible dokploy et forgejo`.

**Critère d'arrêt :** si la RAM utilisée après installation dépasse ~4,5 Go (marge insuffisante), s'arrêter et en parler à l'utilisateur avant d'ajouter quoi que ce soit.

### Task 4 : Spike d'API — figer les contrats Dokploy et Forgejo

**Files:**
- Create: `docs/s246/contrat-dokploy.md`, `docs/s246/contrat-forgejo.md`, `docs/s246/spike-dokploy.sh` (appels de découverte, jeton en variable d'environnement)

**Interfaces:**
- Produces : pour chacune des 8 opérations (`apps`, `etat`, `logs`, `redemarrer`, `rollback`, `deployer`, + lecture des sauvegardes pour S247, + création d'un dépôt côté Forgejo) : méthode, chemin, en-têtes d'authentification, corps, forme de la réponse, codes d'erreur, et **l'exemple de réponse réelle** (secrets masqués). Aussi : forme et portée possible de la clé API, existence d'un OpenAPI/Swagger dans la version installée.

- [ ] **Step 1 :** L'utilisateur crée les comptes administrateur (Dokploy, Forgejo) à la première connexion ; générer une clé API Dokploy et un jeton Forgejo **de portée minimale**, les poser dans un fichier privé hors dépôt (0600) — jamais dans le terminal partagé ni dans un commit.
- [ ] **Step 2 :** Relever l'OpenAPI/Swagger de la version installée (si exposé) ; sinon lire la doc de **cette** version. Ne rien déduire de la mémoire.
- [ ] **Step 3 :** Exécuter chaque opération sur l'**app témoin** seulement. Déployer d'abord une app jetable triviale (image `nginx` épinglée) pour valider le cycle, **avant** Calendrier Familial.
- [ ] **Step 4 :** Consigner les réponses réelles (masquer jetons/e-mails) dans les deux fichiers de contrat.
- [ ] **Step 5 :** Noter les écarts avec la conception du fichier S246 (par ex. pas d'endpoint de rollback → à reconstruire par redéploiement de l'image précédente) dans une section « Écarts ».
- [ ] **Step 6 : Commit** `docs(s246): contrats API Dokploy et Forgejo relevés`. **Point d'arrêt : présenter les écarts à l'utilisateur avant la Partie 2.**

### Task 5 : Déployer Calendrier Familial sur Dokploy (preuve manuelle de la chaîne)

**Files:**
- Create: `docs/s246/preuve-calendrier-familial.md`

- [ ] **Step 1 :** Pousser le dépôt `calendrier-familial` dans Forgejo (miroir ; GitHub reste la référence publique). Lire son `README`/`Dockerfile` pour les variables d'environnement requises ; les poser côté Dokploy, pas dans Forgejo.
- [ ] **Step 2 :** Créer l'application dans Dokploy, déployer, vérifier `GET /sante` (ou l'équivalent) et noter l'URL (mesh seulement).
- [ ] **Step 3 :** Provoquer un second déploiement (changement trivial), puis revenir à la version précédente **manuellement** pour confirmer que le mécanisme existe. Ne pas toucher à des données réelles : base de test.
- [ ] **Step 4 :** Consigner dans `preuve-calendrier-familial.md` : versions, temps, RAM, et ce que Dokploy fait réellement d'une migration lors d'un rollback.
- [ ] **Step 5 :** Commit `docs(s246): preuve manuelle de la chaîne dépôt→déploiement`.

---

# PARTIE 2 — Brique `livraison` (squelette ; plan détaillé à écrire après la Task 4)

Chaque tâche suivra le format TDD du plan S245b (test d'abord, faux serveur local, commit par tâche). Interfaces déjà décidées (spec S246) :

| Tâche | Contenu | Dépend de |
|---|---|---|
| 6 | Squelette de brique : `briques/livraison/` (`manifest.json` avec port vérifié libre, `Dockerfile`, `docker-compose.yml` sans `VAR=${VAR:-}`, `/sante`), conforme à `GUIDE-ajouter-une-brique.md` et au filet `tests/test_briques_smoke.py` | rien |
| 7 | Client Dokploy + **faux serveur** reproduisant `contrat-dokploy.md` ; erreurs réseau/401/404/timeout traduites en messages honnêtes | Task 4 |
| 8 | Client Forgejo + faux serveur (`contrat-forgejo.md`) | Task 4 |
| 9 | Capacités de **lecture** : `livraison_apps`, `livraison_etat`, `livraison_logs` (logs filtrés : jetons, e-mails masqués avant lecture par le LLM) | 7 |
| 10 | Capacités **réversibles** : `livraison_redemarrer`, `livraison_rollback`, `livraison_deployer`, avec `"sensibilite": "reversible"` dans le manifeste ; test que l'appel direct est refusé sans approbation (garde S245) et s'exécute après approbation (reprise S245b) | 7, 9 |
| 11 | Contrat manifeste↔route (filet S210) + mise à jour de `Lancer Workplace.command` / registre des ports | 6-10 |
| 12 | Preuve LIVE groupée (SLIVE) : déploiement, redémarrage, rollback de l'app témoin, chacune validée sur Telegram ; **activation des clés d'approbation à ce moment seulement** (procédure dans `docs/sprints/S246-…` et l'ADR S245b) | 11 |

**Rappel de portée :** la capacité `livraison_*` doit tourner dans le contexte du demandeur (utilisateur) ; aucune ne manipule un jeton Forge utilisateur (voir prérequis dans le fichier S246).

## Auto-revue (spec ↔ plan)

- **Étape 0 du fichier S246** (RAM, VM 100) : faite avant ce plan (mesure + option A) ; Task 1 la revérifie avant tout démarrage.
- **Forgejo + Dokploy** : Tasks 3 et 5. **Zéro accès au socket Docker de Workplace** : contrainte globale, vérifiée par le fait que seule l'API HTTP est appelée (Task 7).
- **Spike d'API avant le code** : Task 4, point d'arrêt explicite avant la Partie 2.
- **Sécurité (clés en env, mesh seulement, logs filtrés)** : contraintes globales + Tasks 2, 4, 9.
- **Tests contre un faux serveur, pas la prod** : Tasks 7-8. **Preuve LIVE groupée en SLIVE** : Task 12.
- **Hors périmètre** (sauvegarde/reset, collecte d'erreurs, mobile, migration Vercel) : non traités.
