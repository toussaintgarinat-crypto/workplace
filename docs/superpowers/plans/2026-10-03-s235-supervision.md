# S235 — Implementation Plan

**Goal:** Déployer et prouver la supervision sur le HP sans modifier les applications.
**Architecture:** Prometheus/Grafana existants, node_exporter hôte, Kuma pour les sondes et Telegram.
**Tech Stack:** Docker Compose, Python standard library, Kuma Socket.IO.

## Contraintes

Aucun envoi externe avant accord et configuration. Secrets hors Git. Aucun arrêt applicatif. Images épinglées. Conserver les volumes.

## 1. Inventaire reproductible

- [x] Écrire `outils/observabilite/test_inventory.py` : URL des manifestes actifs, statut déprécié exclu, backend Oria indépendant, sonde du Cœur, intervalle/retries.
- [x] Lancer `python3 -m unittest discover -s outils/observabilite -p 'test_*.py'` et constater l'échec avant implémentation.
- [x] Implémenter `inventory.py` : entrée racine dépôt, sortie JSON de sondes sans secrets, sans appel réseau.
- [x] Relancer les tests ; conserver les URL des manifestes, corriger seulement les adresses loopback pour la topologie Kuma.

## 2. Stack et initialisation

- [x] Étendre `docker-compose.yml` : Kuma, node_exporter, bind LAN explicite, stockage persistant et contrôle de santé.
- [x] Étendre `prometheus.yml` et `alertes.yml` avec ressources hôte ; créer `grafana/tableaux/hote.json`.
- [x] Ajouter `.env.example` sans secrets et `kuma-bootstrap.cjs` pour configuration idempotente via Socket.IO ; authentification requise, pas d'écriture SQL directe.
- [x] Ajouter `README.md` : accès, déploiement, secrets, Telegram, limites de disponibilité et retour arrière.
- [x] Sur HP, sauvegarder les fichiers existants de supervision avant transfert ciblé ; générer des identifiants locaux si absents sans les afficher.
- [x] Valider `docker compose config --quiet`, `promtool check config` et `promtool check rules`, puis `docker compose up -d`.

## 3. Preuves LIVE

- [x] Vérifier HTTP Prometheus/Grafana/Kuma, les scrapes Cœur/hôte et Grafana par API authentifiée.
- [x] Initialiser Kuma et ses sondes ; vérifier séparation adaptateur/backend Oria.
- [x] Démarrer une cible isolée, attendre UP, interrompre la cible, attendre DOWN, relancer et attendre UP ; nettoyer la cible et sa sonde.
- [x] Redémarrer seulement la supervision ; vérifier données et sondes persistantes, règles et scrapes.
- [x] Renseigner `docs/sprints/S235-supervision-resultats.md` avec preuves et critères ouverts. Telegram ne sera marqué validé qu'après configuration et réception des deux notifications.

## Critère restant

- [ ] Configuration du chat/topic Telegram autorisé et réception des notifications panne/rétablissement. Informations utilisateur attendues ; aucun envoi effectué.
