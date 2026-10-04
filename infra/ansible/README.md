# S237 — contrôleur de reconstruction isolée

État : outillage local, sans preuve d'exécution distante. Aucun inventaire réel n'est livré. La VM de production, son identité et son réseau mesh sont refusés. `catalogue.observed.json` décrit les 43 projets et 71 services actifs observés ; il ne constitue pas un profil d'exercice activable.

Installation reproductible du contrôleur Python 3.11 :

```sh
python3.11 -m venv /private/tmp/s237-controller
/private/tmp/s237-controller/bin/pip install -r infra/ansible/requirements.txt
cd infra/ansible
export ANSIBLE_LOCAL_TEMP=/private/tmp/s237-ansible-local
export ANSIBLE_HOME=/private/tmp/s237-ansible-home
python3 -m unittest discover -s tests -v
/private/tmp/s237-controller/bin/ansible-playbook --syntax-check -i inventory.example.yml playbooks/provision.yml
```

L'inventaire d'exemple est volontairement vide. L'inventaire privé doit définir un unique hôte du groupe `rehearsal`, son adresse, `s237_expected_machine_id` relevé indépendamment, `s237_revision` (40 caractères hexadécimaux), `s237_git_url`, `s237_probe_image` (image Python utilisable avec `python3`, référence `repository@sha256:...`), les entrées suivantes et les ressources suffisantes. Le groupe ne doit avoir aucune autre appartenance.

` s237_apt_packages` est une liste de `paquet=version` exacts issus des dépôts Debian 13 et Docker officiels, incluant Docker CE, CLI, containerd.io, Compose plugin, nftables, Git, Python et certificats. `s237_docker_key_sha256` verrouille le fichier ASCII de signature à `https://download.docker.com/linux/debian/gpg` vérifié indépendamment. Le provisionnement configure la source Debian trixie officielle ; aucune version de paquet n'est inventée. Une version indisponible échoue. Pour choisir les versions, consulter les métadonnées signées du dépôt correspondant à l'architecture réelle ; la découverte et le verrou de versions restent à effectuer sur la cible connue.

` s237_catalogue` reprend chaque projet retenu, dans l'ordre des dépendances, avec `directory`, `files`, `services`, `dependencies` et éventuellement `excluded_services: {service: raison}` pour les sidecars et tâches ponctuelles effectivement présents dans Compose mais inactifs. `s237_exclusions: {projet: raison}` couvre chaque projet observé écarté. `mesh-https` et les notifications externes sont interdits. Chaque service Compose doit être retenu ou exclu explicitement ; une dépendance exclue encore référencée est refusée. La réconciliation avec les 76 montages attendus S236 n'est pas encore une preuve de récupération complète.

` s237_private_artifacts` fournit les overrides Linux non versionnés : liste de `{source: /chemin/controleur/0600, destination: chemin/relatif/dans/release}`. Les overrides observés manquants ne sont pas générés arbitrairement. `s237_private_projects` fournit, par projet :

```yaml
s237_private_projects:
  projet:
    env_file: /chemin/prive/controleur/projet.env # 0600, hors Git
    bind_mappings:
      /chemin/source/compose/data: donnees/projet
      /chemin/source/compose/code:
        kind: release
        path: SHA_COMPLET/briques/projet/app
    environment:
      service: {} # revue explicite de TOUS les services ; neutraliser les connecteurs
    probes:
      - url: http://127.0.0.1:PORT/health
        status: 200
        contains: ok
```

Chaque bind est explicitement mappé : chaîne = données sous `/srv/workplace-rehearsal/data`, objet `kind: release` = code immuable dans la release, obligatoirement en lecture seule. Les sources doivent déjà exister et ne pas être des symlinks. Les montages du socket Docker, /proc, /sys, /dev, /etc et /run, privilèges, capabilities ajoutées, devices et modes réseau/pid/ipc spéciaux sont refusés. Les noms fixes de conteneurs sont supprimés, les volumes ont des noms `s237-PROJET-VOLUME`, les réseaux par défaut sont propres au projet ; les réseaux explicitement partagés restent partagés sous un nom `s237-...`. Les ports sont limités à 127.0.0.1. Les secrets résolus restent dans des JSON 0600 sous des répertoires 0700 et ne sont pas publiés dans les logs Ansible.

Exécuter les phases dans cet ordre, avec un inventaire privé et un fichier de variables privées (Ansible Vault possible) :

```sh
ansible-playbook -i /chemin/inventaire.yml playbooks/provision.yml -e @/chemin/prive.yml
ansible-playbook -i /chemin/inventaire.yml playbooks/prepare.yml -e @/chemin/prive.yml
ansible-playbook -i /chemin/inventaire.yml playbooks/isolate.yml -e @/chemin/prive.yml
ansible-playbook -i /chemin/inventaire.yml playbooks/deploy.yml -e @/chemin/prive.yml
ansible-playbook -i /chemin/inventaire.yml playbooks/verify.yml -e @/chemin/prive.yml
```

`prepare` acquiert et construit séquentiellement avant isolation puis épingle les IDs d'images. `isolate` pose uniquement une table nft dédiée, couvre IPv4/IPv6 et refuse toute dérive de ses règles ; chaque réseau Docker doit être réellement `internal`, sans IPv6. Des connexions vers production, mesh et des IP Internet sont réellement tentées depuis l'hôte et une sonde conteneur dans chaque réseau ; une connexion réussie interdit l'activation. SSH établi sur le port 22 et loopback restent autorisés. La représentation JSON nft et les flux réels restent à éprouver sur la VM. Les services ne sont pas démarrés tant que ces contrôles n'ont pas réussi.

