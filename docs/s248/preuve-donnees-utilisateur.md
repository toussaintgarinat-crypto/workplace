# Preuve LIVE S248 (3a + 3b) — données utilisateur, HP, 2026-11-27

Déploiement : Cœur reconstruit (`core-core:s248-3b`), `workplace/studio:0.6.2`, `workplace/livraison:0.3.0` (construits sur le Mac, `docker save | ssh docker load`), `executeur.py` redéployé sur la VM 100 (ancien : `/opt/executeur-restauration/executeur.py.avant-s248`). Clés `LIVRAISON_CHIFFREMENT_CLE` / `STUDIO_SUPPORT_KEY` générées sur le HP (jamais affichées), `briques/livraison/.env` et `briques/studio/.env` en 0600. Registre `/data/contrats.json` = `contrats.exemple.json`. Retours arrière : `core-core:avant-s248-3b`, `workplace/studio:avant-s248-3b` (= 0.6.1), `workplace/livraison:0.2.0`.

Ordre suivi : Cœur → Studio + livraison → recréation. Utilisateurs TÉMOINS `temoin-a` / `temoin-b` (semés directement dans le volume du Studio, nettoyés ensuite).

## Résultats

| Scénario | Résultat |
|---|---|
| Paquet stocké chiffré dans SeaweedFS (magie `WP1`), ni identité ni titre en clair, registre sans identité | OBSERVÉ (partie A, étape 1) |
| Reset sans vérification | refusé 409, rien effacé (A2) |
| Preuve par cible : reset de `temoin-b` après vérification de `temoin-a` | refusé (A4) ; via le Cœur le prérequis de `temoin-b` reste non satisfait quand celui de `temoin-a` passe (B3) |
| Écriture après vérification | « les données ont changé », rien effacé (A5) |
| Objet altéré dans SeaweedFS | « paquet stocké illisible », rien effacé (A6) |
| Reset réel ; l'autre utilisateur intact (même empreinte) | OBSERVÉ (A7) |
| Un paquet = un reset | second reset refusé (A8) |
| Restitution implicite = état d'avant le reset (comptages + empreinte identiques) ; 2e restitution → 404 | OBSERVÉ (A9, B6) |
| Purge d'un paquet expiré : objet supprimé de SeaweedFS et du registre | OBSERVÉ (A10) |
| Journal d'accès : hash seulement ; logs livraison : 0 occurrence de l'identité | OBSERVÉ (A11, A12) |
| Garde via le Cœur (identité `Toussaint` = compte de l'approbateur) : demande niveau `donnees`, prérequis `paquet_verifie`, Telegram, exécution automatique après approbation humaine ; restitution idem | OBSERVÉ (B3-B6) ; approbations données par l'utilisateur sur Telegram |

Non rejoué en LIVE (couvert par tests unitaires/mutation, voir plans) : sortie ambiguë 504 d'un reset, dépassement du budget global 540 s, registre corrompu.

Constats LIVE : (1) un appel MCP anonyme s'exécute sous l'identité `perso` ; la demande n'est alors envoyée à AUCUN approbateur Telegram (l'approbateur est lié à `Toussaint`) : comportement sûr mais piège pour tout test — lancer sous le compte de l'approbateur. (2) `connecteurs` et `synopsis` sont « endormies » (comportement à la demande attendu).

## Partie A — niveau brique (HP, appels directs, `livraison` :6240)

