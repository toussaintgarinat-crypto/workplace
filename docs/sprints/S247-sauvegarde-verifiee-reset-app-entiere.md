# S247 — Sauvegarde vérifiée + remise à zéro de l'app entière

Épopée : [livraison + support](EPOPEE-livraison-support-assistant.md). Statut : **en cours (partie 1 codée sur `sprint/s247-sauvegarde-verifiee`, spike Dokploy à faire)**.
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

## Idée ajoutée (2026-11-25) — miroir de tous les dépôts GitHub dans Forgejo
Contexte : se couvrir contre un GitHub payant ou fermé. Prouvé en S246 sur Calendrier Familial : dépôt Forgejo recréé en *pull mirror* (`POST /repos/migrate` avec `mirror:true`, `mirror_interval:"10m0s"`), commits identiques à GitHub.
À faire ici : (1) mesurer la taille totale des dépôts (VM 100 : 60 Go, partagés avec les images Docker) ; (2) script qui liste le compte GitHub et crée un miroir par dépôt ; (3) jeton GitHub **en lecture seule** pour les dépôts privés (jamais dans le dépôt git) ; (4) **sauvegarde de Forgejo** vers un autre disque/lieu — sans elle le risque est seulement déplacé (VM unique) ; (5) tester la conversion d'un miroir en dépôt normal (bascule si GitHub disparaît).
Limites connues : un miroir ne copie que le code git (pas tickets/PR) ; Dokploy ne redéploie pas seul à la synchro ; nettoyage des images du registre Forgejo (rollback) à prévoir.

## Décisions (2026-11-25)
1. **Destination des sauvegardes** : SeaweedFS du HP (S3, port 9106) + copie USB existante (S233/S236). Ni autre machine ni hors site en S247.
2. **Défaut `/etat` après rollback** : durcir davantage (lire l'état réel du service plutôt que se fier au seul repère mémorisé). Faisabilité à établir par le spike (question 5) ; code en partie 2.
3. **Miroir de tous les dépôts GitHub** : sprint dédié, hors S247. Seule la sauvegarde de Forgejo (point 4 de l'idée) reste en S247.

## Découvertes (partie 1)
- Avant S247, `approbations.exiger` ne transmettait aucun prérequis à `creer` : aucune capacité ne pouvait en déclarer un. Désormais un manifeste peut déclarer `prerequis: [...]` (capacité gardée) et `fournit_preuve: "..."` (capacité de vérification) ; le Cœur lit le verdict dans le résultat de la brique (jamais dans les arguments du LLM). `core/catalogue.py` devait aussi laisser passer ces deux champs.
- Dokploy 0.31.4 : sauvegardes natives pour les bases et le compose, pas pour une application simple (à confirmer au spike, `docs/s247/spike-dokploy.md`).
- `satisfaire_prerequis` n'a toujours pas de verrou (limite 4 de S245b) ; `enregistrer_preuve` l'appelle séquentiellement et reste idempotent.
- Reste mineur noté en revue : course minuscule dans `creer` (prérequis calculés hors de la transaction d'insertion), `expire_a=NaN` accepté mais jamais honoré, écritures du registre de preuves de la brique non verrouillées (1 worker à confirmer).
