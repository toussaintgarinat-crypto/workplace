# S237 — reconstruction isolée de Workplace avec Ansible

Reconstruit Workplace sur une VM Debian 13 vierge, à une révision Git explicite, à partir d'une génération S236 chiffrée, sans jamais toucher la production. La VM de production, son identité (`/etc/machine-id`), son adresse LAN et son mesh sont refusés par les gardes avant toute élévation. Résultats mesurés : [docs/sprints/S237-ansible-resultats.md](../../docs/sprints/S237-ansible-resultats.md).

## Contrôleur

```sh
python3.11 -m venv ~/.s237-private/controller
~/.s237-private/controller/bin/pip install -r infra/ansible/requirements.txt
cd infra/ansible
export ANSIBLE_LOCAL_TEMP=/private/tmp/s237-ansible-local ANSIBLE_HOME=/private/tmp/s237-ansible-home
python3 -m pytest -q tests        # gardes, topologie, restauration, sauvegarde
```

Placer le venv et toutes les entrées privées hors de `/private/tmp`, effacé au redémarrage du Mac. Les répertoires privés sont en 0700, les fichiers en 0600, hors Git.

## Entrées

- `profiles/hp.yml` (versionné, **sans secret**) : catalogue ordonné des 44 projets de l'exercice, exclusions justifiées, mappings de binds, volumes implicites rendus explicites, retraits déclarés (socket Docker, clé USB, IP fixes, `extra_hosts`, dépendances vers des tâches ponctuelles), neutralisations, sondes, supervision et séquestre d'images. Chaque adaptation porte sa raison.
- Inventaire privé : un seul hôte du groupe `rehearsal`, avec `s237_expected_machine_id` relevé côté hyperviseur (`exercise/create_vm.sh` le lit dans le `smbios1` de Proxmox).
- `host.yml` privé : `s237_apt_packages`, versions exactes (`paquet=version`) relevées sur la cible. Docker est verrouillé sur les versions de la production.
- `app.yml` privé : `s237_revision` (SHA complet), `s237_git_url` (dépôt nu sur la cible), `s237_probe_image` (Python épinglé par digest), `s237_inputs` (entrées extraites de la génération), `s237_escrow_dir`, `s237_migration_compatible`.
- `recovery.yml` privé : profil Duplicati, version, fichier de phrase AES (conservé hors HP), image Duplicati épinglée.

## Phases

```sh
exercise/create_vm.sh 106 ~/.s237-private              # VM vierge (image cloud Debian vérifiée SHA512)
ansible-playbook … playbooks/provision.yml              # Debian/Docker épinglés, daemon.json, répertoires
exercise/stage_backup.sh <inventaire> <profil> <id>     # copie du chiffré depuis la destination indépendante
ansible-playbook … playbooks/recover.yml                # Duplicati avec base neuve, vérification, entrées privées
exercise/stage_code.sh <inventaire> <bundle> <sha>      # code : bundle → dépôt nu
ansible-playbook … playbooks/prepare.yml                # release, artefacts, séquestre, fichiers, images de base, builds
ansible-playbook … playbooks/restore.yml                # volumes, PostgreSQL, Qdrant, neutralisations
ansible-playbook … playbooks/isolate.yml                # nftables + refus réels depuis l'hôte et chaque réseau
ansible-playbook … playbooks/deploy.yml                 # activation projet par projet + vérification + supervision
ansible-playbook … playbooks/probes.yml                 # parcours métier authentifiés (crée des utilisateurs d'exercice)
ansible-playbook … playbooks/backup.yml                 # job S236 de l'exercice, timer désactivé
```

`provision` et `recover` n'exigent aucun secret applicatif : ils précèdent la récupération de la génération. Les autres playbooks exigent toutes les entrées et la couverture complète du catalogue observé.

## Topologie de l'exercice

Les réseaux de l'exercice sont tous `--internal`. **Docker 29 ne publie aucun port pour un conteneur qui n'est attaché qu'à des réseaux internes** (vérifié : `docker port` vide, `127.0.0.1` injoignable, IP du bridge joignable). Il n'y a donc aucun port publié. Les sondes visent l'IP du service sur son bridge, ce que nftables autorise.

