# Guide : le contrat de données utilisateur (S248)

Spec : [S248](sprints/S248-contrat-app-reset-par-utilisateur.md). Implémentation de référence :
le Studio (`briques/studio/support.py`, routes `/support/*` de `briques/studio/main.py`).
Bibliothèque partagée : `shared/contrat_donnees.py`. Harnais : `shared/conformite_contrat.py`.

## 1. À quoi ça sert, et quand ne PAS l'implémenter

Le contrat permet à l'assistant de mettre de côté, remettre à zéro puis restituer les données
d'**un seul utilisateur** d'une app, sans toucher aux autres.

À ne **pas** implémenter si les données de l'app ne sont pas isolées par utilisateur (une base
commune, pas de propriétaire sur chaque objet) : on ne sait alors pas découper « les données de
Claire ». Une telle app reste limitée à la portée « app entière » de S247 (sauvegarde vérifiée,
reset bleu/vert), et l'assistant le dit. Ne pas déclarer le bloc plutôt que de le déclarer à moitié.

## 2. Le bloc manifeste

Dans `manifest.json` de la brique :

```json
"contrat_donnees": {
  "version_schema": "1",
  "exporter":      {"methode": "POST", "chemin": "/support/exporter"},
  "reinitialiser": {"methode": "POST", "chemin": "/support/reinitialiser"},
  "importer":      {"methode": "POST", "chemin": "/support/importer"}
}
```

`version_schema` est un entier écrit **en chaîne** (`"1"`, pas `1`). On l'incrémente à chaque
changement de format des données exportées (et on ajoute alors la migration correspondante, voir
section 6). `shared/contrat_donnees.valider_bloc_contrat(bloc)` renvoie la liste des erreurs :
chaîne numérique ASCII, trois actions, méthode `POST`, chemin commençant par `/support/` et sans
segment `..`. Un test de la brique doit l'appeler sur son propre manifeste.

## 3. Les routes

Toutes en `POST`, toutes protégées par `X-Support-Key` (section 4). L'identité visée est
**explicite** (`utilisateur`) ; le cloisonnement ne repose pas sur `X-User-Id`.

