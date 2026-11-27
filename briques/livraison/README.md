# livraison (port 6240)

Brique S246 : pilote Dokploy (VM 100) pour l'assistant. Lecture de l'état et des logs
des apps déployées, et trois actions gardées par approbation (redémarrer, déployer,
revenir en arrière).

- Santé : `GET /sante`
- Variables : voir `.env.example` (aucun secret dans le compose)
- Tests : `python3 -m pytest -q -p no:cacheprovider`

## Clés (à lire avant de déployer)

- `LIVRAISON_API_KEYS` (côté brique, jamais `API_KEYS`) : clé(s) acceptées.
  - Lectures (`/apps`, `/etat`, `/logs`) : vide = mode ouvert.
  - Actions (`/redemarrer`, `/deployer`, `/rollback`) : **fail-closed**. Vide ou absente ⇒
    `403 Route désactivée : configure LIVRAISON_API_KEYS.`, sans aucun appel à Dokploy.
- `LIVRAISON_KEY` (côté **Cœur**) : la clé que le Cœur envoie en `X-API-Key`
  (`orchestrateur.entetes_brique`). Doit valoir **l'une des valeurs** de `LIVRAISON_API_KEYS`.
- Piège : clé posée côté brique seule ⇒ l'assistant reçoit **401**. Le remède est de poser
  `LIVRAISON_KEY` dans l'environnement du Cœur, **jamais** de vider `LIVRAISON_API_KEYS`
  (cela fermerait les actions en 403 et ouvrirait les lectures à tout le LAN).

## Comportements à connaître

- Erreurs métier relayées à l'assistant (`"relayer_erreurs": true` sur les 6 capacités) :
  le `detail` court (≤ 300 caractères) arrive tel quel (« version ambiguë… », « retour arrière
  impossible… »).
- Délais : lectures 20 s, actions 60 s. Un délai dépassé **après** envoi d'une action
  renvoie **504** « l'action a peut-être été exécutée — vérifie avec livraison_etat avant de
  réessayer » (ne pas réapprouver à l'aveugle). « Injoignable » (502) = rien n'est parti.
- « En service » = le déploiement `done` le plus récent ; le rollback par défaut vise le
  `done` antérieur le plus récent portant un `rollbackId`.
- Logs : masqués sur le texte complet, puis réduits aux 20 000 derniers caractères.

## Non utilisé en v1

`forgejo.py` (client Forgejo lecture seule) et `FORGEJO_URL`/`FORGEJO_TOKEN` : codés et testés,
**non branchés** sur une route en v1.

## Données utilisateur (S248)

Export chiffré des données d'UN utilisateur d'une application à contrat (ex. Studio) :
`livraison_donnees_exporter` / `livraison_donnees_verifier` (`POST /contrats/{app}/exporter|verifier`).

- Variables dans `briques/livraison/.env` (0600) : `LIVRAISON_CHIFFREMENT_CLE` (chiffrement
  AES-GCM des paquets) et `STUDIO_SUPPORT_KEY` (même valeur que côté Studio).
- Registre des apps à contrat : `contrats.json`, à copier depuis `contrats.exemple.json` dans
  le volume `/data`.
- Rétention : 14 jours ; purge automatique toutes les heures, déclenchable à la main par
  `POST /contrats/purger`.
- Journal d'accès : `acces.jsonl` (qui a exporté/vérifié/purgé quoi, jamais le contenu).
- Exécuteur : redéployer `executeur.py` sur la VM 100 (nouvelles routes `/objets/`).
- Piège : changer `STUDIO_SUPPORT_KEY` OU `LIVRAISON_CHIFFREMENT_CLE` rend les paquets déjà
  stockés illisibles jusqu'à leur expiration (14 jours au plus) : la purge (`POST /contrats/purger`)
  ne retire que les paquets EXPIRÉS. Après une rotation, ré-exporter.
- Journaux d'accès uvicorn désactivés (`--no-access-log`) : le Cœur duplique les arguments des POST dans
  la query string, l'identité de l'utilisateur y serait écrite en clair.
- `livraison_donnees_verifier` ne déclare volontairement pas `fournit_preuve` (réservé à 3b).
