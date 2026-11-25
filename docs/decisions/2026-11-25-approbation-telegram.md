# Décision — Une action sensible exige une approbation persistante, liée à l'action exacte et tenue par le Cœur

- **Date** : 2026-11-25
- **Statut** : ✅ Adopté (S245) — preuve LIVE avec le vrai bot Telegram différée (SLIVE)
- **Portée** : les capacités dont le `manifest.json` déclare `sensibilite`
  (`reversible | donnees | destructif`) ; toutes les origines d'appel (conversation, incident,
  co-agent, Gateway MCP) car la garde est dans `outils.executer`. Les capacités sans
  `sensibilite` (dont les 133 `action: true` du gate S222) sont **inchangées**.
- **Fichiers liés** : `core/approbations.py`, `core/approbations_canal.py`,
  `core/routers/approbations.py`, `core/outils.py` (`est_sensible`, `_resume_action`,
  garde dans `executer`), `core/catalogue.py`, `briques/connexion/{correspondance,adaptateurs,
  client_assistant,pont,main}.py`, `briques/noyau/manifest.json` (tâche `approbations-relance`)
- **Origine** : sprint `docs/sprints/S245-socle-approbation-telegram.md` ; prolonge l'ADR
  `docs/decisions/2026-08-09-gate-action-structurel.md` (S222), dont il ferme la limite
  « co-agent et Gateway MCP non couverts » pour les capacités sensibles.

> **But de ce document** : consigner ce que la garde garantit *réellement*, les écarts pris
> par rapport au plan, et surtout **ce qu'elle ne garantit pas**.

---

## Le trou

Le gate S222 (`accord_action.py`) suppose **un tour de parole humain dans un fil** :

1. Un incident n'a **pas de fil** : l'alerte vient d'un collecteur, pas d'un humain qui parle.
   Le co-agent et la Gateway MCP appellent `outils.executer` sans passer par `converser` : ils
   contournent le gate (limite déjà consignée en S222).
2. Sur Telegram, un « oui » textuel est interprété par le LLM. Aucun bouton natif
   (`inline_keyboard`, `callback_query` absents de `adaptateurs.py`).
3. **Rien de persistant** : un redémarrage du Cœur efface les accords ; impossible de laisser
   une demande attendre le réveil de l'humain.
4. **Pas de niveaux** : un envoi réversible et une suppression de données se valent.

## La décision

Le **Cœur est l'autorité**, la brique `connexion` n'est qu'un **relais**.

- `approbations.exiger()` est appelé dans `outils.executer`, le chemin commun à toutes les
  origines. Une capacité sensible sans approbation `approuvee` d'empreinte identique (et du
  même niveau) n'est **pas exécutée** : une demande est créée et le refus est renvoyé.
- L'approbation est **persistante** (SQLite), **à usage unique** (consommation atomique par
  `UPDATE … WHERE statut='approuvee' AND expire_a>now`), **expire** (TTL par niveau) et suit une
  machine à états stricte, avec un **journal append-only** (triggers SQLite).
- L'empreinte réutilise `accord_action.empreinte` : une approbation pour « X sur A » ne vaut pas
  pour « X sur B ».
- Telegram : boutons `callback_data = ap:<id32 hex>:<ok|ko>`, vérification d'identité **dans
  la brique avant tout appel au Cœur**, `answerCallbackQuery` puis `editMessageText` vers
  l'état final. Le Cœur fait confiance à `par` : l'authentification est donc faite en amont
  et **fermée par défaut**.
- **Destructif** : le bouton ne suffit pas. Un code à 6 chiffres, généré par le Cœur et affiché
  **uniquement dans l'app**, doit être saisi dans Telegram par l'approbateur.
- **Mode attente** : tâche d'horloge `approbations-relance` qui relance les demandes en attente.

## Décisions tranchées (2026-11-25)

1. **Approbateur explicite.** Pas « tout compte lié » : `correspondances.json` porte
   `approbateur: true`, posé via `POST /correspondances/approbateur`. Il faut **à la fois** ce
   drapeau, le statut « lié » et un **chat privé** (`chat_id == from_id`, `chat_type ==
   private`). Un changement de compte à la liaison retire le droit ; les groupes ne sont
   jamais approbateurs.
2. **Code à 6 chiffres affiché dans l'app uniquement, 3 essais, PAS de Mini App.** Le code
   n'est jamais envoyé à Telegram ni journalisé. Au 3e essai raté la demande est refusée. Un
   message vocal transcrit n'est jamais pris pour un code.
