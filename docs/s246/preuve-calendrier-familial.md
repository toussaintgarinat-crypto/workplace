# S246 — Preuve LIVE de la chaîne dépôt → déploiement → exploitation (2026-11-25)

App témoin : Calendrier Familial (GitHub → miroir Forgejo → Dokploy sur la VM 100). Actions demandées dans le
chat de l'assistant (HP), approuvées par le compte Telegram lié à l'utilisateur, exécutées par le Cœur.

| Action | Approbation | Résultat constaté |
|---|---|---|
| `livraison_redemarrer` | `executee` | conteneur relancé, `healthy` |
| `livraison_deployer` (1ʳᵉ fois) | `echec` à tort | le déploiement PARTAIT (v3 publié) mais la brique exigeait du JSON : `application.redeploy` répond 200 **corps vide** |
| `livraison_deployer` (après correctif) | `executee` | nouveau déploiement `done`, `v4` publié dans Forgejo |
| `livraison_rollback` (1ʳᵉ demande) | — | l'assistant a proposé un **redémarrage** (descriptions ambiguës) ; rien de dangereux, corrigé |
| `livraison_rollback` (après descriptions) | `executee` | image du service `:latest` → `:v3`, conteneur sain |

## Ce que la preuve a révélé (et corrigé)
1. Corps vide des mutations Dokploy (redeploy, rollback) → succès si 2xx (commit « une mutation … à corps vide est un succès »). Le faux serveur divergeait du réel.
2. Choix d'outil du LLM : descriptions de `livraison_redemarrer|deployer|rollback` réécrites avec « UNIQUEMENT quand… / PAS pour… ».
3. **Reste connu** : après un rollback, Dokploy n'ajoute AUCUNE entrée `deployments[]` ; `/etat` continue d'annoncer comme « en service » le dernier déploiement alors que le service tourne sur une version antérieure (ici `:v3`). À corriger (lire le tag d'image réellement en service ou mémoriser le dernier rollback) avant de s'y fier pour décider d'un second rollback.
4. Les tags `v1…v4` ont la même image (code identique) : la preuve se lit sur la référence du service, pas sur l'ID d'image.

## Configuration de production (HP)
- `.env` racine : `APPROBATIONS_CLE`, `CONNEXION_KEY`=`CONNEXION_API_KEYS`, `LIVRAISON_KEY`=`LIVRAISON_API_KEYS`, `DOKPLOY_URL` (mesh), `DOKPLOY_API_KEY` = clé de l'utilisateur **limité au projet `temoin`** (pas la clé owner). Sauvegarde `.env.avant-s246` ; ancienne image `core-core:avant-s246`.
- Approbateur : compte Telegram lié à l'utilisateur ; l'approbation est liée à l'utilisateur demandeur (S245b).
- Pièges rencontrés : `docker compose up` a relancé `workplace_agenda_litestream` (arrêté exprès, plante sans bucket) → arrêté de nouveau, `restart=no` ; `standard-telephonique` non recréé (réseau externe `roomkit-visio_default` absent, il ne tournait pas).