```
=== 0. Semis des utilisateurs TÉMOINS (temoin-a: 2 séries+profil+journal+compte ; temoin-b: 1 série)
seed ok
temoin-a {"comptes": 1, "journaux": 1, "ponts": 0, "profils": 1, "series": 2} 40678c7d412e0f5e
temoin-b {"comptes": 0, "journaux": 0, "ponts": 0, "profils": 0, "series": 1} e7f7011027f9c34e

=== 1. Exporter temoin-a (niveau reversible côté Cœur ; ici appel direct de la brique)
exporter: HTTP 200 {"ok": true, "app": "studio", "paquet_id": "5543cf16ca64104a0ee875f3fad8ff40", "empreinte": "40678c7d412e0f5ebe09e0521fba2d9baffe6cbc86246db36555c9132e4b12f3", "comptages": {"comptes": 1, "journaux": 1, "ponts": 0, "profils": 1, "series": 2}, "version_schema": "1", "expire_a": 1796997898.6985192}
registre: clés = ['app', 'comptages', 'consomme_a', 'cree_a', 'empreinte', 'expire_a', 'h', 'id', 'objet', 'restitue_a', 'verifie_a', 'version_schema'] | contient l'identité en clair ? False
objet S3 contrat/studio/…: GET -> 200, 615 octets, magie=b'WP1', texte clair 'temoin' présent ? False, titre de série présent ? False

=== 2. Reset AVANT vérification valide => refus ; rien n'est effacé
reinitialiser (paquet non vérifié): HTTP 409 {"detail": "aucun paquet vérifié et récent pour cet utilisateur : lance d'abord livraison_donnees_verifier"}
temoin-a {"comptes": 1, "journaux": 1, "ponts": 0, "profils": 1, "series": 2} 40678c7d412e0f5e
temoin-b {"comptes": 0, "journaux": 0, "ponts": 0, "profils": 0, "series": 1} e7f7011027f9c34e

=== 3. Vérifier temoin-a (verdict + preuve_id pour le Cœur)
verifier: HTTP 200 {"app": "studio", "ok": true, "verdict": "valide", "paquet_id": "46091a134d86650e32cf49b9e6a339a2", "preuve_id": "46091a134d86650e32cf49b9e6a339a2", "empreinte": "40678c7d412e0f5ebe09e0521fba2d9baffe6cbc86246db36555c9132e4b12f3", "comptages": {"comptes": 1, "journaux": 1, "ponts": 0, "profils": 1, "series": 2}, "raisons": [], "expire_a": 1795809899.0445297}

=== 4. Preuve liée à la CIBLE : reset de temoin-b sans l'avoir vérifié => refus
reinitialiser temoin-b: HTTP 409 {"detail": "aucun paquet vérifié et récent pour cet utilisateur : lance d'abord livraison_donnees_verifier"}

=== 5. Sabotage (b) : temoin-a écrit une série APRÈS la vérification => « ont changé », rien d'effacé
écrit
reinitialiser temoin-a: HTTP 409 {"detail": "les données ont changé depuis la vérification : relance livraison_donnees_verifier"}
temoin-a {"comptes": 1, "journaux": 1, "ponts": 0, "profils": 1, "series": 3} 23f29c6ab5b949c7
temoin-b {"comptes": 0, "journaux": 0, "ponts": 0, "profils": 0, "series": 1} e7f7011027f9c34e

=== 6. Revérifier (état courant), puis sabotage (a) : on ALTÈRE un octet du paquet dans SeaweedFS => reset refusé
verifier: HTTP 200 {"app": "studio", "ok": true, "verdict": "valide", "paquet_id": "a757a7b167abca823bf3508170b05fe4", "preuve_id": "a757a7b167abca823bf3508170b05fe4", "empreinte": "23f29c6ab5b949c7b3bda6bf598899ef7817d579ab58dbdbdf8767d25afd20ce", "comptages": {"comptes": 1, "journaux": 1, "ponts": 0, "profils": 1, "series": 3}, "raisons": [], "expire_a": 1795809899.5466974}
PUT objet altéré -> 200
reinitialiser (objet altéré): HTTP 409 {"detail": "paquet stocké illisible (altéré ou clé changée) : refais une vérification"}
temoin-a {"comptes": 1, "journaux": 1, "ponts": 0, "profils": 1, "series": 3} 23f29c6ab5b949c7
temoin-b {"comptes": 0, "journaux": 0, "ponts": 0, "profils": 0, "series": 1} e7f7011027f9c34e
restauration de l'objet intact -> 200

=== 7. Reset réel de temoin-a (paquet vérifié, intact) ; temoin-b intact
reinitialiser: HTTP 200 {"app": "studio", "ok": true, "etat": "reinitialise", "paquet_id": "a757a7b167abca823bf3508170b05fe4", "supprimes": {"comptes": 1, "journaux": 1, "ponts": 0, "profils": 1, "series": 3}}
temoin-a {"comptes": 0, "journaux": 0, "ponts": 0, "profils": 0, "series": 0} abdf5599fa43b159
temoin-b {"comptes": 0, "journaux": 0, "ponts": 0, "profils": 0, "series": 1} e7f7011027f9c34e
temoin-b inchangé ? True

=== 8. Un paquet ne sert qu'à UN reset : second reset => refus
reinitialiser (2e fois): HTTP 409 {"detail": "les données ont changé depuis la vérification : relance livraison_donnees_verifier"}

=== 9. Restitution implicite (espace vide) => état initial retrouvé
restituer: HTTP 200 {"app": "studio", "ok": true, "etat": "restitue", "mode": "exacte", "paquet_id": "a757a7b167abca823bf3508170b05fe4", "comptages": {"comptes": 1, "journaux": 1, "ponts": 0, "profils": 1, "series": 3}}
temoin-a {"comptes": 1, "journaux": 1, "ponts": 0, "profils": 1, "series": 3} 23f29c6ab5b949c7
temoin-b {"comptes": 0, "journaux": 0, "ponts": 0, "profils": 0, "series": 1} e7f7011027f9c34e
temoin-a identique (comptages+empreinte) à l'état d'avant le reset ? True
2e restitution implicite (déjà restitué): HTTP 404 {"detail": "aucun paquet à restituer : aucune remise à zéro n'a consommé de paquet pour cet utilisateur (précise paquet_id pour un paquet vérifié)"}

=== 10. Purge : on vieillit un paquet dans le registre, POST /contrats/purger => objet supprimé de SeaweedFS
purger: 200 {'ok': True, 'supprimes': 1, 'restants': 0}
GET objet purgé -> 502 (502 attendu : absent) ; paquet encore au registre ? False

=== 11. Journal d'accès (sans identité ni contenu)
{"t": 1795788299.0444303, "operation": "verifier", "app": "studio", "h": "14b86864b07e3b20", "paquet": "46091a134d86650e32cf49b9e6a339a2", "ok": true}
{"t": 1795788299.513422, "operation": "exporter", "app": "studio", "h": "14b86864b07e3b20", "paquet": "a757a7b167abca823bf3508170b05fe4", "ok": true}
{"t": 1795788299.5465984, "operation": "verifier", "app": "studio", "h": "14b86864b07e3b20", "paquet": "a757a7b167abca823bf3508170b05fe4", "ok": true}
{"t": 1795788300.1147656, "operation": "reinitialiser", "app": "studio", "h": "14b86864b07e3b20", "paquet": "a757a7b167abca823bf3508170b05fe4", "ok": true}
{"t": 1795788300.3876753, "operation": "restituer", "app": "studio", "h": "14b86864b07e3b20", "paquet": "a757a7b167abca823bf3508170b05fe4", "ok": true}
{"t": 1795788300.767133, "operation": "purger", "app": "studio", "h": "14b86864b07e3b20", "paquet": "5543cf16ca64104a0ee875f3fad8ff40", "ok": true}

=== 12. Logs livraison : l'identité n'apparaît pas
occurrences de 'temoin' dans les logs livraison: 0

=== 13. Nettoyage des utilisateurs témoins
nettoyé {'series': 0, 'profils': 0, 'journaux': 0, 'comptes': 0, 'ponts': 0} {'series': 0, 'profils': 0, 'journaux': 0, 'comptes': 0, 'ponts': 0}
```

