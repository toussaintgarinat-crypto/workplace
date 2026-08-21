# Invariant « journal = vérité » — journal_modele.py

**Statut** : conçu, en attente d'implémentation (2e des 4 chantiers de la veille
[deepseek-harness/Cordis], après S234 audit gate Forge).

## Contexte

La veille deepseek-harness (Cordis) formalise un invariant : *tout ce qui atteint une
requête modèle doit être reconstructible depuis un journal de session append-only,
vérifié par un runtime check.*

Audit du Cœur (2026-08-21) : le journal de conversations existant (`core/journal_conversations.py`,
S78) n'enregistre QUE le dernier message user et le texte final assistant d'un tour.
Il ne capture ni le contexte système injecté à chaud (prompt persona/addendum/langue,
digest identité, conscience, instructions projet, souvenirs mémoire proactive, date/heure,
guidance MOA), ni les `tool_calls`/`tool_results` échangés pendant le tour
(`core/assistant.py::converser()`). Au-delà du texte final user/assistant, rien n'est
aujourd'hui reconstructible depuis le journal. L'invariant n'est pas satisfait.

## Décisions de portée (validées avec l'utilisateur)

1. Couvrir à la fois les `tool_calls`/`tool_results` (le plus consequent côté sécurité —
   gate S222, guardrails) ET le contexte système (persona, digest, instructions, date…) —
   pas un sous-ensemble.
2. Nouveau journal **séparé** de `journal_conversations.py`, jamais une extension du
   journal existant : celui-ci sert aussi de mémoire cross-surface
   (`messages_utilisateur()` réinjecte du `{role: user|assistant, content}` tel quel dans
   un futur prompt via le pont Telegram) — y ajouter des rôles tool/system casserait ce
   contrat et pousserait du bruit dans un futur prompt.
3. Runtime check à la fois **vivant en production** (non bloquant, même convention que le
   reste du journal) ET exercé par un **test de caractérisation** en CI.
4. Couverture **système complète**, pas seulement la boucle de chat : accroché au même
   point que `journal_usage.enregistrer()` dans `core/llm_pipeline.py`, qui est déjà le
   point de passage unique de tous les appels LLM du Cœur (`assistant.py`, `classer.py`,
   `moa`/`briefing`/`proprioception`/`summarisation`/`coagent`/`amelioration`/`curateur`…).
   C'est aussi le seul endroit où les messages sont **réellement finalisés** (après
   résumé à froid, trim, cache-préfixe) — `historique` dans `assistant.py` est encore la
   version pré-trim, donc pas fidèle à ce qui part vraiment vers la Gateway.

## Architecture

Nouveau module `core/journal_modele.py`, jumeau structurel de `journal_usage.py` : JSONL
append-only, borné, best-effort/non-bloquant (aucune écriture ne doit jamais casser une
conversation ou un appel LLM).

Accroché dans `core/llm_pipeline.py`, DEUX points d'appel (mêmes lignes que
`journal_usage.enregistrer(...)` déjà présent) :
- `completer()` : juste après une réponse modèle réussie (avant le `return Resultat(...)`).
- `completer_flux()` : juste après l'assemblage du message streamé (avant le
  `yield {"type": "fin", ...}`).

Sur échec total (aucun modèle joignable), une ligne `{modele: None, erreur: ...}` est
écrite en miroir de `journal_usage` — « rien n'a atteint le modèle » devient une trace
explicite plutôt qu'un silence.

### Nouveau paramètre `fil`

`completer()` et `completer_flux()` gagnent un paramètre optionnel `fil: str | None = None`
(défaut `None`, aucun appelant existant à modifier). `core/assistant.py::converser()` le
renseigne avec `fil_accord` (déjà calculé) sur ses deux appels (`completer`/`completer_flux`).
Les appels hors conversation (classement de document, MOA, briefing, proprioception…)
laissent `fil=None` — normal, ce ne sont pas des tours de conversation.

## Format de ligne

```json
{
  "ts": 1755792000.123,
  "fil": "web:dashboard",
  "etiquette": "chat",
  "modele": "openai/gpt-4o-mini",
  "messages": [ /* payload["messages"] EXACT envoyé — post résumé/trim/cache-préfixe */ ],
  "outils_offerts": ["agenda_consulter", "memoire_rappeler", "..."],
  "message_recu": {"role": "assistant", "content": "...", "tool_calls": [ /* ... */ ]}
}
```

