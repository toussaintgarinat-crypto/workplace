# S247 — Sauvegarde vérifiée + remise à zéro de l'app entière

Épopée : [livraison + support](EPOPEE-livraison-support-assistant.md). Statut : **spécifié, non codé**.
Dépend de : S245 (prérequis d'approbation), S246 (Dokploy, brique `livraison`).
Lire d'abord : `docs/specs` S236 (sauvegardes cohérentes), S237b (SeaweedFS), note mémoire
`sprint-sauvegarde-continue-rpo`.

## Objectif

Mettre à jour ou remettre à zéro une application **sans perdre de données**, avec une preuve que
la sauvegarde est restaurable *avant* que l'humain puisse approuver l'opération.

## Conception : jamais d'effacement sur place (bleu/vert)

1. **Mise de côté** : sauvegarde de la base et des volumes (sauvegardes Dokploy vers une
   destination S3 = **SeaweedFS**) + empreinte/comptages (lignes par table, taille des volumes).
2. **Vérification** : restauration de cette sauvegarde dans une **instance jetable** ; contrôles :
   l'app démarre, la santé répond, comptages = ceux de l'origine. Résultat consigné
   (`preuve_sauvegarde` : id, date, verdict).
3. **Nouvelle instance propre** déployée à côté de l'ancienne (« verte »), données restaurées
   dedans, contrôles identiques.
4. **Bascule** du domaine/routage vers la verte ; l'ancienne (« bleue ») est **conservée N jours**
   comme filet. Retour arrière = rebasculer.

**Lien avec S245** : l'opération est de sensibilité `donnees` ; sa demande d'approbation déclare le
prérequis `preuve_sauvegarde`. Le bouton Approuver n'apparaît dans Telegram **qu'après** le
verdict positif de l'étape 2. L'assistant ne peut donc pas te demander d'approuver un reset sans filet.

**Mise à jour avec migration de schéma** : migrer la **copie restaurée** (verte), jamais la
production ; si la migration échoue, la bleue n'a pas bougé.

**Diagnostic préalable** (une fiche que l'assistant remplit avant de proposer un reset) : la cause
est-elle le **code**, la **configuration** ou les **données** ? Seuls les deux premiers cas sont
réglés par un reset ; des données corrompues se réparent (action `donnees`/`destructif`), sinon le
reset reproduit le bug dans la nouvelle instance.

**Mode attente (approche B)** : pendant l'opération, page « maintenance » servie côté utilisateur ;
relances Telegram si l'approbation tarde (mécanisme S245).

## Nouvelles capacités (brique `livraison`)

`livraison_sauvegarder` (donnees), `livraison_verifier_sauvegarde` (lecture/jetable),
`livraison_reset_app` (donnees, prérequis preuve), `livraison_basculer` (donnees),
`livraison_retour_arriere` (reversible).

## Risques et pièges

- **Cohérence** : sauvegarder une base vivante sans verrou donne une copie incohérente. Utiliser
  les mécanismes de sauvegarde transactionnels (dump cohérent / snapshot) ; s'inspirer de S236.
- **Volumes de fichiers** : pas tous couverts par les sauvegardes de base ; les inventorier par app.
- **Secrets** : les variables d'environnement de l'ancienne instance doivent suivre, sans fuiter
  dans les logs ni dans le résumé Telegram.
- **Stockage** : l'ancienne instance et les sauvegardes consomment disque ; politique de rétention.
- **Incertitude Dokploy** : le bleu/vert n'est peut-être pas natif ; il pourrait s'obtenir en
  clonant l'application + changement de domaine. **Spike obligatoire** avant conception finale.

## Tests et preuves

Faux serveur Dokploy pour la logique ; **test de bout en bout sur l'app témoin** : sabotage volontaire
(corruption de la verte → la bascule est refusée, la bleue intacte), puis cas nominal. Mutation
testing du lien « bouton grisé tant que la preuve manque ». LIVE groupé en SLIVE.

## Hors périmètre

Portée par utilisateur (S248). Sauvegardes de Workplace lui-même (déjà couvertes par S236/S237).

## Questions à trancher

1. Durée de conservation de l'instance bleue ?
2. Quelles apps sont éligibles en premier (celles qui ont une vraie base et des volumes) ?