`deploy` nécessite `s237_migration_compatible: true`, déclaration opérationnelle obligatoire sur la compatibilité des données. Il compare le digest privé et les IDs/états réels des conteneurs, puis les images, environnements et montages réels. Une dérive est refusée. Il publie l'entrée active de chaque projet uniquement après santé et sondes. Les retours d'erreur détaillés restent dans `state/diagnostics/failure.json` 0600 ; aucune valeur Compose sensible ne sort sur stdout.

Une mise à jour utilise un autre SHA et `s237_projects: [projet]`, puis prepare/isolate/deploy. L'isolation bloque l'acquisition Internet ultérieure : la réouverture contrôlée de la seule fenêtre d'acquisition côté hôte n'est **pas implémentée** ; prepare échouera si les images nécessaires ne sont pas accessibles. Ne pas supprimer globalement les règles ni démarrer un projet pendant l'acquisition. Le rollback utilise `playbooks/rollback.yml`, le SHA précédent explicite et la même liste de projets. Il charge uniquement l'état précédent des projets sélectionnés, leurs JSON privés vérifiés et IDs d'images ; il ne change pas les autres entrées actives. Il ne restaure aucune migration de données ni ancien contenu des binds de données/configuration. Le plus petit périmètre implémenté est le projet Compose, pas un service individuel d'un projet multi-services.

La supervision requiert `s237_supervision_projects`, `s237_supervision_probes` et `s237_notification_disabled_evidence`. Les API sont sondées et les cibles Prometheus retournées doivent être `up`. L'audit natif des notifications Kuma/Grafana, l'interprétation des métriques et les parcours authentifiés restent à compléter sur les données restaurées.

La sauvegarde copie les outils S236 coherent et duplicati, exige `s237_backup_generation_manifest` sous le répertoire privé de sauvegardes, installe un timer arrêté/désactivé et un service réel `duplicati/job.py` avec une condition de validation des chemins et producteurs propres à l’exercice. Il ne lance aucun export et ne monte aucune clé USB. `s237_backup_private_files` fournit `job.json`, l’inventaire et les profils privés (liste `{source, name}`) sous `private/backup/`. Le manifest doit exister mais son intégrité n’est pas affirmée. Ce rôle est une **préparation**, pas un restaurateur : validation indépendante de génération, déchiffrement, import natif PostgreSQL/Qdrant/etcd/SQLite et raccordement de leurs montages aux projets déployés restent à implémenter et éprouver. Duplicati peut être inclus au catalogue uniquement avec sa configuration privée neutralisée ; aucune récupération Duplicati n'est prétendue.

Les tests locaux et la syntaxe ne prouvent ni Debian vierge, ni deuxième passage zéro changement, ni disponibilité simultanée, ni restauration native, ni mise à jour/rollback réellement exécutés. Le RTO de 8 h, l'acquisition de VM, les volumes de transfert et l'absence de notifications doivent être mesurés séparément. Aucun prune global ni nettoyage production n'est fourni.

La topologie HTTP entre projets reste un écart ouvert : les anciens appels via `host.docker.internal:host-gateway` ne rejoignent pas les listeners limités à loopback. Aucun relais privé ou bus applicatif avec réécriture complète des URLs n’est fourni. La préparation refuse les références restantes à `host.docker.internal`, `host-gateway`, au LAN et au mesh de production. Les overrides privés doivent donc porter une topologie interne éprouvée avant activation. Node-exporter avec pid hôte et montage `/` est également refusé par la politique actuelle ; aucune preuve de supervision complète n’est affirmée tant qu’une exception limitée à la VM vérifiée n’a pas été implémentée et testée.

Corrections de sécurité après relecture : nft autorise désormais les destinations IPv4 des seuls bridges internes dédiés, avec paire interface/subnet issue de Docker inspect ; cela permet les sondes de ports publiés après DNAT sans autoriser une route externe. IPv6 reste refusé sur ces bridges et par la politique OUTPUT (hors loopback). Tout réseau ajouté, port publié ailleurs que loopback, montage supplémentaire, nom/source de volume ou option de privilège divergeant du modèle est refusé. Avant une mise à jour, les conteneurs existants sont comparés au modèle actif, même si le digest demandé change.

Chaque tentative d’activation est journalisée avant Compose. Si B échoue alors qu’A reste déclaré actif, `rollback.yml` peut demander explicitement A ; seuls les états de conteneurs correspondant aux modèles journalisés sont admis pendant la récupération. Le journal disparaît après récupération vérifiée. Les overrides d’un même SHA sont immuables : tous les contenus sont validés avant toute copie, un contenu différent à destination existante échoue. Les configurations finales résolues incorporent un digest d’images dans leur chemin et sont distinctes des brouillons de build.

La clé officielle Docker est verrouillée par défaut au SHA256 vérifié le 4 octobre 2026 ; `docker-key.lock.json` consigne son URL, empreinte GPG et provenance. Une rotation légitime exige une nouvelle vérification et un nouveau verrou explicite.

Les `VOLUME` implicites déclarés dans les images doivent être inventoriés et couverts par des montages explicites dans le profil Compose. La politique refuse les volumes anonymes supplémentaires découverts dans Docker inspect ; elle ne les autorise pas silencieusement. Une entrée active sans aucun conteneur est également refusée avant Compose, sauf récupération explicite d’une tentative journalisée. Une seconde préparation avec sonde et images déjà présentes utilise uniquement Docker inspect et n’effectue aucun pull ; l’acquisition initiale de la sonde est comptée comme changement.
