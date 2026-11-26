# S247 partie 2b — Preuve LIVE du reset bleu/vert (2026-11-26)

Application témoin `calendrier-familial` (HP, Dokploy). Les vraies applications restent sur Vercel.
Chaîne réelle : chat de l'assistant → approbation Cœur → ✅ Telegram de l'utilisateur → brique `livraison` → exécuteur VM 100 + Dokploy.

## Déroulé

| # | Opération | Approbation | Résultat |
|---|---|---|---|
| 1 | Reset nominal (1re tentative) | ✅ utilisateur | **ÉCHEC contrôlé** à l'étape « sauvegarde » (`erreur_dokploy`) : instance A restée active, base `temoin` intacte (42), base neuve supprimée, 0 coupure |
| 2 | Reset nominal (après correctif) | ✅ utilisateur | `reussie` en 8 s : B active, base `temoin_v1c9b9eb9`, 42 lignes |
| 3 | Retour arrière | ✅ utilisateur | `reussie` en 0,4 s : A de nouveau active sur `temoin` |
| 4 | Second reset (réutilisation du jumeau B) | ✅ utilisateur | `reussie` en 7 s : B active, base `temoin_v66ff1237` |

Contrôles après chaque étape (Dokploy + exécuteur) : application active sur l'hôte public, `DATABASE_URL` de l'instance active sur la bonne base, `backup.one.database` = base active, comptages 42 = 42, site public 200.

## Non-coupure
Boucle à ~10 Hz sur le domaine public (Traefik, `Host:` public, `/health`) pendant toute la séquence : **0 réponse non 2xx/3xx** (≈6 500 requêtes sur la dernière boucle, ≈10 600 sur la précédente, y compris autour de l'échec, du redémarrage de la brique, des deux reset et du retour arrière).

## Bug trouvé par le live (corrigé, 611ac34)
`backup.update` de Dokploy 0.31.4 refuse un `customName` à `null` (il doit être **absent**) mais exige `serviceName` et `metadata` (nuls acceptés). Le faux Dokploy était plus permissif que le vrai : il reproduit maintenant cette règle et un test la couvre. Leçon : un fake strict doit être calé sur les réponses réelles relevées en live.

## Comportements confirmés
- Base d'origine `temoin` jamais supprimée ; base d'un essai échoué supprimée.
- Base quittée par un retour arrière **conservée** et nommée dans le message (`temoin_v1c9b9eb9`, « à supprimer à la main ») car elle peut contenir des écritures.
- Le message de fin précise l'heure de la sauvegarde (UTC) : les données écrites après restent dans l'ancienne base.

## Incidents de la séance (honnêteté)
- Le LLM de l'assistant annonce souvent « demande envoyée / en attente » sans appeler l'outil : **toujours vérifier la table `approbations` du Cœur**, ne pas se fier au texte. Un message explicite (« appelle réellement l'outil … avec {…} ») a fonctionné. Piste 2c : durcir les descriptions d'outils / le prompt.
- Un diagnostic de ma part a créé l'approbation `f116d8cd` (utilisateur `perso`), notifiée sur Telegram puis refusée aussitôt ; elle n'a rien exécuté.

## Non couvert (reporté 2c)
Écriture d'une ligne-témoin dans la base quittée (I2), échange partiel provoqué, 503 sans `LIVRAISON_TRAEFIK_URL`, concurrence (vérifier pendant un reset), plantage de la brique pendant la bascule, suppression de la génération N-2 (aujourd'hui conservée volontairement après un retour arrière).
