# Couches de patch déclaratif config assistant — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Résoudre la config assistant (`core/config_assistant.py::charger()`) en 3 couches — global → organisation → utilisateur — stockées via la brique `données`, pour que le modèle/persona/voix/langue/cascade soient surchargeables par tenant sans forker le code.

**Architecture:** Nouveau module `core/config_tenant.py`, autonome (mêmes conventions que `core/muscle.py` : `httpx.AsyncClient` injectable, env var d'URL, timeout court, cache process avec TTL). Câblé à deux endroits existants : le chemin de chat (`core/assistant.py::converser()`) et les endpoints REST (`core/routers/assistant.py`). Aucun changement à `config_assistant.py`, à la brique `données`, ni à la gestion des clés Gateway.

**Tech Stack:** Python 3.11+, FastAPI, httpx (async), SQLite (côté brique `données`, déjà en place), pytest.

## Global Constraints

- Spec de référence : `docs/superpowers/specs/2026-08-22-config-tenant-couches-patch-design.md` — toute divergence avec ce plan doit être résolue en faveur de la spec.
- Fusion = JSON Merge Patch (RFC 7386) : les listes remplacent entièrement, jamais de fusion élément par élément.
- Lecture : ne lève JAMAIS d'exception (repli cache expiré puis `{}`), `except` ciblé sur `(httpx.HTTPError, ValueError)` uniquement — jamais un `except Exception` fourre-tout.
- Écriture : ne masque JAMAIS une erreur réseau — elle remonte à l'appelant.
- Zéro régression : sans couche org/user, `config_tenant.resoudre(...)` doit être identique à `config_assistant.charger()`.
- Code, docstrings, noms de fonctions/variables en français, comme le reste du dépôt.
- Stockage : brique `données` existante (`app_id="_config_assistant"`), aucune migration/nouvelle table.

---

### Task 1: `_fusion` — fusion JSON Merge Patch

**Files:**
- Create: `core/config_tenant.py`
- Create: `core/test_config_tenant.py`

**Interfaces:**
- Produces: `config_tenant._fusion(base: dict, patch: dict) -> dict`

- [ ] **Step 1: Write the failing tests**

Create `core/test_config_tenant.py` :

```python
"""Couches de patch déclaratif pour la config assistant (3e chantier veille dsh/Cordis).

Autonome : aucune vraie brique données (httpx.MockTransport). Mêmes conventions que
core/test_muscle.py.
    $ cd core && python3 -m pytest test_config_tenant.py -v
    $ cd core && python3 test_config_tenant.py
"""
import asyncio
import os
import sys
import tempfile

os.environ["ASSISTANT_CONFIG_PATH"] = os.path.join(tempfile.mkdtemp(), "cfg.json")
os.environ.setdefault("GATEWAY_KEY", "sk-test-local")   # config_assistant l'exige à l'import
sys.path.insert(0, os.path.dirname(__file__))

import httpx  # noqa: E402

import config_tenant  # noqa: E402


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _reset_cache():
    config_tenant._cache.clear()


# ── _fusion (JSON Merge Patch, RFC 7386) ────────────────────────────────────

def test_fusion_remplace_cle_simple():
    base = {"a": 1, "b": 2}
    patch = {"b": 3}
    assert config_tenant._fusion(base, patch) == {"a": 1, "b": 3}


def test_fusion_recursive_sur_dict_imbrique():
    base = {"a": {"x": 1, "y": 2}}
    patch = {"a": {"y": 9}}
    assert config_tenant._fusion(base, patch) == {"a": {"x": 1, "y": 9}}


def test_fusion_remplace_liste_entierement():
    base = {"fallback_models": ["m1", "m2"]}
    patch = {"fallback_models": ["m3"]}
    assert config_tenant._fusion(base, patch) == {"fallback_models": ["m3"]}


def test_fusion_ne_mute_pas_base():
    base = {"a": 1}
    config_tenant._fusion(base, {"a": 2})
    assert base == {"a": 1}


if __name__ == "__main__":
    for nom, fn in list(globals().items()):
        if nom.startswith("test_") and callable(fn):
            fn()
            print(f"  ✓ {nom}")
    print("\n✅ TOUS LES TESTS PASSENT")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd core && python3 -m pytest test_config_tenant.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'config_tenant'`

- [ ] **Step 3: Write minimal implementation**

Create `core/config_tenant.py` :

```python
"""Couches de patch déclaratif pour la config assistant (3e chantier veille dsh/Cordis).

Résout `config_assistant.charger()` (modèle/persona/voix/langue…) en 3 couches de
priorité croissante : global (fichier local, inchangé) → organisation → utilisateur
(ces deux dernières stockées dans la brique `données`, scopées par `X-Org-ID`). Fusion
façon JSON Merge Patch (RFC 7386) : toute valeur non-dict — listes incluses — remplace
entièrement celle de la couche du dessous ; les dicts imbriqués sont fusionnés
récursivement (aucun champ du schéma actuel n'en a, mais le mécanisme reste correct
si un futur champ en ajoute un).

Cf. docs/superpowers/specs/2026-08-22-config-tenant-couches-patch-design.md.
"""


def _fusion(base: dict, patch: dict) -> dict:
    """Fusion façon JSON Merge Patch (RFC 7386)."""
    resultat = dict(base)
    for cle, val in patch.items():
        if isinstance(val, dict) and isinstance(resultat.get(cle), dict):
            resultat[cle] = _fusion(resultat[cle], val)
        else:
            resultat[cle] = val
    return resultat
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd core && python3 -m pytest test_config_tenant.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add core/config_tenant.py core/test_config_tenant.py
git commit -m "$(cat <<'EOF'
feat(config-tenant): fusion JSON Merge Patch (RFC 7386)

Base du 3e chantier de la veille deepseek-harness/Cordis — fusion pure,
sans effet de bord, brique du mécanisme de résolution de couches à venir.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016wGw728KrpVYw16vEiz5kx
EOF
)"
```

---

### Task 2: Lecture de couche avec cache + résilience réseau

**Files:**
- Modify: `core/config_tenant.py`
- Modify: `core/test_config_tenant.py`

**Interfaces:**
- Consumes: `config_tenant._fusion` (Task 1, non utilisé directement ici mais reste dans le fichier)
- Produces: `config_tenant.ORG_DEFAUT`, `config_tenant.APP_ID`, `config_tenant.ENTITE_ORGANISATION`,
  `config_tenant._cache: dict`, `config_tenant._org_eff(org_id: str | None) -> str`,
  `config_tenant._lire_couche(niveau: str, org_id: str, entite_id: str, client: httpx.AsyncClient | None = None) -> dict`,
  `config_tenant.lire_couche_organisation(org_id: str | None, client=None) -> dict`,
  `config_tenant.lire_couche_utilisateur(org_id: str | None, utilisateur: str, client=None) -> dict`

- [ ] **Step 1: Write the failing tests**

Append to `core/test_config_tenant.py` (juste avant le bloc `if __name__ == "__main__":`) :

```python
# ── _lire_couche / lire_couche_organisation / lire_couche_utilisateur ──────

def test_lire_couche_absente_renvoie_vide():
    _reset_cache()
    def h(req):
        assert req.headers.get("X-Org-ID") == "acme"
        return httpx.Response(200, json=[])
    async def go():
        async with _client(h) as c:
            return await config_tenant.lire_couche_organisation("acme", client=c)
    assert asyncio.run(go()) == {}


def test_lire_couche_existante_sans_metadonnees():
    _reset_cache()
    def h(req):
        return httpx.Response(200, json=[
            {"persona": "pro", "_id": "r1", "_cree": "t0", "_maj": "t1"}
        ])
    async def go():
        async with _client(h) as c:
            return await config_tenant.lire_couche_utilisateur("acme", "alice", client=c)
    assert asyncio.run(go()) == {"persona": "pro"}


def test_cache_evite_appel_reseau_dans_ttl():
    _reset_cache()
    appels = []
    def h(req):
        appels.append(1)
        return httpx.Response(200, json=[{"persona": "pro", "_id": "r1"}])
    async def go():
        async with _client(h) as c:
            await config_tenant.lire_couche_organisation("acme", client=c)
            return await config_tenant.lire_couche_organisation("acme", client=c)
    resultat = asyncio.run(go())
    assert resultat == {"persona": "pro"}
    assert len(appels) == 1


def test_panne_reseau_repli_cache_expire():
    _reset_cache()
    def h_ok(req):
        return httpx.Response(200, json=[{"persona": "pro", "_id": "r1"}])
    async def premiere_lecture():
        async with _client(h_ok) as c:
            return await config_tenant.lire_couche_organisation("acme", client=c)
    asyncio.run(premiere_lecture())
    # Fait vieillir l'entrée de cache au-delà du TTL sans la vider.
    cle = ("organisation", "acme", config_tenant.ENTITE_ORGANISATION)
    _, patch = config_tenant._cache[cle]
    config_tenant._cache[cle] = (0.0, patch)

    def h_down(req):
        raise httpx.ConnectError("refused", request=req)
    async def deuxieme_lecture():
        async with _client(h_down) as c:
            return await config_tenant.lire_couche_organisation("acme", client=c)
    assert asyncio.run(deuxieme_lecture()) == {"persona": "pro"}


def test_panne_reseau_sans_cache_renvoie_vide():
    _reset_cache()
    def h_down(req):
        raise httpx.ConnectError("refused", request=req)
    async def go():
        async with _client(h_down) as c:
            return await config_tenant.lire_couche_organisation("acme", client=c)
    assert asyncio.run(go()) == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd core && python3 -m pytest test_config_tenant.py -v`
Expected: FAIL — `AttributeError: module 'config_tenant' has no attribute 'lire_couche_organisation'`

- [ ] **Step 3: Write minimal implementation**

Replace `core/config_tenant.py` entièrement par :

```python
"""Couches de patch déclaratif pour la config assistant (3e chantier veille dsh/Cordis).

Résout `config_assistant.charger()` (modèle/persona/voix/langue…) en 3 couches de
priorité croissante : global (fichier local, inchangé) → organisation → utilisateur
(ces deux dernières stockées dans la brique `données`, scopées par `X-Org-ID`). Fusion
façon JSON Merge Patch (RFC 7386) : toute valeur non-dict — listes incluses — remplace
entièrement celle de la couche du dessous ; les dicts imbriqués sont fusionnés
récursivement (aucun champ du schéma actuel n'en a, mais le mécanisme reste correct
si un futur champ en ajoute un).

Cf. docs/superpowers/specs/2026-08-22-config-tenant-couches-patch-design.md.
"""
import logging
import os
import time

import httpx

logger = logging.getLogger(__name__)

# Mêmes conventions que core/muscle.py : env var d'override, pas de dépendance au
# registre de briques (brique connue à l'avance, comme calcul/5990).
DONNEES_URL = os.getenv("DONNEES_URL", "http://host.docker.internal:5500").rstrip("/")
_TIMEOUT = float(os.getenv("CONFIG_TENANT_TIMEOUT", "5"))
_TTL_S = float(os.getenv("CONFIG_TENANT_CACHE_TTL", "90"))

APP_ID = "_config_assistant"
ENTITE_ORGANISATION = "_organisation"
ORG_DEFAUT = "defaut"

# Cache process : (niveau, org_id, entite_id) -> (timestamp_pose, patch)
_cache: dict[tuple[str, str, str], tuple[float, dict]] = {}


def _org_eff(org_id: str | None) -> str:
    return org_id or ORG_DEFAUT


def _fusion(base: dict, patch: dict) -> dict:
    """Fusion façon JSON Merge Patch (RFC 7386)."""
    resultat = dict(base)
    for cle, val in patch.items():
        if isinstance(val, dict) and isinstance(resultat.get(cle), dict):
            resultat[cle] = _fusion(resultat[cle], val)
        else:
            resultat[cle] = val
    return resultat


def _url(entite_id: str) -> str:
    return f"{DONNEES_URL}/apps/{APP_ID}/entites/{entite_id}/enregistrements"


def _sans_metadonnees(enregistrement: dict) -> dict:
    return {k: v for k, v in enregistrement.items() if not str(k).startswith("_")}


async def _lire_couche(niveau: str, org_id: str, entite_id: str,
                       client: httpx.AsyncClient | None = None) -> dict:
    """Patch brut d'une couche, {} si absente. Sert le cache dans le TTL sans appel
    réseau. Hors TTL, tente une lecture fraîche ; si la brique données est injoignable,
    sert le cache même expiré (mieux qu'un repli silencieux vers le global seul). Sans
    aucun cache et brique down, renvoie {} — la résolution continue avec les couches
    disponibles. Ne lève jamais : `except` ciblé sur les erreurs réseau/parsing."""
    cle_cache = (niveau, org_id, entite_id)
    pose = _cache.get(cle_cache)
    if pose and (time.monotonic() - pose[0]) < _TTL_S:
        return pose[1]

    propre = client is None
    client = client or httpx.AsyncClient(timeout=_TIMEOUT)
    try:
        r = await client.get(_url(entite_id), headers={"X-Org-ID": org_id})
        r.raise_for_status()
        enregistrements = r.json()
        patch = _sans_metadonnees(enregistrements[-1]) if enregistrements else {}
        _cache[cle_cache] = (time.monotonic(), patch)
        return patch
    except (httpx.HTTPError, ValueError) as e:
        logger.warning("brique données injoignable (lecture %s/%s/%s) : %s",
                       niveau, org_id, entite_id, e)
        return pose[1] if pose else {}
    finally:
        if propre:
            await client.aclose()


async def lire_couche_organisation(org_id: str | None,
                                   client: httpx.AsyncClient | None = None) -> dict:
    """Patch brut de la couche organisation (pas le résolu)."""
    return await _lire_couche("organisation", _org_eff(org_id), ENTITE_ORGANISATION, client)


async def lire_couche_utilisateur(org_id: str | None, utilisateur: str,
                                  client: httpx.AsyncClient | None = None) -> dict:
    """Patch brut de la couche utilisateur (pas le résolu)."""
    return await _lire_couche("utilisateur", _org_eff(org_id), utilisateur, client)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd core && python3 -m pytest test_config_tenant.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add core/config_tenant.py core/test_config_tenant.py
git commit -m "$(cat <<'EOF'
feat(config-tenant): lecture de couche avec cache TTL + repli sur panne

Lit une couche org/utilisateur depuis la brique données (magasin générique
déjà existant, aucune nouvelle table). Cache process 90s évite un aller-retour
réseau à chaque message assistant. Panne réseau : repli cache expiré puis {},
jamais d'exception qui casserait un tour de conversation.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016wGw728KrpVYw16vEiz5kx
EOF
)"
```

---

### Task 3: `resoudre()` + `resoudre_avec_provenance()`

**Files:**
- Modify: `core/config_tenant.py`
- Modify: `core/test_config_tenant.py`

**Interfaces:**
- Consumes: `config_assistant.charger() -> dict` (existant), `config_tenant.lire_couche_organisation`,
  `config_tenant.lire_couche_utilisateur`, `config_tenant._fusion` (Tasks 1-2)
- Produces: `config_tenant.resoudre(org_id: str | None, utilisateur: str, client=None) -> dict`,
  `config_tenant.resoudre_avec_provenance(org_id: str | None, utilisateur: str, client=None) -> dict`

- [ ] **Step 1: Write the failing tests**

Append to `core/test_config_tenant.py` (avant le bloc `if __name__ == "__main__":`) :

```python
# ── resoudre / resoudre_avec_provenance ─────────────────────────────────────

def test_resoudre_sans_couches_egale_charger():
    import config_assistant
    _reset_cache()
    def h(req):
        return httpx.Response(200, json=[])
    async def go():
        async with _client(h) as c:
            return await config_tenant.resoudre("acme", "alice", client=c)
    assert asyncio.run(go()) == config_assistant.charger()


def test_resoudre_precedence_global_organisation_utilisateur():
    _reset_cache()
    def h(req):
        if "/entites/_organisation/" in req.url.path:
            return httpx.Response(200, json=[
                {"persona": "pro", "fallback_models": ["m-org"], "_id": "r1"}
            ])
        if "/entites/alice/" in req.url.path:
            return httpx.Response(200, json=[{"persona": "chaleureux", "_id": "r2"}])
        return httpx.Response(200, json=[])
    async def go():
        async with _client(h) as c:
            return await config_tenant.resoudre("acme", "alice", client=c)
    conf = asyncio.run(go())
    assert conf["persona"] == "chaleureux"          # utilisateur gagne sur organisation
    assert conf["fallback_models"] == ["m-org"]      # organisation gagne sur global
    assert conf["langue"] == "fr"                    # ni touché : reste le global


def test_resoudre_avec_provenance():
    _reset_cache()
    def h(req):
        if "/entites/_organisation/" in req.url.path:
            return httpx.Response(200, json=[{"langue": "en", "_id": "r1"}])
        if "/entites/alice/" in req.url.path:
            return httpx.Response(200, json=[{"persona": "pro", "_id": "r2"}])
        return httpx.Response(200, json=[])
    async def go():
        async with _client(h) as c:
            return await config_tenant.resoudre_avec_provenance("acme", "alice", client=c)
    r = asyncio.run(go())
    assert r["resolu"]["langue"] == "en"
    assert r["resolu"]["persona"] == "pro"
    assert r["provenance"] == {"langue": "organisation", "persona": "utilisateur"}
    assert "model" not in r["provenance"]            # jamais touché → pas de provenance
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd core && python3 -m pytest test_config_tenant.py -v`
Expected: FAIL — `AttributeError: module 'config_tenant' has no attribute 'resoudre'`

- [ ] **Step 3: Write minimal implementation**

Append à la fin de `core/config_tenant.py` (après `lire_couche_utilisateur`) :

```python
async def resoudre(org_id: str | None, utilisateur: str,
                   client: httpx.AsyncClient | None = None) -> dict:
    """Config résolue : global < organisation < utilisateur (JSON Merge Patch)."""
    import config_assistant  # import tardif : évite tout cycle au chargement
    base = config_assistant.charger()
    patch_org = await lire_couche_organisation(org_id, client)
    fusionne = _fusion(base, patch_org)
    patch_user = await lire_couche_utilisateur(org_id, utilisateur, client) if utilisateur else {}
    return _fusion(fusionne, patch_user)


async def resoudre_avec_provenance(org_id: str | None, utilisateur: str,
                                   client: httpx.AsyncClient | None = None) -> dict:
    """Résolu + provenance : pour chaque clé effectivement patchée par une couche,
    quelle couche a eu le dernier mot ('organisation'|'utilisateur'). Une clé absente
    de `provenance` vient de la couche globale (comportement par défaut) — cohérent
    avec l'invariant « visible du modèle = traçable » (journal_modele)."""
    import config_assistant  # import tardif : évite tout cycle au chargement
    base = config_assistant.charger()
    patch_org = await lire_couche_organisation(org_id, client)
    patch_user = await lire_couche_utilisateur(org_id, utilisateur, client) if utilisateur else {}
    resolu = _fusion(_fusion(base, patch_org), patch_user)
    provenance = {cle: "organisation" for cle in patch_org}
    provenance.update({cle: "utilisateur" for cle in patch_user})
    return {"resolu": resolu, "provenance": provenance}
```

Note : l'import de `config_assistant` est tardif (à l'intérieur des fonctions) parce que
`core/test_config_tenant.py` importe `config_tenant` AVANT que `ASSISTANT_CONFIG_PATH`/`GATEWAY_KEY`
soient garantis posés pour un import top-level propre — même motif que `config_assistant.definir_langue`
qui importe `langue` tardivement (cf. `core/config_assistant.py:233`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd core && python3 -m pytest test_config_tenant.py -v`
Expected: PASS (12 tests)

- [ ] **Step 5: Commit**

```bash
git add core/config_tenant.py core/test_config_tenant.py
git commit -m "$(cat <<'EOF'
feat(config-tenant): résolution 3 couches + endpoint de provenance

resoudre() compose global < organisation < utilisateur. resoudre_avec_provenance()
ajoute, pour chaque clé patchée, quelle couche a eu le dernier mot — transparence
cohérente avec l'invariant journal=vérité posé côté journal_modele.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016wGw728KrpVYw16vEiz5kx
EOF
)"
```

---

### Task 4: Écriture de couche (validation + upsert)

**Files:**
- Modify: `core/config_tenant.py`
- Modify: `core/test_config_tenant.py`

**Interfaces:**
- Consumes: `config_assistant.charger().keys()`, `config_tenant._fusion`, `config_tenant._url`,
  `config_tenant._sans_metadonnees`, `config_tenant._org_eff`, `config_tenant._cache` (Tasks 1-3)
- Produces: `config_tenant.CLES_CONNUES: frozenset`, `config_tenant.valider_patch(patch: dict) -> None`
  (lève `ValueError`), `config_tenant.ecrire_couche_organisation(org_id, patch, client=None) -> dict`,
  `config_tenant.ecrire_couche_utilisateur(org_id, utilisateur, patch, client=None) -> dict`

- [ ] **Step 1: Write the failing tests**

Append to `core/test_config_tenant.py` (avant le bloc `if __name__ == "__main__":`) :

```python
# ── valider_patch / ecrire_couche_* ─────────────────────────────────────────

