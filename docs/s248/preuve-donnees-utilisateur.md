# S248 : preuve LIVE des données utilisateur (modèle à remplir)

Statut : **à exécuter** (SLIVE, après accord explicite). Aucune ligne ci-dessous n'est une sortie
réelle tant qu'elle n'est pas remplie. Utilisateurs TÉMOINS uniquement, jamais un vrai compte.

## Prérequis et déploiement

Ordre obligatoire : 1) image du Cœur (3b) reconstruite sur le Mac et chargée (`docker save | ssh
debian@192.168.1.89 docker load`) ; 2) Studio 0.6.2 et livraison 0.3.0 ensemble ; 3) Cœur recréé
(relit le registre des manifestes). Un ancien Cœur indexe la preuve par app seule et coupe à 30 s.

| Étape | Commande / vérification | Résultat |
|---|---|---|
| Images construites sur le Mac (livraison, studio : tags du compose, code 3b ; Studio reconstruit : en-tête `X-Utilisateur`) | `docker save \| ssh debian@192.168.1.89 docker load` | |
| Retour arrière gardé (`workplace/livraison:0.2.0`, `workplace/studio:0.6.1`, image du Cœur : tag à relever sur le HP avant build : `docker inspect`) | `docker images` | |
| `executeur.py` sur la VM 100, service redémarré | `GET /sante` | |
| Limite du reverse proxy (80 Mio) | | |
| `LIVRAISON_CHIFFREMENT_CLE`, `STUDIO_SUPPORT_KEY` posées (0600, même valeur côté Studio) | | |
| `/data/contrats.json` avec l'URL réelle du Studio | | |
| Cœur recréé en dernier (image 3b déjà chargée) ; tags réels en service | `docker inspect` | |

## Jeu de données

| Utilisateur | Contenu créé | Comptages | Empreinte |
|---|---|---|---|
| `temoin-a` | 2 séries + 1 profil | | |
| `temoin-b` | 1 série | | |

## Scénario nominal (via l'assistant, Telegram)

| # | Action | Attendu | Observé |
|---|---|---|---|
| 1 | `livraison_donnees_exporter` temoin-a (approbation `reversible`) | `paquet_id`, comptages, empreinte | |
| 2 | Objet `contrat/studio/<h>/<id>.bin` dans SeaweedFS ; `strings` sans titre de série | objet présent, pas de clair | |
| 3 | `livraison_donnees_reinitialiser` temoin-a AVANT vérification | demande en attente, prérequis `False`, aucun bouton | |
| 3b | `livraison_donnees_verifier` temoin-a | verdict `valide`, renotification prérequis `True` | |
| 4 | Refus croisé : reset de `temoin-b` sans l'avoir vérifié | prérequis `False` (preuve de temoin-a non réutilisée) | |
| 5 | Approuver le reset de `temoin-a` | `reinitialise` ; temoin-a à zéro ; temoin-b intact (comptages + empreinte inchangés) | |
| 6 | `livraison_donnees_restituer` temoin-a sans `paquet_id` (espace vide, approbation `donnees`) | empreinte identique à l'étape 1 | |

## Sabotages

| # | Scénario | Attendu | Observé |
|---|---|---|---|
| a | Modifier un octet de l'objet dans SeaweedFS puis reset | refus 409 « illisible », rien effacé | |
| b | Écrire une série pour temoin-a entre vérification et reset | refus 409 « les données ont changé » | |
| c | Restitution implicite avec espace NON vide | refus 409 (« ni vide ni identique »), rien restitué | |
| d | Restitution implicite avec 2 paquets consommés candidats | refus 409 listant les identifiants ; `paquet_id` explicite = fusion voulue (objets du paquet remplaçant ceux de même identifiant, plus récents conservés ; réponse `mode: fusion`) | |
| e | 504 ambigu (app coupée/lente pendant le reset) | message avec l'id du paquet ; `verifier` puis `restituer` si des données manquent | |
| f | Preuve croisée : vérifier temoin-a puis reset temoin-b | refus, prérequis `False` | |
| g | Reset rejoué avec le même paquet (déjà consommé) | refus 409 « aucun paquet vérifié et récent » | |
| h | Expiration (ou horloge du registre avancée) puis `POST /contrats/purger` | objet et entrée supprimés | |

## Journal d'accès

Extraits de `acces.jsonl` (seul `h` apparaît, jamais l'identité) et contrôle : aucune identité en
clair dans les logs du conteneur (`--no-access-log`).

```
(à coller)
```

## Nettoyage

| Action | Fait |
|---|---|
| Utilisateurs témoins et objets supprimés | |
| `STUDIO_SUPPORT_KEY` retirée si usage non voulu | |
| Mémoire mise à jour | |

Verdict global : (à conclure)