- `messages` : la liste réellement envoyée à la Gateway pour l'appel qui a abouti (pas
  une reconstruction a posteriori) — c'est la fidélité que l'invariant demande.
- `outils_offerts` : noms seuls, pas les schémas JSON complets (statiques/dérivables du
  code `outils.py` — les stocker à chaque ligne gonflerait le journal pour une information
  qui ne varie pas avec l'état). Ce qui varie et mérite d'être tracé, c'est LA LISTE
  offerte ce tour-ci (filtrée par `routage_outils`), pas leur définition.
- En cas de retries multi-modèles (bascule sur échec), seule la ligne de l'appel qui a
  **réellement répondu** est journalisée (comme `journal_usage` le fait déjà pour le coût) —
  les tentatives échouées n'ont rien montré à aucun modèle.
- Sur un **hit du cache sémantique** (`completer(cache=True)`, jamais emprunté par
  `assistant.py` qui désactive le cache dès qu'il y a des outils) : par définition aucune
  requête n'a atteint un modèle ce tour-ci — la réponse vient d'un appel PASSÉ déjà
  journalisé à l'époque. Pas de nouvelle ligne dans ce cas ; cohérent avec l'invariant
  (rien de nouveau n'a atteint le modèle), pas une omission.

## Runtime check vivant

Après chaque écriture réussie dans `journal_modele.enregistrer_appel(...)`, le module relit
IMMÉDIATEMENT la dernière ligne physique du fichier et vérifie qu'elle égale (après
`json.loads`) le dict qu'on vient de sérialiser. Un écart (troncature disque, écriture
concurrente corrompue, échec silencieux) déclenche `logger.error(...)` — jamais une
exception qui remonte et casse l'appel LLM en cours, même convention « best-effort non
bloquant » que `journal_conversations`. C'est un check qui s'exécute à CHAQUE appel en
production (pas seulement en test) : il vérifie en continu que « ce qui est dans le
journal » égale « ce qui vient d'atteindre le modèle », donc que le journal reste la
vérité durable — pas une best-effort qui pourrait dériver sans que personne ne le sache.

## Bornage & vie privée

- `MODELE_JOURNAL_PATH` (défaut `/data/journal_modele.jsonl`), `MODELE_JOURNAL_MAX`
  (défaut 2000 — plus bas que `CONVERSATIONS_JOURNAL_MAX`=5000 vu la taille des lignes,
  qui embarquent des historiques de messages entiers). Même mécanique de bornage que
  `journal_conversations._borner()` (réécriture quand on dépasse `max * 1.2`).
- Pas de nouvel endpoint HTTP exposé : trace interne/debug, pas une fonctionnalité front.
  Les données qu'elle contient sont un sur-ensemble de ce que le modèle voit déjà (donc
  pas de nouvelle classe d'exposition), simplement dans un second fichier.

## Tests

`core/test_journal_modele.py` :
1. Écrire un appel avec `tool_calls`, relire, vérifier le round-trip exact.
2. Vérifier le bornage (dépassement de `MODELE_JOURNAL_MAX` → réécriture tronquée).
3. Simuler un désaccord entre écrit/relu (mock du comparateur) → vérifie que le check
   loggue une erreur SANS lever d'exception.

`core/test_assistant_routes.py` (ou nouveau fichier dédié) : test bout-en-bout avec
`llm_pipeline` mocké — un tour à 2 itérations (1 tool call puis 1 réponse finale) doit
produire exactement 2 lignes dans `journal_modele`, avec le bon `fil` et les bons
`tool_calls`/`message_recu`.

## Hors périmètre (différé)

- Pas d'UI de consultation du nouveau journal (comme le panneau Historique côté
  `journal_conversations`) — trace technique, pas une fonctionnalité utilisateur.
- Pas de correctif sur `shadow.py` (rejeu en tâche de fond d'un candidat moins cher) —
  à vérifier séparément s'il passe par `llm_pipeline.completer()` ou appelle la Gateway
  directement ; hors scope de ce chantier.
- Les 2 autres chantiers de la veille (couches de patch déclaratif multi-tenant, seams
  3 rôles pour dev-auto-atelier/5955) restent non entamés.
