# S186 — Isolation par personne de la brique memoire — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Isoler la brique `memoire` (port 5600, aucune auth aujourd'hui) par personne du
foyer, sur les deux surfaces où le trou existe : l'assistant (outils LLM) et la tuile
dashboard « Mémoire & graphe IPCRA », y compris un vrai sélecteur d'espace dans le front React
sans rouvrir la faille du proxy `/api/v1/*` brut.

**Architecture:** Motif mail (S185) transposé : `MEMOIRE_KEY` gage la confiance du Cœur,
`X-User-Id` désigne la personne, l'espace logique `"perso"` devient un espace Memory par
personne (`Perso:{identite}`, avec repli legacy `"Perso"` pour l'identité par défaut — zéro
migration). Le proxy générique `/api/v1/*` (qui relaie au backend Memory avec un JWT de
service propriétaire de TOUS les espaces) est gardé par une allowlist des deux espaces
autorisés (solution + perso courant). Nouveau proxy Cœur `/memoire-app/*` (motif
`mail_proxy.py`) sert la tuile dashboard en injectant l'identité de session, jamais celle du
navigateur.

**Tech Stack:** FastAPI (brique memoire + Cœur), httpx, pytest + pytest-asyncio + respx (tests
Python), React + Zustand + Vite (front `briques/memoire/memory/frontend`).

## Global Constraints

- Spec de référence : `docs/superpowers/specs/2026-07-19-s186-memoire-isolation-design.md`
  (commit `bd80a2c`) — toute divergence avec ce plan doit être résolue en faveur de la spec.
- Repli legacy obligatoire : l'identité par défaut `"perso"` DOIT mapper vers le nom d'espace
  Memory `"Perso"` (pas `"Perso:perso"`) — zéro migration des souvenirs déjà stockés.
- Mode ouvert (pas de `MEMOIRE_KEY` configurée) DOIT rester strictement inchangé — aucune
  régression pour Forge/tests/dev existants.
- Dialecte unique `X-API-Key` pour toutes les briques « cercle privé » (agenda, ecoute, mail,
  memoire) — pas d'`Authorization: Bearer` pour ce mécanisme.
- Pas de déploiement LIVE HP dans ce sprint (régime preuve Docker différée) — code + tests
  uniquement.
- Commits fréquents, un par tâche, tests au vert avant de passer à la suivante.

---

## File Structure

| Fichier | Rôle |
|---|---|
| `briques/memoire/auth.py` (nouveau) | Dépendance FastAPI `identite()` — motif `briques/ecoute/auth.py` |
| `briques/memoire/main.py` (modifié) | `_normaliser_espace`, `Depends(auth.identite)` sur le contrat, garde du proxy `/api/v1/*`, boot `_index_injecte`/`spa` |
| `briques/memoire/test_memoire.py` (modifié) | + tests isolation contrat, garde proxy, boot |
| `briques/memoire/memory/frontend/src/services/api.ts` (modifié) | `BASE` configurable via `window.MEMOIRE_API_BASE` |
| `briques/memoire/memory/frontend/src/components/layout/TopBar.tsx` (modifié) | Sélecteur d'espace Commun/Personnel |
| `core/outils_communs.py` (modifié) | `BRIQUES_PAR_PERSONNE` += `"memoire"` |
| `core/graphe_apprentissage.py` (modifié) | Dialecte `X-API-Key` au lieu d'`Authorization: Bearer` |
| `core/test_graphe_apprentissage.py` (modifié) | + test du dialecte |
| `core/routers/memoire_proxy.py` (nouveau) | Proxy `/memoire-app/*` — motif `mail_proxy.py` |
| `core/test_memoire_proxy.py` (nouveau) | Tests du proxy — motif `core/test_mail_proxy.py` |
| `core/main.py` (modifié) | Enregistrement du router `memoire_proxy` |
| `core/routers/dashboard.py` (modifié) | Tuile Mémoire → `/memoire-app/` |
| `core/test_contexte_tenant.py` (modifié) | + assertion `_entetes_brique("memoire")` |
| `.env.example` (modifié) | `MEMOIRE_KEY` documentée |
| `briques/memoire/docker-compose.yml` (modifié) | `env_file` sur le service `memoire` |

---

### Task 1: `briques/memoire/auth.py` — identité de l'appelant

**Files:**
- Create: `briques/memoire/auth.py`
- Test: `briques/memoire/test_auth.py`

**Interfaces:**
- Produces: `identite(x_api_key: str | None = Header(None), authorization: str | None = Header(None), x_user_id: str | None = Header(None)) -> str` — retourne l'identité courante (`X-User-Id` ou repli `"perso"`) ; lève `HTTPException(401, ...)` si `MEMOIRE_KEY` est configurée et que la clé présentée ne correspond pas.

- [ ] **Step 1: Write the failing test**

```python
# briques/memoire/test_auth.py
"""Identité de l'appelant pour la brique memoire (S186) — motif briques/ecoute/auth.py."""
import os

import pytest
from fastapi import HTTPException

import auth


def test_mode_ouvert_sans_cle_retombe_sur_x_user_id(monkeypatch):
    monkeypatch.delenv("MEMOIRE_KEY", raising=False)
    assert auth.identite(x_api_key=None, authorization=None, x_user_id="claire") == "claire"


def test_mode_ouvert_sans_x_user_id_retombe_sur_perso(monkeypatch):
    monkeypatch.delenv("MEMOIRE_KEY", raising=False)
    assert auth.identite(x_api_key=None, authorization=None, x_user_id=None) == "perso"


def test_mode_gage_cle_correcte_forward_identite(monkeypatch):
    monkeypatch.setenv("MEMOIRE_KEY", "cle-coeur")
    assert auth.identite(x_api_key="cle-coeur", authorization=None, x_user_id="claire") == "claire"


def test_mode_gage_cle_absente_401(monkeypatch):
    monkeypatch.setenv("MEMOIRE_KEY", "cle-coeur")
    with pytest.raises(HTTPException) as exc:
        auth.identite(x_api_key=None, authorization=None, x_user_id="claire")
    assert exc.value.status_code == 401


def test_mode_gage_authorization_bearer_accepte(monkeypatch):
    monkeypatch.setenv("MEMOIRE_KEY", "cle-coeur")
    identite = auth.identite(x_api_key=None, authorization="Bearer cle-coeur", x_user_id="marina")
    assert identite == "marina"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd briques/memoire && python3.11 -m pytest test_auth.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'auth'`

- [ ] **Step 3: Write minimal implementation**

