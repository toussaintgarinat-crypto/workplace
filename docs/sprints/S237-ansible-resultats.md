# S237 — Résultats de la reconstruction isolée

Date : 2026-10-04. Branche `s237/release-prod`. Elle part du commit `4ce4141` (code déployé sur le HP), auquel sont ajoutés les commits S235/S236/S237 cherry-pickés, puis l'outillage. Elle est identique à la production pour tout le code applicatif : 0 ligne de différence hors `infra/` et `docs/`, et le seul code applicatif modifié pendant l'exercice (`calcul`, pour la mise à jour test) a été annulé. Production inspectée en lecture seule uniquement. Guide opératoire : [infra/ansible/README.md](../../infra/ansible/README.md).

## Passage chronométré sur VM vierge

Cible : VM Proxmox 106, créée depuis l'image cloud officielle Debian 13, dont la somme SHA512 est vérifiée. Configuration : 4 vCPU (`x86-64-v2-AES`, comme la production), 12 Go et 200 Go. Docker est absent au départ. Mesure par `outils/reconstruction/measure.py`, horloge monotone, révision `a215057`, génération `20261004T115244Z-148a3bc4` récupérée depuis la clé USB chiffrée.

| Phase | Durée |
|---|---|
| Création de la VM jusqu'au SSH | 21 s |
| Provisionnement Debian/Docker épinglés (`provision.yml`) | 77 s |
| Copie du chiffré Duplicati depuis l'USB (354 Mo) | 10 s |
| Déchiffrement avec base Duplicati neuve, vérification des 53 sources, extraction des entrées privées | 104 s |
| Code (bundle → dépôt nu) | 1 s |
| Release, artefacts privés, séquestre, fichiers, images de base, **builds sans cache des 44 projets** | 1 357 s |
| Restauration : 42 arbres de volumes, 6 serveurs PostgreSQL, Qdrant, neutralisation Kuma | 101 s |
| Isolation nftables et refus réels depuis l'hôte et chaque réseau | 403 s |
| Activation des 44 projets, santé, sondes, vérification globale, supervision | 1 246 s |
| Sondes métier authentifiées | 20 s |
| **Total** | **3 340 s (55 min 40 s)** |

**RTO observé : 55 min 40 s pour un objectif de 8 h.**

Ce chiffre a été obtenu dans les conditions suivantes :
- hyperviseur déjà disponible, avec l'image cloud déjà téléchargée sur Proxmox ;
- liaison Internet du LAN pour les images et les paquets ;
- clé USB lue via la VM de production (lecture seule) plutôt que branchée sur l'hôte neuf ;
- contrôleur Ansible déjà installé.

L'obtention d'un nouveau matériel n'est pas mesurée. Les builds représentent 41 % du temps et l'isolation 12 %.

## Résultat sur la cible

- 44 projets et **70 conteneurs actifs simultanément, tous sains**. Ce sont les 71 conteneurs actifs de la production, moins node-exporter et Caddy (exclus), plus le relais de l'exercice.
- Environnements reconstruits depuis la sauvegarde **identiques** à ceux de la production pour les 71 services. Les seuls écarts sont les neutralisations déclarées : jeton Telegram, NetBird, repli payant. La comparaison porte sur les noms de clés et les empreintes ; aucune valeur n'a été affichée.
- PostgreSQL : rôles, extensions et comptages de lignes identiques à la génération, pour les 6 serveurs.
- Qdrant : collections, alias, points et recherche vectorielle identiques.
- 7 sondes métier réussies :
  - sessions Keycloak réelles (Cœur et Oria) ;
  - dashboard du Cœur authentifié (200), et 303 sans session ;
  - CRUD complet dans Données ;
  - Oria authentifié ;
  - lecture Mémoire ;
  - Gateway : 57 modèles restaurés, appel via un fournisseur factice local, 0 appel payant ;
  - recherche Forge.
- Supervision : Prometheus voit ses cibles `coeur` et `prometheus` en état up. La cible `hote` (node-exporter) est exclue et déclarée.
- Notifications : l'unique canal actif restauré (Telegram dans Kuma) est désactivé sur la copie, et la vérification compte 0 notification active. Grafana n'a ni règle ni point de contact configuré, et Prometheus n'a pas d'Alertmanager.
- Isolation : sorties vers Internet, la production et le mesh refusées depuis l'hôte (nftables) et depuis chaque réseau d'exercice ; aucun port publié.
- Préparation de sauvegarde : inventaire S236 généré depuis les 70 conteneurs réels, accepté par le `preflight` S236 réel (aucune dérive) ; phrase de chiffrement propre à l'exercice ; timer `disabled` / `inactive`.

## Second passage, mise à jour et rollback