3. **TTL par niveau : 30 / 120 / 15 min** (réversible / données / destructif), configurables
   par `APPROBATION_TTL_<NIVEAU>_MIN`.

## Écarts assumés

1. **`approuvee → expiree` est autorisée** (une approbation non utilisée ne reste pas valide
   indéfiniment). Après approbation, la fenêtre d'exécution est de 5 min
   (`FENETRE_EXECUTION_S`) ; une approbation par code étend l'expiration à
   `max(expire_a, now + 5 min)`.
2. **La garde s'applique à toutes les origines, conversation comprise**, pour une capacité
   sensible : le « oui » conversationnel ne suffit plus pour elles. `origine` n'est qu'une
   métadonnée journalisée. À valider si l'on voulait garder le simple « oui » pour un
   `reversible`.
3. **Journal dédié** : table `approbations_journal` dans la même base SQLite.
   `journal_modele.py` est le journal des appels LLM (JSONL) et la brique `audit` est un
   produit client : aucun n'est un journal du Cœur.

Ajouts décidés en revue :

4. **`sensibilite` invalide ⇒ destructif (fail closed).** Une valeur inconnue (`destructive`,
   `high`, `True`, `3`…) est traitée comme `destructif`, avec un warning ; `False`, `0` et `""`
   aussi. Seuls `lecture`, l'absence du champ et `None` ne sont pas gardés. La valeur est
   normalisée (`strip`, minuscules).
5. **Résumé expurgé des secrets, affichage seulement.** `_resume_action` masque (récursivement
   dans dict/listes, profondeur max 5) les clés sensibles, les URL à identifiants, les jetons
   opaques longs, les paramètres de query `token/key/password…=` et `Bearer …`. **L'empreinte
   est calculée sur les vrais arguments** : l'approbation reste liée à l'action exacte.
6. **Consommation filtrée par niveau.** `consommer(…, niveau=…)` et `exiger` ne consomment
   qu'une approbation du **même** niveau ; la déduplication à la création en tient compte
   aussi. Sans cela, un bouton `reversible` pouvait valider un `destructif` de même empreinte
   (trouvé en revue ; corrigé).

## Ce que ça ne garantit PAS

- **Que l'humain ait compris l'action.** On garantit qu'il a vu un résumé et cliqué (et, pour
  le destructif, lu un code dans l'app).
- **Un compte Telegram compromis.** Le bouton hérite de ce risque. Le code atténue seulement
  le niveau `destructif` (il faut aussi accéder à l'app) ; pour `reversible` et `donnees`, un
  compte Telegram compromis suffit à approuver. Le TTL court limite la fenêtre.
- **Un Cœur compromis** : il est l'autorité, il peut exécuter sans approbation.
- **`APPROBATIONS_CLE` fuitée** : quiconque la détient peut décider une approbation hors
  destructif (pour le destructif il manque encore le code). À garder dans le réseau docker.
- **Webhook Telegram sans `TELEGRAM_WEBHOOK_SECRET`** : `verifier_webhook` accepte tout, le
  `from.id` du payload n'est alors pas une identité. Les callbacks et les codes sont **ignorés**
  (fail closed), mais les **messages ordinaires restent usurpables** (comportement préexistant).
  **Recommandation : exiger le secret dès qu'on est en mode webhook.**
- **La garde d'authentification du webhook est liée à `reseau == "telegram"`** : un autre
  réseau ne porte pas de boutons d'approbation aujourd'hui, mais la règle n'est pas générique.
- **Les boutons envoyés par `/approbation/notifier` restent inopérants si le secret manque**, et
  rien n'est journalisé à ce moment-là (le clic ignoré, lui, l'est côté pont).
- **Les capacités sans `sensibilite` sont inchangées** (gate S222 conversationnel).
- **Les messages Telegram ne sont édités que si la brique répond** au `notifier` : sinon le
  message d'origine garde ses boutons ; un clic tardif est alors refusé et le message mis à jour.
