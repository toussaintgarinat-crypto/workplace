# S248 — Contrat d'app + remise à zéro par utilisateur

Épopée : [livraison + support](EPOPEE-livraison-support-assistant.md). Statut : **parties 1+2+3a+3b codées ; preuve LIVE (SLIVE) à faire** (voir [plan 3b](../superpowers/plans/2026-11-27-s248-partie3b-reset-restitution-preuve-cible.md) et « Décisions »).
Dépend de : S245, S247 (sauvegarde vérifiée, SeaweedFS). Lire d'abord : `docs/sprints/S182-S187`
(isolation multi-utilisateur), ADR `studio-famille-compte-unique-portabilite-profil` (portabilité par
`profil_id`), `GUIDE-ajouter-une-brique.md`.

## Objectif

Pouvoir, pour **un seul utilisateur** d'une app, mettre ses données de côté, remettre son espace
à zéro et les lui restituer — sans toucher aux autres utilisateurs.

## Le contrat d'app (cœur du sprint)

Chaque app qui veut cette portée déclare dans son `manifest.json` un bloc `contrat_donnees` :

```
"contrat_donnees": {
  "version_schema": "3",
  "exporter":      {"methode": "POST", "chemin": "/support/exporter"},
  "reinitialiser": {"methode": "POST", "chemin": "/support/reinitialiser"},
  "importer":      {"methode": "POST", "chemin": "/support/importer"}
}
```

- `exporter(utilisateur)` → **paquet** : archive avec métadonnées (app, utilisateur, `version_schema`,
  date, nombre d'objets par type, somme de contrôle) + données de cet utilisateur uniquement.
- `reinitialiser(utilisateur)` → remet son espace à l'état neuf. Refuse sans paquet vérifié.
- `importer(utilisateur, paquet)` → réinjecte ; **refuse** si `version_schema` du paquet est
  supérieure à celle de l'app ; migre via un crochet de l'app si elle est inférieure.
- **Sans contrat** : l'assistant ne propose que la portée « app entière » (S247) et le dit.

Les routes `/support/*` sont **internes** (clé de brique, jamais publiques), et vérifient que
l'identité demandée est bien l'utilisateur ciblé (leçon des escalades de privilèges S227/S231).

## Séquence d'une remise à zéro utilisateur

exporter → **vérifier** (importer le paquet dans une instance/espace jetable, comparer les comptages)
→ approbation Telegram (niveau `donnees`, prérequis = paquet vérifié) → réinitialiser → importer →
contrôle final → réponse à l'utilisateur. Le paquet est gardé N jours (rétention à fixer).

## Vie privée (point central)

- **L'assistant manipule le paquet sans le lire** : il ne voit que les métadonnées (comptages,
  version, somme de contrôle), jamais le contenu. Le résumé Telegram ne contient aucune donnée perso.
- Paquets **chiffrés au repos** dans SeaweedFS (clé hors dépôt), accès cloisonné par utilisateur,
  suppression à l'expiration, journal d'accès.
- Cohérent avec la portabilité par `profil_id` déjà décidée pour le Studio.

## App pilote

À choisir au démarrage, parmi les apps qui ont de vraies données utilisateur et une isolation par
compte (candidats à examiner : calendrier familial, Studio, restaurant). Critère : isolation déjà
prouvée (S182-S187), schéma stable, risque faible. Livrer aussi un **gabarit/guide** du contrat
(`GUIDE-contrat-donnees.md`) et un **test de conformité** réutilisable par toute app candidate.

## Tests et preuves

- Test de conformité du contrat : export→reset→import redonne un état identique (comptages +
  somme de contrôle) ; un autre utilisateur n'est **pas** touché (test d'isolation explicite).
- Paquet falsifié, mauvaise version de schéma, paquet d'un autre utilisateur : refusés.
- Mutation testing sur l'isolation (neutraliser le filtre utilisateur → le test d'isolation échoue).
- LIVE groupé en SLIVE.

