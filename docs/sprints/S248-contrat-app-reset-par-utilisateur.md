# S248 — Contrat d'app + remise à zéro par utilisateur

Épopée : [livraison + support](EPOPEE-livraison-support-assistant.md). Statut : **parties 1+2+3a codées ; 3b (reset/restitution, preuve par cible) à exécuter** (voir [plan 3b](../superpowers/plans/2026-11-27-s248-partie3b-reset-restitution-preuve-cible.md) et « Décisions »).
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

État : Parties 1+2 codées — plan `docs/superpowers/plans/2026-11-27-s248-partie1-2-contrat-donnees-studio.md` ; partie 3 à planifier.
