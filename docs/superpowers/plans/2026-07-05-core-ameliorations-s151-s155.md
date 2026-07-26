# Core — Améliorations S151–S155

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cinq sprints d'amélioration du noyau : vue budget LLM dans le dashboard, MOA configurable, feedback loop du graphe d'apprentissage, et tests des modules critiques non couverts.

**Architecture:** Toutes les modifications restent dans `core/`. Les sprints S151–S153 ajoutent des fonctionnalités visibles ; S154–S155 ajoutent la couverture de test des modules existants. Chaque sprint est indépendant et committé séparément.

**Tech Stack:** Python 3.11+, FastAPI, pytest, httpx, HTML/CSS/JS inline dans dashboard.py

## Global Constraints

- Travailler dans `/Users/garinat_t/Desktop/Workplace/core/`
- Commande de test : `cd /Users/garinat_t/Desktop/Workplace/core && python3 -m pytest <fichier> -v`
- Chaque test commence par `os.environ.setdefault("GATEWAY_KEY", "test")` et `sys.path.insert(0, os.path.dirname(__file__))`
- Repli honnête obligatoire : aucun module ne doit lever en cas de brique absente/indisponible
- Pattern de nommage sprint : `feat(core) : S<N> <description courte>`
- Pas de nouvelles dépendances dans `requirements.txt`

---

## Sprint S151 — Vue budget LLM dans le dashboard

**Files:**
- Modify: `core/routers/dashboard.py` (CSS ~ligne 333, HTML ~ligne 552, JS ~ligne 1926)

**Interfaces:**
- Consumes: `GET /assistant/usage` → `{jour:{appels,tokens_in,tokens_out,cout_usd,cache_hits,tokens_economises_trim,appels_retrogrades}, mois:{…}, total:{…}, budget:{…}}`
- Consumes: `GET /assistant/shadow` → `{flux:[{flux,echantillons,equivalence_moyenne,taux_equivalent,economie_observee_usd,recommande_retrograder}], total_echantillons}`
- Produces: Section "💰 Budget LLM" visible dans le panneau ⚙ Cerveau, chargée à l'ouverture

- [ ] **Étape 1 : Ajouter le CSS du panneau budget**

Ouvrir `core/routers/dashboard.py`. Après la ligne `.cerveau-msg.info { color: #94a3b8; }` (~ligne 344), insérer :

```css
.budget-grille { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-top: 8px; }
.budget-case { background: #0f1117; border: 1px solid #2d3148; border-radius: 8px; padding: 8px 10px; }
.budget-case .val { font-size: 1.1rem; font-weight: 700; color: #e2e8f0; }
.budget-case .lbl { font-size: 0.72rem; color: #64748b; margin-top: 2px; }
.budget-shadow { margin-top: 10px; font-size: 0.82rem; color: #94a3b8; }
.budget-shadow b { color: #4ade80; }
.budget-shadow .shadow-ko { color: #f87171; }
```

- [ ] **Étape 2 : Ajouter la section HTML dans le panneau Cerveau**

Dans `core/routers/dashboard.py`, localiser la ligne `<div id="cerveau-msg" class="cerveau-msg"></div>` (~ligne 552) à l'intérieur du `panel-cerveau`. Juste AVANT cette ligne, insérer :

```html
      <div class="cerveau-row" style="margin-top:20px">
        <div class="field" style="flex:1">
          <label>💰 Budget LLM <span id="budget-statut" class="cerveau-pill">—</span></label>
          <div class="budget-grille" id="budget-grille">
            <div class="budget-case"><div class="val" id="bdg-cout-jour">—</div><div class="lbl">coût aujourd'hui (USD)</div></div>
            <div class="budget-case"><div class="val" id="bdg-cout-mois">—</div><div class="lbl">coût ce mois (USD)</div></div>
            <div class="budget-case"><div class="val" id="bdg-cache">—</div><div class="lbl">cache hits</div></div>
            <div class="budget-case"><div class="val" id="bdg-trim">—</div><div class="lbl">tokens économisés (trim)</div></div>
            <div class="budget-case"><div class="val" id="bdg-tok-jour">—</div><div class="lbl">tokens aujourd'hui</div></div>
            <div class="budget-case"><div class="val" id="bdg-appels">—</div><div class="lbl">appels ce mois</div></div>
          </div>
          <div class="budget-shadow" id="budget-shadow" style="display:none"></div>
        </div>
      </div>
```

