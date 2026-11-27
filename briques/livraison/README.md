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
  AES-GCM des paquets) et `STUDIO_SUPPORT_KEY` (même valeur que côté Studio). `LIVRAISON_API_KEYS`,
  `EXECUTEUR_KEY`, `LIVRAISON_CHIFFREMENT_CLE` et `STUDIO_SUPPORT_KEY` vont dans
  `briques/livraison/.env` (0600), JAMAIS dans le `.env` racine : celui-ci est lu par ~40 briques, et
  n'importe laquelle pourrait alors appeler directement les routes d'écriture et contourner la
  porte d'approbation.
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
- `livraison_donnees_verifier` (`action: true`, `sensibilite: reversible`) exige une approbation humaine (il stocke une copie chiffrée 14 jours) et déclare `fournit_preuve: paquet_verifie`.

### Remise à zéro et restitution (S248 3b)

Flux : [approbation `reversible`] `livraison_donnees_verifier` -> [approbation Telegram, niveau `donnees`]
`livraison_donnees_reinitialiser` -> `livraison_donnees_restituer` (approbation `donnees`).
Routes : `POST /contrats/{app}/exporter|verifier|reinitialiser|restituer`, `POST /contrats/purger`.

- **Preuve `paquet_verifie`**, liée à (app, utilisateur visé) : la clé de preuve du Cœur est
  `app|sha256(utilisateur)[:16]` (`core/approbations.py::cle_preuve`, `PREUVES_PAR_CIBLE`). Une
  vérification pour un utilisateur n'autorise JAMAIS la remise à zéro d'un autre. L'identité doit
  être identique au caractère près.
- **Fraîcheur** : 6 h (`PREUVE_TTL_S`). **Un paquet sert UN reset** : il est marqué consommé dès que
  l'effacement a eu lieu ou est possible ; un second reset exige une nouvelle vérification.
- **Budget global** : 540 s par orchestration (`DELAI_GLOBAL_DONNEES_S`) ; le Cœur attend 600 s
  (`TIMEOUT_DONNEES`), donc jamais de coupure côté Cœur avant la brique. Quand les 540 s expirent,
  la brique cesse d'attendre mais une requête déjà envoyée au Studio peut encore tourner, et le
  verrou est relâché : vérifier l'état (`livraison_donnees_verifier`) avant tout nouvel essai.
- **Avant l'effacement**, la brique relit et déchiffre le paquet, ré-exporte et compare l'empreinte
  (écart : 409 « les données ont changé »). Après : contrôle final, tous les comptages doivent être à
  zéro (sinon 409 « résultat incomplet », le paquet reste restituable).
- **Restitution implicite** (sans `paquet_id`) : uniquement le paquet unique CONSOMMÉ par une remise à
  zéro et pas encore restitué, et seulement si l'espace de l'utilisateur est vide (tous comptages à 0,
  mêmes clés) ou identique au paquet. 0 candidat : 404 ; 2 candidats ou plus : 409 qui liste les
  identifiants ; espace non vide : 409. **Avec `paquet_id`** : choix délibéré, c'est une
  FUSION (le Studio écrit les objets par identifiant et ne supprime rien : ceux du paquet remplacent
  les objets de même identifiant, les plus récents sont conservés). Succès si l'export final contient
  au moins les comptages du paquet (réponse `mode: "fusion"`) ; l'implicite exige l'empreinte exacte
  (`mode: "exacte"`). Le paquet doit être vérifié, non expiré, de la même app et du même utilisateur.
- **504 ambigu** (l'application n'a pas répondu, ou budget global dépassé après un appel d'effet) :
  l'effacement a peut-être eu lieu. Ne PAS réessayer à l'aveugle : lancer `livraison_donnees_verifier`
  pour lire l'état. L'identifiant du paquet est dans le message ; il reste restituable avec
  `livraison_donnees_restituer` (`paquet_id`). Sans paquet choisi, le 504 dit « rien n'a été modifié ».
- **Journaux d'accès uvicorn désactivés** (`--no-access-log`) : le Cœur duplique les arguments des POST
  dans la query string, l'identité y serait écrite en clair. `acces.jsonl` ne porte que `h`.

### Procédure de reprise : `paquets.json` corrompu

Symptôme : les écritures (export, vérification, reset, restitution) répondent **503 « registre des
paquets illisible »** ; les lectures voient un registre vide ; la purge, aveugle, ne retire rien.

1. Ne rien supprimer. Arrêter ou isoler les opérations de données.
2. Inspecter `/data/paquets.json` (volume `livraison_data`) ; si le contenu est réparable (JSON
   tronqué), le corriger à la main, sinon le **déplacer de côté** (`mv paquets.json paquets.json.corrompu`).
   Absent = registre vide, les écritures reprennent.
3. Les objets S3 `contrat/<app>/<h>/<id>.bin` des paquets perdus deviennent **orphelins** : la purge
   suit le registre et ne les voit plus. Les lister (via l'exécuteur ou SeaweedFS) et les supprimer
   à la main ; ils sont chiffrés mais gardent le nom de l'app et `h`.
4. Les anciennes vérifications ne sont plus reconnues : refaire `livraison_donnees_verifier` avant
   tout reset. Un paquet perdu ne peut plus être restitué par `paquet_id` (registre) ; l'objet reste
   lisible seulement avec la clé et son nom d'objet (nom = contexte de chiffrement).