- **La relance est at-most-once** (marquée avant notification) : un échec d'envoi ne la rejoue pas.
- **`GET /approbations/en_attente` n'est pas filtré par utilisateur** : toute session voit toutes
  les demandes en attente (et donc le code destructif, qui est affiché dans l'app).
- **Secrets en texte brut non masqués dans le résumé** : `password=x` dans un texte libre,
  `Basic …`, `api-key=…` ne sont pas reconnus. L'expurgation est une meilleure-effort.
- **Telegram est un tiers** : il conserve le texte du résumé envoyé.
- *(corrigé en revue finale : la comparaison du secret de webhook est désormais à temps constant,
  `hmac.compare_digest` sur des octets.)*
- **L'approbation n'est PAS liée à un utilisateur ni à un tenant.** L'empreinte couvre
  capacité + arguments seulement. Dans le Cœur multi-utilisateur (S182), l'utilisateur B qui appelle
  la même action avec des arguments identiques dans la fenêtre d'exécution consomme l'approbation
  de l'utilisateur A ; chaque approbateur reçoit chaque demande et le message ne nomme pas le
  demandeur. **Écart connu, à fermer AVANT que la première capacité multi-utilisateur déclare
  `sensibilite`.** Proposition : stocker utilisateur/org dans la ligne, filtrer
  `creer`/`consommer`/`_derniere`/`en_attente`, afficher le demandeur dans le message Telegram.
- **Pas d'exécution automatique après approbation.** Le modèle est « approuver puis ré-appeler » :
  après le clic, l'humain ou le LLM doit relancer l'outil dans la fenêtre de 5 minutes. Les
  origines co-agent et incident n'ont aucun mécanisme de reprise : leurs approbations expirent. Un
  mécanisme de reprise à l'approbation est à planifier (S246+).
- **Le code destructif n'est lisible que via `GET /approbations/en_attente`** (session) : aucun
  panneau de tableau de bord ne l'affiche encore (interface à venir).
- **`ORIGINE`** (conversation / coagent / mcp) est posée à l'entrée de `outils.executer` par les
  trois appelants (`core/assistant.py`, `core/coagent.py`, `core/mcp.py`) via
  `approbations.avec_origine`. Toute autre voie (incident, tâche d'horloge, appel direct) reste
  `inconnue`, sauf si l'appelant passe `origine=` explicitement.
- **Piège d'exploitation : `API_KEYS`** est une liste de clés partagée, lue par de nombreuses
  briques depuis le `.env` racine ; la renseigner pour activer les approbations ferme toutes ces
  briques d'un coup. Recommandation (suivi) : une variable dédiée aux clés acceptées par la brique
  connexion.
- **`satisfaire_prerequis` n'est pas protégé par un verrou** (lecture-modif-écriture du JSON des
  prérequis) : à corriger en S247, quand les prérequis serviront réellement.
- **Prérequis et destructif (corrigé en revue finale)** : `armer_saisie_code` et
  `valider_code_saisi` imposent désormais les prérequis (sinon un code correct approuvait un
  destructif sans sauvegarde vérifiée). Un code soumis prérequis non réunis n'approuve jamais, ne
  compte pas comme essai raté et désarme la saisie.
- **Un approbateur qui envoie 6 chiffres** sans saisie armée n'est plus jamais relayé au LLM ni
  journalisé : réponse « Aucune saisie de code en cours ».

## Limites assumées

- **SQLite mono-processus** : un seul worker du Cœur. Un déploiement multi-processus demanderait
  un verrou externe ; l'arbitre atomique reste l'UPDATE conditionnel.
- **Pas de migration des 133 actions** existantes vers ce système.
- **Page « maintenance »** côté utilisateur : S246/S247 (elle exige Dokploy). Les prérequis
  (`satisfaire_prerequis`) sont prêts mais ne sont utilisés qu'à partir de S247.
- **Preuve LIVE avec le vrai bot différée en SLIVE** (régime « preuve Docker différé »).
  Recette dans `docs/sprints/S245-socle-approbation-telegram.md`.

## Filet

Fichiers de test (comptes mesurés le 2026-11-25) :

| Fichier | Tests |
|---|---|
| `core/test_approbations.py` (état, TTL, code, atomicité, journal, persistance) | 51 |
| `core/test_approbations_garde.py` (garde dans `executer`, non-régression, expurgation) | 41 |
| `core/test_approbations_routes.py` (routes HTTP, clé, relance) | 38 |
| `core/test_approbations_canal.py` (Cœur → connexion) | 12 |
| `briques/connexion/test_pont.py` | 75 |
| `briques/connexion/test_main.py` | 34 |
| `briques/connexion/test_correspondance.py`, `test_adaptateurs.py`, `test_client_assistant.py` | 14, 28, 12 |

Suites complètes : `core` **1251 passed, 3 xfailed** (xfail préexistants dans
`test_routage_demandes_courtes.py`) ; `briques/connexion` **196 passed**.
Tests ajoutés en revue finale : prérequis du destructif (armer refusé, code refusé, puis accepté),
code 6 chiffres jamais relayé (approbateur) / relayé (non-approbateur), webhook en temps constant,
TTL invalide, message final ✅ Exécutée / ⚠️ Échec, origine (MCP de bout en bout + ContextVar).
L'origine du chat et du co-agent n'est testée que par la plomberie ContextVar et le chemin MCP
(pas de double de test existant pour la boucle de l'assistant).

**Preuve par mutation** (convention du dépôt, cf. S222). Chaque mutation a été appliquée seule,
les tests lancés, puis le fichier restauré (`git diff` vide). Un test qui passe avant *et* après
ne prouve rien : seules les colonnes « échoue » comptent.

| # | Mutation | Tests lancés | Résultat mesuré |
|---|---|---|---|
| a | `outils.executer` : `niveau = None` au lieu de `est_sensible(...)` (garde neutralisée) | `test_approbations_garde.py` (41) | **14 échouent, 27 passent** (re-mesuré en revue finale ; aux 11 d'origine s'ajoutent les 3 tests du message final et de l'origine). Échouent : `test_sans_approbation_rien_ne_s_execute…`, `test_le_llm_ne_peut_pas_se_confirmer_tout_seul`, `test_approuvee_puis_executee_une_fois`, `test_approbation_pour_crm_ne_vaut_pas_pour_autre`, `test_refus_bloque_la_redemande_immediate`, `test_destructif_exige_le_code_pas_le_bouton`, `test_un_echec_d_execution_est_journalise`, `test_typo_sensibilite_exige_une_approbation`, `test_conclure_meme_si_executer_leve`, `test_notification_en_echec_ne_se_propage_pas`, `test_secrets_differents_empreintes_differentes_resume_masque`. Passent (non-régression) : `test_lecture_passe_sans_approbation`, `test_capacite_sans_sensibilite_garde_le_comportement_historique`, `test_est_sensible_lit_le_manifeste`, normalisation/lecture de `est_sensible`, expurgation du résumé. |
| b | `approbations.consommer` : filtre `sensibilite` retiré (SELECT et UPDATE) | `test_approbations_garde.py` + `test_approbations.py` (81) | **2 échouent, 79 passent** : `test_approbation_reversible_ne_debloque_pas_destructif`, `test_consommer_destructif_ne_prend_pas_une_approbation_reversible`. |
| c | `approbations.valider_code_saisi` : comparaison du code remplacée par `if True` | `test_approbations.py` + `test_approbations_routes.py` (80) | **6 échouent, 74 passent** : `test_trois_codes_faux_refusent_la_demande`, `test_le_bon_code_apres_refus_n_approuve_rien`, `test_saisie_non_ascii_ou_mal_formee_compte_comme_essai_sans_crash`, `test_essais_concurrents_ne_depassent_pas_la_limite`, `test_code_faux_decremente_restants`, `test_code_non_ascii_ne_plante_pas`. |
| d | `pont.traiter_callback` : condition `est_approbateur` retirée | `briques/connexion` (196) | **3 échouent, 190 passent** : `test_callback_non_approbateur_ignore_sans_appeler_le_coeur`, `test_callback_inconnu_ou_en_attente_ignore`, `test_callback_statut_ouvert_ne_donne_pas_le_droit`. |
| d2 | `pont.traiter_callback` : contrôles `chat_type == private` et `chat_id == from_id` retirés (le « mauvais chat » est une condition distincte de d) | `briques/connexion` (196) | **2 échouent, 191 passent** : `test_callback_approbateur_en_groupe_ignore`, `test_callback_chat_different_de_l_emetteur_ignore`. |
| e | `main.py` webhook : garde `if authentifiee:` retirée devant `traiter_callback` | `briques/connexion` (196) | **1 échoue, 192 passent** : `test_webhook_callback_sans_secret_est_refuse_sans_toucher_le_coeur`. |
| e2 | `main.py` webhook : `source_authentifiee=True` forcé pour les messages | `briques/connexion` (196) | **1 échoue, 192 passent** : `test_webhook_message_transmet_le_drapeau_source_authentifiee[None-entete0-False]`. |
| e3 | `pont.traiter` : abandon des 6 chiffres d'un approbateur en source non authentifiée retiré | `briques/connexion` (196) | **1 échoue, 192 passent** : `test_code_d_un_approbateur_via_source_non_authentifiee_est_ignore`. |

Les 8 mutations sont attrapées. Le brief attendait que la mutation d fasse aussi échouer le
test « mauvais chat » ; ce n'est pas le cas, car ce contrôle est indépendant de
`est_approbateur` (d2 le couvre séparément).

## S245b (2026-11-25) : approbation liée à l'utilisateur, reprise par le Cœur

Branche `s245b-approbation-liee-utilisateur`. Ferme trois limites d'S245. Les clés ne sont
toujours **pas posées sur le HP** : le tout reste dormant jusqu'à l'activation en fin d'S246.

### Les 3 décisions

- **Q1 = A : seul le demandeur approuve.** La demande porte `utilisateur` et `org_id` ; `creer`,
  `consommer`, `_derniere`, `en_attente`, `approuver`, `refuser`, `armer_saisie_code` et
  `valider_code_saisi` filtrent par utilisateur ; l'argument `utilisateur` (kw-only) n'est obligatoire
  que pour `approuver`, `refuser`, `armer_saisie_code` et `valider_code_saisi` ; `creer`, `consommer`
  et `_derniere` prennent par défaut l'utilisateur du contexte tenant. Côté
  brique connexion, la demande n'est envoyée qu'à l'approbateur lié à ce demandeur
  (`correspondance.approbateurs_de`) et le pont résout l'utilisateur de l'approbateur
  (`utilisateur_de`) avant d'appeler le Cœur, qui revérifie.
- **Q2 = A : `CONNEXION_API_KEYS` propre à la brique.** Variable présente mais vide = brique
  ouverte ; variable absente = repli sur `API_KEYS`. Le Cœur et les briques appelantes envoient
  `CONNEXION_KEY`. On ne renseigne jamais `API_KEYS` pour cela (une vingtaine de briques la lisent).
- **Q3 = A : le Cœur exécute l'action approuvée** (`core/approbations_reprise.py`), dans le contexte
  (utilisateur + org) du demandeur, déclenchée par le bouton **et** par le code destructif valide.
  Les arguments sont purgés à tout état final.

### Ajouts au-delà du plan (revues)

- `approbations.abandonner` : une demande `approuvee` dont la capacité n'est plus sensible, ou dont
  la garde refuse à la reprise, passe à `expiree` et est journalisée `abandonnee`, pour que
  l'horloge ne la rejoue pas indéfiniment. Le message Telegram est édité au mieux à l'état final (« ⌛ Expirée »,
  sans jamais lever) ; ce même abandon couvre aussi les arguments absents.
- `pont._tenter_code` : un approbateur sans compte lié est avalé en échec fermé
  (`approbateur_sans_compte`) ; ses 6 chiffres ne sont jamais relayés au LLM.
- Anti-redemande de 5 min après une exécution réussie (`DELAI_APRES_EXECUTION_S`).
- Reprise des `approuvee` orphelines par l'horloge (`/approbations/relancer`, champ `reprises`).
- Une exception avant consommation lors de la reprise laisse la demande `approuvee` ; elle est
  journalisée (`reprise_echec`, type d'exception seul) et réessayée, bornée à 3 échecs : au
  troisième, abandon (`expiree`, message édité).

### Écarts et limites assumés

1. **Args en clair en base** jusqu'à l'état final : l'exécution exige les vrais arguments, donc ils ne peuvent pas être expurgés (le résumé affiché, lui, reste expurgé). Mitigation : purge (`args = NULL`) à toute sortie de `en_attente`/`approuvee` vers un état final, jamais exposés par une route.
2. **Pas de JWT à la reprise, repli sur le compte de service** : `user_token` n'est pas persisté. À la reprise `_user_token` vaut None, `contexte_tenant.entetes_forge()` renvoie `{}` et l'adaptateur Forge RETOMBE sur son compte de service (`core/outils_communs.py`, `entetes_forge_sortants`). Une capacité de la brique Forge s'exécuterait donc sous l'identité de service, pas celle du demandeur (changement de privilège possible), et n'échouerait pas. Prérequis avant de rendre sensible une capacité Forge : voir S246. Le contexte repris porte `utilisateur` + `org_id`.
3. **Résultat non réinjecté dans le fil de conversation** : le résultat de la reprise est visible dans le message Telegram édité (✅/⚠️) et dans `approbations.resultat`. Le réinjecter dans le journal de conversation est reporté (hors périmètre).
4. **Au plus une exécution** : `consommer` marque `executee` *avant* d'exécuter. Un crash du Cœur pendant l'exécution laisse la demande `executee` sans résultat, sans rejeu automatique (sens sûr).
5. **`org_id` hors filtres** : `org_id` ne fait pas partie des filtres de consommation/dédoublonnage (seul `utilisateur`) : un utilisateur actif dans deux organisations pourrait voir une approbation de l'une consommée pour l'autre à arguments identiques — à traiter si le multi-organisation par utilisateur devient réel.
6. Limite 3 d'S245 (écran affichant le code destructif) et 4 (`satisfaire_prerequis` sans verrou, S247) : non traitées ici. Reste aussi : webhook Telegram sans secret (callbacks et codes ignorés dans ce cas).
