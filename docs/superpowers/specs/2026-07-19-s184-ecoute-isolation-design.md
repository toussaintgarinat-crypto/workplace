# S184 — Isolation par personne de la brique `ecoute` (mots-clés sur mesure)

Date : 2026-07-19 · Mémoire : [[sprint-s182-s183-multiutilisateur-espaces]]
Suite de [[sprint-s181-acces-distant-cercle-prive]] et S182/S183 (audit
`docs/rapport-s183-audit-isolation.md`). Réalise/généralise le motif « chacun son espace »
établi sur l'agenda (S182) pour la brique `ecoute` (port 5800).

## Constat (audit S183)

`briques/ecoute/` (mots-clés de réveil « comme Siri » + palier payant « nom de marque sur
mesure ») n'a **aucune authentification** sur aucune route : `/sante`, `/noms`, WS `/ecoute`,
`/paiement/etat`, `POST /commandes`, `GET /commandes`, `GET /commandes/{cid}`,
`POST /commandes/{cid}/payer`, `POST /paiement/webhook`, `POST /entrainement/traiter`. Sa table
`commandes` (`briques/ecoute/commandes.py:102`) n'a pas de colonne propriétaire. Cette brique
gère des paiements réels (Stripe one-off, `briques/ecoute/paiement.py`) : n'importe qui sur le
réseau peut aujourd'hui lister toutes les commandes, en créer, ou (en mode mock) marquer un
paiement comme payé, sans la moindre autorisation.

## Décisions de kickoff (confirmées par l'utilisateur le 2026-07-19)

1. **Isolation par personne** (motif agenda S182), pas seulement par tenant/clé API : chaque
   compte Keycloak ne voit et ne peut agir que sur SES propres commandes.