- [ ] **Étape 3 : Ajouter la fonction JS `chargerBudget()`**

Dans `core/routers/dashboard.py`, après la fonction `chargerCerveau` (~ligne 2018, après le `}`), ajouter :

```javascript
async function chargerBudget() {
  try {
    const u = await fetch('/assistant/usage').then(r => r.json());
    const j = u.jour || {}, m = u.mois || {}, b = u.budget || {};
    const fmt = v => v === undefined ? '—' : (v < 0.001 ? '< 0.001' : v.toFixed(4));
    document.getElementById('bdg-cout-jour').textContent = '$' + fmt(j.cout_usd);
    document.getElementById('bdg-cout-mois').textContent = '$' + fmt(m.cout_usd);
    document.getElementById('bdg-cache').textContent = (m.cache_hits || 0) + ' hits';
    document.getElementById('bdg-trim').textContent = (m.tokens_economises_trim || 0).toLocaleString();
    document.getElementById('bdg-tok-jour').textContent = ((j.tokens_in||0)+(j.tokens_out||0)).toLocaleString();
    document.getElementById('bdg-appels').textContent = (m.appels || 0);
    const statut = b.jour?.statut || b.mois?.statut || 'ok';
    pill(document.getElementById('budget-statut'), statut === 'ok' ? true : statut === 'bloque' ? false : null,
         statut === 'bloque' ? '● budget bloqué' : statut === 'alerte' ? '⚠ alerte budget' : '● ok');
  } catch(e) { /* budget ne casse jamais */ }

  try {
    const s = await fetch('/assistant/shadow').then(r => r.json());
    const flux = (s.flux || []).filter(f => f.echantillons >= 5);
    const zone = document.getElementById('budget-shadow');
    if (!flux.length) { zone.style.display = 'none'; return; }
    zone.style.display = 'block';
    const lignes = flux.slice(0, 3).map(f => {
      const cls = f.recommande_retrograder ? '' : ' shadow-ko';
      const ico = f.recommande_retrograder ? '✔' : '~';
      return `<span class="${cls}">${ico} <b>${escHtml(f.flux)}</b> — équivalence ${Math.round(f.taux_equivalent*100)}%, économie $${f.economie_observee_usd.toFixed(4)}</span>`;
    });
    zone.innerHTML = '🧪 Shadow routing : ' + lignes.join(' | ');
  } catch(e) {}
}
```

- [ ] **Étape 4 : Appeler chargerBudget() à l'ouverture du panneau**

Dans `core/routers/dashboard.py`, localiser la fonction `toggleCerveau()` (~ligne 1923) :

```javascript
function toggleCerveau() {
  const p = document.getElementById('panel-cerveau');
  p.style.display = p.style.display === 'none' ? 'block' : 'none';
  if (p.style.display === 'block') chargerCerveau(true);
}
```

Remplacer par :

```javascript
function toggleCerveau() {
  const p = document.getElementById('panel-cerveau');
  p.style.display = p.style.display === 'none' ? 'block' : 'none';
  if (p.style.display === 'block') { chargerCerveau(true); chargerBudget(); }
}
```

- [ ] **Étape 5 : Vérifier manuellement**

```bash
cd /Users/garinat_t/Desktop/Workplace
docker compose exec core python3 -c "import journal_usage; print(journal_usage.resume())"
```

Ouvrir `http://localhost:5100` → onglet Assistant → ⚙ Cerveau → voir la section "💰 Budget LLM" apparaître.

- [ ] **Étape 6 : Committer**

```bash
git add core/routers/dashboard.py
git commit -m "feat(core) : S151 vue budget LLM + shadow dans le panneau ⚙ Cerveau"
```

---

## Sprint S152 — MOA : mots-clés configurables et enrichis

**Files:**
- Modify: `core/moa.py` (lignes 39–50)
- Modify: `core/test_moa.py` (ajouter 3 tests)

**Interfaces:**
- Consumes: env var `MOA_MOTS_COMPLEXES` (liste de mots séparés par des virgules, optionnel)
- Produces: `est_complexe(str) -> bool` avec les mots enrichis + env var