## Partie B — la garde (Cœur, approbations Telegram)

```
=== B0. Semis TÉMOINS + outils exposés par le Cœur
seed ok
temoin-a {"comptes": 1, "journaux": 0, "ponts": 0, "profils": 1, "series": 2} 2b89d20e5b8f8232
temoin-b {"comptes": 0, "journaux": 0, "ponts": 0, "profils": 0, "series": 1} e7f7011027f9c34e
outils livraison_donnees_* exposés: ['livraison_donnees_exporter', 'livraison_donnees_reinitialiser', 'livraison_donnees_restituer', 'livraison_donnees_verifier']
identité du test (compte de l'approbateur Telegram): Toussaint

=== B1. Reset de temoin-a SANS vérification => demande créée, prérequis NON satisfait (pas de preuve)
réponse outil: [registre] 42 brique(s) chargée(s) : ['agenda', 'atelier-images-video', 'atelier-veille', 'audit', 'audit-fichiers', 'calcul', 'connecteurs', 'connexion', 'dev', 'donnees', 'ecoute', 'export', 'forge', 'gateway', 'gateway-sync', 'generateur', 'geo', 'images', 'ingestion', 'jeu-factions', 'livraison'
demande temoin-a: en_attente donnees {"paquet_verifie": false}

=== B2. Reset de temoin-b SANS vérification => idem
réponse outil: [registre] 42 brique(s) chargée(s) : ['agenda', 'atelier-images-video', 'atelier-veille', 'audit', 'audit-fichiers', 'calcul', 'connecteurs', 'connexion', 'dev', 'donnees', 'ecoute', 'export', 'forge', 'gateway', 'gateway-sync', 'generateur', 'geo', 'images', 'ingestion', 'jeu-factions', 'livraison'
demande temoin-b: en_attente donnees {"paquet_verifie": false}

=== B3. Vérification de temoin-a (via le Cœur) => la preuve se lève POUR temoin-a SEULEMENT
réponse outil: [registre] 42 brique(s) chargée(s) : ['agenda', 'atelier-images-video', 'atelier-veille', 'audit', 'audit-fichiers', 'calcul', 'connecteurs', 'connexion', 'dev', 'donnees', 'ecoute', 'export', 'forge'
demande temoin-a: en_attente {"paquet_verifie": true}
demande temoin-b: en_attente {"paquet_verifie": false} <= doit rester non satisfait
>>> ACTION HUMAINE : approuver sur Telegram la demande de remise à zéro de temoin-a ; NE PAS approuver temoin-b

=== B4. Attente de l'approbation humaine du reset de temoin-a (le Cœur rejoue l'action après accord)
  [reset temoin-a] statut = en_attente
  [reset temoin-a] statut = executee
issue: executee | {"app": "studio", "ok": true, "etat": "reinitialise", "paquet_id": "3d3e0709dcc10dfc20288d254f022880", "supprimes": {"comptes": 1, "journaux": 0, "ponts": 0, "profils": 1, "series": 2}}
temoin-a {"comptes": 0, "journaux": 0, "ponts": 0, "profils": 0, "series": 0} abdf5599fa43b159
temoin-b {"comptes": 0, "journaux": 0, "ponts": 0, "profils": 0, "series": 1} e7f7011027f9c34e

=== B5. temoin-b : jamais approuvé => rien exécuté ; on REFUSE la demande restante
refus de la demande temoin-b: (True, 'ok')

=== B6. Restitution de temoin-a via le Cœur (niveau donnees, approbation Telegram)
réponse outil: [registre] 42 brique(s) chargée(s) : ['agenda', 'atelier-images-video', 'atelier-veille', 'audit', 'audit-fichiers', 'calcul', 'connecteurs', 'connexion', 'dev', 'donnees', 'ecoute', 'export', 'forge', 'gateway', 'gateway-sync', 'generateur', 'geo', 'images', 'ingestion', 'jeu-factions', 'livraison'
demande restitution: en_attente donnees {}
>>> ACTION HUMAINE : approuver sur Telegram la RESTITUTION de temoin-a
  [restitution temoin-a] statut = en_attente
  [restitution temoin-a] statut = executee
issue: executee | {"app": "studio", "ok": true, "etat": "restitue", "mode": "exacte", "paquet_id": "3d3e0709dcc10dfc20288d254f022880", "comptages": {"comptes": 1, "journaux": 0, "ponts": 0, "profils": 1, "series": 2}}
temoin-a {"comptes": 1, "journaux": 0, "ponts": 0, "profils": 1, "series": 2} 2b89d20e5b8f8232
temoin-b {"comptes": 0, "journaux": 0, "ponts": 0, "profils": 0, "series": 1} e7f7011027f9c34e

=== B7. Nettoyage
nettoyé {'temoin-a': 0, 'temoin-b': 0}
FIN
```
