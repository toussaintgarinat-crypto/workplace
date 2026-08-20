# Installer Workplace sur un PC neuf, avec les données d'une clé de sauvegarde

Destiné à être suivi par un agent de code (Claude Code, OpenCode…) à qui on demande
« installe Workplace ici » — sur le modèle de `MIGRATION-HP.md`, mais pour un PC personnel
plutôt que le HP, et avec restauration depuis une clé USB plutôt qu'un déploiement neuf.

## Ce qui voyage — et ce qui ne voyage pas

- Le CODE voyage par `git clone` (dépôt public/privé GitHub).
- Les SECRETS (`.env`) voyagent par un canal choisi par l'utilisateur (Drive, autre clé…),
  **jamais** par la clé de sauvegarde des bases (cf. spec S233, non-objectifs).
- Les DONNÉES (bases Postgres/SQLite) voyagent par la clé de sauvegarde USB.

## 1. Cloner

```bash
git clone https://github.com/<compte>/workplace.git
cd workplace
```

## 2. Poser le `.env`

Récupérer le fichier `.env` (fourni séparément par l'utilisateur, via le bouton « Exporter le
.env » du dashboard sur l'ancienne machine) et le placer à la racine du dépôt cloné.

## 3. Démarrer le Cœur (et les briques dont on veut restaurer les données)

```bash
cd core && docker compose up -d --build
```

Démarrer aussi, AVANT de demander la restauration, les briques dont on veut récupérer les
données (au minimum leurs conteneurs de base doivent être démarrés pour que la restauration
trouve une cible — cf. `core/sauvegarde_usb.py::decouvrir_conteneurs_par_brique`, Task 5) :

```bash
cd ../briques/<brique> && docker compose up -d --build
```

## 4. Restaurer les données depuis la clé

Brancher la clé de sauvegarde sur CE PC. Le point de montage automatique (règle udev) est
propre au HP — sur un PC personnel, monter manuellement (ou adapter la règle, cf.
`outils/sauvegarde-usb/README.md`) et définir `SAUVEGARDE_USB_MONTAGE` dans le `.env` local
si le point de montage diffère de `/mnt/sauvegarde-usb`.

Une fois le Cœur démarré et la clé montée, demander à l'assistant (dashboard `/dashboard`,
onglet Assistant) : **« restaure depuis la clé »** — ou utiliser le bouton « Restaurer depuis
la clé » du panneau ⚙ Sauvegarde.
