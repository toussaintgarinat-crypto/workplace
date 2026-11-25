# S248 — Contrat d'app + remise à zéro par utilisateur

Épopée : [livraison + support](EPOPEE-livraison-support-assistant.md). Statut : **spécifié, non codé**.
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

## Questions à trancher

1. Quelle app pilote ?
2. Durée de rétention des paquets ; qui peut les restituer à l'utilisateur ?
3. Format du paquet : JSON + fichiers dans une archive signée, ou autre ?