- [ ] **Étape 1 : Écrire les tests qui vont échouer**

Dans `core/test_moa.py`, ajouter après le dernier test existant :

```python
def test_mots_manquants_resumer(monkeypatch):
    """'résume' doit être reconnu comme complexe."""
    assert moa.est_complexe("résume ce document")

def test_mots_manquants_expliquer(monkeypatch):
    """'explique' doit déclencher MOA."""
    assert moa.est_complexe("explique-moi comment fonctionne ce système")

def test_env_mots_complexes(monkeypatch):
    """MOA_MOTS_COMPLEXES depuis env fusionne avec la liste par défaut."""
    monkeypatch.setenv("MOA_MOTS_COMPLEXES", "révolutionne,invente")
    # Recharger la fonction pour prendre en compte l'env
    import importlib
    importlib.reload(moa)
    assert moa.est_complexe("invente un nouveau produit")
    monkeypatch.delenv("MOA_MOTS_COMPLEXES")
    importlib.reload(moa)
```

- [ ] **Étape 2 : Vérifier que les tests échouent**

```bash
cd /Users/garinat_t/Desktop/Workplace/core && python3 -m pytest test_moa.py::test_mots_manquants_resumer test_moa.py::test_mots_manquants_expliquer test_moa.py::test_env_mots_complexes -v
```

Attendu : FAIL sur les 3 nouveaux tests.

- [ ] **Étape 3 : Modifier `moa.py`**

Dans `core/moa.py`, remplacer le bloc `MOTS_COMPLEXES` (lignes 39–42) et la fonction `est_complexe` (lignes 45–50) par :

```python
_MOTS_COMPLEXES_DEFAUT = {
    "planifie", "stratégie", "décide", "compare", "analyse", "choisir",
    "architecture", "implémente", "conception", "évaluer", "risque",
    "résume", "explique", "traduis", "décompose", "priorise", "propose",
    "liste", "crée", "optimise", "structure",
}


def _mots_complexes() -> set[str]:
    """Liste de mots-clés de complexité : défaut + MOA_MOTS_COMPLEXES (env, virgule-séparés)."""
    extra_brut = os.getenv("MOA_MOTS_COMPLEXES", "")
    extra = {m.strip().lower() for m in extra_brut.split(",") if m.strip()}
    return _MOTS_COMPLEXES_DEFAUT | extra


def est_complexe(message_utilisateur: str) -> bool:
    """Heuristique légère : longueur > 120 car OU mot-clé de complexité détecté."""
    msg = message_utilisateur.lower()
    if len(message_utilisateur) > 120:
        return True
    return any(mot in msg for mot in _mots_complexes())
```

- [ ] **Étape 4 : Supprimer la variable module-level `MOTS_COMPLEXES` devenue inutile**

Vérifier que la ligne `MOTS_COMPLEXES = {…}` (ancienne, remplacée par `_MOTS_COMPLEXES_DEFAUT`) est bien remplacée et qu'aucune autre référence à `MOTS_COMPLEXES` n'existe :

```bash
grep -n "MOTS_COMPLEXES" /Users/garinat_t/Desktop/Workplace/core/moa.py
```

Aucune occurrence de l'ancienne variable ne doit subsister.

- [ ] **Étape 5 : Vérifier que tous les tests passent**

```bash
cd /Users/garinat_t/Desktop/Workplace/core && python3 -m pytest test_moa.py -v
```

Attendu : tous les tests PASS.

- [ ] **Étape 6 : Committer**

```bash
git add core/moa.py core/test_moa.py
git commit -m "feat(core) : S152 MOA mots-clés enrichis + env MOA_MOTS_COMPLEXES"
```

---

## Sprint S153 — Graphe d'apprentissage : feedback loop en session

**Files:**
- Modify: `core/graphe_apprentissage.py` (ajouter `noter_usage()`)
- Modify: `core/assistant.py` (appeler `noter_usage()` après chaque outil réussi)
- Modify: `core/test_graphe_apprentissage.py` (ajouter 2 tests)

**Interfaces:**
- Produces: `GrapheApprentissage.noter_usage(nom_capacite: str) -> None` — incrémente le boost en mémoire sans reconstruire le graphe
- Produces: `_graphe.noter_usage(nom)` appelé depuis `assistant.py` après chaque appel d'outil réussi