def test_valider_patch_rejette_cle_inconnue():
    try:
        config_tenant.valider_patch({"persona": "pro", "bidule": 1})
        assert False, "aurait dû lever ValueError"
    except ValueError as e:
        assert "bidule" in str(e)


def test_valider_patch_accepte_patch_partiel_valide():
    config_tenant.valider_patch({"persona": "pro", "langue": "en"})  # ne lève pas


def test_ecrire_couche_creation():
    _reset_cache()
    def h(req):
        if req.method == "GET":
            return httpx.Response(200, json=[])
        assert req.method == "POST"
        assert req.headers.get("X-Org-ID") == "acme"
        import json as _json
        assert _json.loads(req.content) == {"persona": "pro"}
        return httpx.Response(201, json={"persona": "pro", "_id": "r1",
                                         "_cree": "t0", "_maj": "t0"})
    async def go():
        async with _client(h) as c:
            return await config_tenant.ecrire_couche_organisation("acme", {"persona": "pro"}, client=c)
    assert asyncio.run(go()) == {"persona": "pro"}


def test_ecrire_couche_mise_a_jour_fusionne_sur_existant():
    _reset_cache()
    def h(req):
        if req.method == "GET":
            return httpx.Response(200, json=[
                {"persona": "pro", "langue": "en", "_id": "r1", "_cree": "t0", "_maj": "t0"}
            ])
        assert req.method == "PUT"
        assert req.url.path.endswith("/r1")
        import json as _json
        assert _json.loads(req.content) == {"persona": "pro", "langue": "fr"}
        return httpx.Response(200, json={"persona": "pro", "langue": "fr",
                                         "_id": "r1", "_cree": "t0", "_maj": "t1"})
    async def go():
        async with _client(h) as c:
            return await config_tenant.ecrire_couche_organisation("acme", {"langue": "fr"}, client=c)
    assert asyncio.run(go()) == {"persona": "pro", "langue": "fr"}


