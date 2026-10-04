# S237 — État d'exécution et preuves

Date : 2026-10-04. **En cours ; reconstruction complète non validée.** Production inspectée uniquement en lecture seule. Conception approuvée par l'utilisateur ; branche de travail `sprint/s237-ansible`.

## État réel observé

Le HP de production est la VM Debian 13.5, identité `f0490b65d4414f4fa4db80bdc3f75da6`, adresses LAN `192.168.1.89` et mesh `100.124.248.226`. Ces identités doivent être refusées par les gardes. `/health` du Cœur répond 200 ; 71 conteneurs actifs affichent healthy. Docker Engine 29.6.1 et Compose 5.2.0 sont installés sur cet hôte ; cela ne constitue pas un verrouillage des paquets d'une autre cible.

Les labels Compose de production ont permis d'enregistrer 43 projets et 71 services actifs dans `infra/ansible/catalogue.observed.json`, sans exporter les environnements. L'inventaire S236 couvre 76 conteneurs avec montages, incluant des services inactifs : les deux périmètres ne sont pas interchangeables.

Seize overrides effectifs sont absents du checkout Git : les `docker-compose.override.yml` des briques agenda, atelier-veille, audit, donnees, forge, gateway, generateur, geo, images, memoire, personnages, restaurant, studio, synopsis, transcription et video. Ils doivent être récupérés comme configurations privées et explicitement rattachés à la release. Un clone seul du SHA de production ne suffit donc pas à reproduire l'installation observée.

La VM de production dispose d'environ 24 Go de RAM et 204 Go libres ; aucun outil `qm` ou `virsh` n'y a été trouvé. Le Mac dispose de 76 Gio libres. Aucun accès à une VM Debian de test ni à l'hyperviseur permettant d'en créer une n'a encore été établi. Les ressources disponibles sur la VM de production ne constituent pas une autorisation d'y lancer le stack de test.

## Outillage et vérifications locales

Contrôleur de validation installé sous `/private/tmp/s237-controller`, Python 3.11.15, ansible-core 2.19.13 ; pas d'installation Ansible globale. Les répertoires temporaires Ansible sont placés sous `/private/tmp` pour respecter les permissions du contrôleur. La version et ses dépendances installées ont été relevées par `ansible --version` et `pip freeze`.

Un véritable lancement local de `playbooks/provision.yml` avec l'identité de production a été refusé à la première assertion, avant connexion SSH ou élévation : `ok=0 changed=0 unreachable=0 failed=1`, code retour 2 attendu. Ce test de refus ne provisionne aucun hôte.

`outils/reconstruction/measure.py` mesure des phases avec une horloge monotone, conserve les logs privés et arrête l'exécution au premier échec. Huit tests locaux passent : succès mesuré sans déclaration de reprise, arrêt avant phase suivante, timeout, commande absente, plans invalides sans mutation, cible existante et parents symlink refusés, arrêt des descendants sur échec/timeout, types de métadonnées validés. Le test initial échouait sur l'import du module absent avant implémentation. Une relecture indépendante a identifié le descendant survivant à un retour non nul ; régression reproduite puis corrigée et relue. Ce sont des tests de l'outil de mesure, pas une mesure du RTO de Workplace.

Les suites unittest existantes S236 restent vertes : 12 tests sous `outils/sauvegarde/coherent` et 27 sous `outils/sauvegarde/duplicati`. La suite pytest complète de ces deux répertoires a également été exécutée : 85 tests réussis. Ces tests ne remplacent pas une reconstruction.

## Socle Ansible implémenté et relu

`infra/ansible/` fournit six playbooks : provisionnement, préparation Git/configurations/builds, isolation, déploiement, vérification et rollback. Les rôles séparent gardes, prérequis, releases, réseaux, projets Compose, supervision et préparation S236. Le contrôleur et ses dépendances sont épinglés ; les versions des paquets Debian/Docker restent obligatoires dans le verrou privé à établir pour la cible. La clé publique officielle Docker a été téléchargée en HTTPS et contrôlée avec SHA256 et empreinte GPG, consignées dans `docker-key.lock.json`.

Les configurations résolues, images et manifestes sont privés et rattachés à chaque projet. La préparation refuse les overrides modifiés pour un SHA déjà installé ; les données et volumes gardent des noms stables. Le runtime réel est comparé aux images, réseaux, publications de ports, montages et privilèges attendus. Les références vers l'hôte de production et `host.docker.internal` non remplacées sont refusées. La table nft ne doit autoriser que loopback, réponses SSH et bridges internes inspectés de l'exercice ; cette politique doit encore être éprouvée sur une VM.

La mise à jour journalise sa tentative avant activation et ne publie qu'après sondes. Une activation échouée peut revenir au manifeste encore actif ; le rollback d'une activation réussie utilise le précédent. Aucun rollback automatique des données. La préparation S236 installe les véritables outils cohérents/Duplicati et un service de sauvegarde limité aux chemins et producteurs de l'exercice ; le timer reste arrêté et désactivé. Elle ne constitue pas un adaptateur de restauration.

Une relecture indépendante a fait corriger : sondes bloquées par OUTPUT, réseaux/montages/ports supplémentaires non détectés, rollback après activation échouée, artefacts SHA écrasables, dérive réparée avant contrôle, téléchargement inutile d'une sonde déjà présente et disparition complète des conteneurs actifs. Les corrections ont été reproduites par tests puis relues. Verdict final : aucun défaut important supplémentaire identifié dans le socle examiné ; conservation comme implémentation partielle, pas validation du sprint.

Vérification finale locale : **114 tests pytest réussis** (21 gardes/état Ansible, 8 mesure, 85 S236). Les six playbooks passent `--syntax-check` avec Ansible 2.19.13 et imports statiques des rôles. L'inventaire d'exemple est volontairement vide : le contrôle syntaxique n'a exécuté aucun déploiement distant.

Dernière inspection SSH en lecture seule : toujours 71 conteneurs actifs, 71 statuts healthy et `/health` du Cœur HTTP 200. Aucune commande de déploiement, arrêt, export ou restauration n'a été exécutée sur la production. Cette comparaison de disponibilité n'est pas un relevé exhaustif avant/après des identifiants de toutes les ressources.

## Acceptation encore à prouver

- Adaptateur de restauration native vers les montages Compose, routage privé interprojets, métriques hôte S235 compatibles avec l'isolation et acquisition des images pour une mise à jour après fermeture des sorties : intégrations encore à compléter.
- Provisionnement d'une VM Debian vierge sans images applicatives préexistantes.
- Récupération d'une génération depuis une destination indépendante sans export suspendant la production.
- Raccordement des données restaurées aux projets Compose stables et démarrage simultané du périmètre déclaré.
- Refus effectif des flux vers production et intégrations externes depuis l'hôte et les conteneurs.
- Santé, intégrité des données et parcours métier authentifiés.
- Second passage sans changement réel de provisionnement/déploiement.
- Mise à jour ciblée et rollback avec conservation des données et des autres services.

**Temps de reprise : non mesuré.** Objectif conservé : 8 h. Aucun résultat synthétique ou temps de test local ne sera présenté comme RTO complet. S237 reste ouvert jusqu'aux preuves ci-dessus.