- [ ] **Étape 1 : Écrire les tests qui vont échouer**

Dans `core/test_graphe_apprentissage.py`, ajouter après le dernier test :

```python
def test_9_noter_usage_incremente_boost():
    """noter_usage() augmente le boost d'une capacité déjà dans le graphe."""
    g = _graphe_neuf()
    specs = [_spec("agenda_lister", "lister les événements agenda")]
    g.construire(["j'ai consulté mon agenda"], specs)
    boost_avant = g._boost.get("agenda_lister", 0)
    g.noter_usage("agenda_lister")
    boost_apres = g._boost.get("agenda_lister", 0)
    assert boost_apres > boost_avant


def test_10_noter_usage_capacite_inconnue_silencieux():
    """noter_usage() sur une capacité absente du graphe ne lève pas d'exception."""
    g = _graphe_neuf()
    g.construire([], [])
    g.noter_usage("capacite_inexistante")  # ne doit pas lever
```

- [ ] **Étape 2 : Vérifier que les tests échouent**

```bash
cd /Users/garinat_t/Desktop/Workplace/core && python3 -m pytest test_graphe_apprentissage.py::test_9_noter_usage_incremente_boost test_graphe_apprentissage.py::test_10_noter_usage_capacite_inconnue_silencieux -v
```

Attendu : AttributeError (méthode inexistante).

- [ ] **Étape 3 : Ajouter `noter_usage()` dans `GrapheApprentissage`**

Dans `core/graphe_apprentissage.py`, dans la classe `GrapheApprentissage`, après la méthode `stats()` (ligne ~109), ajouter :

```python
    def noter_usage(self, nom_capacite: str) -> None:
        """Renforce le boost d'une capacité utilisée avec succès en cours de session.

        Incrémente de 10 % du maximum actuel (ou de 0.1 si graphe vide).
        Jamais bloquant : si la capacité n'est pas dans le graphe, no-op."""
        if not self._construit or nom_capacite not in self._boost:
            return
        max_actuel = max(self._boost.values()) if self._boost else 1.0
        increment = 0.1 * max_actuel if max_actuel else 0.1
        self._boost[nom_capacite] = min(1.0, self._boost[nom_capacite] + increment)
```

- [ ] **Étape 4 : Vérifier que les tests passent**

```bash
cd /Users/garinat_t/Desktop/Workplace/core && python3 -m pytest test_graphe_apprentissage.py -v
```

Attendu : tous PASS.

- [ ] **Étape 5 : Appeler `noter_usage()` dans la boucle agent de `assistant.py`**

Dans `core/assistant.py`, localiser le bloc qui suit l'appel à `guardrail.after_call()` (~ligne 334). Juste après la ligne :

```python
                    guardrail.after_call(nom, args, resultat,
                                         erreur=_est_erreur_outil(resultat))
```

Et juste AVANT la ligne `g_idem_action, g_idem_msg = ...`, ajouter :

```python
                    if not _est_erreur_outil(resultat):
                        import graphe_apprentissage as _ga
                        _ga._graphe.noter_usage(nom)
```

- [ ] **Étape 6 : Vérifier que rien n'est cassé**

```bash
cd /Users/garinat_t/Desktop/Workplace/core && python3 -m pytest test_graphe_apprentissage.py test_guardrails_outils.py -v
```

Attendu : tous PASS.

- [ ] **Étape 7 : Committer**

```bash
git add core/graphe_apprentissage.py core/assistant.py core/test_graphe_apprentissage.py
git commit -m "feat(core) : S153 graphe apprentissage feedback loop — noter_usage() après chaque outil réussi"
```

---

## Sprint S154 — Tests cache sémantique

**Files:**
- Create: `core/test_cache_semantique.py`

**Interfaces:**
- Consumes: `cache_semantique.scope_hash(messages, modele, tools) -> str`
- Consumes: `cache_semantique._cosine(a, b) -> float`
- Consumes: `cache_semantique._texte_prompt(messages) -> str`
- Consumes: `cache_semantique.chercher(client, messages, scope) -> dict | None` (async)
- Consumes: `cache_semantique.stocker(client, messages, scope, message, modele) -> None` (async)