def test_ecrire_couche_invalide_cache_avant_expiration():
    _reset_cache()
    def h(req):
        if req.method == "GET":
            return httpx.Response(200, json=[])
        return httpx.Response(201, json={"persona": "pro", "_id": "r1"})
    async def ecrire():
        async with _client(h) as c:
            return await config_tenant.ecrire_couche_organisation("acme", {"persona": "pro"}, client=c)
    asyncio.run(ecrire())

    def h_jamais_appele(req):
        raise AssertionError("ne doit pas taper le réseau : le cache vient d'être posé")
    async def relire():
        async with _client(h_jamais_appele) as c:
            return await config_tenant.lire_couche_organisation("acme", client=c)
    assert asyncio.run(relire()) == {"persona": "pro"}


def test_ecrire_couche_panne_reseau_remonte_erreur():
    _reset_cache()
    def h_down(req):
        raise httpx.ConnectError("refused", request=req)
    async def go():
        async with _client(h_down) as c:
            return await config_tenant.ecrire_couche_organisation("acme", {"persona": "pro"}, client=c)
    try:
        asyncio.run(go())
        assert False, "aurait dû laisser remonter httpx.ConnectError"
    except httpx.ConnectError:
        pass


def test_ecrire_couche_utilisateur_cle_cache_distincte_de_organisation():
    _reset_cache()
    def h(req):
        if req.method == "GET":
            return httpx.Response(200, json=[])
        return httpx.Response(201, json={"persona": "chaleureux", "_id": "r1"})
    async def go():
        async with _client(h) as c:
            return await config_tenant.ecrire_couche_utilisateur(
                "acme", "alice", {"persona": "chaleureux"}, client=c)
    asyncio.run(go())
    assert ("utilisateur", "acme", "alice") in config_tenant._cache
    assert ("organisation", "acme", config_tenant.ENTITE_ORGANISATION) not in config_tenant._cache
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd core && python3 -m pytest test_config_tenant.py -v`
Expected: FAIL — `AttributeError: module 'config_tenant' has no attribute 'valider_patch'`

- [ ] **Step 3: Write minimal implementation**

Append à la fin de `core/config_tenant.py` :

```python
def _cles_connues() -> frozenset:
    import config_assistant  # import tardif : évite tout cycle au chargement
    return frozenset(config_assistant.charger().keys())


