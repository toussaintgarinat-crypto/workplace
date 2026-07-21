# Design — S193 : prospection géo-scrapée + intégration mémoire pour la famille veille

**Date** : 2026-07-21
**Statut** : validé, prêt pour plan d'implémentation

## Contexte

3e sous-brique de la famille `veille` (🔭), après `geo` (retaggé, S161) et `veille-info`
(RSS→résumé+audio, S193 était noté à l'origine dans
`docs/superpowers/plans/2026-07-21-veille-famille-geo-retag.md` comme « prospection
géo-scrapée » — au-delà du suivi Sirene actuel, une vraie base de prospects exploitable en
démarchage). Élargi en cours de brainstorming pour couvrir aussi l'intégration de la brique
`memoire` (RAG déjà existant, jamais utilisé par la famille veille) à `veille-info` en même
temps.

Clarifications actées avec l'utilisateur :
- **Le périmètre réel de S193**, une fois le code de `geo` inspecté : l'API Sirene qu'il
  utilise (`recherche-entreprises.api.gouv.fr`) énumère déjà TOUTES les entreprises actives
  d'une zone×NAF (pas seulement les créations récentes) — élargir la source n'était donc pas
  le vrai manque. Les deux besoins réels : **orchestrer** des campagnes de prospection
  automatisées (aujourd'hui, tout le pipeline `geo_prospecter_lot` → `forge_crm_importer_lot`
  → `mail_demarchage_preparer` exige un déclenchement manuel/vocal) et **enrichir plus
  profondément** chaque prospect (dirigeants, effectifs, réseaux sociaux).