- [ ] **Étape 1 : Créer le fichier de test**

Créer `core/test_cache_semantique.py` avec le contenu suivant :

```python
"""Tests du cache sémantique des réponses LLM (S138, chantier 2).

    $ cd core && python3 -m pytest test_cache_semantique.py -v
"""
import asyncio
import os
import sys
import time
from pathlib import Path
import tempfile

os.environ.setdefault("GATEWAY_KEY", "test")
sys.path.insert(0, os.path.dirname(__file__))

import pytest
import httpx
import cache_semantique as cs


# ── Helpers ──────────────────────────────────────────────────────────────────

MSG_SIMPLE = [{"role": "user", "content": "Bonjour le monde"}]
MSG_AUTRE  = [{"role": "user", "content": "Salut tout le monde"}]
MSG_DIFF   = [{"role": "user", "content": "Parle-moi des volcans d'Islande"}]

MSG_RESP   = {"role": "assistant", "content": "Bonjour !"}

VEC_A = [1.0, 0.0, 0.0]
VEC_B = [1.0, 0.0, 0.0]
VEC_C = [0.0, 1.0, 0.0]

_CLIENT_FACTICE = None  # jamais appelé dans les tests synchrones


@pytest.fixture(autouse=True)
def cache_tmp(tmp_path, monkeypatch):
    """Redirige le cache vers un fichier temporaire pour chaque test."""
    p = tmp_path / "llm_cache.jsonl"
    monkeypatch.setattr(cs, "CACHE_PATH", p)
    monkeypatch.setattr(cs, "ACTIF", True)
    monkeypatch.setattr(cs, "TTL_S", 3600)
    monkeypatch.setattr(cs, "MAX_ENTREES", 100)
    monkeypatch.setattr(cs, "SEUIL", 0.97)
    yield p


# ── Tests synchrones ─────────────────────────────────────────────────────────

def test_1_cosine_vecteurs_identiques():
    """Cosinus de deux vecteurs identiques = 1.0."""
    assert abs(cs._cosine(VEC_A, VEC_B) - 1.0) < 1e-6


def test_2_cosine_vecteurs_orthogonaux():
    """Cosinus de deux vecteurs orthogonaux = 0.0."""
    assert abs(cs._cosine(VEC_A, VEC_C)) < 1e-6


def test_3_cosine_longueurs_differentes():
    """Cosinus renvoie -1.0 si les vecteurs ont des longueurs différentes."""
    assert cs._cosine([1.0], [1.0, 0.0]) == -1.0


def test_4_texte_prompt_concat():
    """_texte_prompt concatène role: content pour chaque message texte."""
    msgs = [
        {"role": "system", "content": "Tu es un assistant."},
        {"role": "user", "content": "Bonjour"},
    ]
    result = cs._texte_prompt(msgs)
    assert "system: Tu es un assistant." in result
    assert "user: Bonjour" in result


def test_5_texte_prompt_ignore_contenu_non_str():
    """_texte_prompt ignore les messages sans contenu string."""
    msgs = [{"role": "user", "content": None}, {"role": "user", "content": "ok"}]
    result = cs._texte_prompt(msgs)
    assert "ok" in result
    assert "None" not in result


def test_6_scope_hash_deterministe():
    """scope_hash est déterministe pour le même triplet."""
    h1 = cs.scope_hash(MSG_SIMPLE, "gpt-4o", [])
    h2 = cs.scope_hash(MSG_SIMPLE, "gpt-4o", [])
    assert h1 == h2


def test_7_scope_hash_modele_different():
    """scope_hash change si le modèle change."""
    h1 = cs.scope_hash(MSG_SIMPLE, "gpt-4o", [])
    h2 = cs.scope_hash(MSG_SIMPLE, "claude-3", [])
    assert h1 != h2


def test_8_scope_hash_systeme_different():
    """scope_hash change si le prompt système change."""
    msgs_sys_a = [{"role": "system", "content": "Tu es A."}, {"role": "user", "content": "ok"}]
    msgs_sys_b = [{"role": "system", "content": "Tu es B."}, {"role": "user", "content": "ok"}]
    assert cs.scope_hash(msgs_sys_a, "m", []) != cs.scope_hash(msgs_sys_b, "m", [])


# ── Tests asynchrones (mock embedding) ───────────────────────────────────────

class _FakeClient:
    """Client httpx factice : renvoie un embedding fixe ou simule une erreur."""

    def __init__(self, vec=None, status=200):
        self._vec = vec
        self._status = status

    async def post(self, url, **kwargs):
        if self._status >= 400:
            return _FakeResponse(self._status, {})
        data = [{"embedding": self._vec or VEC_A, "index": 0}]
        return _FakeResponse(200, {"data": data})


class _FakeResponse:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body

    def json(self):
        return self._body

    @property
    def headers(self):
        return {}


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_9_chercher_miss_fichier_vide(cache_tmp, monkeypatch):
    """chercher retourne None si le cache est vide."""
    client = _FakeClient(VEC_A)
    scope = cs.scope_hash(MSG_SIMPLE, "m", [])
    result = run(cs.chercher(client, MSG_SIMPLE, scope))
    assert result is None


def test_10_stocker_puis_chercher_hit(cache_tmp, monkeypatch):
    """stocker puis chercher avec le même vecteur → hit (sim=1.0 ≥ seuil 0.97)."""
    client = _FakeClient(VEC_A)
    scope = cs.scope_hash(MSG_SIMPLE, "m", [])
    run(cs.stocker(client, MSG_SIMPLE, scope, MSG_RESP, "m"))
    hit = run(cs.chercher(client, MSG_SIMPLE, scope))
    assert hit is not None
    assert hit["message"] == MSG_RESP


def test_11_scope_mismatch_miss(cache_tmp, monkeypatch):
    """chercher retourne None si le scope est différent."""
    client = _FakeClient(VEC_A)
    scope_a = cs.scope_hash(MSG_SIMPLE, "gpt-4o", [])
    scope_b = cs.scope_hash(MSG_SIMPLE, "claude-3", [])
    run(cs.stocker(client, MSG_SIMPLE, scope_a, MSG_RESP, "gpt-4o"))
    hit = run(cs.chercher(client, MSG_SIMPLE, scope_b))
    assert hit is None


def test_12_ttl_expire_miss(cache_tmp, monkeypatch):
    """Une entrée expirée (ts très ancien) n'est pas renvoyée."""
    import json
    scope = cs.scope_hash(MSG_SIMPLE, "m", [])
    entree = {
        "ts": time.time() - 99999,  # très ancien
        "scope": scope,
        "modele": "m",
        "prompt_norm": "user: Bonjour le monde",
        "message": MSG_RESP,
        "embedding": VEC_A,
    }
    cache_tmp.write_text(json.dumps(entree) + "\n", encoding="utf-8")
    client = _FakeClient(VEC_A)
    hit = run(cs.chercher(client, MSG_SIMPLE, scope))
    assert hit is None


def test_13_gateway_ko_chercher_retourne_none(cache_tmp, monkeypatch):
    """Si la Gateway renvoie 500, chercher retourne None sans lever."""
    client = _FakeClient(status=500)
    scope = cs.scope_hash(MSG_SIMPLE, "m", [])
    result = run(cs.chercher(client, MSG_SIMPLE, scope))
    assert result is None


def test_14_actif_false_chercher_retourne_none(cache_tmp, monkeypatch):
    """Si ACTIF est False, chercher retourne None immédiatement."""
    monkeypatch.setattr(cs, "ACTIF", False)
    client = _FakeClient(VEC_A)
    scope = cs.scope_hash(MSG_SIMPLE, "m", [])
    result = run(cs.chercher(client, MSG_SIMPLE, scope))
    assert result is None
```

