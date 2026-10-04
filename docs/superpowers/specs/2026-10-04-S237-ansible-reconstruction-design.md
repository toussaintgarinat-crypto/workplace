# S237 — Provisionnement Ansible et reconstruction isolée

Date : 2026-10-04. Statut : conception validée par l'utilisateur le 4 octobre ; implémentation en cours. Reconstruction sur VM vierge non exécutée.

## Objectif et état constaté

Transformer les procédures de `MIGRATION-HP.md`, S235 et S236 en installation répétable. Séparer préparation Debian/Docker, déploiement d'une révision explicite, restauration et vérification. Ne modifier ni la VM de production 103, ni ses conteneurs, volumes, réseaux, secrets, sauvegardes ou planifications.

Inspection SSH en lecture seule du 4 octobre : Debian 13.5, environ 24 Go de RAM, 204 Go libres ; 71 conteneurs actifs affichés healthy ; `/health` du Cœur répond 200. Aucun exécutable `qm` ou `virsh` trouvé sur cette VM. Ansible absent du PATH du contrôleur Mac. Le dépôt contient les outils de restauration S236, mais aucun déploiement Ansible. Ces constats ne prouvent pas la disponibilité d'une VM de test.

## Choix de la cible

Approche retenue : VM Debian distincte, avec disque et daemon Docker propres, accessible par SSH, sans accès aux données de production. Elle peut résider sur un hyperviseur de test ou Proxmox si les ressources libres sont vérifiées et plafonnées sans modifier la VM 103. L'identité de la cible, son IP, sa version Debian, ses ressources et son accès sudo doivent être établis avant toute mutation distante. Aucun inventaire exécutable ne doit utiliser une adresse fictive comme cible implicite.

Alternative : VM locale sur le Mac ; meilleure indépendance physique mais compatibilité ARM/x86 et capacité disque à vérifier. Alternative écartée pour l'acceptation : conteneurs supplémentaires sur le Docker de production ; ils ne prouvent ni installation Docker ni indépendance des images et volumes.

L'exercice doit pouvoir télécharger les paquets, le code et les images. Une fois ces artefacts présents, bloquer les sorties applicatives vers la production et Internet avant de démarrer les services restaurés. La politique couvre les flux Docker transférés, IPv4/IPv6 et le réseau hôte ; une simple règle INPUT ou UFW ne suffit pas. Vérifier réellement le refus des connexions vers production et intégrations externes. Autoriser uniquement SSH d'administration et les sondes internes nécessaires. Aucune notification, tunnel, inscription mesh, réplication ou connecteur externe actif dans l'exercice.

## Organisation Ansible

Créer `infra/ansible/` : configuration, dépendances épinglées, inventaire d'exemple non exécutable, variables non secrètes, playbooks séparés et rôles `guard`, `host`, `release`, `networks`, `compose`, `observability`, `backup`, `verify`. Les versions exactes d'Ansible et des collections seront sélectionnées après vérification de leur compatibilité Debian 13 et Docker, puis verrouillées avant exécution.

`provision.yml` installe les prérequis Debian, Python, Git, Docker Engine et Compose v2, démarre Docker et prépare les répertoires. Les versions de paquets retenues sont consignées ; une version indisponible échoue explicitement. Aucun formatage, repartitionnement, remplacement de SSH ou configuration du réseau de production.

`deploy.yml` reçoit un SHA Git complet obligatoire et un catalogue ordonné de projets Compose. Il prépare une release distincte, vérifie le SHA obtenu, pose les configurations privées et overrides Linux, crée les réseaux, valide les Compose et construit séquentiellement. Données persistantes hors des releases. Les noms de projet, volumes et montages doivent rester stables entre deux releases ; inventorier les chemins relatifs et `container_name` avant activation. Le second passage sur le même SHA, configurations et catalogue ne reconstruit ni ne recrée les conteneurs.

Le catalogue explicite les fichiers Compose/overrides, services, dépendances, ports, sondes et artefacts privés de chaque projet attendu. Le comparer à l'inventaire S236 et à la réalité observée : aucune omission silencieuse. Ordre topologique : moteurs et identités nécessaires, gateway, briques dépendantes, Cœur, supervision ; pas de builds parallèles. Les détails Forge, Mémoire, Oria, PeerTube et Keycloak sont issus des Compose effectifs, pas seulement du runbook historique minimal.

Garde préalable avant toute élévation : groupe d'exercice explicite, identité attendue de la VM, adresse résolue différente de la production LAN/mesh, chemin cible dédié, absence de montages de production et capacité disque suffisante. Une variable booléenne seule ne constitue pas une preuve d'isolation. Toute divergence arrête le playbook. Nettoyage limité aux ressources identifiées de l'exercice ; aucun prune global.

## Secrets, supervision et sauvegardes

