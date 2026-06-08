# Brique Persistance (`donnees`)

Magasin **CRUD générique multi-tenant** : remplace le `localStorage` des applications
générées par une **vraie persistance serveur** (condition pour livrer en entreprise,
plusieurs utilisateurs sur la même donnée).

- **Port** : 5500
- **Stockage** : SQLite (`/data/donnees.db`, volume Docker `donnees_data`)
- **Multi-tenant** : tout est rangé par `(app_id, entite_id)`. Une app = un `app_id`
  (celui du Générateur) ; une entité = un module métier (devis, clients…).
- **Identifiants serveur** : chaque enregistrement reçoit un `uuid` stable → édition et
  suppression fiables (l'ancien localStorage supprimait par position dans le tableau).
- **CORS ouvert** : les apps générées tournent depuis n'importe quelle origine.

## API

| Méthode | Route | Rôle |
|---|---|---|
| `GET`    | `/apps/{app}/entites/{entite}/enregistrements` | lister |
| `POST`   | `/apps/{app}/entites/{entite}/enregistrements` | créer (corps = objet JSON) |
| `PUT`    | `/apps/{app}/entites/{entite}/enregistrements/{id}` | modifier |
| `DELETE` | `/apps/{app}/entites/{entite}/enregistrements/{id}` | supprimer |
| `POST`   | `/apps/{app}/entites/{entite}/seed` | semer des exemples (idempotent : seulement si vide) |
| `GET`    | `/apps/{app}/resume` | compte par entité |
| `DELETE` | `/apps/{app}` | purge d'une app |
| `GET`    | `/sante` | santé |

Chaque enregistrement renvoyé est aplati : `{...champs métier, _id, _cree, _maj}`.

## Authentification (optionnelle, pilotée par l'environnement)

Par défaut la brique est **ouverte** (aucun changement pour le dev central, les apps
exportées, l'aperçu du Générateur). Dans un **bundle livré**, le packager active la
garde JWT — chaque route de données exige alors un jeton du Keycloak du bundle :

| Variable | Défaut | Rôle |
|---|---|---|
| `AUTH_ENABLED` | `false` | `true` ⇒ Bearer Keycloak exigé sur toutes les routes de données |
| `KEYCLOAK_URL` | — | URL **interne** du serveur d'identité (ex. `http://identite:8080`) |
| `KEYCLOAK_REALM` | — | realm du client (ex. `client-acme`) |
| `KEYCLOAK_AUDIENCE` | (vide) | vide ⇒ `verify_aud` désactivé (multi-tenant) |
| `JWKS_TTL` | `600` | durée de cache des clés publiques (s) |
| `CORS_ORIGINS` | `*` | origines autorisées, séparées par des virgules |

- Sans token ou token invalide → **401**. `/sante` reste **publique** (sondes).
- L'`iss` du jeton n'est pas contrôlé : seule la **signature** est validée contre les
  clés du realm → `KEYCLOAK_URL` peut viser le réseau Docker même si le navigateur a
  obtenu le jeton via `localhost`.
- Logique dans `auth.py` (self-contained : le bundle n'embarque pas le module partagé).

## Lancer

```bash
cd ~/Desktop/Workplace/briques/donnees && make up
```