En production, les briques s'appellent par `host.docker.internal:PORT` ou `192.168.1.89:PORT`. Dans l'exercice, chaque service rejoint aussi le réseau partagé `s237-workplace` sous l'alias `s237-<projet>-<service>`. Sur ce réseau, le projet `relais` (premier du catalogue) porte l'alias `host.docker.internal`. Il n'écoute que les ports publiés par les projets du catalogue, et les relaie vers le bon service (`data/relais/routes/routes.json`, généré par `prepare`). Les valeurs d'environnement contenant `192.168.1.89` sont réécrites vers `host.docker.internal`. Toute autre référence à `host-gateway`, au LAN de production ou au mesh reste refusée. Les configurations montées et les bases restaurées (moniteurs Kuma, cibles Prometheus) fonctionnent ainsi sans réécriture.

## Données

`restore_data.py files` copie avant les builds les binds de données (`repo/<chemin>`, `workspace`) depuis l'arbre du dépôt de la génération. `restore_data.py engines` restaure ensuite, dans les volumes nommés exacts des modèles préparés et avec les images de l'exercice :

- les arbres de volumes ;
- les dumps PostgreSQL, avec rôles, extensions et comptages de lignes comparés ;
- les snapshots Qdrant, avec alias et recherche ;
- les neutralisations déclarées, par exemple la désactivation de la notification Telegram restaurée dans Kuma.

Chaque conteneur de production est rattaché à son projet d'exercice par ses labels Compose (répertoire de travail + service). Une cible déjà remplie hors journal est refusée. etcd n'est **pas** restauré : il ne contient que l'état DCS de Patroni, lié à l'identifiant système de l'ancien cluster. Patroni adopte le répertoire restauré par dump logique.

## Acquisition, mise à jour et rollback

`prepare` télécharge pendant la fenêtre d'acquisition (avant `isolate`) :

- les images manquantes ;
- les images de base des `FROM`, comme images taguées, pour qu'une mise à jour ultérieure se construise hors ligne.

Les images que les registres ne publient plus peuvent être chargées depuis le séquestre privé (`s237_image_escrow`), avec contrôle de leur ID. Le profil HP n'en déclare plus aucune depuis S237b : MinIO, dont l'image n'était plus publiée, a été remplacé par SeaweedFS.

Chaque image préparée garde un tag `s237-retained/…` : le magasin d'images containerd supprime les images non taguées, ce qui rendrait un rollback impossible sans reconstruction.

- **Mise à jour** : `prepare.yml` puis `deploy.yml` avec un autre `s237_revision` et `s237_projects: [projet]`.
- **Rollback** : `rollback.yml` avec le SHA précédent et les mêmes projets.

Un échec d'activation laisse la release active intacte. Pour récupérer, demander `rollback.yml` avec le SHA encore actif. Un échec de *première* activation peut simplement être relancé. Aucun rollback ne défait une migration de données : `s237_migration_compatible: true` est une déclaration opérationnelle obligatoire.

## Limites connues

- node-exporter est exclu (`pid: host` et montage de `/`) : les métriques hôte de la VM ne sont pas couvertes, et la cible Prometheus `hote` est exclue explicitement.
- Le socket Docker du Cœur et de l'atelier est retiré : le pilotage des briques par le Cœur n'est pas éprouvé.
- Mesh HTTPS (Caddy en réseau hôte) exclu.
- La destination de sauvegarde de l'exercice est un répertoire local, et non un système de fichiers indépendant. Le job est prêt et son `preflight` S236 est accepté, mais un export réel serait refusé par la validation de destination tant qu'aucun support indépendant n'est monté.
- Le contrôle d'isolation depuis chaque réseau est lent (environ 6 min pour 46 réseaux).
- `business_probes.py` modifie le client Keycloak de l'exercice (grants directs) et crée des utilisateurs : ne pas l'exécuter pendant un contrôle d'idempotence.
