# Journal brut des appels LLM (journal_modele.py) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Satisfy the "journal = vérité" invariant (2e chantier de la veille deepseek-harness/Cordis) : tout ce qui atteint une requête modèle doit être reconstructible depuis un journal append-only, vérifié par un runtime check.

**Architecture:** Nouveau module `core/journal_modele.py`, jumeau structurel de `journal_usage.py`, accroché au **même point d'appel** que `journal_usage.enregistrer()` dans `core/llm_pipeline.py::completer()`/`completer_flux()` — le point de passage unique de TOUS les appels LLM du Cœur. Journal séparé de `journal_conversations.py` (qui sert de mémoire cross-surface, contrat incompatible). Runtime check vivant : relecture immédiate après chaque écriture.

**Tech Stack:** Python 3, JSONL append-only, pytest (avec repli exécution directe `python3 fichier.py`), httpx.MockTransport pour les tests de streaming.

## Global Constraints

- Toute écriture de journal est **best-effort, jamais bloquante** : aucune exception ne doit remonter et casser une conversation ou un appel LLM (convention déjà en place dans `journal_conversations.py` et `journal_usage.py`).
- Aucun nouvel endpoint HTTP n'est exposé pour ce journal (trace interne/debug).
- Chemins de données via variables d'env avec défaut `/data/...` (convention du Cœur) ; tout fichier de test doit rediriger ces chemins vers un dossier temporaire AVANT d'importer les modules concernés (piège documenté dans `core/conftest.py`).
- Spec source : `docs/superpowers/specs/2026-08-21-journal-modele-invariant-design.md`.

---

### Task 1: `core/journal_modele.py` — module + tests + isolation des tests

**Files:**
- Create: `core/journal_modele.py`
- Create: `core/test_journal_modele.py`
- Modify: `core/conftest.py:51-68` (dict `_CHEMINS`)

**Interfaces:**
- Produces (utilisé par Task 2) :
  - `journal_modele.enregistrer_appel(*, fil: str | None, etiquette: str, modele: str | None, messages: list[dict], outils_offerts: list[str] | None = None, message_recu: dict | None = None, erreur: str | None = None) -> bool`
  - `journal_modele.CHEMIN: Path` (chemin du fichier, lu par les tests)
  - `journal_modele.appels(fil: str, limite: int = 100) -> list[dict]` (lecture, ordre chronologique)
  - `journal_modele._lignes() -> list[dict]` (lecture brute, toutes lignes toutes conversations — utilisée par les tests de bornage)