def valider_patch(patch: dict) -> None:
    """Lève ValueError si le patch contient une clé hors du schéma connu de
    config_assistant.charger() — jamais de clé inconnue écrite silencieusement."""
    inconnues = set(patch) - _cles_connues()
    if inconnues:
        raise ValueError(f"clé(s) inconnue(s) : {', '.join(sorted(inconnues))}")


async def _ecrire_couche(niveau: str, org_id: str, entite_id: str, patch: dict,
                         client: httpx.AsyncClient | None = None) -> dict:
    """Fusionne `patch` sur la couche existante et la persiste (upsert : PUT si un
    enregistrement existe déjà pour (app_id, entite_id), POST sinon). Jamais
    silencieuse : une erreur réseau vers données remonte à l'appelant (pas de faux
    succès, pas de patch perdu sans le dire)."""
    valider_patch(patch)
    propre = client is None
    client = client or httpx.AsyncClient(timeout=_TIMEOUT)
    try:
        entetes = {"X-Org-ID": org_id}
        r = await client.get(_url(entite_id), headers=entetes)
        r.raise_for_status()
        existants = r.json()
        if existants:
            actuel = _sans_metadonnees(existants[-1])
            nouveau = _fusion(actuel, patch)
            r = await client.put(f"{_url(entite_id)}/{existants[-1]['_id']}",
                                 json=nouveau, headers=entetes)
        else:
            nouveau = dict(patch)
            r = await client.post(_url(entite_id), json=nouveau, headers=entetes)
        r.raise_for_status()
        resultat = _sans_metadonnees(r.json())
        _cache[(niveau, org_id, entite_id)] = (time.monotonic(), resultat)
        return resultat
    finally:
        if propre:
            await client.aclose()