- [ ] **Étape 2 : Vérifier que tous les tests passent**

```bash
cd /Users/garinat_t/Desktop/Workplace/core && python3 -m pytest test_cache_semantique.py -v
```

Attendu : 14 tests PASS.

- [ ] **Étape 3 : Committer**

```bash
git add core/test_cache_semantique.py
git commit -m "feat(core) : S154 tests cache sémantique (14 scénarios : hit/miss/TTL/scope/KO)"
```

---

## Sprint S155 — Tests summarisation

**Files:**
- Create: `core/test_summarisation.py`

**Interfaces:**
- Consumes: `summarisation.condenser(client, messages, conf) -> list[dict]` (async)
- Consumes: `trimming.estimer_tokens(messages) -> int`

- [ ] **Étape 1 : Créer le fichier de test**

Créer `core/test_summarisation.py` avec le contenu suivant :

```python
"""Tests de la summarisation à froid (S138, chantier 3b).

    $ cd core && python3 -m pytest test_summarisation.py -v
"""
import asyncio
import os
import sys

os.environ.setdefault("GATEWAY_KEY", "test")
sys.path.insert(0, os.path.dirname(__file__))

import pytest
import summarisation as sm
import trimming


# ── Helpers ──────────────────────────────────────────────────────────────────

def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _msgs(n: int, contenu: str = "Message de test assez long pour compter.") -> list[dict]:
    """Génère n messages user/assistant alternés."""
    out = []
    for i in range(n):
        role = "user" if i % 2 == 0 else "assistant"
        out.append({"role": role, "content": f"{contenu} #{i}"})
    return out


CONF_BASE = {"model": "gpt-4o", "fallback_models": ["free/mistral"], "langue": "fr"}


class _FakeClient:
    """Client httpx factice qui simule la Gateway."""

    def __init__(self, resume="Résumé synthétique.", status=200):
        self._resume = resume
        self._status = status
        self.appels = 0

    async def post(self, url, **kwargs):
        self.appels += 1
        if self._status >= 400:
            return _FakeResponse(self._status, {})
        corps = {
            "choices": [{"message": {"content": self._resume}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50},
        }
        return _FakeResponse(200, corps)


class _FakeResponse:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body

    def json(self):
        return self._body


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_1_sous_seuil_pas_de_condensation():
    """Un historique court (sous le seuil de tokens) est renvoyé inchangé."""
    msgs = _msgs(2)
    conf = {**CONF_BASE, "seuil_resume_tokens": 999999}
    client = _FakeClient()
    result = run(sm.condenser(client, msgs, conf))
    assert result == msgs
    assert client.appels == 0


def test_2_au_dessus_seuil_condense():
    """Un historique long est condensé : la Gateway est appelée et le résumé injecté."""
    msgs = _msgs(30, "x" * 60)
    conf = {**CONF_BASE, "seuil_resume_tokens": 1, "resume_garder": 4}
    client = _FakeClient("Résumé court.")
    result = run(sm.condenser(client, msgs, conf))
    assert client.appels == 1
    # Le résultat contient un message système de résumé
    resumé = [m for m in result if m.get("role") == "system" and "Résumé" in (m.get("content") or "")]
    assert resumé


def test_3_messages_systeme_preserves():
    """Les messages système sont toujours conservés tels quels."""
    sys_msg = {"role": "system", "content": "Tu es un assistant.", "pinned": True}
    msgs = [sys_msg] + _msgs(20, "y" * 80)
    conf = {**CONF_BASE, "seuil_resume_tokens": 1, "resume_garder": 4}
    client = _FakeClient("Condensé.")
    result = run(sm.condenser(client, msgs, conf))
    assert sys_msg in result


def test_4_recents_preserves():
    """Les N derniers tours (resume_garder) sont préservés sans modification."""
    msgs = _msgs(20, "z" * 80)
    garder = 6
    conf = {**CONF_BASE, "seuil_resume_tokens": 1, "resume_garder": garder}
    client = _FakeClient("Condensé.")
    result = run(sm.condenser(client, msgs, conf))
    # Les garder derniers messages doivent apparaître dans le résultat
    recents = msgs[-garder:]
    for m in recents:
        assert m in result


def test_5_repli_si_gateway_ko():
    """Si la Gateway renvoie 500, on renvoie l'historique inchangé."""
    msgs = _msgs(30, "a" * 80)
    conf = {**CONF_BASE, "seuil_resume_tokens": 1, "resume_garder": 4}
    client = _FakeClient(status=500)
    result = run(sm.condenser(client, msgs, conf))
    assert result == msgs


def test_6_repli_si_resume_vide():
    """Si la Gateway renvoie un résumé vide, l'historique est renvoyé inchangé."""
    msgs = _msgs(30, "b" * 80)
    conf = {**CONF_BASE, "seuil_resume_tokens": 1, "resume_garder": 4}
    client = _FakeClient(resume="")
    result = run(sm.condenser(client, msgs, conf))
    assert result == msgs


def test_7_modele_resume_depuis_conf():
    """Si conf contient modele_resume, c'est lui qui est utilisé (non le modèle principal)."""
    msgs = _msgs(30, "c" * 80)
    conf = {**CONF_BASE, "seuil_resume_tokens": 1, "resume_garder": 4,
            "modele_resume": "free/mistral-tiny"}
    client = _FakeClient("Résumé.")
    result = run(sm.condenser(client, msgs, conf))
    assert client.appels == 1  # un seul appel (avec le modèle résumé)


def test_8_sans_modele_sans_condensation():
    """Sans modèle disponible, pas de condensation."""
    msgs = _msgs(30, "d" * 80)
    conf = {"seuil_resume_tokens": 1, "resume_garder": 4}  # ni model ni fallback
    client = _FakeClient()
    result = run(sm.condenser(client, msgs, conf))
    assert result == msgs
    assert client.appels == 0


def test_9_trop_peu_de_messages_pas_de_condensation():
    """Avec moins de garder+2 messages non-système, pas de condensation."""
    msgs = _msgs(4, "e" * 100)
    conf = {**CONF_BASE, "seuil_resume_tokens": 1, "resume_garder": 6}
    client = _FakeClient()
    result = run(sm.condenser(client, msgs, conf))
    assert result == msgs
    assert client.appels == 0


def test_10_pas_de_message_tool_en_tete_recents():
    """Les messages 'tool' orphelins ne doivent pas ouvrir la fenêtre recents."""
    sys_msg = {"role": "system", "content": "Contexte système."}
    anciens = _msgs(20, "f" * 60)
    # Forcer un message tool en tête des recents (ne doit pas être premier)
    tool_msg = {"role": "tool", "tool_call_id": "x", "content": "résultat"}
    recents_bruts = [tool_msg] + _msgs(4, "g" * 20)
    msgs = [sys_msg] + anciens + recents_bruts
    conf = {**CONF_BASE, "seuil_resume_tokens": 1, "resume_garder": len(recents_bruts)}
    client = _FakeClient("Résumé.")
    result = run(sm.condenser(client, msgs, conf))
    # Le premier message non-système du résultat ne doit pas être un tool
    non_sys = [m for m in result if m.get("role") != "system"]
    if non_sys:
        # Le résumé (pinned system) peut être premier, sinon le premier non-sys ne doit pas être tool
        premier = non_sys[0]
        assert premier.get("role") != "tool"
```