Variables publiques versionnées ; secrets fournis par Ansible Vault ou fichiers privés hors Git. Fichiers et rapports sensibles 0600, répertoires 0700, `no_log` et désactivation des diffs pour les tâches sensibles. Aucun secret en argument de commande ou sortie Compose. Déployer un profil d'exercice qui conserve les secrets de chiffrement nécessaires aux données, neutralise les identifiants des connecteurs et remplace les endpoints de production. Tester la politique réseau indépendamment de cette neutralisation.

Inclure Prometheus, Grafana, Kuma et node-exporter S235 ; sonder leurs API et vérifier les cibles Prometheus. Ne pas activer les notifications restaurées. Les métriques hôte représentent uniquement la VM de test.

Préparer outils S236, Duplicati, unités systemd et paramètres privés ; timer désactivé par défaut. Ne pas rattacher ni remonter la clé USB utilisée par la production. Consommer une génération complète existante ou sa récupération chiffrée, en lecture seule, puis travailler sur une copie privée sur la cible. Ne pas déclencher un nouvel export, qui suspendrait les producteurs de production. Absence de sauvegarde indépendante vérifiable : échec de la preuve de reprise complète.

## Reconstruction et mesure

Ne pas lancer simplement le rehearsal S236 existant : il réutilise les images disponibles et démarre par phases. Adapter la restauration pour rattacher les données restaurées aux projets Compose déployés sur le Docker neuf, puis démarrer simultanément tous les services du périmètre déclaré. Vérifier dumps PostgreSQL, rôles/extensions, intégrité SQLite, fichiers, recherche et alias Qdrant, etcd et parcours authentifiés représentatifs déjà éprouvés en S236. Documenter tout service exclu ; une reprise minimale ne vaut pas clôture du stack complet.

Chronométrer avec une horloge monotone : acquisition/création de la VM, provisionnement, récupération/déchiffrement/vérification de sauvegarde, acquisition du code et images, builds, restauration, démarrage et contrôles métier. RTO visé : 8 h, repris de S236. Publier durée observée, matériel, SHA, versions, génération et taille transférée, conditions réseau et présence de caches. Si la VM est fournie déjà installée, publier le temps depuis Debian vierge séparément et signaler que le délai d'obtention de la VM reste non mesuré. Ne pas inclure le second passage ou le rollback dans le RTO initial.

## Mise à jour et retour arrière

Tester sur la même VM une modification réelle et limitée d'un service entre deux SHA explicites, puis retour au premier. Rebuild ciblé, dépendances inchangées non redémarrées, état des données préservé, sondes métier avant/après. Garder le pointeur de release précédente ; ne déclarer la nouvelle release active qu'après les sondes. Un échec reste visible avec diagnostic privé et procédure de reprise.

Le rollback applicatif remet code, configurations compatibles et images ; il n'annule pas une migration de données. Refuser toute promesse de downgrade automatique : une migration incompatible exige une restauration cohérente et une stratégie de compatibilité explicites. Le test utilise une évolution sans migration irréversible et vérifie les données après retour arrière.

## Acceptation et preuves

- Tests des gardes : IP production, alias résolvant vers production, mauvais groupe, révision flottante, secret manquant, dépendance inconnue, cible non vierge ou montage interdit refusés avant mutation.
- Syntaxe Ansible, validation de l'inventaire et des Compose ; versions des dépendances verrouillées et installation contrôleur reproductible.
- Premier passage sur Debian vierge sans images/volumes applicatifs ; stack du périmètre déclaré simultanément sain, contrôles de données et métier réussis.
- Deuxième passage réel : zéro changement pour provisionnement/déploiement, IDs et dates de démarrage des conteneurs inchangés ; vérifications sans effet de bord.
- Mise à jour ciblée puis rollback réellement exécutés ; sondes et données vérifiées ; services hors cible inchangés.
- Sorties applicatives bloquées et notifications absentes, sauvegarde indépendante vérifiée, état de production inspecté en lecture seule avant/après.
- Rapport `docs/sprints/S237-ansible-resultats.md` contenant résultats, durées, limites et commandes reproductibles ; backlog clôturé seulement si toutes les preuves requises existent.

## Séquence d'exécution après validation

1. Établir l'accès à une cible vierge et ses ressources ; inventorier les projets effectifs et les sources privées sans imprimer leurs valeurs.
2. Rédiger le plan détaillé, installer un contrôleur Ansible isolé et implémenter gardes et rôles avec tests de refus.
3. Prouver provisionnement et déploiement sur la cible ; corriger les écarts sans toucher à la production.
4. Reconstruire les données depuis la sauvegarde indépendante, vérifier le stack simultané et mesurer chaque phase.
5. Prouver idempotence, mise à jour et rollback ; rédiger les résultats et le guide opératoire avec les limites réellement observées.