- **Avis clients (Google/tiers) exclus du périmètre** : ça viendrait d'une plateforme tierce,
  pas de ce que l'entreprise publie elle-même — incohérent avec le principe déjà posé dans
  `briques/geo/enrichissement.py` (« uniquement ce que l'entité affiche elle-même, jamais
  d'annuaires tiers »).
- **memoire/RAG couvre S193 ET veille-info ensemble**, dans un **espace `memoire` dédié
  "Veille"** (pas un simple wing dans l'espace solution existant) — séparation plus forte,
  un wing par sous-brique à l'intérieur (`veille-info`, `veille-prospection`).
- **Cet espace "Veille" doit être isolé par personne**, pas partagé par le foyer — ce que le
  code actuel de `memoire` ne permet pas (seul le mot-clé `perso` déclenche l'isolation par
  personne ; un espace custom nommé est toujours partagé, compte de service). Une extension
  ciblée de `memoire` est donc dans le périmètre de ce spec (voir plus bas), vérifiée
  rétrocompatible avec tous les appelants actuels.

## État constaté du code (vérifié, pas supposé)

- `briques/geo/fournisseurs.py` (`RechercheEntreprises.entreprises_recentes`) : énumère déjà
  tous les établissements ACTIFS d'une zone (bbox ou communes) × NAF, sans filtre de date côté
  API — la notion de « nouveauté » vient uniquement de l'upsert par SIRET côté `geo`, pas d'une
  limite de la donnée source.
- `briques/geo/main.py:220-263` (`POST /prospection/enrichir-lot`) : prend `{bbox, type?, naf?,
  limite?, force?}` — **PAS de `zone_id`**, donc ne peut pas cibler une zone définie par
  communes (`ZoneEntree.communes`, sans bbox). Plafond `GEO_ENRICHIR_LOT_MAX` (défaut 50).
- `briques/geo/domaine.py:140-176` (`normaliser_entreprise`) : construit `metadata` depuis le
  payload brut `recherche-entreprises.api.gouv.fr` mais n'extrait que `nom/naf/adresse/
  commune/siren` — le payload brut (`brute`, avant troncature) contient aussi `dirigeants`
  (liste nom/prénom/qualité) et une tranche d'effectifs (`complements.tranche_effectif_salarie`
  côté unité légale, ou `tranche_effectif_salarie` côté établissement) — **jamais extraits**,
  aucun appel réseau supplémentaire nécessaire pour les récupérer.
- `briques/geo/enrichissement.py::enrichir` : appelle `recherche` (`/rechercher` puis
  `/lire-page`) sur le site officiel, extrait emails/téléphones du texte. `/lire-page` renvoie
  aussi `liens` (déjà lu par `trouver_lien_contact`) — les liens vers des domaines sociaux
  (facebook.com, instagram.com, linkedin.com, x.com/twitter.com, tiktok.com) trouvés SUR le
  site officiel sont, par construction, publiés par l'entreprise elle-même : cohérent avec le
  principe existant, contrairement aux avis tiers.
- `briques/forge/main.py:629` (`POST /crm/import-lot`) : `{prospects: [...], statut?}`,
  dé-doublonné par email/nom d'entreprise, réutilisable tel quel, sans changement.
- `briques/memoire/main.py:205-221` (`_resoudre_espace`) : seul le mot-clé `perso` déclenche
  une isolation par personne (espace `Perso-{utilisateur}`, jeton personnel). Tout espace
  custom (`_normaliser_espace` renvoie la valeur brute) est toujours résolu via
  `_espace_id(client, nom)` — **partagé, compte de service**, quel que soit `utilisateur`.
- `briques/memoire/main.py:233-242` (`_identite_service`) : `utilisateur` vient du header
  `X-User-Id` (gagé par `MEMOIRE_KEY` si définie), repli `UTILISATEUR_DEFAUT = "perso"` sinon —
  motif identique à `mail`/`veille-info` (S185).
- **Vérifié qu'aucun appelant actuel d'un espace custom ne transmet `X-User-Id`** : Forge
  (`memory_palace.py`, espaces `forge-org-{id}`) et la route `transcription/main.py:232`
  (`espace=body.espace`) n'envoient jamais ce header — l'extension ci-dessous ne change donc
  RIEN à leur comportement (ils resteront sur `utilisateur == UTILISATEUR_DEFAUT`, branche
  inchangée).
- `core/outils_communs.py:51` (`BRIQUES_PAR_PERSONNE`) : `memoire` y est déjà, mais ça ne
  couvre que les appels **Cœur → memoire**. Un appel **brique → memoire** (ex. `veille-info`
  ou la nouvelle `veille-prospection` poussant un résumé) doit lui-même transmettre
  `X-User-Id` — non couvert par ce mécanisme, à faire explicitement dans le code de chaque
  brique appelante (comme `mail`/`veille-info` le font déjà pour leurs propres routes).
- Manifest `memoire` (capacités assistant) : `memoire_rappeler`/`memoire_lister_souvenirs` ont
  `espace: enum[solution, perso]` — sans ajout, l'assistant ne pourrait jamais demander
  `espace="veille"`, la donnée serait stockée mais inatteignable en conversation.

## Architecture

### 1. Extension `memoire` — espace custom isolable par personne

Généraliser `_resoudre_espace` :

```python
async def _resoudre_espace(client, espace_brut, utilisateur):
    if (espace_brut or "").strip().lower() == "perso":
        ... inchangé ...
    nom = _normaliser_espace(espace_brut)
    if nom is not None and utilisateur != UTILISATEUR_DEFAUT:
        jeton_personne = await _token_personne(client, utilisateur)
        return (await _espace_id_personne(client, jeton_personne, utilisateur,
                                          f"{nom}-{utilisateur}"), jeton_personne)
    return await _espace_id(client, nom), await _token(client)
```

- `nom is not None` exclut `"solution"`/`None` (l'espace partagé « Workplace » ne devient
  JAMAIS personnel, même avec un `X-User-Id` réel — comportement Forge/dashboard inchangé).
- `utilisateur != UTILISATEUR_DEFAUT` exclut le mode mono-user/service (aucun `X-User-Id`
  transmis) — reste alors partagé, comme aujourd'hui.
- Un espace nommé `"Veille"` appelé avec un vrai `X-User-Id` devient donc `Veille-{utilisateur}`,
  isolé (jeton personnel), sans toucher au cas `"perso"` ni aux espaces custom déjà en
  production (Forge, transcription) qui ne transmettent jamais ce header.

Manifest `memoire` : ajouter `"veille"` à l'énum `espace` de `memoire_rappeler` et
`memoire_lister_souvenirs` (description mise à jour : « veille = résumés de la famille de
briques veille, isolé par personne »).

### 2. Extensions `geo`

- `ProspecterLotEntree` (ou nouvel endpoint `POST /prospection/enrichir-zone/{zone_id}`) :
  accepte un `zone_id`, résout la zone stockée (bbox déjà présent OU dérivé des `communes` via
  la même logique que l'ingestion horloge existante), puis réutilise
  `stockage.chercher_bbox`/`chercher_communes` tel quel. Décision d'implémentation (bbox
  dérivé vs. requête directe par communes) laissée au plan — le contrat externe est : « donne
  un `zone_id`, reçois les mêmes prospects qu'avec un bbox ».
- `domaine.normaliser_entreprise` : ajoute `metadata["dirigeants"]` (liste `{nom, prenom,
  qualite}`, tronquée à un nombre raisonnable, ex. 5) et `metadata["effectifs"]` (tranche
  brute Sirene, ex. `"10 à 19 salariés"`) depuis le payload déjà reçu — zéro appel réseau
  supplémentaire.
- `enrichissement.py::enrichir` : après lecture de la page officielle, extrait les liens dont
  le domaine matche une liste `DOMAINES_SOCIAUX` (facebook.com, instagram.com, linkedin.com,
  x.com, twitter.com, tiktok.com) parmi les `liens` déjà renvoyés par `/lire-page` — stocké
  dans `rapport["reseaux_sociaux"]` (liste d'URLs), puis dans `metadata["reseaux_sociaux"]`
  côté objet enrichi (même mécanique que `email`/`telephone` aujourd'hui).
- `_prospect_crm` : expose `dirigeants`, `effectifs`, `reseaux_sociaux` dans la vue prospect
  déjà renvoyée par `/prospection/enrichir-lot` (et le nouvel endpoint zone_id).

### 3. Nouvelle brique `veille-prospection` (port 6140, famille `veille`)

Sur le modèle exact de `veille-info` (isolation, cadence horloge, tests, manifest) :

- **Modèle** : `campagnes(id, user_id, zone_id, actif, derniere_execution, created_at)` —
  référence une zone `geo` EXISTANTE par id (pas de duplication de la définition de zone :
  l'utilisateur crée sa zone dans `geo` une fois, l'active en campagne ici).
- `POST /campagnes` (créer, `{zone_id}`), `GET /campagnes` (lister les siennes), `DELETE
  /campagnes/{id}` (désactiver) — isolation par personne, motif exact `tenant_actuel` de
  `veille-info` (`X-User-Id` → `f"perso:{x_user_id or 'perso'}"`).
- `POST /campagnes/executer` (tâche horloge quotidienne, `tolere_echec: true`, `entete_token_
  env: VEILLE_PROSPECTION_KEY`, motif exact `digest-quotidien` de `veille-info`) : pour chaque
  personne ayant au moins une campagne active,
  1. appelle `geo` (`/prospection/enrichir-zone/{zone_id}` ou équivalent, clé `GEO_KEY` si
     définie, `X-User-Id` transmis) → liste de prospects enrichis ;
  2. si non vide, appelle `forge` (`/crm/import-lot`, clé `FORGE_KEY` si définie, motif
     `_resoudre_pole_crm` existant, inchangé — pas de propagation d'identité personne, connu et
     documenté comme limite pré-existante S169/170) ;
  3. pousse un résumé lisible de l'exécution vers `memoire` (`POST /retenir`, `espace="veille"`,
     `wing="veille-prospection"`, `X-User-Id` transmis pour l'isolation personnelle, contenu =
     zone + nombre de prospects trouvés/nouveaux/déjà connus + date) — **best-effort, jamais
     bloquant** (même filet try/except que le reste du pipeline, cf. leçon S189/audio : tout ce
     qui suit un succès reste dans le même filet) ;
  4. journalise un décompte honnête par campagne (`trouves`, `nouveaux_crm`, `erreur`) dans une
     table `executions(campagne_id, date, trouves, nouveaux_crm, erreur, created_at)`.
- Isolation : ajouter `veille-prospection` à `BRIQUES_PAR_PERSONNE`
  (`core/outils_communs.py`), motif exact `veille-info` (déjà couvre le piège tiret→underscore
  découvert lors du déploiement de `veille-info`, corrigé de façon générique — rien à refaire
  ici).
- Capacités assistant (manifest) : `veille_prospection_campagnes_lister` (lecture),
  `veille_prospection_campagne_creer`/`_supprimer` (action), niveau 1 comme `veille_info_
  source_ajouter`.

### 4. Retrofit `veille-info`

Dans `digest.py::_traiter_utilisateur`, juste après l'insertion du digest (et de l'audio,
déjà dans le même filet) : appel `POST {MEMOIRE_URL}/retenir` avec `espace="veille"`,
`wing="veille-info"`, `X-User-Id: user_id` (dérivé du même `user_id` que le reste de la
fonction), contenu = texte du résumé, titre = date du digest. Best-effort, dans le filet
`_traiter_utilisateur_sans_planter` déjà en place — un échec ici ne doit ni bloquer le digest
texte/audio déjà créés, ni empêcher le traitement des autres personnes.

## Modèle de données

`veille-prospection` (nouvelle base SQLite, motif `veille-info/stockage.py`) :

```sql
CREATE TABLE IF NOT EXISTS campagnes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    zone_id TEXT NOT NULL,
    actif INTEGER NOT NULL DEFAULT 1,
    derniere_execution TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_campagnes_user ON campagnes(user_id);

CREATE TABLE IF NOT EXISTS executions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campagne_id INTEGER NOT NULL REFERENCES campagnes(id),
    date TEXT NOT NULL,
    trouves INTEGER NOT NULL DEFAULT 0,
    deja_connus INTEGER NOT NULL DEFAULT 0,
    nouveaux_crm INTEGER NOT NULL DEFAULT 0,
    erreur TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_executions_campagne ON executions(campagne_id);
```

`geo` : aucune nouvelle table, `metadata` (JSON déjà libre) accueille les 3 nouvelles clés.

`memoire` : aucune nouvelle table (le backend Memory gère déjà nœuds/espaces).

## Erreurs / dégradation

- `geo` injoignable ou zone introuvable lors d'une exécution de campagne → `executions.erreur`
  rempli, `nouveaux_crm=0`, la campagne reste active pour le lendemain (pas de désactivation
  automatique).
- `forge` injoignable après des prospects trouvés → même traitement, `trouves` renseigné mais
  `nouveaux_crm=0` et `erreur` renseigné — les prospects ne sont PAS perdus côté `geo` (déjà
  persistés là par l'enrichissement), rejouable au prochain passage.
- `memoire` injoignable → n'affecte JAMAIS le CRM ni le journal `executions` (étape la plus en
  aval, purement best-effort, jamais dans le chemin critique).
- Toute étape après un succès (insertion `executions`, écriture SQLite) reste dans le MÊME
  `try/except` que ce qui précède — application directe de la leçon S189/S190 (3 bugs de cette
  catégorie déjà trouvés dans `veille-info`, à ne pas réintroduire ici).
- `memoire` : `_resoudre_espace` généralisé — si `_token_personne` échoue (backend Memory
  indisponible), l'appelant (`retenir`) lève déjà une `HTTPException(502, ...)` existante,
  inchangée ; les appelants best-effort (`veille-info`, `veille-prospection`) l'attrapent et
  continuent sans bloquer.

## Tests

- `memoire` : nouveaux tests `_resoudre_espace` — espace custom + `X-User-Id` réel → espace
  `{nom}-{utilisateur}` isolé, jeton personnel ; espace custom + `utilisateur` défaut → inchangé
  (partagé, compte de service) ; `"perso"` + `X-User-Id` réel → comportement EXISTANT non
  modifié ; `"solution"`/`None` + `X-User-Id` réel → reste partagé (jamais personnel).
- `geo` : tests `domaine.normaliser_entreprise` (dirigeants/effectifs extraits du payload brut
  quand présents, absents proprement sinon) ; test `enrichissement.enrichir` (réseaux sociaux
  extraits des liens de la page officielle, domaines non-sociaux ignorés) ; test du nouvel
  endpoint/paramètre `zone_id` sur une zone à communes (pas de bbox).
- `veille-prospection` : suite complète motif `veille-info` — CRUD campagnes isolé par
  personne, `POST /campagnes/executer` (mock `geo`/`forge`/`memoire`, aucun réseau réel) :
  décompte honnête, tolérance de panne à chaque étage (geo/forge/memoire injoignables un par
  un), idempotence (ré-exécution le même jour ne double pas les leads CRM — déjà garanti côté
  `forge` par la dé-duplication existante).
- `veille-info` : extension `test_digest.py` — appel `memoire` mocké, succès/injoignable, dans
  le même filet que les tests audio existants.

## Hors périmètre (explicitement)

- Avis clients / plateformes tierces (Google, Pages Jaunes, etc.) — incohérent avec le
  principe « uniquement ce que l'entité publie elle-même », voir Contexte.
- Élargissement de la source de données Sirene elle-même — déjà exhaustive (zone×NAF), rien à
  changer côté `fournisseurs.py`.
- Propagation de l'identité personne jusqu'au pôle CRM Forge (`_resoudre_pole_crm` reste
  service-account, limite déjà connue et documentée S169/170, non traitée ici).
- Retry automatique d'un push `memoire` échoué (best-effort, comme l'audio de `veille-info`).
- Toute UI dédiée (création de campagne, affichage des résumés rappelés) — capacités
  assistant + API seulement ; l'intégration à `atelier-veille` (front) est un sujet séparé, à
  reprendre plus tard si besoin.