2. **Catalogue partagé, commandes privées** : une fois un nom de marque **livré** (modèle
   entraîné), il rejoint la liste sélectionnable de `/noms` et du WS `/ecoute` pour **tout le
   foyer** (comme aujourd'hui — bien partagé, même logique que la bibliothèque de voix clonées,
   cf. verdict "partagée à raison" de l'audit S183 sur `voix`). Seul l'historique de commande
   (qui a commandé, statut de paiement) devient privé par personne.

## Modèle de données

Ajout d'une colonne à la table `commandes` (`briques/ecoute/commandes.py`, méthode `init_db`) :

```sql
ALTER TABLE commandes ADD COLUMN proprietaire TEXT NOT NULL DEFAULT 'perso'
```

Migration = **alias**, motif identique à S182 : les commandes déjà en base (s'il y en a — cette
brique est `statut: a_tester` au manifest, pas encore utilisée en LIVE, donc risque de migration
nul en pratique) restent visibles sous `perso`, zéro rewrite de leur contenu.

`MagasinCommandes.creer(nom_marque, proprietaire="perso")` : nouveau paramètre optionnel avec
défaut `"perso"` — les tests existants (`test_commandes.py`, qui appellent `.creer(nom)` sans ce
paramètre) continuent de passer sans modification. Toutes les méthodes de lecture qui doivent
respecter l'isolation prennent un paramètre `proprietaire: str | None = None` : `None` = pas de
filtre (usage interne, ex. la file d'entraînement qui traite tout le monde), une valeur = filtre
`WHERE proprietaire = ?`.

## Transport de l'identité (motif S182, généralisé)

Aujourd'hui `core/outils_communs._entetes_brique` (`core/outils_communs.py:48-70`) ne forwarde
`X-User-Id` que pour la brique `"agenda"` (commentaire explicite : "les autres briques ignorent
cet en-tête"). Ce sprint généralise ce point d'extension à un **ensemble** de briques « cercle
privé », pas un seul nom en dur :

```python
BRIQUES_PAR_PERSONNE = {"agenda", "ecoute"}
...
if brique.lower() in BRIQUES_PAR_PERSONNE:
    entetes.update(contexte_tenant.entetes_agenda())  # même helper : {"X-User-Id": ...}
```

(Renommer/généraliser `contexte_tenant.entetes_agenda()` en un helper neutre type
`entetes_par_personne()` fait partie de ce sprint — même implémentation, nom qui ne mentionne
plus une seule brique.)

Côté `briques/ecoute/`, nouveau module `auth.py` (motif copié de
`briques/agenda/backend/auth.py`, branche S2S) :
- Env `ECOUTE_KEY` (optionnelle, comme partout : absente = brique en mode ouvert dev/démo).
- Si `X-API-Key` (ou `Authorization: Bearer`) == `ECOUTE_KEY` **et** `X-User-Id` présent →
  identité = ce `X-User-Id` (gage de confiance : seul le Cœur, qui détient `ECOUTE_KEY`, peut
  forwarder une identité).
- Sinon (mode ouvert, ou clé absente) → identité = `"perso"` (repli, comme l'agenda sans
  session).
- Une dépendance FastAPI distincte `service_key` (sans notion de personne) protège
  `/entrainement/traiter` : exige `ECOUTE_KEY` si configurée (401 sinon), sans lire `X-User-Id`
  — cette route traite la file pour tout le monde, ce n'est pas une action "au nom de X".

## Routes impactées

| Route | Dépendance ajoutée | Comportement |
|---|---|---|
| `GET /noms`, WS `/ecoute` | aucune (inchangé) | catalogue partagé, pas de filtre |
| `GET /paiement/etat` | aucune (inchangé) | info non sensible |
| `POST /paiement/webhook` | aucune (inchangé) | déjà protégé par signature Stripe (S21) |
| `POST /commandes` | `proprietaire = Depends(identite)` | commande créée sous ce propriétaire |
| `GET /commandes` | `proprietaire = Depends(identite)` | liste filtrée `WHERE proprietaire = ?` |
| `GET /commandes/{cid}` | `proprietaire = Depends(identite)` | 404 (pas 403) si la commande appartient à un autre propriétaire — motif mail/restaurant : ne pas révéler l'existence |
| `POST /commandes/{cid}/payer` | `proprietaire = Depends(identite)` | 404 si pas le propriétaire ; sinon comportement inchangé |
| `POST /entrainement/traiter` | `Depends(service_key)` | inchangé fonctionnellement, juste gardé |

## Cas limite : doublon de commande entre deux personnes

Aujourd'hui, `MagasinCommandes._en_cours_pour_marque(modele)` (`commandes.py`) cherche une
commande non terminale pour ce slug **tous propriétaires confondus** et la renvoie telle
quelle — avec l'isolation, ça fuiterait la commande privée d'un autre propriétaire via l'appel
`POST /commandes` lui-même. Deux changements dans `commandes.py` :

1. `_en_cours_pour_marque(modele, proprietaire)` est maintenant scopée aux deux colonnes
   (`WHERE modele = ? AND proprietaire = ? AND statut NOT IN ('livree','echec')`) : chacun peut
   avoir sa propre commande en cours pour la même marque, sans voir celle des autres.
2. Avant de créer une nouvelle commande, si le modèle est déjà **livré** (peu importe qui l'a
   payé — `livrees()` reste une requête globale, cohérente avec "catalogue partagé"), `creer()`
   court-circuite : renvoie un statut `"deja_disponible"` (pas de nouvelle commande, pas de
   paiement) plutôt que de refaire payer un modèle déjà entraîné et public.

## Tests

- `briques/ecoute/test_isolation.py` (nouveau, motif `briques/mail/test_isolation.py`) : deux
  identités (`X-User-Id` A et B sous `ECOUTE_KEY`) → commande de A invisible pour B (`GET
  /commandes/{cid}` → 404, absente de `GET /commandes` de B, `POST /commandes/{cid}/payer` par B
  → 404) ; `/noms` reste identique pour A et B (catalogue partagé) ; sans `ECOUTE_KEY` configurée,
  tout retombe sur `"perso"` (mode ouvert, rétrocompatible).
- `briques/ecoute/test_commandes.py` : ajout de tests pour `_en_cours_pour_marque` scopée par
  propriétaire et le court-circuit "déjà disponible" — tests existants inchangés (défaut
  `proprietaire="perso"` préserve leur comportement).
- `core/test_contexte_tenant.py` / `core/test_outils_dynamiques.py` : `_entetes_brique("ecoute")`
  forwarde `X-User-Id` comme `_entetes_brique("agenda")` (même assertion, brique différente).
- `make test-core` et la suite `briques/ecoute/` restent au vert.

## Hors périmètre

- Pas d'UI dédiée dans le dashboard : `/commandes*` est piloté par l'assistant via les capacités
  déjà déclarées au manifest (`ecoute_commandes`, etc.), pas de front à modifier.
- Pas de migration de données réelles : la brique est `statut: a_tester` au manifest, jamais
  déployée en LIVE avec de vraies commandes à ce jour.
- Pas de changement au modèle Stripe/webhook (déjà correct, motif S21, signature vérifiée).
- Pas de déploiement LIVE HP dans ce sprint (régime preuve Docker différée, cf.
  [[regime-preuve-docker-differe]]) — code + tests uniquement.

## Risques

- Généraliser `_entetes_brique`/`entetes_agenda()` touche du code partagé avec l'agenda (S182) —
  mitigé par les tests existants de `core/test_contexte_tenant.py` qui doivent rester verts sans
  modification de leurs assertions sur `"agenda"`.
- Le court-circuit "déjà disponible" change une réponse d'API existante (`POST /commandes`) —
  mitigé par le fait que la brique n'est pas encore en usage LIVE (pas de client existant à
  casser) et que c'est strictement une amélioration (évite un double paiement).
