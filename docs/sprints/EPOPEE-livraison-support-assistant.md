# Épopée : livraison + support d'applications piloté par l'assistant (S245→S249)

> **Sommaire.** Ce fichier reste court : il ne porte que l'objectif, les décisions et l'état.
> Le détail de chaque sprint vit dans son propre fichier `docs/sprints/S2xx-*.md` (les 5 sont
> rédigés, au niveau conception). **Ne lire que le fichier du sprint en cours.** Au démarrage d'un
> sprint : relire son fichier, lever ses « questions à trancher », puis `writing-plans`.

Créé le 2026-11-25 (brainstorming). Statut global : **S245 codé + revu (preuve LIVE Telegram différée en SLIVE) ; S246+S247+S248 livrés et prouvés LIVE ; S249 spécifié**.

## Objectif

Que l'assistant puisse **exploiter les applications déployées et résoudre le problème d'un
utilisateur** : diagnostiquer, proposer une action, la faire valider par l'humain sur
Telegram, l'exécuter, vérifier le résultat, répondre à l'utilisateur.

Outils visés : Dokploy (remplace Vercel), Forgejo (remplace GitHub, GitHub gardé en miroir
pour le public), chaîne Capacitor/Gradle pour le mobile (en dernier).
Workplace **orchestre** ces outils ; il ne les réimplémente pas.

## Décisions prises

1. **Toute action au-delà de la lecture est validée par l'humain sur Telegram.** Lecture et
   diagnostic restent autonomes.
2. **Approbation liée à l'action exacte**, avec identifiant, expiration (~30 min), seul le
   compte Telegram de l'utilisateur peut approuver, tout est journalisé.
3. **Niveaux de sensibilité** : lecture (aucune validation) → réversible (bouton Telegram) →
   données touchées (bouton grisé tant que la sauvegarde n'est pas vérifiée) → destructif
   (confirmation renforcée : Mini App ou code).
4. **Urgence : mode attente (approche B)** : relance après X min, page « maintenance » côté
   utilisateur, mais l'assistant n'agit jamais sans validation.
5. **Remise à zéro sans perte** : jamais d'effacement sur place. Sauvegarde vérifiée →
   nouvelle instance propre à côté (bleu/vert) → restauration → contrôles → bascule.
   Ancienne instance gardée quelques jours.
6. **Deux portées** : app entière (mises à jour) ET par utilisateur (support). La portée par
   utilisateur exige un **contrat d'app** dans `manifest.json` : `exporter`, `reinitialiser`,
   `importer` (avec contrôle de version du schéma). Sans contrat : portée entière seulement.
7. Piège connu : si la cause est dans les données (migration cassée, ligne corrompue), un
   reset les reproduit. Diagnostiquer code/config/données **avant** de proposer un reset.
8. Limite mobile : un correctif natif impose rebuild + revue du store ; Capacitor permet des
   mises à jour OTA de la couche web. iOS impose le Mac comme runner (mesh NetBird).
9. Dokploy sur **VM Proxmox dédiée**, pas sur la VM 103, pour éviter le conflit avec Caddy.

## Sprints

| Sprint | Contenu | Dépend de | Fichier détail | État |
|---|---|---|---|---|
| S245 | Socle d'approbation Telegram (demandes liées à l'action, niveaux, journal) | S75/S76 existants | [S245-socle-approbation-telegram.md](S245-socle-approbation-telegram.md) | codé + revu + S245b (liaison utilisateur, reprise, `CONNEXION_API_KEYS`) ; LIVE à prouver |
| S246 | Forgejo + Dokploy, outils d'exploitation (logs, redémarrer, rollback) | S245 | [S246-forgejo-dokploy-exploitation.md](S246-forgejo-dokploy-exploitation.md) | LIVRÉ + LIVE (redémarrer/déployer/rollback approuvés sur Telegram) ; approbations ACTIVES sur le HP |
| S247 | Sauvegarde vérifiée + reset app entière (bleu/vert) | S246 | [S247-sauvegarde-verifiee-reset-app-entiere.md](S247-sauvegarde-verifiee-reset-app-entiere.md) | en cours (partie 1 codée, spike à faire) |
| S248 | Contrat d'app + reset par utilisateur (app pilote) | S247 | [S248-contrat-app-reset-par-utilisateur.md](S248-contrat-app-reset-par-utilisateur.md) | **CLOS 2026-11-27** : contrat + Studio pilote + stockage chiffré + reset/restitution par utilisateur, LIVE HP prouvé |
| S249 | Collecte d'erreurs (GlitchTip), bouton « signaler », diagnostic auto ; puis Android (runner), iOS (Mac) | S246 | [S249-collecte-erreurs-signalement-diagnostic.md](S249-collecte-erreurs-signalement-diagnostic.md) | spécifié |

## Points ouverts

- **VM Proxmox 100 « dokploy »** : existe, arrêtée, ISO Debian 13 encore branchée, aucune
  trace de config Dokploy. État réel inconnu. À vérifier au démarrage de S246 (attention : ~5 Go
  de RAM libres seulement sur le nœud, la VM en demande 5,8).
- Nom de la brique Forgejo à choisir (« Forge » est déjà pris dans Workplace).
- App pilote du contrat d'app (S248) à choisir.
