# Guide — ajouter un outil à l'assistant du Cœur

> **À qui ça sert** : tu veux que l'assistant (le « Jarvis ») sache **faire** quelque chose de
> nouveau en langage naturel. Il y a **deux voies**. Choisis la plus simple qui marche.

## Décider : déclaratif (manifest) ou en dur (Cœur) ?

| | Voie A — capacité déclarative | Voie B — outil en dur |
|---|---|---|
| **Où** | `briques/<brique>/manifest.json` | `core/outils_domaines/<domaine>.py` + `core/outils.py` |
| **Code Cœur** | **Aucun** | Oui |
| **Convient à** | un appel HTTP **JSON** simple (1 requête → 1 réponse) | orchestration multi-étapes, remap de champs, portes spéciales, flux binaire |
| **Exemples réels** | mail, recherche, images, téléphonie, voix, paiements | studio, personnages, transcription (multi-étapes), co-agent, amélioration |

**Règle** : si ta brique peut répondre en **un seul appel JSON**, prends la **Voie A** (déclaratif,
zéro dette dans le Cœur). Ne descends en Voie B que si tu as une vraie raison (plusieurs appels
enchaînés, transformation de payload, octets binaires).

---

## Voie A — capacité déclarative (recommandée)
C'est exactement le `capacites` du `GUIDE-ajouter-une-brique.md`. Le Cœur lit le manifest
(`core/catalogue.py::collecter_capacites`) et **fabrique l'outil du LLM tout seul**.

```json
{
  "nom": "ma_brique_faire",
  "description": "Quand l'appeler (le LLM se décide sur CETTE phrase — sois précis).",
  "methode": "POST",
  "chemin": "/faire",
  "params": { "cible": { "type": "string", "description": "…" } },
  "action": true
}
```
- **`action: true`** = écrit/modifie ⇒ **porte de confirmation automatique** (voir plus bas). Toute
  écriture DOIT le porter.
- **`action: false`** = lecture ⇒ exécuté directement.
- `niveau ≥ 1` = outil **différé** derrière `competence_charger` (divulgation progressive S90) si tu
  ne veux pas qu'il pèse en permanence sur le contexte.
- Limite : seuls les contrats **JSON** sont déclarables (`_appel_dynamique` ne sait que le JSON).
  Un flux binaire (audio, multipart, image) reste appelé en direct par son client.

Preuve : `curl /capacites` liste `ma_brique_faire`, puis l'assistant l'utilise. **Aucun fichier du
Cœur édité.**

---

## Voie B — outil en dur dans le Cœur
Pour les outils qui ne tiennent pas en un appel JSON. Trois éditions :

### 1. La spec function-calling — `core/outils.py`, liste `OUTILS`
Ajoute l'entrée dans la **bonne section** (LECTURE ou ACTION — l'ordre présenté au LLM compte, ne
le resplit pas par domaine) :
```python
{"type": "function", "function": {
    "name": "mon_outil",
    "description": "Quand l'appeler (le LLM se décide là-dessus).",
    "parameters": _p({
        "cible": {"type": "string"},
        "confirme": {"type": "boolean"},   # ← présent SI c'est une action
    }, ["cible"])}},
```

### 2. Le dispatch — `core/outils_domaines/<domaine>.py`
Chaque domaine expose `async def dispatch(nom, args, registre, client) -> str | None` : renvoie une
chaîne si le nom lui appartient, sinon `None`. Ajoute ta branche dans le domaine qui correspond
(systeme/agenda/forge/usine/studio/documents/transcription/amelioration), ou crée un nouveau module
et inscris-le dans `_DISPATCHERS` (`core/outils.py`).
```python
if nom == "mon_outil":
    if args.get("action") and not args.get("confirme"):
        return _confirmation("mon_outil", args.get("cible", ""))   # porte
    # … appel HTTP via les helpers de outils_communs …
    return json.dumps(resultat, ensure_ascii=False)
```
`executer` (dans `outils.py`) interroge chaque dispatcher dans l'ordre, garde le `try/except`
centralisé, et retombe sur les capacités dynamiques (Voie A) si aucun dispatcher ne reconnaît le nom.

### 3. Les helpers HTTP — `core/outils_communs.py`
Mutualise les appels (`_forge_appel`, `_studio_appel`, `_appel_dynamique`…). Si tes tests
**appellent** (ne patchent pas) un interne, ré-exporte-le depuis `outils.py` (motif S115).

---

## La porte de confirmation (vaut pour A **et** B)
Toute action qui **modifie l'état** est gardée : `core/outils_communs.py::_confirmation` renvoie un
`confirmation_requise: true` qui force le LLM à **redemander l'accord** à l'utilisateur, puis à
rappeler le **même** outil avec `confirme=true`. Le tap d'un bouton suggéré (S76) **injecte un
message**, il ne court-circuite **jamais** la porte.

- Voie A : la porte est **automatique** dès `action: true` dans le manifest
  (`_appel_dynamique` : `if cap.get("action") and not confirme`).
- Voie B : tu l'appelles toi-même au début du dispatch (`if args.get("action") and not confirme`).

> **Ne JAMAIS auto-câbler une capacité d'écriture sans porte.** C'est un invariant du projet (gate
> humain), couvert par `core/test_s122_atelier_branchees.py`.

## Tester
- Voie A : `make smoke` (contrat manifest) + `curl /capacites` + preuve assistant.
- Voie B : tests Cœur ciblés — `pytest -c /dev/null core/test_outils*.py` (la `pytest.ini` racine
  scope `pytest` nu sur `tests/`, d'où le `-c /dev/null` pour les tests du Cœur). Vérifie la
  **non-régression** contre une baseline worktree (le sandbox a 78 échecs pré-existants `/data` +
  `_FakeClient` — ne lis jamais les compteurs bruts).
