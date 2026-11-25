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
3. Après un rollback, Dokploy n'ajoute AUCUNE entrée `deployments[]` : `/etat` annonçait comme « en service » le dernier déploiement alors que le service tournait sur une version antérieure (`:v3`). **Corrigé** : la brique mémorise, par application, le déploiement visé et le plus récent au moment du rollback (`repere_rollback.py`, volume `livraison_data`) ; `/etat` renvoie `en_service` = version visée + `via_rollback: true` tant qu'aucun déploiement plus récent n'apparaît, et un second rollback par défaut vise la version antérieure à celle en service.
4. Les tags `v1…v4` ont la même image (code identique) : la preuve se lit sur la référence du service, pas sur l'ID d'image.

## Configuration de production (HP)
- `.env` racine : `APPROBATIONS_CLE`, `CONNEXION_KEY`=`CONNEXION_API_KEYS`, `LIVRAISON_KEY`=`LIVRAISON_API_KEYS`, `DOKPLOY_URL` (mesh), `DOKPLOY_API_KEY` = clé de l'utilisateur **limité au projet `temoin`** (pas la clé owner). Sauvegarde `.env.avant-s246` ; ancienne image `core-core:avant-s246`.
- Approbateur : compte Telegram lié à l'utilisateur ; l'approbation est liée à l'utilisateur demandeur (S245b).
- Pièges rencontrés : `docker compose up` a relancé `workplace_agenda_litestream` (arrêté exprès, plante sans bucket) → arrêté de nouveau, `restart=no` ; `standard-telephonique` non recréé (réseau externe `roomkit-visio_default` absent, il ne tournait pas).

## Clôture S246 (2026-11-25)
- `AUTH_SESSION_SECRET` du Cœur (défini en clair dans `core/docker-compose.override.yml` du HP, fichier non suivi par git et jamais committé) a été **tourné** après avoir été affiché par erreur dans une session ; les sessions ouvertes sont déconnectées (reconnexion Keycloak). Ancien fichier : `core/docker-compose.override.yml.avant-rotation` (0600, sur le HP). Piste d'hygiène : sortir ce secret du compose vers le `.env` racine.
- Prérequis inchangé avant toute capacité **Forge** sensible : à la reprise il n'y a pas de JWT et l'adaptateur Forge retombe sur son compte de service (voir fichier S246). Aucune capacité Forge n'est sensible aujourd'hui.
- Non utilisé en v1 : `forgejo.py` (client Forgejo lecture seule) n'est pas branché.
- Preuve live du repère de rollback (`via_rollback`) : couverte par 5 tests ; à constater en vrai au prochain rollback réel.