async def ecrire_couche_organisation(org_id: str | None, patch: dict,
                                     client: httpx.AsyncClient | None = None) -> dict:
    """Patch (partiel) la couche organisation. Lève ValueError (clé inconnue) ou
    httpx.HTTPError (brique données injoignable)."""
    return await _ecrire_couche("organisation", _org_eff(org_id), ENTITE_ORGANISATION,
                                patch, client)


async def ecrire_couche_utilisateur(org_id: str | None, utilisateur: str, patch: dict,
                                    client: httpx.AsyncClient | None = None) -> dict:
    """Patch (partiel) la couche utilisateur. Lève ValueError (clé inconnue) ou
    httpx.HTTPError (brique données injoignable)."""
    return await _ecrire_couche("utilisateur", _org_eff(org_id), utilisateur, patch, client)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd core && python3 -m pytest test_config_tenant.py -v`
Expected: PASS (19 tests)

Aussi : `cd core && python3 test_config_tenant.py` doit imprimer `✅ TOUS LES TESTS PASSENT`
(lanceur autonome — convention `test_muscle.py`).

- [ ] **Step 5: Commit**

```bash
git add core/config_tenant.py core/test_config_tenant.py
git commit -m "$(cat <<'EOF'
feat(config-tenant): écriture de couche — liste blanche + upsert, jamais silencieuse

