# S236 — Preuves et état de livraison

Date : 2026-10-03. Implémentation préparée et testée ; réception complète en attente de la cohérence Gateway et d’une destination indépendante.

Conception validée, RPO 24 h et RTO visé 8 h. Le stockage doit être indépendant du disque du HP : disque externe, clé USB, NAS ou serveur sur le LAN/hors site. Destination choisie par l’utilisateur : clé USB. Clé PHILIPS détectée sur Proxmox Yourown puis rattachée à chaud à la VM 103 sur usb1. Partition exFAT de 62 702 747 648 octets, UUID `6A01-B378`, désormais visible dans Debian. Profil privé et phrase AES préparés, avec copie privée de récupération sur le Mac hors Git. Montage et premier transfert encore en attente d’authentification administrateur confirmée. Le timer est préparé, pas activé ; aucune copie indépendante n’est encore acquittée.

## Périmètre implémenté

Inventaire de 76 conteneurs : 71 actifs au départ, cinq sidecars arrêtés conservés ainsi. Les sources couvrent 45 ensembles de fichiers, six serveurs PostgreSQL, Qdrant et etcd. Les configurations montées, le dépôt applicatif et les environnements Docker privés sont inclus. Les secrets restent dans le staging privé et ne peuvent être transportés que chiffrés.

Les exports suspendent les producteurs, utilisent les API natives des moteurs et reprennent les conteneurs par identité avec un journal durable. Une génération partielle n’est jamais publiée. La restauration impose des chemins et ressources Docker nouveaux, réseau interne et aucun port public. Le rapport distingue contrôle des données, démarrage du Cœur et reprise de toutes les briques.

## Preuves obtenues

- Tests automatisés : 64 réussis avec `python3 -m pytest -o asyncio_default_fixture_loop_scope=function outils/sauvegarde/coherent outils/sauvegarde/duplicati`.
- Geo réelle : arrêt ciblé, export cohérent d’une base SQLite en mode WAL checkpointée sur montage RO, vérification, restauration et comparaison des empreintes. Source inchangée et conteneur relancé.
- Un pilote a exporté les 45 ensembles de fichiers avant un échec PostgreSQL Oria. Les 71 conteneurs ont repris ; aucune génération partielle publiée. Cause identifiée : compte applicatif sans droits sur les rôles ; exporteur corrigé pour le compte administrateur Patroni.
- Export Oria corrigé vérifié : trois bases, 186 tables et rôles. Droits administrateur vérifiés sur les six serveurs PostgreSQL. Exports natifs Qdrant et etcd vérifiés séparément avant la prochaine suspension complète ; le nettoyage etcd passe par un helper limité à son volume, sans dépendre des utilitaires absents de son image.
- Génération complète `20261003T142222Z-rescued-0690bdb2` : 53 sources, 1 380 124 640 octets, exports en 183,9 s. Après correction du vérificateur qui rejetait son propre manifeste, la génération a été contrôlée contre son scellement original, sans recalcul des empreintes, puis publiée sous verrou. Les identités des 71 conteneurs initialement actifs étaient reprises ; journal de reprise absent. Audit séparé conservé hors génération.
- Duplicati stable 2.4.0.0 : génération complète chiffrée AES (15 archives), vérification complète et récupération avec une base Duplicati vierge. Les trois opérations retournent 0 ; toutes les empreintes et sources de la génération récupérée sont vérifiées. Ce test utilise un répertoire de laboratoire sur le HP, pas une destination indépendante.
- Depuis cette récupération AES : 45 ensembles de fichiers/SQLite restaurés et contrôlés ; PostgreSQL Mémoire, Keycloak, Oria, PeerTube et Forge restaurés avec rôles/extensions/comptages ; etcd sain ; Qdrant restauré, une collection et une recherche sur un vecteur réel validées.
- Cœur démarré sur les copies récupérées : `/health` 200 et `/dashboard` 303 vers `/auth/login`, comportement également constaté en production. La sonde ne suit pas le SSO hors du réseau isolé. Le dashboard authentifié et les parcours métier de toutes les briques ne sont pas validés.
- Gateway : la restauration stricte échoue sur `public.LiteLLM_ToolTable_tool_name_key`. Lecture séquentielle de la source : 21 groupes de noms non nuls dupliqués, malgré un index déclaré unique/valide. Image identique pour la source et la cible. Aucun changement en production. En laboratoire distinct, seuls les éléments TOC de cet index sont exclus : les deux bases, 65 tables et 6 695 lignes sont récupérées, avec extensions et comptages exacts ; les quatre autres index de cette table sont conservés. Cette récupération dégradée ne vaut pas restauration complète du schéma.
- Interface Duplicati temporaire : HTTP 200, API sans authentification refusée (401), base serveur persistante sous `/data`, port publié uniquement sur localhost. Instance de test supprimée.
- Supervision : règles Prometheus contrôlées (13 au total) et collecteur node-exporter actif. Statut S236 reçu ; aucune copie indépendante vérifiée signalée correctement.

Les preuves privées contenant données ou paramètres de récupération restent sous `/home/debian/s236-tools/` et `/home/debian/.local/share/workplace-backups/`, hors du dépôt Git.

## Acceptation restante

Résoudre l’incohérence de l’index Gateway, puis refaire sa restauration stricte. La suppression de lignes ou une modification du schéma de production ne fait pas partie des actions exécutées. La restauration normale reste stricte et n’ignore aucun index en échec.

La validation métier de toutes les briques et le RTO complet, incluant reconstruction de l’hôte et récupération distante, restent distincts de ces contrôles. Les ressources Docker des tests sont nettoyées ; les preuves et générations privées sont conservées.

Monter la partition USB identifiée sans formatage, vérifier son espace libre, puis réaliser un premier transfert et une récupération depuis cette destination avant activation du timer. La phrase de chiffrement est conservée hors HP dans un fichier privé sur le Mac ; elle doit rester accessible après perte du HP. Une clé débranchée ne garantit pas à elle seule une copie plus récente que 24 h.

Guides : [sauvegardes cohérentes](../../outils/sauvegarde/coherent/README.md), [Duplicati](../../outils/sauvegarde/duplicati/README.md), [conception](../superpowers/specs/2026-10-03-S236-sauvegardes-coherentes-design.md).