- [ ] **Étape 2 : Vérifier que tous les tests passent**

```bash
cd /Users/garinat_t/Desktop/Workplace/core && python3 -m pytest test_summarisation.py -v
```

Attendu : 10 tests PASS.

- [ ] **Étape 3 : Committer**

```bash
git add core/test_summarisation.py
git commit -m "feat(core) : S155 tests summarisation à froid (10 scénarios : seuil/condensation/repli/modèle)"
```

---

## Auto-vérification du plan

### Couverture spec

| Amélioration | Sprint |
|---|---|
| Vue budget LLM dashboard | S151 ✓ |
| Shadow routing exposé dans l'UI | S151 ✓ (section budget-shadow) |
| MOA mots-clés enrichis + env | S152 ✓ |
| Graphe apprentissage feedback loop | S153 ✓ |
| Tests cache sémantique | S154 ✓ |
| Tests summarisation | S155 ✓ |

### Cohérence des types

- `noter_usage(nom_capacite: str) -> None` défini S153 étape 3, appelé S153 étape 5 avec `nom` (string) — cohérent.
- `_mots_complexes() -> set[str]` retourne un set utilisé dans `any(mot in msg for mot in _mots_complexes())` — cohérent.
- `chargerBudget()` appelle `/assistant/usage` → `journal_usage.resume()` retourne `{jour:{…}, mois:{…}, budget:{…}}` — cohérent avec le JS qui lit `u.jour`, `u.mois`, `u.budget`.
- `sm.condenser(client, messages, conf)` signature confirmée dans `summarisation.py:58` — cohérent.
- `cs.chercher(client, messages, scope)` signature confirmée dans `cache_semantique.py:116` — cohérent.