## Hors périmètre

Généraliser le contrat à toutes les apps (au fil de l'eau). Export RGPD « public » destiné à l'usager
final (le paquet de support est un outil interne).

## Décisions (2026-11-27)

1. App pilote = **Studio** (isolation par personne prouvée S187, `profil_id` portable, données en JSON fichier).
2. Rétention = **14 jours** puis suppression automatique ; restitution à l'utilisateur seulement par lui-même, après validation Telegram (partie 3).
3. Format = **tar.gz** (`meta.json` signé HMAC + `donnees.json` canonique) ; **chiffrement au repos assuré par `livraison`** (le Studio reste stdlib seule), clé hors dépôt (partie 3).

Reset : l'app exige l'empreinte exacte des données courantes (paquet = état actuel). Clé dédiée `STUDIO_SUPPORT_KEY`.

Guide du contrat : [GUIDE-contrat-donnees.md](../GUIDE-contrat-donnees.md).

## Livré en 3b (codé et testé sans Docker)

- Outils `livraison_donnees_reinitialiser` et `livraison_donnees_restituer` (niveau `donnees`) ;
  `livraison_donnees_verifier` fournit la preuve `paquet_verifie`.
- Preuve liée à (app, utilisateur visé) dans le Cœur (`PREUVES_PAR_CIBLE`, `cle_preuve`) : une
  vérification n'autorise jamais le reset d'un autre utilisateur ; fraîcheur 6 h, un paquet = un reset.
- Orchestration : relecture + ré-export avant effacement, contrôle final à zéro, budget global 540 s
  (Cœur 600 s), 504 ambigus explicites, restitution implicite stricte (paquet consommé unique, espace
  vide), `paquet_id` = écrasement délibéré.
- Journaux d'accès uvicorn coupés ; procédure de reprise du registre dans le README de `livraison`.
- Studio : identité en en-tête `X-Utilisateur` (Task 0) ; test de livraison contre le vrai Studio.
- Limites connues : `docs/GUIDE-contrat-donnees.md` section 7.

## Reste pour la preuve LIVE (SLIVE)

Modèle : [docs/s248/preuve-donnees-utilisateur.md](../s248/preuve-donnees-utilisateur.md).

1. Copier `outils/executeur-restauration/executeur.py` sur la VM 100, redémarrer le service, `GET /sante`.
2. Poser `LIVRAISON_CHIFFREMENT_CLE` et `STUDIO_SUPPORT_KEY` dans `briques/livraison/.env` (0600) ;
   `STUDIO_SUPPORT_KEY` (même valeur) côté Studio ; copier `contrats.exemple.json` en
   `/data/contrats.json` (volume `livraison_data`) avec l'URL réelle du Studio.
3. Images : les `docker-compose.yml` épinglent `workplace/livraison:0.2.0` et `workplace/studio:0.6.1`
   (commit 1b06195), AVANT les changements de 3b. Construire sur le Mac les images depuis le HEAD de la
   branche sous ces tags si elles n'ont jamais été construites ; sinon bumper (ex. 0.2.1 / 0.6.2) dans
   les compose. Le tag déployé doit contenir le code 3b. **L'image Studio DOIT être reconstruite** : la
   Task 0 a changé ses routes `/support/*` (identité en en-tête `X-Utilisateur`) ; l'ancienne image est
   incompatible avec la nouvelle `livraison`. `docker save | ssh debian@192.168.1.89 docker load`
   (build pip impossible sur le HP).
4. Redémarrer le Cœur (nouveau registre d'outils et logique de preuve par cible) ; `up -d` des deux
   briques et vérifier le tag réel par `docker inspect`.
5. Jouer le scénario du modèle sur des utilisateurs témoins, consigner, nettoyer, retirer
   `STUDIO_SUPPORT_KEY` si l'usage n'est pas voulu.