valider_patch rejette toute clé hors du schéma connu de config_assistant.charger().
ecrire_couche_organisation/utilisateur font l'upsert (GET puis PUT ou POST) et
invalident immédiatement le cache de lecture (write-through). Contrairement à la
lecture, une panne réseau à l'écriture remonte toujours une vraie erreur.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016wGw728KrpVYw16vEiz5kx
EOF
)"
```

---

### Task 5: Câblage des endpoints REST (`core/routers/assistant.py`)

**Files:**
- Modify: `core/routers/assistant.py:19` (imports), `core/routers/assistant.py:371-403` (`assistant_config_get`),
  `core/routers/assistant.py:462` (nouvel emplacement, juste après `assistant_config_post`)
- Create: `core/test_config_tenant_routes.py`

**Interfaces:**
- Consumes: `config_tenant.resoudre`, `config_tenant.resoudre_avec_provenance`,
  `config_tenant.lire_couche_organisation`, `config_tenant.lire_couche_utilisateur`,
  `config_tenant.ecrire_couche_organisation`, `config_tenant.ecrire_couche_utilisateur` (Tasks 2-4),
  `contexte_tenant.contexte_actuel() -> Contexte(utilisateur, org_id, user_token)` (existant)
- Produces: endpoints `GET /assistant/config` (modifié), `GET|PUT /assistant/config/organisation`,
  `GET|PUT /assistant/config/utilisateur`, `GET /assistant/config/resolue`

- [ ] **Step 1: Write the failing tests**

Create `core/test_config_tenant_routes.py` :

```python
"""Endpoints /assistant/config/{organisation,utilisateur,resolue} (S234-veille chantier 3) :
traduction des erreurs de config_tenant en HTTPException.

Fonctions testées directement (pas de TestClient) — même philosophie que
test_assistant_routes.py : pas besoin de monter toute l'app pour prouver le câblage.
    $ cd core && python3 -m pytest test_config_tenant_routes.py -v
"""
import asyncio
import os

os.environ.setdefault("VAULT_SECRET", "test-secret-0123456789")
os.environ.setdefault("GATEWAY_KEY", "test")
os.environ.setdefault("AUTH_SESSION_SECRET", "test-session-secret-0123456789")

import httpx  # noqa: E402
import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

import config_tenant  # noqa: E402
import contexte_tenant  # noqa: E402
from routers.assistant import (  # noqa: E402
    assistant_config_organisation_put,
    assistant_config_utilisateur_put,
)


def test_organisation_put_cle_inconnue_leve_400():
    contexte_tenant.definir_contexte(org_id="acme", utilisateur="alice")
    async def faux_ecrire(org_id, patch, client=None):
        raise ValueError("clé(s) inconnue(s) : bidule")
    ancien = config_tenant.ecrire_couche_organisation
    config_tenant.ecrire_couche_organisation = faux_ecrire
    try:
        with pytest.raises(HTTPException) as exc:
            asyncio.run(assistant_config_organisation_put({"bidule": 1}))
        assert exc.value.status_code == 400
    finally:
        config_tenant.ecrire_couche_organisation = ancien


def test_organisation_put_panne_reseau_leve_502():
    contexte_tenant.definir_contexte(org_id="acme", utilisateur="alice")
    async def faux_ecrire(org_id, patch, client=None):
        raise httpx.ConnectError("refused", request=httpx.Request("GET", "http://x"))
    ancien = config_tenant.ecrire_couche_organisation
    config_tenant.ecrire_couche_organisation = faux_ecrire
    try:
        with pytest.raises(HTTPException) as exc:
            asyncio.run(assistant_config_organisation_put({"persona": "pro"}))
        assert exc.value.status_code == 502
    finally:
        config_tenant.ecrire_couche_organisation = ancien


