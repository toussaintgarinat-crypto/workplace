# S236 — Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development task-by-task; tests before code, then task review and final review.

**Goal:** Exporter les données de Workplace de manière cohérente et prouver la restauration sur une cible isolée.

**Architecture:** Un orchestrateur hôte Docker fige les producteurs, exporte PostgreSQL/Qdrant/etcd via leurs outils natifs, et sauvegarde volumes/fichiers avec SQLite Backup API. Duplicati reçoit seulement les générations complètes et vérifiées ; support USB/disque externe et NAS/serveur local ou distant.

**Tech Stack:** Python standard library, Docker CLI, PostgreSQL pg_dump, Qdrant HTTP, Duplicati stable épinglé.

## Global Constraints

- RPO accepté : 24 h ; RTO accepté : 8 h. Mesurer avant de promettre ces délais.
- Aucune restauration sur la production ; réseaux et volumes isolés sans proxy_net ni ports publics.
- Sources obligatoires explicites, dérive détectée, pas de succès silencieux pour un conteneur absent.
- Aucun secret dans les sorties ; staging privé et chiffrement Duplicati obligatoire.
- Suspendre les producteurs pendant l’export ; relancer exactement ceux qui étaient actifs, même après échec.
- Support externe : montage réel et identité du support vérifiés ; refus si absent.
- Destination choisie et vérifiée : clé USB PHILIPS, UUID 6A01-B378. Premier transfert et récupération validés ; timer non activé.

## Task 1 — Artifacts cohérents et restauration de fichiers

Files: `outils/sauvegarde/coherent/artifacts.py`, `outils/sauvegarde/coherent/test_artifacts.py`.

- [x] Tests réels : SQLite en WAL avec connexion ouverte, archive complète de fichiers et métadonnées, DB nommée .db non SQLite conservée comme fichier, contenu altéré, traversée de chemins et symlink dangereux refusés.
- [x] Exécuter `python3 -m pytest outils/sauvegarde/coherent/test_artifacts.py` : constater échec avant implémentation.
- [x] Implémenter export_tree(source, target) avec SQLite Backup API et integrity_check ; détection magic SQLite indépendante des extensions ; exclusions WAL/SHM uniquement pour bases détectées. Conserver fichiers et liens sûrs, inventaire SHA-256 et métadonnées.
- [x] Implémenter verify_tree et restore_tree : aucun remplacement de cible existante, manifeste validé avant extraction, chemin relatif strict, permissions conservées.
- [x] Vérifier tests, relire et produire rapport.

## Task 2 — Orchestrateur hôte, inventaire, supervision

Files: `outils/sauvegarde/coherent/backup.py`, `outils/sauvegarde/coherent/test_backup.py`, `outils/sauvegarde/coherent/inventory-hp.json`.

- [x] Tests d’échec source obligatoire, verrou concurrent, reprise après erreur d’export, aucune publication partielle, changement inventaire, métriques échec.
- [x] Inventorier conteneurs/images/montages sans valeurs d’environnement ; dédupliquer sources physiques. Vérifier toutes les sources attendues et nouvelles sources non classées.
- [x] Exporter avec un helper Python déjà disponible sur HP et montages RO. PostgreSQL : toutes bases hors templates, format custom, rôles protégés, extensions et contrôles tables ; Qdrant collections/snapshots/alias ; etcd snapshot natif ; autres volumes statiques pendant arrêt des producteurs.
- [x] Exclure de l’arrêt PostgreSQL, Qdrant, etcd et observabilité métriques ; arrêter Kuma en premier pour prévenir les fausses alertes et redémarrer en dernier.
- [x] Persister journal de reprise avant chaque arrêt ; timeouts, espace disque, verrou, manifest/checksums et publication atomique ; ne jamais purger le dernier succès non transféré.
- [x] Fournir inventaire JSON et commandes preflight, backup, verify, recover et status ; métriques Prometheus sans valeur sensible.

## Task 3 — Restauration des moteurs et transport Duplicati

Files: `outils/sauvegarde/coherent/restore.py`, `outils/sauvegarde/coherent/test_restore.py`, `outils/sauvegarde/duplicati/`, `outils/sauvegarde/coherent/README.md`.

- [x] Tester validation des cibles isolées, génération corrompue refusée, destination non montée refusée.
- [ ] Valider une restauration stricte de tous les moteurs. Les arbres sont restaurés vers de nouveaux répertoires privés ; cinq serveurs PostgreSQL, Qdrant et etcd sont validés. Gateway bloque sur un index unique incohérent dans la source ; récupération intégrale des lignes prouvée séparément en laboratoire dégradé.
- [x] Préparer Duplicati épinglé, exports RO, localhost et fichiers secrets privés ; destinations file pour USB/NAS monté, SFTP/S3/WebDAV pour serveur. Refuser endpoint vide et chiffrement absent.
- [x] Préparer timer 12 h (marge sous RPO 24 h) non activé, rétention configurable ; verrou commun export/transfert/purge, succès distant seulement après Duplicati test.
- [x] Documenter récupération sans base locale Duplicati, conservation hors HP de la phrase secrète, aide choix destination et limites physiques USB débranchée.

## Task 4 — Pilote et preuves

Files: `docs/sprints/S236-sauvegardes-resultats.md`, backlog sprint, spec actualisée.

- [x] Tester unités et revoir le diff.
- [x] Copier uniquement outils S236 sur HP sans pull/rebuild global ; lancer inventaire/préflight puis export cohérent réel.
- [ ] Clôturer la restauration stricte de toutes les bases sur réseau Docker isolé. Fichiers/configurations, cinq serveurs PostgreSQL, etcd, recherche Qdrant et démarrage du Cœur validés depuis la récupération AES ; incohérence Gateway restante.
- [x] Tester source absente et destination absente sur fixtures ; vérifier santé production après reprise.
- [x] Prouver chiffrement/restauration Duplicati avec destination fixture locale, explicitement distincte d’une sauvegarde indépendante.
- [x] Rapporter mesures, sources couvertes et limites ; pas de clôture complète sans destination indépendante ni contrôle métier de Workplace isolé.

## État de réception

64 tests passent. Les preuves réelles et les conditions restantes (restauration stricte Gateway et parcours métier complets) sont décrites dans [les résultats S236](../../sprints/S236-sauvegardes-resultats.md). Premier transfert indépendant USB et récupération vérifiés ; aucun timer activé.