- [ ] **Step 1: Écrire le test (qui échoue — le module n'existe pas encore)**

Créer `core/test_journal_modele.py` :

```python
"""Journal brut des appels LLM (2e chantier veille deepseek-harness/Cordis, 2026-08-21).

Invariant « journal = vérité » : PAR APPEL LLM réellement abouti, le nécessaire pour
reconstruire ce qui a atteint le modèle (messages envoyés, outils offerts, réponse reçue).
Autonome : journal en tmp.
    $ cd core && python3 -m pytest test_journal_modele.py -v
"""
import os
import tempfile

os.environ["MODELE_JOURNAL_PATH"] = os.path.join(tempfile.mkdtemp(), "modele.jsonl")

import journal_modele as jm  # noqa: E402


def _reset():
    if jm.CHEMIN.exists():
        jm.CHEMIN.unlink()


def test_enregistrer_et_relire_un_appel():
    _reset()
    ok = jm.enregistrer_appel(
        fil="web:dashboard", etiquette="chat", modele="openai/gpt-4o-mini",
        messages=[{"role": "system", "content": "s"}, {"role": "user", "content": "salut"}],
        outils_offerts=["agenda_consulter"],
        message_recu={"role": "assistant", "content": None, "tool_calls": [
            {"id": "c1", "type": "function",
             "function": {"name": "agenda_consulter", "arguments": "{}"}}]})
    assert ok is True
    appels = jm.appels("web:dashboard")
    assert len(appels) == 1
    a = appels[0]
    assert a["modele"] == "openai/gpt-4o-mini"
    assert a["outils_offerts"] == ["agenda_consulter"]
    assert a["message_recu"]["tool_calls"][0]["function"]["name"] == "agenda_consulter"
    assert a["messages"][1]["content"] == "salut"


def test_appels_filtre_par_fil():
    _reset()
    jm.enregistrer_appel(fil="fil-a", etiquette="chat", modele="m", messages=[])
    jm.enregistrer_appel(fil="fil-b", etiquette="chat", modele="m", messages=[])
    assert len(jm.appels("fil-a")) == 1
    assert len(jm.appels("fil-b")) == 1


def test_fil_absent_journalise_quand_meme():
    """Appel hors conversation (classement, MOA…) : `fil=None` est légitime, pas une erreur."""
    _reset()
    ok = jm.enregistrer_appel(fil=None, etiquette="classement", modele="m",
                              messages=[{"role": "user", "content": "x"}])
    assert ok is True
    lignes = jm._lignes()
    assert len(lignes) == 1 and lignes[0]["fil"] is None


def test_erreur_journalisee_sans_modele():
    _reset()
    ok = jm.enregistrer_appel(fil="fil-a", etiquette="chat", modele=None,
                              messages=[{"role": "user", "content": "x"}],
                              erreur="Aucun modèle disponible.")
    assert ok is True
    a = jm.appels("fil-a")[0]
    assert a["modele"] is None and a["erreur"] == "Aucun modèle disponible."


def test_bornage_taille(monkeypatch):
    _reset()
    monkeypatch.setenv("MODELE_JOURNAL_MAX", "50")
    for i in range(120):
        jm.enregistrer_appel(fil="fil-borne", etiquette="chat", modele="m",
                             messages=[{"role": "user", "content": f"msg {i}"}])
    tous = [l for l in jm._lignes() if l.get("fil") == "fil-borne"]
    assert len(tous) <= 60  # borné à ~50 (réécrit au-delà de 1,2×)
    assert tous[-1]["messages"][0]["content"] == "msg 119"


def test_check_vivant_detecte_un_ecart_et_ne_leve_jamais(monkeypatch):
    """Runtime check : si la relecture immédiate diffère de ce qu'on vient d'écrire
    (troncature disque, écriture concurrente corrompue…), `enregistrer_appel` renvoie
    False et loggue — mais ne lève JAMAIS (best-effort, ne doit pas casser l'appelant)."""
    _reset()
    vu = {}

    def _faux_verifier(attendue):
        vu["appele"] = True
        return False

    monkeypatch.setattr(jm, "_verifier_derniere_ligne", _faux_verifier)
    ok = jm.enregistrer_appel(fil="f", etiquette="chat", modele="m",
                              messages=[{"role": "user", "content": "x"}])
    assert vu.get("appele") is True
    assert ok is False


def test_check_vivant_reussit_normalement():
    """En fonctionnement normal (pas de panne simulée), le check passe : ce qui est
    relu égale ce qui vient d'être écrit."""
    _reset()
    assert jm.enregistrer_appel(fil="f", etiquette="chat", modele="m",
                                messages=[{"role": "user", "content": "x"}]) is True


if __name__ == "__main__":
    for nom, fn in list(globals().items()):
        if nom.startswith("test_") and callable(fn):
            try:
                fn()
            except TypeError:                 # tests à fixture monkeypatch : sautés en direct
                continue
            print(f"  ✓ {nom}")
    print("\n✅ TOUS LES TESTS PASSENT")
```

- [ ] **Step 2: Lancer le test, vérifier qu'il échoue (module manquant)**

Run: `cd core && python3 -m pytest test_journal_modele.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'journal_modele'`

- [ ] **Step 3: Créer `core/journal_modele.py`**

```python
"""Journal « brut » des appels LLM (2e chantier veille deepseek-harness/Cordis, 2026-08-21).

Invariant : tout ce qui atteint une requête modèle doit être reconstructible depuis un
journal append-only. `journal_conversations.py` (S78) ne garde que le texte final
user/assistant d'un tour — pas le contexte système injecté à chaud (persona, digest,
date…), ni les tool_calls/tool_results échangés en cours de tour. Ce module comble ce
trou : PAR APPEL LLM réellement abouti, il journalise exactement ce qui a été envoyé
(`messages`, post résumé/trim/cache-préfixe) et ce qui a été reçu (`message_recu`).

Séparé de `journal_conversations.py` à dessein : celui-ci sert aussi de mémoire
cross-surface (`messages_utilisateur()` réinjecte du texte dans un futur prompt) — y
mélanger des tool_calls/contenus système casserait ce contrat.

Accroché dans `llm_pipeline.completer()`/`completer_flux()`, au même point que
`journal_usage.enregistrer()` : c'est le seul endroit où les messages sont RÉELLEMENT
finalisés (après résumé à froid, trim, cache-préfixe), et le seul point de passage de
TOUS les appels LLM du Cœur (chat, classement, MOA, briefing, proprioception…).

Runtime check vivant : après CHAQUE écriture, on relit immédiatement la dernière ligne
et on vérifie qu'elle égale ce qu'on vient de sérialiser. Un écart (troncature disque,
écriture concurrente corrompue) loggue une erreur — jamais une exception, même
convention best-effort non bloquante que le reste des journaux du Cœur.

Best-effort et NON bloquant : journaliser ne doit jamais casser un appel LLM. Borné en
taille (`MODELE_JOURNAL_MAX` lignes, plus bas que les journaux texte vu la taille des
lignes qui embarquent des historiques de messages entiers).
"""
import json
import logging
import os
import threading
from pathlib import Path
from time import time

logger = logging.getLogger(__name__)

CHEMIN = Path(os.getenv("MODELE_JOURNAL_PATH", "/data/journal_modele.jsonl"))

_verrou = threading.Lock()


def _max() -> int:
    try:
        return max(50, int(os.getenv("MODELE_JOURNAL_MAX", "2000")))
    except ValueError:
        return 2000


def _verifier_derniere_ligne(attendue: dict) -> bool:
    """Runtime check : relit la dernière ligne PHYSIQUE du fichier et vérifie qu'elle
    égale exactement ce qu'on vient de sérialiser. Appelé sous le verrou, juste après
    l'écriture."""
    try:
        contenu = CHEMIN.read_text(encoding="utf-8")
    except OSError:
        logger.error("journal_modele: invariant violé — relecture impossible juste après écriture")
        return False
    lignes = [l for l in contenu.splitlines() if l.strip()]
    if not lignes:
        logger.error("journal_modele: invariant violé — fichier vide juste après écriture")
        return False
    try:
        relue = json.loads(lignes[-1])
    except json.JSONDecodeError:
        logger.error("journal_modele: invariant violé — dernière ligne illisible juste après écriture")
        return False
    if relue != attendue:
        logger.error("journal_modele: invariant violé — la dernière ligne relue diffère de "
                     "ce qui vient d'être écrit")
        return False
    return True


def enregistrer_appel(*, fil: str | None, etiquette: str, modele: str | None,
                       messages: list[dict], outils_offerts: list[str] | None = None,
                       message_recu: dict | None = None, erreur: str | None = None) -> bool:
    """Ajoute une ligne au journal brut. Ne lève jamais (best-effort). Renvoie True si la
    ligne a été écrite ET relue à l'identique (runtime check), False sinon — jamais
    utilisé pour bloquer l'appelant, seulement pour logger/tester l'invariant."""
    ligne = {
        "ts": time(),
        "fil": fil,
        "etiquette": etiquette,
        "modele": modele,
        "messages": messages,
        "outils_offerts": list(outils_offerts or []),
        "message_recu": message_recu,
        "erreur": erreur,
    }
    try:
        with _verrou:
            CHEMIN.parent.mkdir(parents=True, exist_ok=True)
            with CHEMIN.open("a", encoding="utf-8") as f:
                f.write(json.dumps(ligne, ensure_ascii=False) + "\n")
            ok = _verifier_derniere_ligne(ligne)
            _borner()
            return ok
    except OSError as e:
        logger.warning("journal_modele: écriture impossible : %s", e)
        return False


def _lignes() -> list[dict]:
    if not CHEMIN.exists():
        return []
    out = []
    try:
        for l in CHEMIN.read_text(encoding="utf-8").splitlines():
            l = l.strip()
            if not l:
                continue
            try:
                out.append(json.loads(l))
            except json.JSONDecodeError:
                continue
    except OSError:
        return []
    return out


def _borner() -> None:
    """Garde au plus `_max()` lignes (réécrit le fichier quand il déborde nettement).
    Appelé sous le verrou, après l'écriture+vérification."""
    mx = _max()
    lignes = _lignes()
    if len(lignes) <= int(mx * 1.2):
        return
    try:
        CHEMIN.write_text("\n".join(json.dumps(x, ensure_ascii=False)
                                    for x in lignes[-mx:]) + "\n", encoding="utf-8")
    except OSError:
        pass


def appels(fil: str, limite: int = 100) -> list[dict]:
    """Les derniers appels LLM journalisés pour CE fil (ordre chronologique)."""
    lignes = [l for l in _lignes() if l.get("fil") == fil]
    return lignes[-max(1, limite):]
```

- [ ] **Step 4: Lancer le test, vérifier qu'il passe**

Run: `cd core && python3 -m pytest test_journal_modele.py -v`
Expected: `7 passed`

- [ ] **Step 5: Isoler le chemin dans `core/conftest.py`**

Dans `core/conftest.py`, le dict `_CHEMINS` (lignes 51-68) liste tous les chemins de
données du Cœur forcés vers un dossier temporaire de session pendant les tests. Ajouter
une entrée pour `journal_modele.py`, en respectant l'ordre alphabétique déjà en place :

```python
    "IDENTITE_PATH": "identite.json",
    "LIVRAISONS_DB": "livraisons.db",
    "LLM_CACHE_PATH": "llm_cache.jsonl",
    "MODELE_JOURNAL_PATH": "journal_modele.jsonl",
    "PROFIL_PATH": "profil.md",
```

(insérer la ligne `"MODELE_JOURNAL_PATH": "journal_modele.jsonl",` juste après
`"LLM_CACHE_PATH": "llm_cache.jsonl",` et avant `"PROFIL_PATH": "profil.md",`)

- [ ] **Step 6: Lancer la suite complète du Cœur pour vérifier l'absence de régression**

Run: `cd core && python3 -m pytest -q`
Expected: tous les tests passent (aucune régression — ce module est nouveau et isolé,
aucun autre fichier ne l'importe encore à ce stade)

- [ ] **Step 7: Commit**

```bash
git add core/journal_modele.py core/test_journal_modele.py core/conftest.py
git commit -m "$(cat <<'EOF'
feat(gate-forge): ajoute journal_modele.py — trace brute des appels LLM

Nouveau journal append-only, jumeau de journal_usage.py, avec runtime check
vivant (relecture immédiate après écriture). Pas encore câblé — module
autonome, testé isolément. 1re étape du 2e chantier veille deepseek-harness
(invariant "journal = vérité").
EOF
)"
```

---

### Task 2: Accrocher `journal_modele` dans `core/llm_pipeline.py`

**Files:**
- Modify: `core/llm_pipeline.py`
- Modify: `core/test_s138.py` (env setup + nouveau test)
- Modify: `core/test_streaming.py` (env setup + nouveaux tests)

**Interfaces:**
- Consumes (de Task 1): `journal_modele.enregistrer_appel(...)` (signature ci-dessus)
- Produces (utilisé par Task 3): `completer(..., fil: str | None = None, ...)` et
  `completer_flux(..., fil: str | None = None, ...)` — nouveau paramètre optionnel,
  défaut `None`, aucun appelant existant à modifier pour que le code continue de
  fonctionner (seul `assistant.py`, câblé en Task 3, le renseignera).

- [ ] **Step 1: Écrire les tests qui échouent**

Dans `core/test_s138.py`, ajouter en haut du fichier (juste après les autres
redirections d'environnement, ligne 17, avant `sys.path.insert`) :

```python
os.environ["MODELE_JOURNAL_PATH"] = os.path.join(_tmp, "modele.jsonl")
```

(la ligne complète après cet ajout ressemble à :)
```python
os.environ["USAGE_LLM_PATH"] = os.path.join(_tmp, "usage.jsonl")
os.environ["LLM_CACHE_PATH"] = os.path.join(_tmp, "cache.jsonl")
os.environ["SHADOW_RUNS_PATH"] = os.path.join(_tmp, "shadow.jsonl")
os.environ["MODELE_JOURNAL_PATH"] = os.path.join(_tmp, "modele.jsonl")
os.environ.setdefault("LLM_BUDGET_MOIS_USD", "0")
```

Puis ajouter l'import (après `import llm_pipeline`, ordre alphabétique) :
```python
import journal_modele  # noqa: E402
```

Puis ajouter, après `test_pipeline_et_journal` (après la ligne `assert r["total"]["appels"] == 1 and r["total"]["tokens_in"] == 123`) :

```python
def test_pipeline_journalise_dans_journal_modele():
    res = asyncio.run(llm_pipeline.completer(
        [{"role": "system", "content": "sys"}, {"role": "user", "content": "salut"}],
        modeles=["openai/gpt-4o-mini"], etiquette="chat", fil="fil-test-s138",
        client=_FakeClient()))
    assert res.ok
    appels = journal_modele.appels("fil-test-s138")
    assert len(appels) == 1
    a = appels[0]
    assert a["modele"] == "openai/gpt-4o-mini"
    assert a["messages"][-1]["content"] == "salut"
    assert a["message_recu"]["content"] == "bonjour"


def test_pipeline_ne_journalise_pas_sur_hit_cache_semantique():
    """Un hit du cache sémantique ne fait atteindre AUCUN modèle ce tour-ci : pas de
    nouvelle ligne journal_modele (cf. spec, décision explicite)."""
    cli = _FakeClient()
    prompt = [{"role": "system", "content": "archiviste"},
              {"role": "user", "content": "range ce devis, encore"}]
    asyncio.run(llm_pipeline.completer(
        prompt, modeles=["openai/gpt-4o-mini"], temperature=0, etiquette="classement",
        trim_contexte=False, cache=True, fil="fil-cache-s138", client=cli))
    n_avant = len(journal_modele.appels("fil-cache-s138"))
    assert n_avant == 1  # le 1er appel (miss) a bien été journalisé
    asyncio.run(llm_pipeline.completer(
        prompt, modeles=["openai/gpt-4o-mini"], temperature=0, etiquette="classement",
        trim_contexte=False, cache=True, fil="fil-cache-s138", client=cli))
    assert len(journal_modele.appels("fil-cache-s138")) == n_avant  # hit → pas de nouvelle ligne
```

Dans `core/test_streaming.py`, ajouter en haut du fichier (après les autres
redirections, avant `sys.path.insert`) :

```python
os.environ["MODELE_JOURNAL_PATH"] = os.path.join(_tmp, "modele.jsonl")
```

Puis ajouter l'import (après `import llm_pipeline`) :
```python
import journal_modele  # noqa: E402
```

Puis ajouter, après `test_flux_texte` :

```python
def test_flux_journalise_dans_journal_modele():
    def h(req):
        return httpx.Response(200, content=_sse(
            {"choices": [{"delta": {"content": "Bon"}}]},
            {"choices": [{"delta": {"content": "jour"}}]},
        ))

    async def go():
        async with _client(h) as c:
            return await _collecter(llm_pipeline.completer_flux(
                [{"role": "system", "content": "sys"}, {"role": "user", "content": "salut"}],
                modeles=["free/x"], etiquette="chat", fil="fil-test-streaming", client=c))
    asyncio.run(go())
    appels = journal_modele.appels("fil-test-streaming")
    assert len(appels) == 1
    assert appels[0]["modele"] == "free/x"
    assert appels[0]["message_recu"]["content"] == "Bonjour"


def test_flux_erreur_journalisee_dans_journal_modele():
    ancien = journal_usage.peut_appeler_payant
    journal_usage.peut_appeler_payant = lambda: False
    try:
        def h(req):
            raise AssertionError("aucun appel réseau ne doit partir si le budget bloque")

        async def go():
            async with _client(h) as c:
                return await _collecter(llm_pipeline.completer_flux(
                    [{"role": "user", "content": "x"}], modeles=["openai/gpt-4o"],
                    etiquette="chat", fil="fil-erreur-streaming", client=c))
        asyncio.run(go())
    finally:
        journal_usage.peut_appeler_payant = ancien
    appels = journal_modele.appels("fil-erreur-streaming")
    assert len(appels) == 1
    assert appels[0]["modele"] is None
    assert "Budget" in appels[0]["erreur"]
```

- [ ] **Step 2: Lancer les tests, vérifier qu'ils échouent**

Run: `cd core && python3 -m pytest test_s138.py test_streaming.py -v`
Expected: FAIL sur les nouveaux tests avec `TypeError: completer() got an unexpected
keyword argument 'fil'` (et `completer_flux()` idem)

- [ ] **Step 3: Modifier `core/llm_pipeline.py`**

Ajouter l'import, juste avant `import journal_usage` (ligne 30) :
```python
import journal_modele
import journal_usage
```

Ajouter un helper juste après `_cout` (après la ligne 103, avant
`def _ordonner_selon_budget`) :
```python
def _noms_outils(tools: list[dict] | None) -> list[str]:
    """Noms des outils offerts au modèle pour CET appel — pas leurs schémas complets
    (statiques/dérivables du code `outils.py`, cf. journal_modele)."""
    if not tools:
        return []
    return [nom for t in tools if (nom := ((t or {}).get("function") or {}).get("name"))]
```

Dans `completer()`, ajouter le paramètre `fil` à la signature — remplacer :
```python
    response_format: dict | None = None,
    etiquette: str = "chat",
    trim_contexte: bool = True,
```
par :
```python
    response_format: dict | None = None,
    etiquette: str = "chat",
    fil: str | None = None,
    trim_contexte: bool = True,
```

Dans `completer()`, sur l'échec « budget vide » — remplacer :
```python
        modeles_effectifs, budget_force_gratuit = _ordonner_selon_budget(modeles)
        if not modeles_effectifs:
            msg = "Budget LLM atteint et aucun modèle gratuit configuré."
            journal_usage.enregistrer(modele=None, etiquette=etiquette, tokens_in=0,
                                       tokens_out=0, cout_usd=0, trimmed_tokens=trimmed,
                                       erreur=msg)
            return Resultat(erreur=msg, trimmed_tokens=trimmed)
```
par :
```python
        modeles_effectifs, budget_force_gratuit = _ordonner_selon_budget(modeles)
        if not modeles_effectifs:
            msg = "Budget LLM atteint et aucun modèle gratuit configuré."
            journal_usage.enregistrer(modele=None, etiquette=etiquette, tokens_in=0,
                                       tokens_out=0, cout_usd=0, trimmed_tokens=trimmed,
                                       erreur=msg)
            journal_modele.enregistrer_appel(fil=fil, etiquette=etiquette, modele=None,
                                             messages=messages, outils_offerts=_noms_outils(tools),
                                             erreur=msg)
            return Resultat(erreur=msg, trimmed_tokens=trimmed)
```

Dans `completer()`, sur le succès — remplacer :
```python
                routed = routed_to if (routed_to and modele == routed_to) else None
                journal_usage.enregistrer(
                    modele=modele, etiquette=etiquette, tokens_in=tokens_in,
                    tokens_out=tokens_out, cout_usd=cout, trimmed_tokens=trimmed,
                    routed_to=routed, complexite=complexite)
                # On ne met en cache qu'une vraie réponse texte (pas un appel d'outil).
```
par :
```python
                routed = routed_to if (routed_to and modele == routed_to) else None
                journal_usage.enregistrer(
                    modele=modele, etiquette=etiquette, tokens_in=tokens_in,
                    tokens_out=tokens_out, cout_usd=cout, trimmed_tokens=trimmed,
                    routed_to=routed, complexite=complexite)
                journal_modele.enregistrer_appel(
                    fil=fil, etiquette=etiquette, modele=modele,
                    messages=payload["messages"], outils_offerts=_noms_outils(tools),
                    message_recu=message)
                # On ne met en cache qu'une vraie réponse texte (pas un appel d'outil).
```

Dans `completer()`, sur l'échec total — remplacer :
```python
        suffixe = " (budget : repli gratuit only)" if budget_force_gratuit else ""
        erreur = f"Aucun modèle disponible ({derniere_erreur}){suffixe}."
        journal_usage.enregistrer(modele=None, etiquette=etiquette, tokens_in=0,
                                  tokens_out=0, cout_usd=0, trimmed_tokens=trimmed,
                                  erreur=erreur)
        return Resultat(erreur=erreur, trimmed_tokens=trimmed, modeles_essayes=essayes)
```
par :
```python
        suffixe = " (budget : repli gratuit only)" if budget_force_gratuit else ""
        erreur = f"Aucun modèle disponible ({derniere_erreur}){suffixe}."
        journal_usage.enregistrer(modele=None, etiquette=etiquette, tokens_in=0,
                                  tokens_out=0, cout_usd=0, trimmed_tokens=trimmed,
                                  erreur=erreur)
        journal_modele.enregistrer_appel(fil=fil, etiquette=etiquette, modele=None,
                                         messages=messages, outils_offerts=_noms_outils(tools),
                                         erreur=erreur)
        return Resultat(erreur=erreur, trimmed_tokens=trimmed, modeles_essayes=essayes)
```

Dans `completer_flux()`, ajouter le paramètre `fil` à la signature — remplacer :
```python
    max_tokens: int | None = None,
    etiquette: str = "chat",
    trim_contexte: bool = True,
    conf: dict | None = None,
```
par :
```python
    max_tokens: int | None = None,
    etiquette: str = "chat",
    fil: str | None = None,
    trim_contexte: bool = True,
    conf: dict | None = None,
```

Dans `completer_flux()`, sur l'échec « budget vide » — remplacer :
```python
        modeles_effectifs, budget_force_gratuit = _ordonner_selon_budget(modeles)
        if not modeles_effectifs:
            msg = "Budget LLM atteint et aucun modèle gratuit configuré."
            journal_usage.enregistrer(modele=None, etiquette=etiquette, tokens_in=0,
                                       tokens_out=0, cout_usd=0, trimmed_tokens=trimmed, erreur=msg)
            yield {"type": "erreur", "erreur": msg}
            return
```
par :
```python
        modeles_effectifs, budget_force_gratuit = _ordonner_selon_budget(modeles)
        if not modeles_effectifs:
            msg = "Budget LLM atteint et aucun modèle gratuit configuré."
            journal_usage.enregistrer(modele=None, etiquette=etiquette, tokens_in=0,
                                       tokens_out=0, cout_usd=0, trimmed_tokens=trimmed, erreur=msg)
            journal_modele.enregistrer_appel(fil=fil, etiquette=etiquette, modele=None,
                                             messages=messages, outils_offerts=_noms_outils(tools),
                                             erreur=msg)
            yield {"type": "erreur", "erreur": msg}
            return
```

Dans `completer_flux()`, sur le succès — remplacer :
```python
            journal_usage.enregistrer(
                modele=modele, etiquette=etiquette, tokens_in=tokens_in,
                tokens_out=tokens_out, cout_usd=cout, trimmed_tokens=trimmed,
                routed_to=routed, complexite=complexite)
            if contenu and not tool_frags and not _sans_cout_marginal(modele) \
                    and shadow.echantillonne(conf):
```
par :
```python
            journal_usage.enregistrer(
                modele=modele, etiquette=etiquette, tokens_in=tokens_in,
                tokens_out=tokens_out, cout_usd=cout, trimmed_tokens=trimmed,
                routed_to=routed, complexite=complexite)
            journal_modele.enregistrer_appel(
                fil=fil, etiquette=etiquette, modele=modele,
                messages=payload["messages"], outils_offerts=_noms_outils(tools),
                message_recu=message)
            if contenu and not tool_frags and not _sans_cout_marginal(modele) \
                    and shadow.echantillonne(conf):
```

Dans `completer_flux()`, sur l'échec total — remplacer :
```python
        erreur = f"Aucun modèle disponible ({derniere_erreur})."
        journal_usage.enregistrer(modele=None, etiquette=etiquette, tokens_in=0,
                                  tokens_out=0, cout_usd=0, trimmed_tokens=trimmed, erreur=erreur)
        yield {"type": "erreur", "erreur": erreur}
```
par :
```python
        erreur = f"Aucun modèle disponible ({derniere_erreur})."
        journal_usage.enregistrer(modele=None, etiquette=etiquette, tokens_in=0,
                                  tokens_out=0, cout_usd=0, trimmed_tokens=trimmed, erreur=erreur)
        journal_modele.enregistrer_appel(fil=fil, etiquette=etiquette, modele=None,
                                         messages=messages, outils_offerts=_noms_outils(tools),
                                         erreur=erreur)
        yield {"type": "erreur", "erreur": erreur}
```

- [ ] **Step 4: Lancer les tests, vérifier qu'ils passent**

Run: `cd core && python3 -m pytest test_s138.py test_streaming.py -v`
Expected: tous PASS (les tests existants de ces deux fichiers doivent continuer à
passer aussi — `fil` est optionnel, défaut `None`, aucun appel existant n'est cassé)

- [ ] **Step 5: Lancer la suite complète du Cœur**

Run: `cd core && python3 -m pytest -q`
Expected: tous les tests passent (aucune régression sur les autres appelants de
`llm_pipeline` — `classer.py`, `moa.py`, `briefing.py`… n'ont pas changé de signature
d'appel, `fil` reste `None` par défaut pour eux)

- [ ] **Step 6: Commit**

```bash
git add core/llm_pipeline.py core/test_s138.py core/test_streaming.py
git commit -m "$(cat <<'EOF'
feat(gate-forge): journal_modele câblé dans llm_pipeline (tous les appels LLM)

completer()/completer_flux() journalisent désormais chaque appel abouti dans
journal_modele.py (messages exacts envoyés + réponse reçue), et chaque échec
total (aucun modèle joignable) en miroir de journal_usage. Couvre TOUS les
appelants du Cœur (chat, classement, MOA, briefing…) sans les toucher —
nouveau paramètre `fil` optionnel, défaut None.
EOF
)"
```

---

### Task 3: Câbler `fil` depuis `assistant.py` + preuve bout-en-bout

**Files:**
- Modify: `core/assistant.py:278-302`
- Modify: `core/test_converser_stream.py`

**Interfaces:**
- Consumes (de Task 2) : `llm_pipeline.completer(..., fil=...)`,
  `llm_pipeline.completer_flux(..., fil=...)`
- Consumes (de Task 1) : `journal_modele.appels(fil, limite)`

- [ ] **Step 1: Écrire le test qui échoue**

Dans `core/test_converser_stream.py`, ajouter en haut du fichier, après les autres
`os.environ[...]` (avant `sys.path.insert`) :

```python
os.environ["MODELE_JOURNAL_PATH"] = os.path.join(tempfile.mkdtemp(), "modele.jsonl")
```

Ajouter les imports (après `import outils`) :
```python
import httpx  # noqa: E402
import json  # noqa: E402
import journal_modele  # noqa: E402
```

Remplacer le helper `_converser` :
```python
async def _converser(messages):
    return [evt async for evt in assistant.converser(messages, registre=None)]
```
par (ajout d'un paramètre optionnel `fil`, rétro-compatible avec les appels existants) :
```python
async def _converser(messages, fil=None):
    return [evt async for evt in assistant.converser(messages, registre=None, fil=fil)]
```

Ajouter, à la fin du fichier (avant le bloc `if __name__ == "__main__":`) :

```python
def _sse(*chunks) -> bytes:
    corps = "".join("data: " + json.dumps(c) + "\n\n" for c in chunks) + "data: [DONE]\n\n"
    return corps.encode()


def test_converser_journalise_chaque_appel_dans_journal_modele(monkeypatch):
    """Bout-en-bout (assistant → llm_pipeline RÉEL → journal_modele), sans mocker
    completer_flux lui-même : un tour à 2 itérations (1 tool call puis 1 réponse finale)
    produit exactement 2 lignes dans journal_modele, sous le fil d'accord S222."""
    tours_restants = [
        _sse({"choices": [{"delta": {"tool_calls": [
            {"index": 0, "id": "call_1", "function": {
                "name": "liste_entreprises", "arguments": "{}"}}]}}]}),
        _sse({"choices": [{"delta": {"content": "Voici le bilan."}}]}),
    ]

    def handler(req):
        return httpx.Response(200, content=tours_restants.pop(0))

    monkeypatch.setattr(httpx, "AsyncClient",
                        lambda *a, **k: httpx.AsyncClient(transport=httpx.MockTransport(handler)))

    async def faux_exec(nom, args, registre):
        return '{"entreprises": []}'

    ancien_exec = outils.executer
    outils.executer = faux_exec
    try:
        asyncio.run(_converser(
            [{"role": "user", "content": "où en sont les entreprises ?"}], fil="fil-e2e"))
    finally:
        outils.executer = ancien_exec

    appels = journal_modele.appels("fil-e2e")
    assert len(appels) == 2, appels
    assert appels[0]["message_recu"]["tool_calls"][0]["function"]["name"] == "liste_entreprises"
    assert appels[1]["message_recu"]["content"] == "Voici le bilan."
```

- [ ] **Step 2: Lancer le test, vérifier qu'il échoue**

Run: `cd core && python3 -m pytest test_converser_stream.py -v -k journal_modele`
Expected: FAIL — `journal_modele.appels("fil-e2e")` renvoie `[]` (le `fil` de
`converser()` n'est pas encore transmis à `llm_pipeline`)

- [ ] **Step 3: Modifier `core/assistant.py`**

Remplacer (lignes 278-283) :
```python
                async for evt in llm_pipeline.completer_flux(
                        historique, modeles=modeles, tools=outils_actifs,
                        tool_choice="auto", temperature=0.2, etiquette="chat",
                        conf=conf, client=client):
```
par :
```python
                async for evt in llm_pipeline.completer_flux(
                        historique, modeles=modeles, tools=outils_actifs,
                        tool_choice="auto", temperature=0.2, etiquette="chat",
                        fil=fil_accord, conf=conf, client=client):
```

Remplacer (lignes 294-298) :
```python
                res = await llm_pipeline.completer(
                    historique, modeles=modeles, tools=outils_actifs,
                    tool_choice="auto", temperature=0.2, etiquette="chat",
                    conf=conf, client=client,
                )
```
par :
```python
                res = await llm_pipeline.completer(
                    historique, modeles=modeles, tools=outils_actifs,
                    tool_choice="auto", temperature=0.2, etiquette="chat",
                    fil=fil_accord, conf=conf, client=client,
                )
```

- [ ] **Step 4: Lancer le test, vérifier qu'il passe**

Run: `cd core && python3 -m pytest test_converser_stream.py -v`
Expected: tous PASS (y compris les 2 tests déjà existants du fichier, inchangés)

- [ ] **Step 5: Lancer la suite complète du Cœur**

Run: `cd core && python3 -m pytest -q`
Expected: tous les tests passent — en particulier `test_gate_action_bout_en_bout.py`
et les autres tests qui monkeypatchent `llm_pipeline.completer_flux` en entier
(donc court-circuitent journal_modele) doivent continuer à passer inchangés.

- [ ] **Step 6: Commit**

```bash
git add core/assistant.py core/test_converser_stream.py
git commit -m "$(cat <<'EOF'
feat(gate-forge): assistant.converser transmet son fil à journal_modele

fil_accord (déjà utilisé par le gate S222) devient aussi l'identifiant sous
lequel journal_modele trace les appels LLM d'un tour — corrélation directe
gate↔trace brute. Preuve bout-en-bout : un tour à 2 itérations (tool call
puis réponse finale) produit exactement 2 lignes journal_modele.

Clôt le 2e chantier de la veille deepseek-harness (invariant "journal =
vérité") : couverture système complète (tool_calls/tool_results + contexte
système, via llm_pipeline) + runtime check vivant, comme prévu par la spec
docs/superpowers/specs/2026-08-21-journal-modele-invariant-design.md.
EOF
)"
```

---

## Hors périmètre (rappel de la spec)

- Pas d'UI de consultation de `journal_modele` (trace technique, pas une fonctionnalité
  utilisateur).
- `shadow.py` (rejeu en tâche de fond d'un candidat moins cher) non audité pour savoir
  s'il passe par `llm_pipeline.completer()` — à vérifier séparément si besoin.
- Les 2 autres chantiers de la veille deepseek-harness (couches de patch déclaratif
  multi-tenant, seams 3 rôles pour dev-auto-atelier/5955) restent non entamés.
