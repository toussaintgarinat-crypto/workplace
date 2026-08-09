# Décision — Les arguments d'outil sont validés contre le manifeste avant tout appel réseau

- **Date** : 2026-08-09
- **Statut** : ✅ Adopté (S221)
- **Portée** : la boucle d'inférence du Cœur (`core/assistant.py`) et les 253 capacités
  déclarées par les 34 manifestes qui en portent
- **Fichiers liés** : `core/validation_args.py`, `core/guardrails_outils.py`,
  `core/outils.py` (`schema_arguments`), `core/routers/systeme.py`
  (`/validation/ecarts`), `GUIDE-ajouter-un-outil.md`
- **Origine** : veille sur [LIA-Assistant](https://github.com/jgouviergmail/LIA-Assistant)
  (AGPL-3.0 — **idée reprise, aucun code**), `docs/technical/PLANNER.md`, leur `PlanValidator`
  et ses 14 catégories d'écart. Backlog : `docs/sprints/S221-S226-emprunts-lia-assistant.md`

> **But de ce document** : consigner *pourquoi* on revérifie ce que le LLM renvoie alors qu'on
> lui a déjà donné le schéma, *où* la vérification est branchée, et *ce qu'on renonce
> volontairement à bloquer*.

---

## En bref (l'état retenu)

- `outils.schema_arguments(nom, registre)` expose **la même** source de schéma que celle
  présentée au LLM (outils en dur, méta-outil de la porte S90, capacités de manifeste).
  Valider contre elle ne peut donc pas diverger du contrat annoncé.
- `validation_args.valider()` compare les arguments à ce schéma et renvoie des écarts typés.
- `Guardrail.before_call` (S143) refuse l'appel si un écart est bloquant, avec un message
  **corrigeable** ; les écarts non bloquants deviennent une annotation `warn`.
- Un appel bloqué est compté comme un échec (`after_call(erreur=True)`), sinon un LLM qui
  s'obstine sur les mêmes arguments invalides reboucle jusqu'à `MAX_ITERATIONS`.

## Le problème

`_spec_depuis_capacite` fabriquait déjà un schéma function-calling depuis le manifeste
(`type`, `requis`, `enum`) et le donnait au LLM — puis **plus rien ne revérifiait la réponse**.
Les arguments partaient tels quels vers la brique, qui répondait 422, et `_appel_dynamique`
traduisait ça en :

```
Brique « forge » a refusé (422).
```

Un message dont le LLM ne peut **rien** faire : il ne sait ni quel paramètre est en cause, ni
pourquoi. Il retente donc souvent à l'identique. Coût par erreur : un aller-retour réseau + un
tour de LLM complet, pour une faute détectable localement en microsecondes.

## La décision

Valider **au niveau de l'appel unitaire**, pas du plan. LIA valide un plan multi-étapes entier
avant exécution ; nous n'avons pas de plan, et cinq de leurs quatorze catégories se
transposent telles quelles à un appel isolé : outil inconnu, paramètre requis manquant, type
faux, valeur hors énumération, borne dépassée, format non respecté. Les neuf autres
(dépendances circulaires, forward reference, référence `$steps.X`, condition non-safe…) n'ont
de sens qu'avec un plan — elles arriveront avec S226 ou jamais.

Point de branchement : `Guardrail.before_call`, qui savait **déjà** répondre
`allow | warn | block` et était **déjà** appelé avant chaque outil. Aucune plomberie nouvelle
dans la boucle. Le validateur est **injecté** (`Guardrail(valideur=…)`) et non importé : le
garde-fou reste une machine à états sans dépendance, testable sans registre ni manifeste, et
son comportement S143 est strictement inchangé quand aucun validateur n'est fourni.

## Ce qu'on renonce à bloquer, et pourquoi

Un validateur qui produit des faux positifs est **pire que pas de validateur** : il coûte
exactement le tour de LLM qu'il prétend économiser, sur un appel qui aurait marché.

- **Chaîne numérique pour un nombre** (`"10"` pour `integer`) : acceptée. Les arguments
  partent en query string (GET) ou vers un modèle Pydantic en mode souple — les deux coercent
  déjà. Refuser serait un faux positif pur.
- **`"true"` / `"false"` / `"1"` / `"0"` pour un booléen** : acceptés, même raison.
- **Paramètre envoyé mais non déclaré** : signalé, **non bloquant**. Le LLM improvise parfois
  un argument que la brique ignore ; ça ne justifie pas de perdre le tour.
- **Éléments d'un tableau** (`items`) : contrôle superficiel, non bloquant — `items` peut
  décrire des objets imbriqués qu'on ne prétend pas valider en profondeur.
- **Motif (`pattern`) illisible dans un manifeste** : ignoré silencieusement. Un manifeste mal
  écrit ne doit jamais bloquer un appel légitime.

Garde explicite dans l'autre sens : un **booléen** là où un `integer` est attendu est refusé.
En Python `True` est un `int` ; sans ce cas particulier, une vraie erreur du LLM passerait.

## Ce que ça mesure (et pourquoi ça compte pour S226)

`/validation/ecarts` expose le comptage par catégorie et par outil depuis le
démarrage. C'est délibérément le **critère de décision de S226** (plan explicite validé) :

- écarts massivement `param_requis` / `type` / `enum` → le LLM se trompe d'**arguments**, la
  validation unitaire suffit, S226 ne se justifie pas ;
- peu d'écarts malgré des tours d'outils nombreux → le problème est ailleurs, dans
  l'**enchaînement**, et un plan explicite adresse un vrai manque.

Sans cette mesure, S226 se déciderait sur les chiffres auto-déclarés de LIA (« 4–8× moins de
tokens que ReAct »), publiés sans protocole ni charge de référence. On préfère les nôtres.

## Filet

`core/test_validation_args.py` — 35 cas. Le plus important n'est pas unitaire : il parcourt
**les manifestes réels du dépôt** et vérifie qu'un appel vide ne produit jamais qu'un écart
`param_requis`. Tout autre écart (type, énumération) sur un appel vide trahirait un manifeste
mal formé, et surtout un futur faux positif en production.