- **Second passage** (VM 105, puis rejoué sur la VM 106 avec l'outillage final) : zéro changement pour la récupération, la restauration des fichiers, la préparation, la restauration des moteurs et le déploiement. Les 70 conteneurs ont des ID, des dates de démarrage et des images inchangés.
- **Mise à jour ciblée par Ansible** (`calcul`, 0.2.0 → 0.2.1, sans migration), puis **rollback** vers le SHA précédent en 35 s, sans aucune reconstruction. L'empreinte du volume de données de `calcul` reste identique à chaque étape, et tous les autres conteneurs sont inchangés.
- La récupération d'une activation échouée par rollback vers le SHA encore actif a été éprouvée : journal effacé, release active intacte.

## Constats de reproductibilité

1. **Docker 29 ne publie aucun port pour un conteneur attaché seulement à des réseaux `--internal`.** Les sondes initiales sur `127.0.0.1` ne pouvaient donc pas réussir. Désormais, aucun port n'est publié : les sondes visent l'IP du bridge, et un relais interne aliasé `host.docker.internal` porte les appels inter-projets d'origine.
2. **`minio/minio:RELEASE.2025-09-07T16-13-09Z` (Oria) n'est plus téléchargeable**, ni sur Docker Hub ni sur Quay. L'exercice utilise un séquestre (`docker save` depuis le cache de la production, ID `14cea49…` vérifié). **À faire :** que S236 sauvegarde ces images, ou remplacer MinIO par une source maintenue. Sans cela, un hôte neuf ne peut plus démarrer Oria si la production est perdue.
3. **`/etc/docker/daemon.json` de la production** (pools d'adresses, `userland-proxy: false`) n'était ni provisionné ni sauvegardé. Avec les pools par défaut, la création des réseaux échoue au 30ᵉ. Il est maintenant provisionné, sans le pool `192.168.0.0/16`, qui jouxte le LAN.
4. **Avec le magasin containerd, les images non taguées sont supprimées.** Le premier rollback réel a échoué sans dommage. Chaque image préparée garde désormais un tag de rétention.
5. **BuildKit résout les images de base sur le registre même sans `--pull`.** Une mise à jour après isolation échouait. Les images de base des `FROM` sont maintenant acquises comme images taguées pendant la fenêtre d'acquisition. Sur la VM 105, celle de `calcul` a été chargée depuis la production pour le test : l'étape n'existait pas encore.
6. Le projet Compose `oria` de la production mélange deux répertoires (`oria-stack/oria` et `briques/oria`). Il est scindé en `oria` et `oria-adaptateur`.
7. L'override Keycloak fige `postgres` sur l'IP `172.27.0.3` (avec `extra_hosts`). Les deux sont retirés de façon déclarée ; le DNS du réseau suffit.
8. etcd ne contient que l'état DCS de Patroni (`/service/oria-pg/*`), lié à l'ancien identifiant système. Il n'est pas restauré, et Patroni adopte le cluster restauré par dump. Une configuration dynamique modifiée à chaud serait perdue.
9. Le provisionnement exigeait les secrets applicatifs, inaccessibles avant la récupération. La garde d'identité est désormais séparée des entrées applicatives. `cache_valid_time` masquait aussi le dépôt Docker ajouté : le cache est maintenant forcé à changement.

## Limites restantes

- node-exporter est exclu : les métriques hôte de la cible ne sont pas couvertes.
- Les sockets Docker du Cœur et de l'atelier sont retirés : le pilotage de conteneurs depuis le Cœur n'est pas éprouvé.
- Le mesh HTTPS est exclu.
- La destination de sauvegarde de l'exercice n'est pas un système de fichiers indépendant : un export réel serait refusé tant qu'aucun support n'est monté. La préparation est prouvée ; la sauvegarde depuis l'hôte reconstruit ne l'est pas.
- Le refus des adresses dans la configuration ne vise textuellement que l'IP de la production et celle du mesh. Les autres adresses du LAN ne sont bloquées que par l'isolation réseau.
- La VM de test était sur-allouée (12 Go sur un hôte qui n'en avait que 5 de libres), avec une boucle de vidage de cache. La production est restée saine pendant tout l'exercice (71 healthy, Cœur 200), mais cela ne remplace pas un hôte dimensionné.
- Pas de relecture indépendante par un autre agent dans cette session : relecture par l'auteur seulement.

## Production

Comparaison avant/après en lecture seule, couvrant l'exercice VM 105 : identifiants, états, dates de démarrage et images des conteneurs identiques ; volumes et 46 réseaux identiques. Les seules opérations sur la production ont été des lectures : `docker compose config`, `docker inspect`, `docker save` (MinIO et `python:3.12-slim`), et la lecture du chiffré sur la clé USB.

## Vérifications locales

**135 tests passent** : 42 dans `infra/ansible/tests` (gardes, topologie, relais, sondes, restauration, récupération, inventaire de sauvegarde), 8 pour l'outil de mesure et 85 pour S236 (68 cohérents, 17 Duplicati).