| Chemin | Entrée | Réponse | Refus |
|---|---|---|---|
| `/support/exporter` | JSON `{"utilisateur": "..."}` | 200, corps = paquet `application/gzip` ; en-têtes `X-Empreinte` (empreinte des données) et `X-Comptages` (JSON, nombre d'objets par type) | 422 si `utilisateur` vide |
| `/support/verifier` | query `?utilisateur=`, corps = octets du paquet | 200 `{"ok", "comptages", "empreinte", "version_schema"}` ; rejoue l'import dans un dossier jetable, ré-exporte, compare l'empreinte ; n'écrit jamais dans le volume réel | 422 paquet invalide/refusé |
| `/support/reinitialiser` | JSON `{"utilisateur", "empreinte"}` | 200 `{"ok": true, "supprimes": {comptages}}` | 409 `empreinte` ; 422 sinon |
| `/support/importer` | query `?utilisateur=`, corps = octets du paquet | 200 `{"ok": true, "comptages": {...}}` | 409 `conflit` ; 422 sinon |

Codes communs : **401** clé de support invalide ou absente de la requête, **503** fonction
désactivée (variable d'environnement non définie), **409** pour les raisons `empreinte` et
`conflit`, **422** pour toutes les autres raisons de refus. Le `detail` d'une erreur ne porte que
la **raison** (jamais de donnée de l'utilisateur) : `signature`, `somme_controle`, `format`, `app`,
`utilisateur`, `version_future`, `illisible`, `trop_gros` (paquet, `PaquetInvalide`) ; `empreinte`,
`conflit`, `objet_etranger`, `incoherent`, `migration`, `verification`, `format` (app, `Refus`).

Le paquet est une archive tar.gz de deux membres : `meta.json` (app, utilisateur, `version_schema`,
date, comptages, empreinte, signature HMAC-SHA256) et `donnees.json` (JSON canonique). `lire_paquet`
vérifie dans cet ordre : lisibilité, signature, somme de contrôle, app, utilisateur, version. Un
paquet de version supérieure à celle de l'app est refusé (`version_future`) ; un paquet plus ancien
passe par les migrations.

### Sémantique de l'export, du reset et de l'import

- **Export** : ne renvoie que les objets de l'utilisateur, triés, en JSON canonique (même état =
  même empreinte). Les objets sont **clés sur le nom de fichier sans `.json`** : seul le fichier
  réellement lu fait foi, jamais le champ `id` qu'il contient (un objet dont l'id diffère du nom,
  ou dont l'identifiant n'est pas sûr, n'est ni exporté ni supprimé).
- **Reset** : exige l'**empreinte exacte** des données courantes (celle du paquet exporté juste
  avant) ; sinon refus 409 `empreinte`, rien n'est supprimé. Il ne supprime **que ce que l'export
  renvoie** : jamais un fichier déduit autrement. Il renvoie les comptages supprimés.
- **Import** : **valide tout avant d'écrire**. Refus si : clés ou types inattendus, identifiant
  non sûr, doublon, objet appartenant à un autre utilisateur (`objet_etranger`), cible existante
  appartenant à un autre utilisateur ou illisible (`conflit`), journal sans profil ou pont sans
  série (`incoherent`), plus d'un compte. Un objet déjà présent **appartenant au même
  utilisateur** est écrasé (écriture atomique via fichier temporaire + `os.replace`).

## 4. Authentification

Clé **dédiée**, propre à l'app : `STUDIO_SUPPORT_KEY` pour le Studio, `<APP>_SUPPORT_KEY` pour une
autre, envoyée dans le header `X-Support-Key`. Elle est lue fraîche à chaque requête.

- Variable absente ou vide : **503**, jamais de repli ouvert.
- Clé fausse ou manquante : **401** (comparaison à temps constant).
- **Ne jamais réutiliser** la clé de service du Cœur ni `API_KEYS` : ni `STUDIO_KEY` ni `API_KEYS`
  n'ouvrent ces routes.
- La même clé **signe** les paquets (HMAC). Conséquence : **changer la clé rend illisibles les
  paquets exportés avant** (refus `signature`). Avant une rotation, vider ou ré-exporter les
  paquets conservés.

## 5. Recette pour brancher une nouvelle app

1. **Copier la bibliothèque** : ajouter la brique à `CONTRAT_BRIQUES` dans `outils/sync_socle.sh`
   (aujourd'hui `CONTRAT_BRIQUES=(studio)`) puis lancer le script ; chaque brique est une image
   autonome, `shared/contrat_donnees.py` y est copié en `contrat_donnees.py`. Un test de la brique
   vérifie que la copie est à jour (modèle : `test_copie_de_la_bibliotheque_a_jour`).
2. **Module de logique pure `support.py`** : `exporter`, `reinitialiser`, `importer`, `migrer`,
   `verifier`, tous **paramétrés par une racine** (défaut : le volume réel). Sans FastAPI : cela
   permet à `verifier` de rejouer l'import dans un dossier jetable.
3. **Un seul filtre d'appartenance** : une fonction unique (`_appartient(objet, utilisateur,
   serie)` dans le Studio) dit à qui est un objet ; export, reset et import l'utilisent tous. C'est
   le point que le test de mutation neutralise.
4. **Exposer les routes** de la section 3 avec la dépendance de clé dédiée, une cible explicite et
   des erreurs qui ne portent que la raison.
5. **Brancher le harnais** `shared/conformite_contrat.py` : écrire un adaptateur avec
   `peupler(u)`, `exporter(u)`, `etat(u)` (comptages + empreinte, lus via les en-têtes de l'export),
   `reinitialiser(u, empreinte)` et `importer(u, octets)` qui lèvent `Refus` sur tout code 4xx.
   Modèle : `AdaptateurStudio` dans `briques/studio/test_support_routes.py`. Ajouter le **test de
   mutation** : neutraliser le filtre d'appartenance (`monkeypatch` sur `_appartient`) doit faire
   échouer `verifier_conformite`, et un second test prouve que la mutation change réellement
   l'export (sinon l'échec pourrait être accidentel).

## 6. Règles non négociables

- **Export déterministe** : tri stable + JSON canonique ; un même état donne la même empreinte.
- **Reset exige l'empreinte exacte** des données courantes, et ne supprime que ce que l'export
  renvoie.
- **Import valide tout avant d'écrire** ; un refus ne modifie rien, pour personne.
- **Identifiants validés par regex** (`^[A-Za-z0-9_-]{1,64}$` côté Studio) avant d'entrer dans un
  chemin ; l'identité de l'utilisateur n'est jamais utilisée telle quelle dans un chemin (le
  compte du Studio est nommé par un hachage `sha256`).
- **Messages d'erreur sans donnée perso** : la raison seule.
- **Migrations par crochets** `{version_source: fonction}` (`MIGRATIONS` dans `support.py`) :
  chaque fonction transforme les objets de la version `v` vers `v+1` ; `migrer` les enchaîne et
  refuse (`migration`) s'il en manque une. L'import et la vérification passent par `migrer`.
- **L'assistant ne lit jamais `donnees.json`** : il ne voit que `meta` (comptages, version,
  empreinte) et les en-têtes.

## 7. Limites connues

- **Médias hors paquet** : les images et l'audio des séries vivent dans d'autres briques ; le
  paquet n'en contient que les références. Restaurer un paquet ne restaure pas les fichiers
  médias.
- **Pas de retour arrière** si une écriture échoue en cours d'import (disque plein) : les objets
  déjà écrits restent. La validation préalable écarte les refus logiques, pas les pannes d'E/S.
- **Pas de verrou** entre la vérification d'empreinte du reset et ses suppressions : une écriture
  de l'utilisateur dans cette fenêtre est perdue (l'empreinte détecte un changement avant le
  reset, pas pendant).
- **Corps de requête non plafonné côté HTTP** : la bibliothèque borne le paquet (64 Mio et taille
  de chaque membre avant décompression), mais le corps est lu en entier avant ; un plafond
  `Content-Length` (413) reste à ajouter.
- **Lacunes mineures consignées pour un suivi** (revues des tâches 1, 3 et 4) : identifiant
  `"abc\n"` accepté par la regex (`re.match` + `$` au lieu de `fullmatch`) ; un profil dont l'id
  finit par `-journal` est exclu de l'export / peut entrer en collision avec un journal ; des
  `profil_id`/`serie_id` non hachables donnent une `TypeError` plutôt qu'un `Refus` ; exceptions
  non-`Refus` (hook de migration, `OSError`) remontées en 500 ; handlers `async` avec E/S bloquantes
  et sans verrou par utilisateur ; pas de test positif « clé de support correcte alors que
  `STUDIO_KEY`/`API_KEYS` sont configurées » ; `CORS_ORIGINS` à resserrer.
- **Hors parties 1+2 (partie 3)** : chiffrement au repos, stockage SeaweedFS, rétention de 14
  jours, journal d'accès, outils de l'assistant, validation du bloc par le Cœur, preuve LIVE.