def test_utilisateur_put_cle_inconnue_leve_400():
    contexte_tenant.definir_contexte(org_id="acme", utilisateur="alice")
    async def faux_ecrire(org_id, utilisateur, patch, client=None):
        raise ValueError("clé(s) inconnue(s) : bidule")
    ancien = config_tenant.ecrire_couche_utilisateur
    config_tenant.ecrire_couche_utilisateur = faux_ecrire
    try:
        with pytest.raises(HTTPException) as exc:
            asyncio.run(assistant_config_utilisateur_put({"bidule": 1}))
        assert exc.value.status_code == 400
    finally:
        config_tenant.ecrire_couche_utilisateur = ancien
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd core && python3 -m pytest test_config_tenant_routes.py -v`
Expected: FAIL — `ImportError: cannot import name 'assistant_config_organisation_put' from 'routers.assistant'`

- [ ] **Step 3: Write minimal implementation**

In `core/routers/assistant.py`, add the import (ligne 19, juste après `import config_assistant`) :

```python
import config_assistant
import config_tenant
import contexte_tenant
```

Replace the existing `assistant_config_get` handler (lignes 371-403) :

```python
@router.get("/assistant/config", tags=["assistant"])
async def assistant_config_get():
    """État du « cerveau » : modèle courant, modèles disponibles, clé OpenRouter définie ?

    Résolu par tenant (S234-veille chantier 3) : global < organisation < utilisateur."""
    ctx = contexte_tenant.contexte_actuel()
    conf = await config_tenant.resoudre(ctx.org_id, ctx.utilisateur)
    return {
        "model": conf["model"],
        "fallback_models": conf["fallback_models"],
        "modeles_disponibles": await config_assistant.lister_modeles(),
        "cle_openrouter_definie": config_assistant.cle_openrouter_definie(),
        # Clés des autres fournisseurs LLM (Anthropic, Groq, OpenCode Go…) : état défini/absent.
        "cles_fournisseurs": config_assistant.cles_fournisseurs_etat(),
        "voix_provider": conf["voix_provider"],
        "unmute_url": conf["unmute_url"],
        "wakeword_url": conf["wakeword_url"],
        "voix_fin_mode": conf["voix_fin_mode"],
        "voix_silence_ms": conf["voix_silence_ms"],
        "persona": conf["persona"],
        "personas": personas.catalogue(),
        "langue": conf["langue"],
        "langues": langue_mod.catalogue(),
        "routage_actif": conf["routage_actif"],
        "modele_econome": conf["modele_econome"],
        # Cascade auto (cost-first) : gratuits → repli payant, + chaîne effective.
        "cascade_auto": conf["cascade_auto"],
        "repli_payant": conf["repli_payant"],
        "cascade_free_n": conf["cascade_free_n"],
        "chaine_effective": await config_assistant.chaine_modeles(conf),
        # Muscle déporté (brique calcul, roadmap S58) : opt-in + état des nœuds.
        "muscle_actif": conf["muscle_actif"],
        # Repli souverain CPU sur le Cœur (S62) : dernier maillon local de la cascade.
        "repli_souverain": conf["repli_souverain"],
        "repli_souverain_avant_payant": conf["repli_souverain_avant_payant"],
    }
```

Add these five endpoints right after `assistant_config_post` (après la ligne 462, avant le bloc
`# ── Profil utilisateur …`) :

```python
@router.get("/assistant/config/organisation", tags=["assistant"])
async def assistant_config_organisation_get():
    """Patch brut de la couche organisation (pas le résolu) — pour l'inspecter/l'éditer."""
    ctx = contexte_tenant.contexte_actuel()
    return await config_tenant.lire_couche_organisation(ctx.org_id)


@router.put("/assistant/config/organisation", tags=["assistant"])
async def assistant_config_organisation_put(corps: dict):
    """Patch (partiel) la couche organisation. Corps : clés du schéma config_assistant
    (model, persona, langue, voix_provider…). Clé hors schéma → 400."""
    ctx = contexte_tenant.contexte_actuel()
    try:
        return await config_tenant.ecrire_couche_organisation(ctx.org_id, corps)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"brique données injoignable : {e}")


@router.get("/assistant/config/utilisateur", tags=["assistant"])
async def assistant_config_utilisateur_get():
    """Patch brut de la couche utilisateur (pas le résolu)."""
    ctx = contexte_tenant.contexte_actuel()
    return await config_tenant.lire_couche_utilisateur(ctx.org_id, ctx.utilisateur)


@router.put("/assistant/config/utilisateur", tags=["assistant"])
async def assistant_config_utilisateur_put(corps: dict):
    """Patch (partiel) la couche utilisateur. Clé hors schéma connu → 400."""
    ctx = contexte_tenant.contexte_actuel()
    try:
        return await config_tenant.ecrire_couche_utilisateur(ctx.org_id, ctx.utilisateur, corps)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"brique données injoignable : {e}")


@router.get("/assistant/config/resolue", tags=["assistant"])
async def assistant_config_resolue_get():
    """Debug/transparence : résolu + provenance par clé (quelle couche a eu le dernier
    mot). Cohérent avec l'invariant « visible du modèle = traçable » (journal_modele)."""
    ctx = contexte_tenant.contexte_actuel()
    return await config_tenant.resoudre_avec_provenance(ctx.org_id, ctx.utilisateur)
```

(`HTTPException` et `httpx` sont déjà importés en tête de `core/routers/assistant.py`, lignes 7-8 —
aucun nouvel import requis pour ces deux noms.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd core && python3 -m pytest test_config_tenant_routes.py -v`
Expected: PASS (3 tests)

Aussi, vérifier que le module entier importe toujours proprement (pas de faute de frappe) :
Run: `cd core && python3 -c "import routers.assistant"`
Expected: pas d'erreur (import silencieux)

- [ ] **Step 5: Commit**

```bash
git add core/routers/assistant.py core/test_config_tenant_routes.py
git commit -m "$(cat <<'EOF'
feat(config-tenant): endpoints REST /assistant/config/{organisation,utilisateur,resolue}

GET /assistant/config renvoie désormais le résolu (global+org+user) au lieu du
global seul. Nouveaux GET|PUT par couche + GET resolue (debug/provenance). Les
endpoints définir_* existants (persona, langue, voix, cascade…) sont inchangés :
ils continuent d'écrire la couche globale, le panneau ⚙ Cerveau n'a rien à changer.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016wGw728KrpVYw16vEiz5kx
EOF
)"
```

---

### Task 6: Câblage du chemin de chat (`core/assistant.py::converser`)

**Files:**
- Modify: `core/assistant.py:24` (imports), `core/assistant.py:151-152` (call site)
- Create: `core/test_converser_config_tenant.py`

**Interfaces:**
- Consumes: `config_tenant.resoudre(org_id, utilisateur, client=None) -> dict` (Task 3),
  `contexte_tenant.contexte_actuel() -> Contexte` (existant)
- Produces: `converser()` résout désormais sa config via le tenant courant au lieu de
  `config_assistant.charger()` en dur

- [ ] **Step 1: Write the failing test**

Create `core/test_converser_config_tenant.py` :

```python
"""Câblage de config_tenant dans le chemin de chat (assistant.converser, S234-veille
chantier 3) : le tour de conversation résout la config via le tenant courant
(contexte_tenant), pas via config_assistant.charger() en dur.

Autonome, même harnais que test_converser_stream.py (llm_pipeline doublé).
    $ cd core && python3 test_converser_config_tenant.py
    $ cd core && python3 -m pytest test_converser_config_tenant.py -v
"""
import asyncio
import os
import sys
import tempfile