```python
# briques/memoire/auth.py
"""Identité de l'appelant pour la brique memoire (S186).

Motif copié de `briques/ecoute/auth.py` (S184) : `MEMOIRE_KEY` est le gage de confiance du
Cœur — seul lui la détient et peut donc forwarder l'identité de l'utilisateur connecté via
`X-User-Id`. Sans clé configurée, la brique reste en mode ouvert (dev/démo, convention du
monorepo) : l'identité retombe sur `X-User-Id` si présent, sinon `"perso"`.

Pas de dialecte « tenant externe » (contrairement à mail) : l'audit S183 classe `memoire`
« personne », pas « bundle-client ».
"""
from __future__ import annotations

import os
from typing import Optional

from fastapi import Header, HTTPException


def _presentee(x_api_key: Optional[str], authorization: Optional[str]) -> Optional[str]:
    return x_api_key or (authorization or "").removeprefix("Bearer ").strip() or None


def identite(x_api_key: Optional[str] = Header(None),
             authorization: Optional[str] = Header(None),
             x_user_id: Optional[str] = Header(None)) -> str:
    """Identité courante pour les routes du contrat et le proxy `/api/v1/*`."""
    cle_configuree = os.environ.get("MEMOIRE_KEY")
    if not cle_configuree:
        return x_user_id or "perso"
    if _presentee(x_api_key, authorization) != cle_configuree:
        raise HTTPException(401, "Clé API manquante ou invalide (header X-API-Key).")
    return x_user_id or "perso"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd briques/memoire && python3.11 -m pytest test_auth.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add briques/memoire/auth.py briques/memoire/test_auth.py
git commit -m "feat(memoire): identité de l'appelant (MEMOIRE_KEY + X-User-Id, S186)"
```

---

### Task 2: Verrou d'espace sur les routes du contrat

**Files:**
- Modify: `briques/memoire/main.py:146-155` (`_normaliser_espace`), routes `/retenir` (158-192),
  `/rappeler` (195-221), `/souvenirs` (224-259), `/taxonomy` (262-279),
  `DELETE /souvenir/{id}` (282-291)
- Test: `briques/memoire/test_memoire.py`

**Interfaces:**
- Consumes: `auth.identite` (Task 1)
- Produces: `_normaliser_espace(espace: str | None, identite: str) -> str | None` (remplace la
  fonction actuelle à 1 argument)

- [ ] **Step 1: Write the failing tests**

Ajouter à `briques/memoire/test_memoire.py` (après `_mock_auth_et_espace`, avant les tests
existants — les tests existants n'envoient pas de `X-User-Id`/`X-API-Key` et doivent continuer
à passer tels quels, en mode ouvert) :

```python
PERSO_ID = "22222222-2222-2222-2222-222222222222"
AUTRE_PERSO_ID = "33333333-3333-3333-3333-333333333333"


def _mock_espace_perso(rsx: respx.MockRouter, nom: str, espace_id: str):
    """Le backend Memory répond 'espace absent' au GET filtré, puis renvoie l'espace créé."""
    import re
    rsx.post(f"{API}/api/v1/spaces").mock(
        return_value=httpx.Response(200, json={"id": espace_id, "name": nom})
    )


@pytest.fixture(autouse=True)
def _memoire_key_absente(monkeypatch):
    """Par défaut, mode ouvert (comportement historique) — Task 2 active le verrou seulement
    si MEMOIRE_KEY est explicitement posée dans un test."""
    monkeypatch.delenv("MEMOIRE_KEY", raising=False)
    yield


@pytest.mark.asyncio
@respx.mock
async def test_espace_perso_identite_par_defaut_reste_nomme_perso():
    """Repli legacy : identite='perso' (mode ouvert, sans X-User-Id) → espace 'Perso',
    PAS 'Perso:perso' — zéro migration des souvenirs déjà stockés sous ce nom."""
    _mock_auth_et_espace(respx.mock)
    route = respx.get(f"{API}/api/v1/spaces").mock(
        return_value=httpx.Response(200, json=[
            {"id": ESPACE_ID, "name": "Workplace"},
            {"id": PERSO_ID, "name": "Perso"},
        ])
    )
    respx.get(f"{API}/api/v1/spaces/{PERSO_ID}/search").mock(
        return_value=httpx.Response(200, json=[])
    )
    r = await _appel("GET", "/rappeler", params={"q": "x", "espace": "perso"})
    assert r.status_code == 200
    espace_demande = [c for c in route.calls if c.request.method == "GET"]
    assert espace_demande  # au moins une résolution d'espace a eu lieu


@pytest.mark.asyncio
@respx.mock
async def test_espace_perso_isole_par_personne_en_mode_gage(monkeypatch):
    """MEMOIRE_KEY + X-User-Id distincts → espaces Memory distincts (Perso:claire vs Perso:marina)."""
    monkeypatch.setenv("MEMOIRE_KEY", "cle-coeur")
    _mock_auth_et_espace(respx.mock)
    respx.get(f"{API}/api/v1/spaces").mock(return_value=httpx.Response(
        200, json=[{"id": ESPACE_ID, "name": "Workplace"}]
    ))
    route_creation = respx.post(f"{API}/api/v1/spaces").mock(side_effect=[
        httpx.Response(200, json={"id": PERSO_ID, "name": "Perso:claire"}),
        httpx.Response(200, json={"id": AUTRE_PERSO_ID, "name": "Perso:marina"}),
    ])
    respx.get(f"{API}/api/v1/spaces/{PERSO_ID}/search").mock(return_value=httpx.Response(200, json=[]))
    respx.get(f"{API}/api/v1/spaces/{AUTRE_PERSO_ID}/search").mock(return_value=httpx.Response(200, json=[]))
    await _appel("GET", "/rappeler", params={"q": "x", "espace": "perso"},
                headers={"X-API-Key": "cle-coeur", "X-User-Id": "claire"})
    await _appel("GET", "/rappeler", params={"q": "x", "espace": "perso"},
                headers={"X-API-Key": "cle-coeur", "X-User-Id": "marina"})
    noms_crees = [_json_body(c.request)["name"] for c in route_creation.calls]
    assert noms_crees == ["Perso:claire", "Perso:marina"]


@pytest.mark.asyncio
@respx.mock
async def test_espace_libre_ignore_en_mode_gage_retombe_sur_solution(monkeypatch):
    """En mode gagé, une valeur d'espace arbitraire (tentative de viser l'espace d'un autre)
    est ignorée — repli sur l'espace solution, jamais honorée telle quelle."""
    monkeypatch.setenv("MEMOIRE_KEY", "cle-coeur")
    _mock_auth_et_espace(respx.mock)
    route = respx.get(f"{API}/api/v1/spaces/{ESPACE_ID}/search").mock(
        return_value=httpx.Response(200, json=[])
    )
    r = await _appel("GET", "/rappeler", params={"q": "x", "espace": "Perso:marina"},
                     headers={"X-API-Key": "cle-coeur", "X-User-Id": "claire"})
    assert r.status_code == 200
    assert route.called  # a bien tapé l'espace SOLUTION, pas un espace nommé "Perso:marina"
```

Ajouter un petit helper en haut du fichier (à côté de `_appel`) :

```python
def _json_body(request) -> dict:
    import json as _json
    return _json.loads(request.content)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd briques/memoire && python3.11 -m pytest test_memoire.py -k espace -v`
Expected: FAIL — `_normaliser_espace()` actuel ignore `identite`, les espaces perso ne sont
pas distingués (les 3 nouveaux tests échouent ; les tests existants passent encore).

- [ ] **Step 3: Write minimal implementation**

Dans `briques/memoire/main.py`, remplacer l'import et la fonction `_normaliser_espace`
(lignes 146-155) :

```python
from fastapi import Depends, FastAPI, Header, HTTPException  # ligne 29, + Depends

import auth  # nouvel import, à côté de httpx (ligne 28)


def _normaliser_espace(espace: str | None, identite: str) -> str | None:
    """Normalise l'espace + verrouille l'identité (S186).

    - 'solution' / vide → None (espace commun, inchangé).
    - 'perso' → nom d'espace Memory par personne : 'Perso' pour l'identité par défaut
      (repli legacy 'perso', ZÉRO migration des souvenirs déjà stockés sous ce nom),
      'Perso:{identite}' pour toute autre personne.
    - Toute AUTRE valeur, si MEMOIRE_KEY est configurée (mode gagé) : ignorée, repli
      solution — l'identité vient TOUJOURS du serveur, jamais de ce que le client demande.
      En mode ouvert (pas de clé), comportement historique inchangé (valeur brute honorée).
    """
    if not espace or espace.strip().lower() == "solution":
        return None
    if espace.strip().lower() == "perso":
        return "Perso" if identite == "perso" else f"Perso:{identite}"
    if os.environ.get("MEMOIRE_KEY"):
        return None
    return espace
```

Mettre à jour chaque route du contrat pour prendre `identite: str = Depends(auth.identite)`
et passer les deux arguments à `_normaliser_espace` :

```python
@app.post("/retenir", summary="Mémoriser un souvenir")
async def retenir(s: Souvenir, identite: str = Depends(auth.identite)):
    s = s.model_copy(update={"espace": _normaliser_espace(s.espace, identite)})
    ...  # reste inchangé
```

```python
@app.get("/rappeler", summary="Retrouver des souvenirs (recherche hybride)")
async def rappeler(q: str = "", limite: int = 8, type: str | None = None,
                   espace: str | None = None, identite: str = Depends(auth.identite)):
    espace = _normaliser_espace(espace, identite)
    ...  # reste inchangé
```

```python
@app.get("/souvenirs", summary="Lister les souvenirs récents")
async def souvenirs(limite: int = 20, type: str | None = None,
                    wing: str | None = None, room: str | None = None,
                    espace: str | None = None, identite: str = Depends(auth.identite)):
    espace = _normaliser_espace(espace, identite)
    ...  # reste inchangé
```

```python
@app.get("/taxonomy", summary="Comptes par type (pour les onglets/wings)")
async def taxonomy(espace: str | None = None, identite: str = Depends(auth.identite)):
    espace = _normaliser_espace(espace, identite)
    ...  # reste inchangé
```

```python
@app.delete("/souvenir/{souvenir_id}", summary="Supprimer un souvenir")
async def supprimer(souvenir_id: str, espace: str | None = None,
                    identite: str = Depends(auth.identite)):
    espace = _normaliser_espace(espace, identite)
    ...  # reste inchangé
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd briques/memoire && python3.11 -m pytest test_memoire.py -v`
Expected: tous les tests passent (existants + 3 nouveaux)

- [ ] **Step 5: Commit**

```bash
git add briques/memoire/main.py briques/memoire/test_memoire.py
git commit -m "feat(memoire): verrou d'espace par personne sur le contrat (retenir/rappeler/souvenirs/taxonomy/supprimer)"
```

---

### Task 3: Garde du proxy générique `/api/v1/{chemin:path}`

**Files:**
- Modify: `briques/memoire/main.py:309-337` (`proxy_api`)
- Test: `briques/memoire/test_memoire.py`

**Interfaces:**
- Consumes: `auth.identite` (Task 1), `_espace_id` (existant, `briques/memoire/main.py:79`)
- Produces: `proxy_api` gagne un comportement de garde en mode gagé — aucune nouvelle fonction
  publique, comportement observable via HTTP uniquement.

- [ ] **Step 1: Write the failing tests**

Ajouter à `briques/memoire/test_memoire.py` :

```python
@pytest.mark.asyncio
@respx.mock
async def test_proxy_filtre_get_spaces_en_mode_gage(monkeypatch):
    """GET /api/v1/spaces ne renvoie QUE l'espace solution + l'espace perso de l'appelant —
    pas la liste complète du compte de service (la faille trouvée en conception)."""
    monkeypatch.setenv("MEMOIRE_KEY", "cle-coeur")
    _mock_auth_et_espace(respx.mock)
    respx.get(f"{API}/api/v1/spaces").mock(return_value=httpx.Response(200, json=[
        {"id": ESPACE_ID, "name": "Workplace"},
        {"id": PERSO_ID, "name": "Perso:claire"},
        {"id": AUTRE_PERSO_ID, "name": "Perso:marina"},
    ]))
    r = await _appel("GET", "/api/v1/spaces",
                     headers={"X-API-Key": "cle-coeur", "X-User-Id": "claire"})
    assert r.status_code == 200
    ids = {e["id"] for e in r.json()}
    assert ids == {ESPACE_ID, PERSO_ID}
    assert AUTRE_PERSO_ID not in ids


@pytest.mark.asyncio
@respx.mock
async def test_proxy_404_hors_allowlist_en_mode_gage(monkeypatch):
    """.../spaces/{id}/... avec un id hors allowlist → 404, requête jamais transmise en amont."""
    monkeypatch.setenv("MEMOIRE_KEY", "cle-coeur")
    _mock_auth_et_espace(respx.mock)
    respx.get(f"{API}/api/v1/spaces").mock(return_value=httpx.Response(
        200, json=[{"id": ESPACE_ID, "name": "Workplace"}, {"id": PERSO_ID, "name": "Perso:claire"}]
    ))
    route_interdite = respx.get(f"{API}/api/v1/spaces/{AUTRE_PERSO_ID}/nodes").mock(
        return_value=httpx.Response(200, json=[{"id": "fuite"}])
    )
    r = await _appel("GET", f"/api/v1/spaces/{AUTRE_PERSO_ID}/nodes",
                     headers={"X-API-Key": "cle-coeur", "X-User-Id": "claire"})
    assert r.status_code == 404
    assert not route_interdite.called


@pytest.mark.asyncio
@respx.mock
async def test_proxy_post_spaces_bloque_en_mode_gage(monkeypatch):
    """POST /api/v1/spaces (création) est bloqué en mode gagé — les 2 espaces existent déjà."""
    monkeypatch.setenv("MEMOIRE_KEY", "cle-coeur")
    _mock_auth_et_espace(respx.mock)
    respx.get(f"{API}/api/v1/spaces").mock(return_value=httpx.Response(
        200, json=[{"id": ESPACE_ID, "name": "Workplace"}, {"id": PERSO_ID, "name": "Perso:claire"}]
    ))
    r = await _appel("POST", "/api/v1/spaces", json={"name": "Fuite"},
                     headers={"X-API-Key": "cle-coeur", "X-User-Id": "claire"})
    assert r.status_code == 403


@pytest.mark.asyncio
@respx.mock
async def test_proxy_passthrough_integral_en_mode_ouvert():
    """Sans MEMOIRE_KEY configurée (mode ouvert historique) : aucun filtre, comportement
    identique à avant S186 — pas de régression pour Forge/tests/dev."""
    _mock_auth_et_espace(respx.mock)
    route = respx.get(f"{API}/api/v1/spaces").mock(return_value=httpx.Response(200, json=[
        {"id": ESPACE_ID, "name": "Workplace"},
        {"id": PERSO_ID, "name": "Perso:claire"},
    ]))
    r = await _appel("GET", "/api/v1/spaces")
    assert r.status_code == 200
    assert len(r.json()) == 2  # liste NON filtrée
    assert route.called
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd briques/memoire && python3.11 -m pytest test_memoire.py -k proxy_filtre -v`
Expected: FAIL — `proxy_api` actuel n'a aucun filtre (le test `test_proxy_404_hors_allowlist`
échoue avec un `200`, `test_proxy_filtre_get_spaces` échoue avec les 3 ids, `test_proxy_post_spaces`
échoue avec un statut différent de 403).

- [ ] **Step 3: Write minimal implementation**

Dans `briques/memoire/main.py`, ajouter en haut du fichier (à côté des imports existants) :

```python
import json
import re
```

Ajouter juste avant `proxy_api` (avant la ligne `@app.api_route("/api/v1/{chemin:path}", ...)`) :

```python
_RE_SPACE_ID = re.compile(r"^spaces/([^/]+)")


async def _espaces_autorises(client: httpx.AsyncClient, identite: str) -> set[str]:
    """Les DEUX espaces Memory que cet appelant a le droit d'adresser via le proxy brut :
    l'espace solution (commun) et son propre espace perso (créé à la demande)."""
    sol_id = await _espace_id(client)
    nom_perso = "Perso" if identite == "perso" else f"Perso:{identite}"
    perso_id = await _espace_id(client, nom_perso)
    return {sol_id, perso_id}
```

Remplacer `proxy_api` (lignes 309-337) :

```python
@app.api_route(
    "/api/v1/{chemin:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def proxy_api(chemin: str, request: Request, identite: str = Depends(auth.identite)):
    """Relaie /api/v1/* vers le backend Memory interne en forçant l'auth de service.

    On IGNORE l'Authorization éventuel du front (jeton injecté, peut-être périmé) et on
    pose toujours un JWT de service frais : la brique est mono-locataire côté Memory (un
    seul compte de service, propriétaire de TOUS les espaces).

    En mode gagé (MEMOIRE_KEY configurée, S186) : ce JWT unique a accès à TOUS les espaces
    de TOUT le monde — sans garde ici, le sélecteur d'espace du front serait contournable
    depuis la console du navigateur (GET /api/v1/spaces listerait tout, un id d'espace
    deviné donnerait accès à l'espace perso d'un autre). Donc : réponse de `GET /spaces`
    filtrée à {solution, perso de l'appelant} ; tout chemin `spaces/{id}/...` avec un id
    hors de ces deux-là → 404 sans jamais atteindre le backend ; `POST /spaces` (création)
    bloqué (les deux espaces existent déjà, créés au boot). Mode ouvert : inchangé,
    passthrough intégral (comme avant S186).
    """
    corps = await request.body()
    entetes = {
        k: v for k, v in request.headers.items()
        if k.lower() not in _HOP_BY_HOP and k.lower() != "authorization"
    }
    cle_configuree = os.environ.get("MEMOIRE_KEY")
    async with await _client() as client:
        entetes["Authorization"] = f"Bearer {await _token(client)}"
        autorises: set[str] = set()
        if cle_configuree:
            autorises = await _espaces_autorises(client, identite)
            if chemin == "spaces" and request.method == "POST":
                raise HTTPException(403, "Création d'espace non autorisée depuis le front.")
            m = _RE_SPACE_ID.match(chemin)
            if m and m.group(1) not in autorises:
                raise HTTPException(404)
        amont = await client.request(
            request.method,
            f"{MEMORY_API}/api/v1/{chemin}",
            params=dict(request.query_params),
            content=corps,
            headers=entetes,
        )
    if (cle_configuree and chemin == "spaces" and request.method == "GET"
            and amont.status_code < 400):
        try:
            data = json.loads(amont.content or b"[]")
        except ValueError:
            data = []
        filtre = [e for e in data if e.get("id") in autorises]
        return Response(content=json.dumps(filtre).encode(), status_code=amont.status_code,
                        media_type="application/json")
    sortie = {
        k: v for k, v in amont.headers.items() if k.lower() not in _HOP_BY_HOP
    }
    return Response(content=amont.content, status_code=amont.status_code,
                    headers=sortie, media_type=amont.headers.get("content-type"))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd briques/memoire && python3.11 -m pytest test_memoire.py -v`
Expected: tous les tests passent

- [ ] **Step 5: Commit**

```bash
git add briques/memoire/main.py briques/memoire/test_memoire.py
git commit -m "feat(memoire): garde du proxy /api/v1/* par allowlist d'espaces (S186)"
```

---

### Task 4: Boot du front — `workplace_spaces` + `MEMOIRE_API_BASE`

**Files:**
- Modify: `briques/memoire/main.py:350-385` (`_index_injecte`, `spa`)
- Modify: `briques/memoire/memory/frontend/src/services/api.ts:20`
- Test: `briques/memoire/test_memoire.py`

**Interfaces:**
- Consumes: `auth.identite`, `_espace_id`, `_token`
- Produces: `_index_injecte(identite: str) -> str` (signature changée, prenait 0 argument avant)

- [ ] **Step 1: Write the failing test**

Remplacer le test existant `test_spa_injecte_le_bootstrap` (lignes 247-263 de
`briques/memoire/test_memoire.py`) par :

```python
@pytest.mark.asyncio
@respx.mock
async def test_spa_injecte_le_bootstrap(tmp_path, monkeypatch):
    """La route SPA /memory rend l'index avec auth_token, active_space_id (solution, défaut
    inchangé) ET workplace_spaces (nouveau, S186 — {solution, perso} pour le sélecteur front)."""
    _mock_auth_et_espace(respx.mock)
    respx.get(f"{API}/api/v1/spaces").mock(return_value=httpx.Response(
        200, json=[{"id": ESPACE_ID, "name": "Workplace"}]
    ))
    (tmp_path / "index.html").write_text(
        "<!doctype html><html><head><title>x</title></head><body></body></html>",
        encoding="utf-8",
    )
    monkeypatch.setattr(main, "UI_DIR", tmp_path)
    r = await _appel("GET", "/memory")
    assert r.status_code == 200
    html = r.text
    assert "localStorage.setItem('auth_token'" in html
    assert "jwt-de-service" in html
    assert f"localStorage.setItem('active_space_id','{ESPACE_ID}')" in html
    assert "workplace_spaces" in html
    assert ESPACE_ID in html
    assert "</head>" in html


@pytest.mark.asyncio
@respx.mock
async def test_spa_workplace_spaces_porte_l_espace_perso_en_mode_gage(tmp_path, monkeypatch):
    """En mode gagé, workplace_spaces.perso pointe vers l'espace Perso:{identite} du
    demandeur (créé à la demande) — pas un id partagé avec d'autres personnes."""
    monkeypatch.setenv("MEMOIRE_KEY", "cle-coeur")
    _mock_auth_et_espace(respx.mock)
    respx.get(f"{API}/api/v1/spaces").mock(return_value=httpx.Response(
        200, json=[{"id": ESPACE_ID, "name": "Workplace"}]
    ))
    respx.post(f"{API}/api/v1/spaces").mock(
        return_value=httpx.Response(200, json={"id": PERSO_ID, "name": "Perso:claire"})
    )
    (tmp_path / "index.html").write_text(
        "<!doctype html><html><head><title>x</title></head><body></body></html>",
        encoding="utf-8",
    )
    monkeypatch.setattr(main, "UI_DIR", tmp_path)
    r = await _appel("GET", "/memory", headers={"X-API-Key": "cle-coeur", "X-User-Id": "claire"})
    assert r.status_code == 200
    assert PERSO_ID in r.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd briques/memoire && python3.11 -m pytest test_memoire.py -k spa_ -v`
Expected: FAIL — `_index_injecte()` actuel ne prend pas d'argument `identite` et n'injecte pas
`workplace_spaces`.

- [ ] **Step 3: Write minimal implementation**

Remplacer `_index_injecte` (lignes 350-366) et `spa` (lignes 374-385) dans
`briques/memoire/main.py` :

```python
async def _index_injecte(identite: str) -> str:
    """index.html du front avec un <script> qui pré-remplit localStorage (auth + espaces)."""
    index = UI_DIR / "index.html"
    if not index.is_file():
        return ("<!doctype html><meta charset=utf-8><title>Mémoire</title>"
                "<p>Front non buildé (image construite sans le stage Node ?).</p>")
    html = index.read_text(encoding="utf-8")
    async with await _client() as client:
        token = await _token(client)
        sol_id = await _espace_id(client)
        perso_id = None
        if os.environ.get("MEMOIRE_KEY"):
            nom_perso = "Perso" if identite == "perso" else f"Perso:{identite}"
            perso_id = await _espace_id(client, nom_perso)
    espaces = json.dumps({"solution": sol_id, "perso": perso_id})
    boot = (
        "<script>try{"
        f"localStorage.setItem('auth_token',{token!r});"
        f"localStorage.setItem('active_space_id',{sol_id!r});"
        f"localStorage.setItem('workplace_spaces',{espaces!r});"
        "}catch(e){}</script>"
    )
    return html.replace("</head>", boot + "</head>", 1)


@app.get("/", include_in_schema=False)
async def racine():
    return RedirectResponse("/memory")


@app.get("/{chemin:path}", include_in_schema=False)
async def spa(chemin: str, identite: str = Depends(auth.identite)):
    """Fallback SPA : toute route front (/memory, /memory/graph, …) rend l'index injecté.

    Déclaré en DERNIER : le contrat (/sante, /retenir…) et /api/v1 sont matchés avant.
    Un fichier statique racine présent (favicon.svg…) est servi tel quel.
    """
    if chemin and UI_DIR.is_dir():
        cible = UI_DIR / chemin
        if cible.is_file() and cible.resolve().is_relative_to(UI_DIR.resolve()):
            return Response(content=cible.read_bytes(), media_type=_type_mime(cible.name))
    return HTMLResponse(await _index_injecte(identite))
```

(`json` est déjà importé en tête de fichier depuis la Task 3.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd briques/memoire && python3.11 -m pytest test_memoire.py -v`
Expected: tous les tests passent

- [ ] **Step 5: Update the frontend `api.ts` base URL**

Dans `briques/memoire/memory/frontend/src/services/api.ts:20`, remplacer :

```ts
const BASE = '/api/v1'
```

par :

```ts
// window.MEMOIRE_API_BASE est posé par le proxy du Cœur (/memoire-app/*, S186) pour que
// tous les appels passent par lui, isolés par personne. Vide en usage autoporté direct
// (comportement historique inchangé — zéro effet hors du proxy).
const BASE = ((window as unknown as { MEMOIRE_API_BASE?: string }).MEMOIRE_API_BASE || '') + '/api/v1'
```

- [ ] **Step 6: Commit**

```bash
git add briques/memoire/main.py briques/memoire/test_memoire.py \
        briques/memoire/memory/frontend/src/services/api.ts
git commit -m "feat(memoire): boot front injecte workplace_spaces + BASE configurable (S186)"
```

---

### Task 5: Sélecteur d'espace dans le front (TopBar)

**Files:**
- Modify: `briques/memoire/memory/frontend/src/components/layout/TopBar.tsx`

**Interfaces:**
- Consumes: `useAppStore().setActiveSpace(id: string)` (existant,
  `briques/memoire/memory/frontend/src/stores/appStore.ts:8`), `localStorage.workplace_spaces`
  (posé par Task 4, JSON `{solution: string, perso: string|null}`)
- Produces: composant visuel, pas d'interface consommée par d'autres tâches.

- [ ] **Step 1: Write the component (pas de test front dans ce monorepo — pas de suite Vitest
      existante sur `memory/frontend` ; vérification par build + revue manuelle, cf. Step 3)**

Dans `briques/memoire/memory/frontend/src/components/layout/TopBar.tsx`, ajouter en haut du
fichier (après les imports existants) :

```tsx
import { useAppStore } from '../../stores/appStore'
import * as api from '../../services/api'

interface EspacesFoyer {
  solution: string
  perso: string | null
}

function lireEspacesFoyer(): EspacesFoyer | null {
  const brut = localStorage.getItem('workplace_spaces')
  if (!brut) return null
  try {
    return JSON.parse(brut) as EspacesFoyer
  } catch {
    return null
  }
}

function SelecteurEspace() {
  const activeSpaceId = useAppStore((s) => s.activeSpaceId)
  const setActiveSpace = useAppStore((s) => s.setActiveSpace)
  const espaces = lireEspacesFoyer()
  if (!espaces || !espaces.perso) return null  // pas de session gagée → pas de sélecteur

  const surPerso = activeSpaceId === espaces.perso
  function basculer(versPerso: boolean) {
    const cible = versPerso ? espaces!.perso! : espaces!.solution
    if (cible === activeSpaceId) return
    setActiveSpace(cible)
    window.location.reload()  // données déjà chargées en mémoire React, on repart propre
  }

  return (
    <div className="flex items-center rounded-lg bg-surface-2 border border-border p-0.5 text-xs">
      <button
        onClick={() => basculer(false)}
        className={`px-2.5 py-1 rounded-md transition-colors ${!surPerso ? 'bg-memory-600/30 text-text-heading' : 'text-text'}`}
      >
        Commun
      </button>
      <button
        onClick={() => basculer(true)}
        className={`px-2.5 py-1 rounded-md transition-colors ${surPerso ? 'bg-memory-600/30 text-text-heading' : 'text-text'}`}
      >
        Personnel
      </button>
    </div>
  )
}
```

(`api` n'est pas utilisé par `SelecteurEspace` mais déjà importé par le fichier existant sous
le nom `* as api` en ligne 5 — ne pas le réimporter en double.)

Dans le JSX de `TopBar` (ligne 60), insérer `<SelecteurEspace />` juste avant
`<div className="relative ml-auto" ref={menuRef}>` :

```tsx
      <SelecteurEspace />

      <div className="relative ml-auto" ref={menuRef}>
```

- [ ] **Step 2: Corriger le doublon d'import**

Le fichier importe déjà `useAppStore` (ligne 4) et `api` (ligne 5) — retirer les deux lignes
d'import ajoutées au Step 1 en tête de fichier (elles sont redondantes avec les imports
existants du fichier) ; ne garder que les définitions de `EspacesFoyer`,
`lireEspacesFoyer` et `SelecteurEspace`.

- [ ] **Step 3: Vérifier le build**

Run: `cd briques/memoire/memory/frontend && npm run build`
Expected: build réussi, aucune erreur TypeScript (`EspacesFoyer`/`lireEspacesFoyer` bien
typés, pas de `any` implicite).

- [ ] **Step 4: Commit**

```bash
git add briques/memoire/memory/frontend/src/components/layout/TopBar.tsx
git commit -m "feat(memoire): sélecteur d'espace Commun/Personnel dans la topbar (S186)"
```

---

### Task 6: Câblage assistant — `BRIQUES_PAR_PERSONNE` + dialecte `graphe_apprentissage`

**Files:**
- Modify: `core/outils_communs.py:51`
- Modify: `core/graphe_apprentissage.py:127-149`
- Test: `core/test_contexte_tenant.py`, `core/test_graphe_apprentissage.py`

**Interfaces:**
- Produces: `outils_communs.BRIQUES_PAR_PERSONNE` inclut `"memoire"` ;
  `graphe_apprentissage.charger_graphe` présente `X-API-Key` au lieu d'`Authorization: Bearer`.

- [ ] **Step 1: Write the failing tests**

Dans `core/test_contexte_tenant.py`, modifier `test_entetes_brique_par_personne_forwarde_identite`
(lignes 149-159) :

```python
def test_entetes_brique_par_personne_forwarde_identite():
    """S182 (agenda) + S184 (ecoute) + S185 (mail) + S186 (memoire) : la surface /service
    (outils de l'assistant) doit porter X-User-Id = utilisateur connecté pour les briques
    « cercle privé » ; les autres briques ne le portent pas."""
    _reset_complet()
    import outils_communs
    ct.definir_contexte(utilisateur="claire")
    assert outils_communs._entetes_brique("agenda")["X-User-Id"] == "claire"
    assert outils_communs._entetes_brique("ecoute")["X-User-Id"] == "claire"
    assert outils_communs._entetes_brique("mail")["X-User-Id"] == "claire"
    assert outils_communs._entetes_brique("memoire")["X-User-Id"] == "claire"
    # Une autre brique (ex. restaurant) ne reçoit PAS X-User-Id (elle l'ignorerait).
```

Ajouter à `core/test_graphe_apprentissage.py` (après `test_9_brique_indisponible_graphe_vide`) :

```python
def test_13_presente_x_api_key_pas_authorization_bearer():
    """S186 : dialecte unifié avec agenda/ecoute/mail — X-API-Key, pas Authorization Bearer
    (sinon 401 dès que la brique memoire vérifie réellement MEMOIRE_KEY)."""
    appels = []

    class _FakeResponse:
        status_code = 200
        def raise_for_status(self):
            pass
        def json(self):
            return {"souvenirs": []}

    class _FakeClient:
        def __init__(self, *a, **k):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False
        async def get(self, url, headers=None, params=None):
            appels.append((url, headers))
            return _FakeResponse()

    import httpx as _httpx
    real_async_client = _httpx.AsyncClient
    _httpx.AsyncClient = _FakeClient
    os.environ["MEMOIRE_KEY"] = "cle-test"
    try:
        asyncio.run(ga.charger_graphe([_spec("x")]))
    finally:
        _httpx.AsyncClient = real_async_client
        del os.environ["MEMOIRE_KEY"]
        ga._graphe.construire([], [])
    assert appels
    _, entetes = appels[0]
    assert entetes.get("X-API-Key") == "cle-test"
    assert "Authorization" not in entetes
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd core && python3 -m pytest test_contexte_tenant.py -k par_personne -v`
Expected: FAIL — `_entetes_brique("memoire")` ne porte pas `X-User-Id`.

Run: `cd core && python3 test_graphe_apprentissage.py` (ou `pytest test_graphe_apprentissage.py -k test_13`)
Expected: FAIL — `charger_graphe` envoie encore `Authorization: Bearer`.

- [ ] **Step 3: Write minimal implementation**

Dans `core/outils_communs.py:51`, remplacer :

```python
BRIQUES_PAR_PERSONNE = {"agenda", "ecoute", "mail"}
```

par :

```python
BRIQUES_PAR_PERSONNE = {"agenda", "ecoute", "mail", "memoire"}
```

Dans `core/graphe_apprentissage.py`, remplacer le bloc `charger_graphe` (lignes 127-138) :

```python
async def charger_graphe(specs_capacites: list[dict]) -> None:
    """Récupère les souvenirs de la brique mémoire et reconstruit le graphe lexical."""
    memoire_url = os.getenv("MEMOIRE_URL", "http://memoire:5600")
    memoire_key = os.getenv("MEMOIRE_KEY", "")
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(
                f"{memoire_url}/souvenirs",
                headers={"X-API-Key": memoire_key} if memoire_key else {},
                params={"limite": 200},
            )
            r.raise_for_status()
            souvenirs = [
                (e.get("contenu") or e.get("titre") or "")
                for e in r.json().get("souvenirs", [])
            ]
    except Exception:  # noqa: BLE001 — brique absente = graphe vide, pas de crash
        souvenirs = []
    _graphe.construire(souvenirs, specs_capacites)
    logger.info(
        "Graphe apprentissage : %d capacités liées depuis %d souvenirs",
        len(_graphe._boost), len(souvenirs),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd core && python3 -m pytest test_contexte_tenant.py test_graphe_apprentissage.py -v`
Expected: tous les tests passent

- [ ] **Step 5: Commit**

```bash
git add core/outils_communs.py core/graphe_apprentissage.py \
        core/test_contexte_tenant.py core/test_graphe_apprentissage.py
git commit -m "feat(core): memoire en BRIQUES_PAR_PERSONNE + dialecte X-API-Key unifié (S186)"
```

---

### Task 7: `core/routers/memoire_proxy.py` — vue native de la tuile dashboard

**Files:**
- Create: `core/routers/memoire_proxy.py`
- Modify: `core/main.py:24,90` (import + enregistrement)
- Test: `core/test_memoire_proxy.py`

**Interfaces:**
- Consumes: `orchestrateur._brique_base`, `outils_communs._entetes_brique("memoire")`
  (Task 6), `auth.exiger_session`, `contexte_tenant.lire_contexte_tenant`
- Produces: router FastAPI monté sous `/memoire-app/*`.

- [ ] **Step 1: Write the failing test**

```python
# core/test_memoire_proxy.py
"""Proxy memoire du Cœur (S186) : vue native /memoire-app/*, isolée PAR PERSONNE.

Sans réseau : httpx.AsyncClient est remplacé par un faux client (motif test_mail_proxy.py).
Vérifie que l'identité forwardée à la brique memoire vient de LA SESSION (contexte de
tenant), jamais de ce que le navigateur a lui-même posé sur sa requête au Cœur — et que le
préfixe /memoire-app est bien injecté pour les assets et l'API.
"""
import os

os.environ.setdefault("VAULT_SECRET", "test-secret-0123456789")
os.environ.setdefault("GATEWAY_KEY", "test")
os.environ["MEMOIRE_KEY"] = "cle-coeur-memoire"

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from routers import memoire_proxy  # noqa: E402

client = TestClient(main.app)

APPELS = []


class _Resp:
    def __init__(self, texte="", status=200, content_type="text/html"):
        self._texte = texte
        self.status_code = status
        self.headers = {"content-type": content_type}
        self.content = texte.encode()

    @property
    def text(self):
        return self._texte


class _FakeClient:
    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def request(self, method, url, headers=None, params=None, content=None):
        APPELS.append((method, url, headers))
        return _Resp()

    async def get(self, url, headers=None):
        APPELS.append(("GET", url, headers))
        return _Resp(texte='<html><head></head><body>'
                            '<script type="module" src="/assets/index-abc.js"></script>'
                            '</body></html>')


def _setup(monkeypatch):
    APPELS.clear()
    monkeypatch.setattr(memoire_proxy, "_base", lambda: "http://memoire")
    monkeypatch.setattr(memoire_proxy, "httpx", type("_H", (), {"AsyncClient": _FakeClient}))


def test_racine_injecte_le_prefixe_et_reecrit_les_assets(monkeypatch):
    _setup(monkeypatch)
    r = client.get("/memoire-app/", headers={"X-User-Id": "claire"})
    assert r.status_code == 200
    assert "window.MEMOIRE_API_BASE='/memoire-app';" in r.text
    assert 'src="/memoire-app/assets/index-abc.js"' in r.text


def test_identite_de_session_forwardee_pas_celle_du_navigateur(monkeypatch):
    _setup(monkeypatch)
    r = client.get("/memoire-app/api/v1/spaces", headers={
        "X-User-Id": "claire", "X-API-Key": "cle-volee-par-le-navigateur",
    })
    assert r.status_code == 200
    methode, url, entetes = APPELS[-1]
    assert url == "http://memoire/api/v1/spaces"
    assert entetes["X-User-Id"] == "claire"
    assert entetes["X-API-Key"] == "cle-coeur-memoire"


def test_deux_personnes_appels_distincts(monkeypatch):
    _setup(monkeypatch)
    client.get("/memoire-app/api/v1/spaces", headers={"X-User-Id": "claire"})
    client.get("/memoire-app/api/v1/spaces", headers={"X-User-Id": "marina"})
    identites = [e["X-User-Id"] for _, _, e in APPELS]
    assert identites == ["claire", "marina"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd core && python3 -m pytest test_memoire_proxy.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'routers.memoire_proxy'`

- [ ] **Step 3: Write minimal implementation**

```python
# core/routers/memoire_proxy.py
"""Proxy « memoire » du Cœur (S186) : vue native de la tuile dashboard, isolée PAR PERSONNE.

Le front React de la brique memoire (`briques/memoire/memory/frontend`) fait ses appels
fetch() en chemin absolu (`/api/v1/...`), et référence ses assets buildés en chemin absolu
(`/assets/...`). On sert la MÊME page sous `/memoire-app/*` en réécrivant ces deux familles
de chemins vers ce préfixe, et on proxy chaque appel vers la vraie brique en y injectant
l'identité de la SESSION Cœur courante (`outils_communs._entetes_brique("memoire")` →
X-User-Id, motif agenda S182 / ecoute S184 / mail S185) — au lieu de laisser le navigateur
appeler la brique en direct, ce qui retomberait sur l'identité « perso » partagée par tout
le foyer (trou S183).

Sécurité : toute en-tête d'identité envoyée par le navigateur (X-API-Key, X-User-Id,
Authorization) est ignorée — seule l'identité de la session Cœur (cookie, `exiger_session` +
`lire_contexte_tenant` posés sur ce router dans `main.py`) compte. La garde fine par espace
(allowlist solution+perso, filtrage de `GET /spaces`) vit côté brique memoire
(`briques/memoire/main.py::proxy_api`), pas ici — ce proxy ne fait que transporter l'identité
correcte, jamais de la logique métier.
"""
from __future__ import annotations

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

import orchestrateur
import outils_communs
from etat import registre

router = APIRouter()

_PREFIXE = "/memoire-app"
_TIMEOUT = 30.0


def _base() -> str:
    return orchestrateur._brique_base(registre, "memoire")


def _entetes(request: Request) -> dict:
    entetes = dict(outils_communs._entetes_brique("memoire"))
    type_contenu = request.headers.get("content-type")
    if type_contenu:
        entetes["Content-Type"] = type_contenu
    return entetes


@router.get(_PREFIXE + "/", response_class=HTMLResponse)
async def memoire_app_racine(request: Request):
    """Page memoire, avec `MEMOIRE_API_BASE` posé pour que TOUS ses appels passent par ce proxy."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.get(f"{_base()}/", headers=_entetes(request))
    page = (r.text
            .replace('="/assets/', f'="{_PREFIXE}/assets/')
            .replace("</head>", f"<script>window.MEMOIRE_API_BASE='{_PREFIXE}';</script></head>"))
    return HTMLResponse(page, status_code=r.status_code)


@router.api_route(_PREFIXE + "/{chemin:path}", methods=["GET", "POST", "DELETE", "PATCH", "PUT"])
async def memoire_app_proxy(chemin: str, request: Request):
    """Proxy générique du reste des routes memoire (assets, /api/v1/*, contrat)."""
    corps = await request.body()
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.request(
            request.method, f"{_base()}/{chemin}",
            params=request.query_params, headers=_entetes(request),
            content=corps or None,
        )
    return Response(content=r.content, status_code=r.status_code,
                    media_type=r.headers.get("content-type"))
```

Dans `core/main.py:24`, remplacer :

```python
from routers import agenda, assistant, dashboard, mail_proxy, profil, systeme, usine
```

par :

```python
from routers import agenda, assistant, dashboard, mail_proxy, memoire_proxy, profil, systeme, usine
```

Dans `core/main.py`, après la ligne 90 (enregistrement de `mail_proxy.router`), ajouter :

```python
# Mémoire (S186) : session obligatoire (comme dashboard/mail) + contexte de tenant
# (X-User-Id de session → identité forwardée à la brique memoire) pour que la vue native
# soit isolée par personne, cf. core/routers/memoire_proxy.py.
app.include_router(memoire_proxy.router, dependencies=[Depends(exiger_session)] + _tenant)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd core && python3 -m pytest test_memoire_proxy.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add core/routers/memoire_proxy.py core/main.py core/test_memoire_proxy.py
git commit -m "feat(core): proxy /memoire-app/* isolé par personne (S186, motif mail_proxy)"
```

---

### Task 8: Dashboard — tuile Mémoire pointée sur le proxy

**Files:**
- Modify: `core/routers/dashboard.py:770`, `core/routers/dashboard.py:3423`

**Interfaces:**
- Consumes: `/memoire-app/` (Task 7)

- [ ] **Step 1: Modifier la tuile**

Dans `core/routers/dashboard.py:770`, remplacer :

```html
<button class="creation-tuile" onclick="ouvrirCreation('__MEMOIRE_UI_URL__', 'Mémoire — graphe IPCRA')">
```

par :

```html
<button class="creation-tuile" onclick="ouvrirCreation('/memoire-app/', 'Mémoire — graphe IPCRA')">
```

(Même origine, session Cœur déjà posée — comme mail. Le bouton « Ouvrir dans un onglet »
généré par `ouvrirCreation()` réutilise la même URL, donc reste isolé par personne lui aussi
— pas de divergence à documenter comme pour mail.)

- [ ] **Step 2: Retirer la substitution devenue inutile**

Dans `core/routers/dashboard.py:3423`, supprimer la ligne :

```python
        .replace("__MEMOIRE_UI_URL__", u("MEMOIRE"))
```

- [ ] **Step 3: Vérifier qu'aucun test ne référence `__MEMOIRE_UI_URL__`**

Run: `cd core && grep -rn "MEMOIRE_UI_URL" .`
Expected: aucune occurrence restante (le placeholder n'existe plus dans le template ni le
remplacement).

- [ ] **Step 4: Run le test de fumée du dashboard**

Run: `cd core && python3 -m pytest test_urls_ui.py -v`
Expected: passe sans modification (le test ne couvrait pas `MEMOIRE_UI_URL`, confirmé au grep
préalable de l'exploration).

- [ ] **Step 5: Commit**

```bash
git add core/routers/dashboard.py
git commit -m "feat(dashboard): tuile Mémoire via le proxy /memoire-app/ (S186)"
```

---

### Task 9: Configuration — `.env.example` + `docker-compose.yml`

**Files:**
- Modify: `.env.example:126` (après `ECOUTE_KEY=`)
- Modify: `briques/memoire/docker-compose.yml:56-64` (service `memoire`)

**Interfaces:** aucune (configuration pure).

- [ ] **Step 1: Documenter `MEMOIRE_KEY`**

Dans `.env.example`, après la ligne 126 (`ECOUTE_KEY=`), insérer :

```
# Clé de service pour l'isolation par personne de la mémoire (S186) : le Cœur la présente en
# X-API-Key sur les routes du contrat (/retenir, /rappeler, /souvenirs, /taxonomy,
# /souvenir/{id}) et sur le proxy /api/v1/* de la brique memoire ; l'horloge/le graphe
# d'apprentissage (core/graphe_apprentissage.py) la présente aussi pour lire /souvenirs.
# MÊME valeur des deux côtés (le Cœur la lit via env_file ; la brique via son propre compose —
# les deux lisent déjà le même .env racine). ⚠ SANS elle, la brique reste en mode ouvert
# (mono-user "perso", pas de vraie isolation entre personnes). Génère : `openssl rand -hex 32`.
MEMOIRE_KEY=
```

- [ ] **Step 2: Câbler le service `memoire` au `.env` racine**

Dans `briques/memoire/docker-compose.yml`, le service `memoire` (lignes 56-64) n'a
actuellement PAS d'`env_file` (seul `memoire-backend` en a un) — `MEMOIRE_KEY` déclarée dans
le `.env` racine ne lui parviendrait donc jamais. Remplacer :

```yaml
  # Adaptateur : contrat Workplace (retenir/rappeler) exposé sur l'hôte (5600).
  memoire:
    build: .
    ports:
      - "5600:8000"
    environment:
      - MEMORY_API=http://memoire-backend:8000
      - MEMOIRE_EMAIL=service@workplace.local
      - MEMOIRE_PASSWORD=workplace-memoire
      - MEMOIRE_ESPACE=Workplace
```

par :

```yaml
  # Adaptateur : contrat Workplace (retenir/rappeler) exposé sur l'hôte (5600).
  memoire:
    build: .
    ports:
      - "5600:8000"
    env_file:
      # MEMOIRE_KEY (S186, isolation par personne) vient du .env racine via env_file — NE
      # PAS la redéclarer en `MEMOIRE_KEY=${MEMOIRE_KEY:-}` sous `environment:` (piège « env
      # shadow » : chaîne VIDE qui écraserait la vraie valeur → brique vue mono-user, cf.
      # docs mémoire fix-env-shadow-composes).
      - path: ../../.env
        required: false
    environment:
      - MEMORY_API=http://memoire-backend:8000
      - MEMOIRE_EMAIL=service@workplace.local
      - MEMOIRE_PASSWORD=workplace-memoire
      - MEMOIRE_ESPACE=Workplace
```

- [ ] **Step 3: Vérifier que le compose reste valide**

Run: `cd briques/memoire && docker compose config -q`
Expected: aucune erreur (validation syntaxique seule, pas de build)

- [ ] **Step 4: Commit**

```bash
git add .env.example briques/memoire/docker-compose.yml
git commit -m "docs(memoire): documente MEMOIRE_KEY (.env.example + env_file compose, S186)"
```

---

### Task 10: Vérification finale

**Files:** aucun (validation uniquement)

- [ ] **Step 1: Suite complète `core`**

Run: `cd core && make test-core` (ou `python3 -m pytest .` selon le Makefile du monorepo)
Expected: tous verts, ancien total + les nouveaux tests de Tasks 6/7 (au moins 460 + 1
assertion memoire + 3 test_memoire_proxy + 1 test_graphe_apprentissage).

- [ ] **Step 2: Suite complète `briques/memoire`**

Run: `cd briques/memoire && python3.11 -m pip install -r requirements-dev.txt -q && python3.11 -m pytest -v`
Expected: tous verts (existants + Tasks 1-4).

- [ ] **Step 3: Build front**

Run: `cd briques/memoire/memory/frontend && npm ci && npm run build`
Expected: build réussi (déjà vérifié en Task 5, reconfirmation après tous les changements).

- [ ] **Step 4: Relecture de la spec vs implémentation**

Relire `docs/superpowers/specs/2026-07-19-s186-memoire-isolation-design.md` section par
section et confirmer que chaque décision de kickoff (1 à 5) a un commit correspondant :
1. Périmètre complet → Tasks 7-8 (proxy dashboard) + Tasks 2-3 (assistant).
2. Motif mail transposé → Task 1-2.
3. Dialecte X-API-Key unifié → Task 6.
4. Verrou d'espace en mode gagé → Task 2.
5. Sélecteur d'espace + garde proxy → Tasks 3-5.

- [ ] **Step 5: Mémoire — mise à jour**

Mettre à jour la mémoire `sprint-s184-s187-isolation-briques-restantes` (fichier
`/Users/garinat_t/.claude/projects/-Users-garinat-t-Desktop-Workplace/memory/sprint-s184-s187-isolation-briques-restantes.md`)
: marquer S186 comme CODE-COMPLET avec le hash du dernier commit, sur le motif des entrées
S184/S185 déjà présentes.

- [ ] **Step 6: Pas de commit ici** — cette tâche est une vérification, pas une modification
      de code. Si un test casse, revenir à la tâche concernée, corriger, recommit.

---

## Self-Review (fait avant remise du plan)

**Couverture de la spec :** les 5 décisions de kickoff sont couvertes (voir Task 10 Step 4) ;
le modèle de données (repli `"Perso"` legacy) est dans Task 2 ; la garde du proxy brut est
dans Task 3 ; le boot + sélecteur front dans Tasks 4-5 ; le câblage Cœur (assistant +
dashboard) dans Tasks 6-8 ; `.env.example` + docker-compose dans Task 9 ; tous les tests listés
dans la spec ont une tâche porteuse.

**Repli legacy vérifié dans le code montré :** `_normaliser_espace` (Task 2) et
`_espaces_autorises`/`_index_injecte` (Tasks 3-4) utilisent tous la même règle
`"Perso" if identite == "perso" else f"Perso:{identite}"` — cohérent partout, pas de
divergence entre les 3 endroits qui en ont besoin.

**Cohérence des types/signatures vérifiée :** `_normaliser_espace(espace, identite)`,
`auth.identite(...)`, `_espaces_autorises(client, identite)` et `_index_injecte(identite)`
utilisent tous le même nom de paramètre et le même type (`str`) à travers les tâches 1-4 —
pas de dérive de signature entre les tâches qui les consomment.
