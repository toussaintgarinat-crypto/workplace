# Audit d'isolation multi-tenant — S183 (2026-07-19)

Méthodologie : docs/superpowers/specs/2026-07-19-s183-audit-isolation-design.md
Deux modèles de tenant coexistent : (a) cercle privé par personne (Keycloak, X-User-Id,
motif établi sur l'agenda en S182) et (b) bundle client business (X-Compte-Id/ADMIN_COMPTE_ID,
épopée bundles S95-S99). L'audit couvre les deux.

## Constat central

`core/outils_communs._entetes_brique` (core/outils_communs.py:48-70) n'envoie que trois
signaux : `X-Compte-Id` (toujours, `ADMIN_COMPTE_ID`), `X-API-Key` (si `{BRIQUE}_KEY` défini),
et `X-User-Id` — **seulement pour `agenda`** (commentaire explicite : "les autres briques
ignorent cet en-tête"). `core/contexte_tenant.py` sait aussi produire `X-Org-ID` (donnees) et
`X-Forge-User-Token` (forge), mais `entetes_donnees()` n'est câblé que dans le flux de cycle de
vie de bundle (`core/cycle_de_vie.py:214`), pas dans le chemin générique d'appel d'outils LLM :
`donnees` ne reçoit donc jamais `X-Org-ID` via les outils de l'assistant et retombe sur l'org
"defaut".

La majorité des briques produit implémentent leur propre multi-tenant **par clé API**
(`tenant = sha256(X-API-Key)[:16]`, motif identique dans mail/geo/telephonie/etc.). C'est le
modèle (b). Mais le Cœur n'envoyant qu'**une seule** `{BRIQUE}_KEY` pour tout son trafic, si ce
Cœur sert un cercle privé (plusieurs proches), ces briques partagent toutes le même tenant côté
cercle privé — sauf l'agenda, seule brique ayant reçu le correctif S182.

## Tableau brique → verdict

| Brique | Port | En-têtes honorés côté serveur | Tenant en DB | Filtre appliqué | Tests d'isolation | Usage probable | Verdict |
|---|---|---|---|---|---|---|---|
| agenda | 8400 | X-User-Id (repli session cookie) | Oui — Calendar.user_id | Oui | Oui | personne | isolée-personne |
| mail | 6030 | X-API-Key/Authorization → hash tenant | Oui — tenant | Oui | Oui | personne | isolée-bundle (1 seule MAIL_KEY/Cœur = risque cercle-privé) |
| memoire | 5600 | Aucun | Non | Non | Non | personne | **TROU** |
| donnees | 5500 | X-Org-ID, Keycloak optionnel | Oui — org_id | Oui | Oui | infra-partagé | isolée-bundle (jamais reçu via outils_communs) |
| restaurant | 6010 | X-Compte-Id+X-API-Key, session Bearer | Oui — compte_id | Oui | Oui | bundle-client | isolée-bundle |
| paiements | 6020 | X-API-Key/Bearer → solution | Oui — solution/compte_id | Oui | Oui | bundle-client | isolée-bundle |
| telephonie | 6050 | X-API-Key/Bearer → solution | Oui | Oui | Oui | bundle-client | isolée-bundle |
| geo | 6110 | X-API-Key/Bearer → tenant hash | Oui — tenant | Oui | Oui | bundle-client | isolée-bundle |
| personnages | 5900 | X-API-Key/Bearer | Oui — cle_api | Oui | Non | bundle-client | isolée-bundle |
| studio | 6060 | X-API-Key/STUDIO_KEY | Non (cree_par capturé, jamais filtré) | Non | Non | bundle-client (visé) | **TROU** |
| calcul | 5990 | X-API-Key/Bearer | Non (parc partagé) | N/A | Oui (hors tenant) | infra-partagé | partagée-à-raison |
| forge | 5700 | X-Forge-User-Token (ContextVar) | Non (propagation identité) | N/A | Oui | infra-partagé | partagée-à-raison |
| connexion | 5870 | X-API-Key, X-Telegram-Init-Data | Oui-partiel — mapping interlocuteur→utilisateur | Oui | Non | personne | isolée-personne (non testée) |
| voix | 5985 | X-API-Key/Bearer | Non (bibliothèque de clones globale) | Non | Non | personne (biométrie vocale) | partagée-à-raison (voulu, sensible) |
| images | 5950 | X-API-Key/Bearer | Non (stateless) | N/A | Non | bundle-client | partagée-à-raison |
| video | 5970 | X-API-Key/Bearer | Non (stateless) | N/A | Non | bundle-client | partagée-à-raison |
| transcription | 5980 | X-API-Key/Bearer | Non (stateless) | N/A | Non | bundle-client | partagée-à-raison |
| vision | 5960 | X-API-Key/Bearer | Non (stateless) | N/A | Non | bundle-client | partagée-à-raison |
| recherche | 6040 | X-API-Key/Bearer | Non (cache global) | N/A | Non | bundle-client | partagée-à-raison |
| peertube | 6100 | X-API-Key | Non | N/A | Non | bundle-client | partagée-à-raison |
| synopsis | 6090 | X-API-Key/Bearer sur /resumer* — **absent sur /jobs/{id}** | Non | Non | Non | bundle-client | **TROU (poll job non authentifié) — FIXÉ CE SPRINT (Task 2)** |
| oria | 6085 | Aucun | Non | N/A | Non | infra-partagé/collaboration | partagée-à-raison |
| audit | 5300 | Aucun | Non | N/A | Oui (hors isolation) | infra-partagé | partagée-à-raison |
| etl | 5200 | Aucun | Non | N/A | Oui (hors isolation) | infra-partagé | partagée-à-raison |
| generateur | 5400 | Aucun | Non | N/A | Non | infra-partagé | partagée-à-raison |
| gateway | 4001 | N/A (proxy LiteLLM) | Non | N/A | Non | infra-partagé | partagée-à-raison |
| dev | 5955 | X-API-Key=DEV_KEY unique | Non | N/A | Non | infra-partagé | partagée-à-raison |
| app-builder | — | pas de code serveur | — | — | — | — | (ignorée) |
| noyau | — | pas de code serveur | — | — | — | — | (ignorée) |

## Trous : action retenue

- **synopsis `/jobs/{job_id}`** : FIX CE SPRINT (Task 2) — motif déjà établi dans le même
  fichier (`Depends(cle_api)` sur les routes sœurs), zéro migration, zéro changement de
  comportement pour un appelant qui respecte déjà le contrat de la brique.
- **memoire** : REPORTÉ — aucune auth du tout aujourd'hui ; corriger exige de concevoir un
  modèle de tenant complet (colonne, filtre sur toutes les routes), pas un fix d'1-2 lignes.
  Candidat prioritaire pour un sprint dédié (donnée éminemment personnelle).
- **studio** : REPORTÉ — `cree_par` est déjà capturé mais jamais filtré (aveu explicite en
  commentaire, socle S51 non fait) ; l'activer maintenant changerait le comportement pour
  toute donnée déjà créée sous des clés différentes. Sprint dédié.
- **mail** (1 seule `MAIL_KEY` par Cœur) : REPORTÉ — aligner sur le motif X-User-Id
  (comme l'agenda) est un changement de comportement, pas un trou à boucher au sens strict.
  Cité dans la mémoire S182/S183 comme candidat mûr pour un sprint dédié.
- **`donnees` (X-Org-ID jamais forwardé via `outils_communs`)** : REPORTÉ — nécessite de
  décider si les outils LLM doivent porter une organisation, hors périmètre "chacun son espace
  par personne".

## Hors périmètre confirmé

Briques stateless ou sans notion de tenant pertinente (images, video, transcription, vision,
recherche, peertube, calcul, forge, gateway, dev, audit, etl, generateur, oria, voix) : verdict
"partagée à raison", aucune action.