os.environ["ASSISTANT_CONFIG_PATH"] = os.path.join(tempfile.mkdtemp(), "cfg.json")
os.environ.setdefault("GATEWAY_KEY", "sk-test-local")
os.environ["STREAM_ACTIF"] = "1"    # même chemin que test_converser_stream.py (éprouvé)
os.environ["MODELE_JOURNAL_PATH"] = os.path.join(tempfile.mkdtemp(), "modele.jsonl")
sys.path.insert(0, os.path.dirname(__file__))

import assistant  # noqa: E402
import config_assistant  # noqa: E402
import config_tenant  # noqa: E402
import contexte_tenant  # noqa: E402
import llm_pipeline  # noqa: E402


def test_converser_resout_avec_le_tenant_courant():
    appels = []

    async def faux_resoudre(org_id, utilisateur, client=None):
        appels.append((org_id, utilisateur))
        return config_assistant.charger()

    async def faux_flux(*a, **k):
        yield {"type": "fin", "message": {"role": "assistant", "content": "salut"},
               "resultat": None}

    jetons = contexte_tenant.definir_contexte(utilisateur="alice", org_id="acme")
    ancien_resoudre, ancien_flux = config_tenant.resoudre, llm_pipeline.completer_flux
    config_tenant.resoudre, llm_pipeline.completer_flux = faux_resoudre, faux_flux
    try:
        async def go():
            return [e async for e in
                    assistant.converser([{"role": "user", "content": "salut"}], registre=None)]
        asyncio.run(go())
    finally:
        config_tenant.resoudre, llm_pipeline.completer_flux = ancien_resoudre, ancien_flux
        contexte_tenant.reinitialiser(jetons)

    assert appels == [("acme", "alice")]


if __name__ == "__main__":
    for nom, fn in list(globals().items()):
        if nom.startswith("test_") and callable(fn):
            fn()
            print(f"  ✓ {nom}")
    print("\n✅ TOUS LES TESTS PASSENT")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd core && python3 test_converser_config_tenant.py`
Expected: FAIL — `assert [] == [('acme', 'alice')]` (le call-site actuel appelle encore
`config_assistant.charger()`, jamais `config_tenant.resoudre`)

- [ ] **Step 3: Write minimal implementation**

In `core/assistant.py`, add imports (ligne 24, juste après `import config_assistant`) :

```python
import config_assistant
import config_tenant
import conscience
```

(la ligne `import conscience` existe déjà juste après `config_assistant` — insérer
`import config_tenant` entre les deux, et ajouter `import contexte_tenant` n'importe où
dans le bloc d'imports, par exemple juste après `import config_tenant`.)

Replace lines 151-152 :

```python
    # Modèle + persona lus à CHAUD (réglables depuis le front, cf. config_assistant).
    conf = config_assistant.charger()
```

by :

```python
    # Modèle + persona lus à CHAUD, résolus par tenant (S234-veille chantier 3) :
    # global < organisation < utilisateur — cf. config_tenant.py.
    ctx = contexte_tenant.contexte_actuel()
    conf = await config_tenant.resoudre(ctx.org_id, ctx.utilisateur)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd core && python3 test_converser_config_tenant.py`
Expected: `  ✓ test_converser_resout_avec_le_tenant_courant` puis `✅ TOUS LES TESTS PASSENT`

Aussi, vérifier la non-régression des tests de streaming existants (aucun changement de
comportement attendu, juste une nouvelle source pour `conf`) :
Run: `cd core && python3 test_converser_stream.py`
Expected: `✅ TOUS LES TESTS PASSENT`

- [ ] **Step 5: Commit**

```bash
git add core/assistant.py core/test_converser_config_tenant.py
git commit -m "$(cat <<'EOF'
feat(config-tenant): chemin de chat résout la config par tenant

converser() lit désormais le tenant courant (contexte_tenant) et résout la
config via config_tenant.resoudre() au lieu de config_assistant.charger() en
dur. Sans override org/user, comportement identique (patches vides = no-op) —
prouvé par la non-régression de test_converser_stream.py.

Clôt le 3e des 4 chantiers de la veille deepseek-harness/Cordis.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016wGw728KrpVYw16vEiz5kx
EOF
)"
```

---

## Hors périmètre (rappel spec)

Pas de couche CLI/overlay, pas de changement à la gestion des clés Gateway, pas de
routage Gateway par tenant au niveau infra, pas d'UI dédiée à la gestion des couches.
Le 4e chantier de la veille (seams 3 rôles pour dev-auto-atelier/5955) reste non entamé.
