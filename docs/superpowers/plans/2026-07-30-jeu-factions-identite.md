# Jeu-factions — identité réelle scopée au cercle privé (S217) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace jeu-factions' generic shared `cle_api` (today a no-op: `API_KEYS` is empty, everyone shares tenant `"public"`) with the real identity of the person connected to the Cœur, using the same signed-token motif already proven for Mémoire (S186) — chosen over Studio's proxy+`X-User-Id` motif because jeu-factions has a WebSocket route that only the token motif covers natively.

**Architecture:** The Cœur signs an HMAC token (`utilisateur:expiration:signature`) and appends it as `?j=` to the jeu-factions tile URL, exactly as it does for Mémoire with `?m=`. The brique's `GET /` route verifies it, serves `front.html`, and sets an httponly cookie (8h). From then on, every JSON route and the combat WebSocket read the identity from that cookie alone — no header, no query param — because the browser sends cookies automatically on every same-origin request, HTTP or WebSocket. `API_KEYS` and the old header-based `cle_api()` disappear entirely: there is no shared-key fallback and no "mode ouvert" after this plan (a deliberate divergence from Mémoire, approved during brainstorming). Existing `cle_api="public"` data is migrated to the first real identity seen.

**Tech Stack:** Python 3, FastAPI, SQLite (stdlib `sqlite3`), pytest, vanilla JS front (no build step). Cœur side: same FastAPI app, `httpx`-free (pure stdlib `hmac`/`hashlib`).

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-30-jeu-factions-identite-design.md` — read it before starting if anything below is ambiguous.
- No new table, no new column, no docker-compose.yml change on either side (env vars already flow through `env_file` — spec, "Configuration").
- `groupes`/`membres_groupe` have no `cle_api` column and need no migration — they follow `personnages_jeu` via `personnage_id` (spec, "Migration").
- `zones`/`scores_zone_guilde`/`zones_archetype`/`competences` stay a shared world, untouched by this plan.
- No custom auth header anywhere (`X-Jeu-Jeton`, `X-API-Key`, `Authorization`) — cookie only, plus the `?j=` query param on `GET /` alone (spec, "Contexte" — simplification found while reading Mémoire's actual code).
- Jeu-factions has **no fallback identity** after this plan — missing/invalid cookie is always `401`, never `"public"` or a service account (spec, Non-objectifs — intentional divergence from Mémoire's `briques/memoire/main.py:293-299`).
- Run brique tests from `briques/jeu-factions/` with `python -m pytest <file> -v` (repo convention, see `docs/superpowers/plans/2026-07-29-jeu-factions-idle.md`).
- Run Cœur tests from `core/` with `python -m pytest <file> -v`.

## File Structure

- **`briques/jeu-factions/jeton.py`** (new) — HMAC verify/emit, `COOKIE_NOM`. Mirrors `briques/memoire/main.py`'s `_verifier_jeton`/`_emettre_jeton`, extracted into its own module (this brique already splits `archetypes.py`/`groupes.py`/`stockage.py` by responsibility).
- **`briques/jeu-factions/stockage.py`** (modify) — one new function, `migrer_public_si_premiere_connexion`.
- **`briques/jeu-factions/main.py`** (modify) — `cle_api()` rewritten to cookie-only, `GET /` becomes a real route (was a bare `FileResponse`), combat WebSocket reads `websocket.cookies` instead of a query param, `API_KEYS`/`_cle_depuis_query` removed.
- **`briques/jeu-factions/conftest.py`** (modify) — `JEU_FACTIONS_KEY` test default added, `API_KEYS` test default removed.
- **`briques/jeu-factions/test_api.py`, `test_isolation.py`, `test_front.py`** (rewritten) — every call site that authenticated via `X-API-Key`/`api_key=` now authenticates via a cookie helper.
- **`briques/jeu-factions/front.html`** (modify) — drop the `localStorage` key box, drop `X-API-Key`, add a "session expired" inline message.
- **`briques/jeu-factions/front_combat.html`** (modify) — same drop, WebSocket URL loses `&api_key=`.
- **`core/jeu_factions_jeton.py`** (new) — Cœur-side emission, exact mirror of `core/memoire_jeton.py`.
- **`core/test_jeu_factions_jeton.py`** (new) — mirrors `core/test_memoire_jeton.py`.
- **`core/routers/dashboard.py`** (modify) — builds `jeu_factions_ui` with `?j=`, same motif as `memoire_ui`.
- **`core/test_dashboard.py`** (modify) — one assertion added to the existing placeholder-injection test.
- **`.env.example`** (modify) — new `JEU_FACTIONS_KEY` block next to `MEMOIRE_KEY`.

---

### Task 1: Jeton signé côté brique (`jeton.py`)

**Files:**
- Create: `briques/jeu-factions/jeton.py`
- Modify: `briques/jeu-factions/conftest.py` (add `JEU_FACTIONS_KEY` test default)
- Test: `briques/jeu-factions/test_jeton.py`

**Interfaces:**
- Produces: `jeton.COOKIE_NOM: str`, `jeton.emettre(utilisateur: str, ttl: int) -> str`, `jeton.verifier(jeton: str | None) -> str | None` — used by Task 3 (`main.py`).

- [ ] **Step 1: Write the failing tests**

Create `briques/jeu-factions/test_jeton.py`:

```python
import jeton as J


def test_roundtrip_emettre_puis_verifier():
    j = J.emettre("sub-alice", ttl=60)
    assert J.verifier(j) == "sub-alice"


def test_verifier_signature_invalide():
    j = J.emettre("sub-alice", ttl=60)
    trafique = j[:-1] + ("0" if j[-1] != "0" else "1")
    assert J.verifier(trafique) is None


def test_verifier_expire():
    j = J.emettre("sub-alice", ttl=-1)
    assert J.verifier(j) is None


def test_verifier_malforme():
    assert J.verifier("pas-un-jeton-valide") is None
    assert J.verifier(None) is None


def test_verifier_sans_secret_configure(monkeypatch):
    monkeypatch.delenv("JEU_FACTIONS_KEY", raising=False)
    assert J.verifier("nimporte:quoi:x") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd briques/jeu-factions && python -m pytest test_jeton.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'jeton'`

- [ ] **Step 3: Add the test env default**

In `briques/jeu-factions/conftest.py`, right after the line `os.environ.setdefault("API_KEYS", "")               # mode ouvert → tenant "public"`, add:

```python
os.environ.setdefault("JEU_FACTIONS_KEY", "cle-test-jeu-factions")  # S217 : secret du jeton
```

(The `API_KEYS` line itself is removed in Task 3, once `main.py` stops reading it — left alone here so Task 1/2 don't touch `main.py` at all.)

- [ ] **Step 4: Create `jeton.py`**

```python
"""Jeton signé Cœur→jeu-factions (S217), miroir de briques/memoire/main.py::_verifier_jeton /
_emettre_jeton — vérifie ici (process brique séparé), même secret `JEU_FACTIONS_KEY` que le
module d'émission côté Cœur (`core/jeu_factions_jeton.py`). HMAC, pas de chiffrement :
l'identité n'est pas confidentielle, seule l'INTÉGRITÉ compte — empêche un utilisateur
connecté de fabriquer le jeton d'un autre en modifiant l'URL."""
import hashlib
import hmac
import os
import time
from typing import Optional

COOKIE_NOM = "jeu_factions_utilisateur"


def _secret() -> bytes:
    return (os.environ.get("JEU_FACTIONS_KEY") or "").encode()


def emettre(utilisateur: str, ttl: int) -> str:
    expire = int(time.time()) + ttl
    message = f"{utilisateur}:{expire}"
    signature = hmac.new(_secret(), message.encode(), hashlib.sha256).hexdigest()
    return f"{message}:{signature}"


def verifier(jeton: Optional[str]) -> Optional[str]:
    if not jeton or not _secret():
        return None
    try:
        utilisateur, expire, signature = jeton.rsplit(":", 2)
        expire_i = int(expire)
    except ValueError:
        return None
    message = f"{utilisateur}:{expire}"
    attendue = hmac.new(_secret(), message.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, attendue) or time.time() > expire_i:
        return None
    return utilisateur
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd briques/jeu-factions && python -m pytest test_jeton.py -v`
Expected: PASS (all 5 tests)

- [ ] **Step 6: Run the full suite to check for regressions**

Run: `cd briques/jeu-factions && python -m pytest -q`
Expected: PASS, no new failures (this task adds a new module and a new env default, touches nothing else yet)

- [ ] **Step 7: Commit**

```bash
git add briques/jeu-factions/jeton.py briques/jeu-factions/test_jeton.py briques/jeu-factions/conftest.py
git commit -m "feat(jeu-factions): jeton signé Cœur→brique (S217)"
```

---

### Task 2: Migration des données `"public"` (`stockage.py`)

**Files:**
- Modify: `briques/jeu-factions/stockage.py` (append after `lire_derniere_presence_personnage`, currently ending at line 168)
- Test: `briques/jeu-factions/test_stockage.py`

**Interfaces:**
- Consumes: `stockage.assurer_joueur`, `stockage.creer_personnage`, `stockage.lister_personnages`, `stockage.lire_personnage`, `stockage._conn` (all existing).
- Produces: `stockage.migrer_public_si_premiere_connexion(cle_api_reelle: str) -> None` — used by Task 3 (`main.py`).

- [ ] **Step 1: Write the failing tests**

Add to `briques/jeu-factions/test_stockage.py` (append at end of file):

```python
def test_migrer_public_reattribue_joueur_et_personnages():
    S.assurer_joueur("public")
    p = S.creer_personnage("public", "Ancien", {"date_naissance": "1990-01-01"}, {"portrait": {}})
    S.migrer_public_si_premiere_connexion("sub-reel-1")
    assert S.lire_personnage("public", p["id"]) is None
    assert S.lire_personnage("sub-reel-1", p["id"]) is not None
    with S._conn() as c:
        assert c.execute("SELECT 1 FROM joueurs WHERE cle_api='public'").fetchone() is None
        assert c.execute("SELECT 1 FROM joueurs WHERE cle_api=?", ("sub-reel-1",)).fetchone() is not None


def test_migrer_public_est_idempotente_pour_la_meme_identite():
    S.assurer_joueur("public")
    S.creer_personnage("public", "Ancien", {"date_naissance": "1990-01-01"}, {"portrait": {}})
    S.migrer_public_si_premiere_connexion("sub-reel-2")
    S.migrer_public_si_premiere_connexion("sub-reel-2")  # rejoué : ne doit pas lever d'erreur
    assert len(S.lister_personnages("sub-reel-2")) == 1


def test_migrer_public_ne_vole_pas_les_donnees_dune_identite_deja_migree():
    S.assurer_joueur("public")
    S.creer_personnage("public", "Ancien", {"date_naissance": "1990-01-01"}, {"portrait": {}})
    S.migrer_public_si_premiere_connexion("sub-premier")
    S.migrer_public_si_premiere_connexion("sub-second")
    assert S.lister_personnages("sub-second") == []
    assert len(S.lister_personnages("sub-premier")) == 1


def test_migrer_public_sans_donnees_publiques_ne_cree_rien():
    S.migrer_public_si_premiere_connexion("sub-frais")
    with S._conn() as c:
        assert c.execute("SELECT 1 FROM joueurs WHERE cle_api=?", ("sub-frais",)).fetchone() is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd briques/jeu-factions && python -m pytest test_stockage.py -v`
Expected: FAIL — `AttributeError: module 'stockage' has no attribute 'migrer_public_si_premiere_connexion'`

- [ ] **Step 3: Implement**

Add at the end of `stockage.py` (after `lire_derniere_presence_personnage`):

```python
def migrer_public_si_premiere_connexion(cle_api_reelle: str) -> None:
    """Idempotent : no-op dès que `cle_api_reelle` a déjà une ligne dans `joueurs` (le cas
    courant, à partir de la 2e requête). Sinon, réattribue les données historiques sous le
    tenant partagé "public" à cette première identité réelle vue — `groupes`/`membres_groupe`
    n'ont pas de colonne `cle_api`, ils suivent `personnages_jeu` sans migration propre
    (spec S217)."""
    with _conn() as c:
        existe = c.execute("SELECT 1 FROM joueurs WHERE cle_api=?", (cle_api_reelle,)).fetchone()
        if existe:
            return
        public = c.execute("SELECT 1 FROM joueurs WHERE cle_api='public'").fetchone()
        if not public:
            return
        c.execute("UPDATE joueurs SET cle_api=? WHERE cle_api='public'", (cle_api_reelle,))
        c.execute("UPDATE personnages_jeu SET cle_api=? WHERE cle_api='public'", (cle_api_reelle,))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd briques/jeu-factions && python -m pytest test_stockage.py -v`
Expected: PASS (all tests including the 4 new ones)

- [ ] **Step 5: Run the full suite to check for regressions**

Run: `cd briques/jeu-factions && python -m pytest -q`
Expected: PASS, no new failures

- [ ] **Step 6: Commit**

```bash
git add briques/jeu-factions/stockage.py briques/jeu-factions/test_stockage.py
git commit -m "feat(jeu-factions): migration des données public vers la première identité réelle (S217)"
```

---

### Task 3: `main.py` — auth cookie-only, `GET /`, WebSocket (breaking change + full test migration)

**Why this is one task, not several:** `cle_api()` is a blanket dependency on almost every route. The moment it stops reading `X-API-Key`, every existing test that authenticates that way goes red — there is no intermediate state where `main.py` and the test suite are both green with only half this task done. This task rewrites `main.py` **and** every affected test file together, as prescribed by Task Right-Sizing.

**Files:**
- Modify: `briques/jeu-factions/main.py` (imports, `cle_api`, `accueil`, `combat_ws`; `API_KEYS`/`_cle_depuis_query` removed)
- Modify: `briques/jeu-factions/conftest.py` (remove the now-dead `API_KEYS` default)
- Modify (full rewrite): `briques/jeu-factions/test_api.py`, `briques/jeu-factions/test_isolation.py`, `briques/jeu-factions/test_front.py`

**Interfaces:**
- Consumes: `jeton.verifier`, `jeton.emettre`, `jeton.COOKIE_NOM` (Task 1); `stockage.migrer_public_si_premiere_connexion` (Task 2).
- Produces: `main.cle_api(request: Request) -> str` (cookie-only, `401` on failure), `GET /` (serves `front.html` + sets cookie, or `401` HTML invite), `/zones/{zone_id}/combat` WS (cookie-only) — consumed by Task 4 (`front.html`) and Task 5 (`front_combat.html`), which rely on the cookie being set by `GET /` and read automatically everywhere else.

- [ ] **Step 1: Write the failing tests**

Replace the entire content of `briques/jeu-factions/test_api.py`:

```python
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

import jeton
from main import app

client = TestClient(app)


def _cookies(identite: str) -> dict:
    return {jeton.COOKIE_NOM: jeton.emettre(identite, ttl=3600)}


def test_sante():
    r = client.get("/sante")
    assert r.status_code == 200
    assert r.json() == {"statut": "ok"}


def _patch_moteur(monkeypatch, portrait_reponse=None, ri_reponse=None):
    async def _portrait(fiche, client=None):
        return portrait_reponse or {"portrait": {"archetype": "Le Sage Contemplatif",
                                                  "stats": {"Sagesse": 100}},
                                     "traditions": {"signe_solaire": {"nom": "Vierge"}},
                                     "empreinte": []}

    async def _ri(description, combien=3, client=None):
        return ri_reponse if ri_reponse is not None else {"exemple_date": "1990-04-01"}

    import main
    monkeypatch.setattr(main.moteur_personnages, "portrait", _portrait)
    monkeypatch.setattr(main.moteur_personnages, "recherche_inverse", _ri)


def test_creer_personnage_par_date(monkeypatch):
    _patch_moteur(monkeypatch)
    r = client.post("/personnages", json={"nom": "Aria", "date_naissance": "1990-09-05"},
                    cookies=_cookies("cree-tenant-1"))
    assert r.status_code == 200
    corps = r.json()
    assert corps["nom"] == "Aria"
    assert corps["snapshot_holistique"]["portrait"]["archetype"] == "Le Sage Contemplatif"


def test_creer_personnage_par_description(monkeypatch):
    _patch_moteur(monkeypatch)
    r = client.post("/personnages", json={"nom": "Vorn", "description": "guerrier colérique"},
                    cookies=_cookies("cree-tenant-2"))
    assert r.status_code == 200
    assert r.json()["donnees_naissance"] == {"description": "guerrier colérique"}


def test_creer_personnage_sans_date_ni_description_422():
    r = client.post("/personnages", json={"nom": "Vide"}, cookies=_cookies("cree-tenant-3"))
    assert r.status_code == 422


def test_creer_personnage_description_sans_date_deduite_422(monkeypatch):
    _patch_moteur(monkeypatch, ri_reponse={"exemple_date": None})
    r = client.post("/personnages", json={"nom": "Flou", "description": "quelque chose"},
                    cookies=_cookies("cree-tenant-4"))
    assert r.status_code == 422


def test_route_personnages_rejette_un_cookie_absent_ou_invalide():
    assert client.get("/personnages").status_code == 401
    assert client.get("/personnages",
                      cookies={jeton.COOKIE_NOM: "pas-un-jeton"}).status_code == 401


def test_lister_et_lire_personnage(monkeypatch):
    _patch_moteur(monkeypatch)
    r = client.post("/personnages", json={"nom": "Lu", "date_naissance": "1990-01-01"},
                    cookies=_cookies("lire-tenant"))
    pid = r.json()["id"]
    assert any(p["id"] == pid for p in client.get("/personnages", cookies=_cookies("lire-tenant")).json())
    assert client.get(f"/personnages/{pid}", cookies=_cookies("lire-tenant")).json()["nom"] == "Lu"


def test_lire_personnage_inconnu_404():
    assert client.get("/personnages/inconnu", cookies=_cookies("lire-tenant-2")).status_code == 404


def test_assigner_zone_personnage_inconnu_404():
    r = client.patch("/personnages/inconnu/zone", json={"zone_id": "zone-belier"},
                     cookies=_cookies("zone-tenant-1"))
    assert r.status_code == 404


def test_assigner_zone_inconnue_404(monkeypatch):
    _patch_moteur(monkeypatch)
    r = client.post("/personnages", json={"nom": "SansZone", "date_naissance": "1990-01-01"},
                    cookies=_cookies("zone-tenant-2"))
    pid = r.json()["id"]
    r2 = client.patch(f"/personnages/{pid}/zone", json={"zone_id": "zone-qui-nexiste-pas"},
                      cookies=_cookies("zone-tenant-2"))
    assert r2.status_code == 404


def test_lire_personnage_inclut_progressions_et_competences(monkeypatch):
    _patch_moteur(monkeypatch)
    r = client.post("/personnages", json={"nom": "Enrichi", "date_naissance": "1990-01-01"},
                    cookies=_cookies("enrichi-tenant"))
    pid = r.json()["id"]
    detail = client.get(f"/personnages/{pid}", cookies=_cookies("enrichi-tenant")).json()
    assert "progressions" in detail and detail["progressions"] == []
    assert "competences" in detail and detail["competences"] == []


import zones


def test_lister_zones_renvoie_les_12_zones():
    zones.seed_zones()
    r = client.get("/zones", cookies=_cookies("zones-tenant"))
    assert r.status_code == 200
    assert len(r.json()) == 12


def test_lire_zone():
    zones.seed_zones()
    zid = zones.lister_zones()[0]["id"]
    r = client.get(f"/zones/{zid}", cookies=_cookies("zones-tenant-2"))
    assert r.status_code == 200
    assert r.json()["id"] == zid


def test_lire_zone_inconnue_404():
    assert client.get("/zones/inconnue", cookies=_cookies("zones-tenant-3")).status_code == 404


def test_zones_visibles_dun_autre_tenant(monkeypatch):
    """Confirme l'exception au cloisonnement : une autre identité voit les mêmes zones."""
    zones.seed_zones()
    r = client.get("/zones", cookies=_cookies("nimporte-quelle-identite"))
    assert len(r.json()) == 12


import archetypes


def _seed_archetypes():
    archetypes.seed_zones_archetype()
    archetypes.seed_competences()


def test_lister_etapes_archetype_inconnu_404():
    assert client.get("/archetypes/Inexistant/etapes", cookies=_cookies("etapes-tenant")).status_code == 404


def test_lister_etapes_archetype_connu(monkeypatch):
    _seed_archetypes()
    r = client.get("/archetypes/Le Sage Contemplatif/etapes", cookies=_cookies("etapes-tenant-2"))
    assert r.status_code == 200
    assert len(r.json()) == 3


def test_creer_groupe_et_rejoindre_via_api(monkeypatch):
    _patch_moteur(monkeypatch, portrait_reponse={
        "portrait": {"archetype": "Le Meneur Charismatique",
                    "stats": {"Charisme": 10, "Combativité": 10, "Énergie": 10}},
        "traditions": {"signe_solaire": {"nom": "Lion"}}, "empreinte": []})
    _seed_archetypes()
    ck = _cookies("groupe-tenant")
    p = client.post("/personnages", json={"nom": "Cible", "date_naissance": "1990-01-01"}, cookies=ck).json()
    etape = client.get("/archetypes/Le Meneur Charismatique/etapes", cookies=ck).json()[0]
    r = client.post("/groupes", json={"personnage_cible_id": p["id"], "zone_archetype_id": etape["id"]}, cookies=ck)
    assert r.status_code == 200
    gid = r.json()["id"]
    aide = client.post("/personnages", json={"nom": "Aide", "date_naissance": "1991-01-01"}, cookies=ck).json()
    r2 = client.post(f"/groupes/{gid}/rejoindre", json={"personnage_id": aide["id"]}, cookies=ck)
    assert r2.status_code == 200
    assert aide["id"] in r2.json()["membres"]


def test_creer_groupe_personnage_cible_inconnu_404():
    r = client.post("/groupes", json={"personnage_cible_id": "inconnu", "zone_archetype_id": "x"},
                    cookies=_cookies("groupe-tenant-2"))
    assert r.status_code == 404


def test_creer_groupe_etape_sautee_400(monkeypatch):
    _patch_moteur(monkeypatch, portrait_reponse={
        "portrait": {"archetype": "Le Sage Contemplatif", "stats": {}},
        "traditions": {"signe_solaire": {"nom": "Vierge"}}, "empreinte": []})
    _seed_archetypes()
    ck = _cookies("groupe-tenant-3")
    p = client.post("/personnages", json={"nom": "Sauteur2", "date_naissance": "1990-01-01"}, cookies=ck).json()
    etapes = client.get("/archetypes/Le Sage Contemplatif/etapes", cookies=ck).json()
    r = client.post("/groupes", json={"personnage_cible_id": p["id"], "zone_archetype_id": etapes[1]["id"]}, cookies=ck)
    assert r.status_code == 400


def test_lister_competences_personnage_inconnu_404():
    assert client.get("/personnages/inconnu/competences", cookies=_cookies("comp-tenant")).status_code == 404


def test_lister_competences_personnage_connu(monkeypatch):
    _patch_moteur(monkeypatch)
    ck = _cookies("comp-tenant-2")
    p = client.post("/personnages", json={"nom": "Vide2", "date_naissance": "1990-01-01"}, cookies=ck).json()
    r = client.get(f"/personnages/{p['id']}/competences", cookies=ck)
    assert r.status_code == 200
    assert r.json() == []


import combat
import mobs


def test_combat_ws_rejette_une_session_absente():
    with client.websocket_connect("/zones/inconnue/combat?personnage_id=x") as ws:
        message = ws.receive()
        assert message["type"] == "websocket.close"
        assert message["code"] == 4401


def test_combat_ws_zone_ou_personnage_inconnu_est_rejete():
    with client.websocket_connect("/zones/inconnue/combat?personnage_id=inconnu",
                                  cookies=_cookies("combat-tenant-1")) as ws:
        message = ws.receive()
        assert message["type"] == "websocket.close"
        assert message["code"] == 4404


def test_combat_ws_connexion_valide_recoit_un_etat_initial(monkeypatch):
    _patch_moteur(monkeypatch)
    zones.seed_zones()
    mobs.seed_mobs()
    ck = _cookies("combat-tenant-2")
    r = client.post("/personnages", json={"nom": "Combattant", "date_naissance": "1990-01-01"}, cookies=ck)
    pid = r.json()["id"]
    zone_id = zones.lister_zones()[0]["id"]
    with client.websocket_connect(f"/zones/{zone_id}/combat?personnage_id={pid}", cookies=ck) as ws:
        premier = ws.receive_json()
        assert premier["type"] == "etat"
        assert pid in premier["joueurs"]
    instance = combat._INSTANCES[zone_id][0]
    assert pid not in instance.etat["joueurs"]  # retiré à la déconnexion (finally du handler)


def test_presence_route_ok():
    r = client.post("/presence", cookies=_cookies("presence-tenant"))
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_presence_route_rejette_sans_cookie():
    r = client.post("/presence")
    assert r.status_code == 401


def test_personnages_expose_bonus_idle_actuel(monkeypatch):
    _patch_moteur(monkeypatch)
    _seed_archetypes()
    import main
    monkeypatch.setattr(main.archetypes, "TAUX_IDLE_PAR_HEURE", 1000.0)
    ck = _cookies("idle-tenant-1")
    r = client.post("/personnages", json={"nom": "Idle1", "date_naissance": "1990-01-01"}, cookies=ck)
    pid = r.json()["id"]
    with main.stockage._conn() as c:
        c.execute("UPDATE joueurs SET derniere_presence=? WHERE cle_api=?",
                  ((datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(), "idle-tenant-1"))
    items = client.get("/personnages", cookies=ck).json()
    perso = next(p for p in items if p["id"] == pid)
    assert perso["bonus_idle_actuel"] > 0


def test_personnages_sans_presence_a_bonus_idle_nul(monkeypatch):
    _patch_moteur(monkeypatch)
    _seed_archetypes()
    ck = _cookies("idle-tenant-2")
    r = client.post("/personnages", json={"nom": "Idle2", "date_naissance": "1990-01-01"}, cookies=ck)
    pid = r.json()["id"]
    items = client.get("/personnages", cookies=ck).json()
    perso = next(p for p in items if p["id"] == pid)
    assert perso["bonus_idle_actuel"] == 0
```

Replace the entire content of `briques/jeu-factions/test_isolation.py`:

```python
# test_isolation.py
"""Filet dédié : personnages/groupes restent cloisonnés par cle_api (identité réelle depuis
S217), zones/scores/étapes restent un monde PARTAGÉ (exception délibérée documentée dans le
spec — cf. docs/superpowers/specs/2026-07-29-jeu-factions-design.md § Architecture)."""
from fastapi.testclient import TestClient

import archetypes
import jeton
import zones
from main import app

client = TestClient(app)


def _cookies(identite: str) -> dict:
    return {jeton.COOKIE_NOM: jeton.emettre(identite, ttl=3600)}


def _patch_moteur(monkeypatch):
    """Évite l'appel HTTP réel vers `personnages` (PERSONNAGES_URL invalide en test, cf.
    conftest.py) — même patch que test_api.py::_patch_moteur, nécessaire pour toute création
    de personnage via la route /personnages."""
    async def _portrait(fiche, client=None):
        return {"portrait": {"archetype": "Le Sage Contemplatif", "stats": {"Sagesse": 100}},
               "traditions": {"signe_solaire": {"nom": "Vierge"}}, "empreinte": []}

    async def _ri(description, combien=3, client=None):
        return {"exemple_date": "1990-04-01"}

    import main
    monkeypatch.setattr(main.moteur_personnages, "portrait", _portrait)
    monkeypatch.setattr(main.moteur_personnages, "recherche_inverse", _ri)


def test_personnage_invisible_pour_un_autre_tenant(monkeypatch):
    _patch_moteur(monkeypatch)
    r = client.post("/personnages", json={"nom": "Secret", "date_naissance": "1990-01-01"},
                    cookies=_cookies("tenant-a"))
    pid = r.json()["id"]
    assert client.get(f"/personnages/{pid}", cookies=_cookies("tenant-a")).status_code == 200
    assert client.get(f"/personnages/{pid}", cookies=_cookies("tenant-b")).status_code == 404
    assert not any(p["id"] == pid for p in
                  client.get("/personnages", cookies=_cookies("tenant-b")).json())


def test_zones_identiques_pour_tous_les_tenants():
    zones.seed_zones()
    a = client.get("/zones", cookies=_cookies("tenant-a")).json()
    b = client.get("/zones", cookies=_cookies("tenant-b")).json()
    assert {z["id"] for z in a} == {z["id"] for z in b}


def test_etapes_archetype_identiques_pour_tous_les_tenants():
    archetypes.seed_zones_archetype()
    a = client.get("/archetypes/Le Sage Contemplatif/etapes", cookies=_cookies("tenant-a")).json()
    b = client.get("/archetypes/Le Sage Contemplatif/etapes", cookies=_cookies("tenant-b")).json()
    assert [e["id"] for e in a] == [e["id"] for e in b]


def test_groupe_dun_tenant_pas_manipulable_par_un_autre(monkeypatch):
    """Un joueur ne peut pas créer un groupe pour un personnage qu'il ne possède pas —
    même si ce personnage existe (appartient à un autre tenant)."""
    _patch_moteur(monkeypatch)
    r = client.post("/personnages", json={"nom": "AutreTenant", "date_naissance": "1990-01-01"},
                    cookies=_cookies("tenant-c"))
    pid = r.json()["id"]
    archetypes.seed_zones_archetype()
    etape = client.get("/archetypes/Le Sage Contemplatif/etapes", cookies=_cookies("tenant-c")).json()[0]
    r2 = client.post("/groupes", json={"personnage_cible_id": pid, "zone_archetype_id": etape["id"]},
                     cookies=_cookies("tenant-d"))
    assert r2.status_code == 404
```

Replace the entire content of `briques/jeu-factions/test_front.py`:

```python
import pytest
from fastapi.testclient import TestClient

import jeton
from main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _vider_cookies_client():
    """`GET /` pose un cookie (Set-Cookie) que le client de test persiste automatiquement
    entre appels (httpx.Client._merge_cookies) — sans ça, un test qui pose un cookie valide
    ferait passer à tort le test suivant qui vérifie l'ABSENCE de cookie."""
    client.cookies.clear()
    yield


def _jeton_url(identite: str) -> str:
    return f"?j={jeton.emettre(identite, ttl=60)}"


def test_accueil_sert_le_html_avec_un_jeton_valide():
    r = client.get("/" + _jeton_url("front-tenant-1"))
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


def test_accueil_refuse_sans_jeton_ni_cookie():
    r = client.get("/")
    assert r.status_code == 401
    assert "text/html" in r.headers["content-type"]


def test_css_servi():
    r = client.get("/workplace.css")
    assert r.status_code == 200


def test_front_contient_le_heartbeat_de_presence():
    r = client.get("/" + _jeton_url("front-tenant-2"))
    assert "/presence" in r.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd briques/jeu-factions && python -m pytest test_api.py test_isolation.py test_front.py -v`
Expected: FAIL — every request that used to send `X-API-Key`/`api_key=` now sends a cookie the still-unchanged `main.py` doesn't know how to read; most assertions fail on status code (still 200/public-tenant behavior instead of the new isolation/401 behavior), and `test_accueil_refuse_sans_jeton_ni_cookie` fails because `GET /` still unconditionally returns 200.

- [ ] **Step 3: Implement `main.py`**

Replace the import block and the `API_KEYS`/`cle_api` block at the top of `main.py` (currently lines 1-43):

```python
"""Brique « jeu-factions » — création de personnage + factions/territoire (PvE).

Réutilise le moteur holistique de `personnages` en HTTP (aucun calcul dupliqué). Voir
docs/superpowers/specs/2026-07-29-jeu-factions-design.md pour le design complet, et
docs/superpowers/specs/2026-07-30-jeu-factions-identite-design.md pour l'identité réelle
(S217) : `cle_api` est désormais un `sub` Keycloak vérifié par cookie, plus une clé partagée.
"""
import asyncio
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

import archetypes
import combat
import groupes
import jeton
import mobs
import moteur_personnages
import stockage
import tick
import zones

app = FastAPI(title="Jeu-factions — factions & territoire (PvE)", version="0.1.0")

_cors = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()] or ["*"]
app.add_middleware(CORSMiddleware, allow_origins=_cors, allow_methods=["*"], allow_headers=["*"])


def cle_api(request: Request) -> str:
    """Identité réelle (S217) : uniquement le cookie posé par `GET /` après vérification du
    jeton signé par le Cœur — plus de clé partagée, plus de mode ouvert (spec, Non-objectifs)."""
    identite = jeton.verifier(request.cookies.get(jeton.COOKIE_NOM))
    if not identite:
        raise HTTPException(401, "Session Cœur requise — rouvre la tuile Jeu-factions depuis le Cœur.")
    stockage.migrer_public_si_premiere_connexion(identite)
    return identite
```

Replace the `accueil` route (currently lines 243-245, `@app.get("/", response_class=FileResponse, ...)`):

```python
_PAGE_REOUVRIR = """<!DOCTYPE html>
<html lang="fr"><head><meta charset="utf-8"><title>Jeu-factions</title>
<link rel="stylesheet" href="/workplace.css"></head>
<body><p>Session expirée ou absente — rouvre la tuile Jeu-factions depuis le tableau de
bord du Cœur.</p></body></html>"""


@app.get("/", include_in_schema=False)
def accueil(request: Request):
    """Point d'entrée : lit le jeton d'URL (posé par le Cœur, `?j=`) en priorité, sinon le
    cookie d'une navigation précédente (S217). Ni l'un ni l'autre -> page d'invite (401,
    HTML — cette route est la seule atteinte par une navigation humaine directe)."""
    jeton_url = request.query_params.get("j")
    identite = jeton.verifier(jeton_url) or jeton.verifier(request.cookies.get(jeton.COOKIE_NOM))
    if not identite:
        return HTMLResponse(_PAGE_REOUVRIR, status_code=401)
    contenu = (Path(__file__).parent / "front.html").read_text(encoding="utf-8")
    reponse = HTMLResponse(contenu)
    if jeton_url:
        reponse.set_cookie(jeton.COOKIE_NOM, jeton.emettre(identite, ttl=8 * 3600),
                           max_age=8 * 3600, httponly=True, samesite="lax")
    return reponse
```

Replace `_cle_depuis_query` and `combat_ws` (currently lines 204-240):

```python
@app.websocket("/zones/{zone_id}/combat")
async def combat_ws(websocket: WebSocket, zone_id: str, personnage_id: str = Query(...)):
    await websocket.accept()
    # S217 : le cookie posé par `GET /` est déjà là au moment du handshake — même origine,
    # envoyé automatiquement par le navigateur, pas de query param `api_key`.
    identite = jeton.verifier(websocket.cookies.get(jeton.COOKIE_NOM))
    if identite is None:
        await websocket.close(code=4401)
        return
    perso = stockage.lire_personnage(identite, personnage_id)
    zone = zones.lire_zone(zone_id)
    if not perso or not zone:
        await websocket.close(code=4404)
        return
    signe = zones.signe_personnage(perso["snapshot_holistique"]) or "Bélier"
    element = dict(zones.ZONES_SEED).get(signe, "Feu")
    gabarits = mobs.lister_mobs_zone(zone_id)
    inst = await combat.rejoindre(zone_id, personnage_id, element, signe, gabarits)
    competences = archetypes.lister_toutes_competences_avec_effet()
    combat.demarrer_boucle_si_necessaire(inst, competences)
    try:
        combat.enregistrer_connexion(inst, personnage_id, websocket)
        await websocket.send_json({"type": "etat", **combat.etat_public(inst), "evenements": []})
        while True:
            message = await websocket.receive_json()
            combat.empiler_action(inst, personnage_id, message)
    except WebSocketDisconnect:
        pass
    finally:
        combat.quitter(inst, personnage_id, time.monotonic())
```

Finally, in `briques/jeu-factions/conftest.py`, remove the now-dead line:

```python
os.environ.setdefault("API_KEYS", "")               # mode ouvert → tenant "public"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd briques/jeu-factions && python -m pytest test_api.py test_isolation.py test_front.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Run the full suite to check for regressions**

Run: `cd briques/jeu-factions && python -m pytest -q`
Expected: PASS, no new failures

- [ ] **Step 6: Commit**

```bash
git add briques/jeu-factions/main.py briques/jeu-factions/conftest.py \
        briques/jeu-factions/test_api.py briques/jeu-factions/test_isolation.py briques/jeu-factions/test_front.py
git commit -m "feat(jeu-factions): identité réelle par cookie, API_KEYS supprimée (S217)"
```

---

### Task 4: Front — retrait de la clé collée, message de session expirée (`front.html`)

**Files:**
- Modify: `briques/jeu-factions/front.html` (whole `<body>`/`<script>`)
- Test: `briques/jeu-factions/test_front.py` (append)

**Interfaces:**
- Consumes: cookie-based auth from Task 3 (nothing to import — this is HTML/JS served as a static string).
- Produces: nothing consumed by later tasks.

- [ ] **Step 1: Write the failing tests**

Append to `briques/jeu-factions/test_front.py`:

```python
def test_front_ne_contient_plus_de_cle_api_localstorage():
    r = client.get("/" + _jeton_url("front-tenant-3"))
    assert "localStorage" not in r.text
    assert "jeu_factions_cle" not in r.text
    assert "X-API-Key" not in r.text


def test_front_gere_une_session_expiree():
    r = client.get("/" + _jeton_url("front-tenant-4"))
    assert "Session expirée" in r.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd briques/jeu-factions && python -m pytest test_front.py -v`
Expected: FAIL — `front.html` still contains `localStorage.getItem("jeu_factions_cle")` and no "Session expirée" text

- [ ] **Step 3: Implement**

Replace the entire content of `briques/jeu-factions/front.html`:

```html
<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<title>Jeu-factions</title>
<link rel="stylesheet" href="/workplace.css">
</head>
<body>
<h1>Jeu-factions — factions &amp; territoire (PvE)</h1>

<p id="messageSession" style="display:none; color:#f87171;"></p>

<section id="creation">
  <h2>Créer un personnage</h2>
  <label><input type="radio" name="mode" value="date" checked> Par date de naissance</label>
  <label><input type="radio" name="mode" value="description"> Par description</label>
  <form id="formCreation">
    <input id="nom" placeholder="Nom du personnage" required>
    <div id="champsDate">
      <input id="date_naissance" type="date">
    </div>
    <div id="champsDescription" style="display:none">
      <textarea id="description" placeholder="Décris le caractère..."></textarea>
    </div>
    <button type="submit">Créer</button>
  </form>
  <pre id="resultatCreation"></pre>
</section>

<section id="mesPersonnages">
  <h2>Mes personnages</h2>
  <ul id="listePersonnages"></ul>
</section>

<section id="zones">
  <h2>Zones de signe (PvE partagé)</h2>
  <ul id="listeZones"></ul>
</section>

<script>
const entetes = () => ({"Content-Type": "application/json"});

function afficherSessionExpiree() {
  const m = document.getElementById("messageSession");
  m.textContent = "Session expirée — rouvre cette page depuis le tableau de bord du Cœur.";
  m.style.display = "block";
}

async function verifierSession(r) {
  if (r.status === 401) { afficherSessionExpiree(); throw new Error("session expirée"); }
  return r;
}

document.querySelectorAll('input[name="mode"]').forEach(r => r.addEventListener("change", e => {
  document.getElementById("champsDate").style.display = e.target.value === "date" ? "block" : "none";
  document.getElementById("champsDescription").style.display = e.target.value === "description" ? "block" : "none";
}));

document.getElementById("formCreation").addEventListener("submit", async e => {
  e.preventDefault();
  const mode = document.querySelector('input[name="mode"]:checked').value;
  const corps = {nom: document.getElementById("nom").value};
  if (mode === "date") corps.date_naissance = document.getElementById("date_naissance").value;
  else corps.description = document.getElementById("description").value;
  const r = await verifierSession(
    await fetch("/personnages", {method: "POST", headers: entetes(), body: JSON.stringify(corps)}));
  document.getElementById("resultatCreation").textContent = JSON.stringify(await r.json(), null, 2);
  chargerPersonnages();
});

async function chargerPersonnages() {
  const r = await verifierSession(await fetch("/personnages", {headers: entetes()}));
  const items = await r.json();
  document.getElementById("listePersonnages").innerHTML = items.map(p => {
    const bonus = p.bonus_idle_actuel > 0
      ? ` — +${p.bonus_idle_actuel} vers la prochaine étape (voie d'archétype)` : "";
    return `<li>${p.nom} — ${(p.snapshot_holistique.portrait || {}).archetype || "?"} (zone: ${p.zone_actuelle || "aucune"})${bonus}</li>`;
  }).join("");
}

async function chargerZones() {
  const r = await verifierSession(await fetch("/zones", {headers: entetes()}));
  const items = await r.json();
  document.getElementById("listeZones").innerHTML = items.map(z =>
    `<li>${z.nom} (${z.element_natif}) — ${z.etat} ` +
    `<a href="/front_combat.html?zone=${z.id}">Rejoindre le combat</a></li>`
  ).join("");
}

chargerPersonnages().catch(() => {});
chargerZones().catch(() => {});

setInterval(() => fetch("/presence", {method: "POST", headers: entetes()}).then(verifierSession).catch(() => {}), 30_000);
</script>
</body>
</html>
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd briques/jeu-factions && python -m pytest test_front.py -v`
Expected: PASS (all 6 tests)

- [ ] **Step 5: Run the full suite to check for regressions**

Run: `cd briques/jeu-factions && python -m pytest -q`
Expected: PASS, no new failures

- [ ] **Step 6: Commit**

```bash
git add briques/jeu-factions/front.html briques/jeu-factions/test_front.py
git commit -m "feat(jeu-factions): front — retrait de la clé API collée, session par cookie (S217)"
```

---

### Task 5: Front combat — retrait du query param `api_key` (`front_combat.html`)

**Files:**
- Modify: `briques/jeu-factions/front_combat.html` (`<script>` block)
- Test: `briques/jeu-factions/test_front_combat.py` (append)

**Interfaces:**
- Consumes: cookie-based auth from Task 3.
- Produces: nothing consumed by later tasks.

- [ ] **Step 1: Write the failing test**

Append to `briques/jeu-factions/test_front_combat.py`:

```python
def test_front_combat_ne_contient_plus_de_cle_api():
    r = client.get("/front_combat.html")
    assert "localStorage" not in r.text
    assert "api_key=" not in r.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd briques/jeu-factions && python -m pytest test_front_combat.py -v`
Expected: FAIL — `front_combat.html` still contains `localStorage.getItem("jeu_factions_cle")` and `&api_key=`

- [ ] **Step 3: Implement**

In `front_combat.html`, replace the top of the `<script>` block:

```javascript
const params = new URLSearchParams(location.search);
const zoneId = params.get("zone");
const cleApi = localStorage.getItem("jeu_factions_cle") || "";

let personnageId = null;
```

with:

```javascript
const params = new URLSearchParams(location.search);
const zoneId = params.get("zone");

let personnageId = null;
```

Replace `initPersonnage`:

```javascript
async function initPersonnage() {
  const r = await fetch("/personnages", {headers: cleApi ? {"X-API-Key": cleApi} : {}});
  const mine = await r.json();
  if (!mine.length) {
    document.getElementById("jeu").textContent = "Crée d'abord un personnage sur la page principale.";
    throw new Error("aucun personnage");
  }
  personnageId = mine[0].id;
  const rc = await fetch(`/personnages/${personnageId}/competences`,
    {headers: cleApi ? {"X-API-Key": cleApi} : {}});
  const sorts = (await rc.json()).filter(c => c.effet_type);
  document.getElementById("sorts").innerHTML = sorts.map(s =>
    `<button data-id="${s.id}">${s.nom}</button>`).join("");
  document.querySelectorAll("#sorts button").forEach(b => b.addEventListener("click", () => {
    if (cibleActive && ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({type: "sort", competence_id: b.dataset.id, cible_id: cibleActive}));
    }
  }));
}
```

with:

```javascript
async function initPersonnage() {
  const r = await fetch("/personnages");
  if (r.status === 401) {
    document.getElementById("jeu").textContent =
      "Session expirée — rouvre cette page depuis le tableau de bord du Cœur.";
    throw new Error("session expirée");
  }
  const mine = await r.json();
  if (!mine.length) {
    document.getElementById("jeu").textContent = "Crée d'abord un personnage sur la page principale.";
    throw new Error("aucun personnage");
  }
  personnageId = mine[0].id;
  const rc = await fetch(`/personnages/${personnageId}/competences`);
  const sorts = (await rc.json()).filter(c => c.effet_type);
  document.getElementById("sorts").innerHTML = sorts.map(s =>
    `<button data-id="${s.id}">${s.nom}</button>`).join("");
  document.querySelectorAll("#sorts button").forEach(b => b.addEventListener("click", () => {
    if (cibleActive && ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({type: "sort", competence_id: b.dataset.id, cible_id: cibleActive}));
    }
  }));
}
```

Replace `connecter`:

```javascript
function connecter() {
  const protocole = location.protocol === "https:" ? "wss:" : "ws:";
  ws = new WebSocket(`${protocole}//${location.host}/zones/${zoneId}/combat` +
    `?personnage_id=${personnageId}&api_key=${encodeURIComponent(cleApi)}`);
```

with:

```javascript
function connecter() {
  const protocole = location.protocol === "https:" ? "wss:" : "ws:";
  ws = new WebSocket(`${protocole}//${location.host}/zones/${zoneId}/combat?personnage_id=${personnageId}`);
```

(the rest of `connecter`'s body — `ws.onmessage = ...` — is unchanged)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd briques/jeu-factions && python -m pytest test_front_combat.py -v`
Expected: PASS

- [ ] **Step 5: Run the full suite to check for regressions**

Run: `cd briques/jeu-factions && python -m pytest -q`
Expected: PASS, no new failures — this is the last brique-side task, confirm the brique's total test count grew by 5 (jeton) + 4 (migration) + 3 (test_api 401 case) + 4 (front) + 1 (front_combat) versus the pre-plan baseline, plus the rewritten-in-place tests in test_api.py/test_isolation.py/test_front.py.

- [ ] **Step 6: Commit**

```bash
git add briques/jeu-factions/front_combat.html briques/jeu-factions/test_front_combat.py
git commit -m "feat(jeu-factions): front combat — retrait du query param api_key (S217)"
```

---

### Task 6: Cœur — émission du jeton + tuile dashboard (`core/`)

**Files:**
- Create: `core/jeu_factions_jeton.py`
- Create: `core/test_jeu_factions_jeton.py`
- Modify: `core/routers/dashboard.py` (import + `jeu_factions_ui` construction + final `.replace(...)`)
- Modify: `core/test_dashboard.py` (append one assertion to `test_urls_briques_injectees`)
- Modify: `.env.example` (new `JEU_FACTIONS_KEY` block)

**Interfaces:**
- Consumes: same HMAC scheme as Task 1's `jeton.py` (`utilisateur:expiration:signature`, `JEU_FACTIONS_KEY` secret) — the two modules never import each other (separate processes), they just agree on the wire format, exactly like `core/memoire_jeton.py` and `briques/memoire/main.py` today.
- Produces: `jeu_factions_jeton.emettre(utilisateur: str, ttl: int = TTL_DEFAUT) -> str | None` — used only by `dashboard.py`, nothing later depends on it.

- [ ] **Step 1: Write the failing tests**

Create `core/test_jeu_factions_jeton.py`:

```python
"""Jeton signé Cœur→jeu-factions (S217) — côté émission (core/jeu_factions_jeton.py). La
vérification (côté brique, process séparé) est testée dans
briques/jeu-factions/test_jeton.py."""
import jeu_factions_jeton as jfj


def test_sans_cle_configuree_aucun_jeton(monkeypatch):
    monkeypatch.delenv("JEU_FACTIONS_KEY", raising=False)
    assert jfj.emettre("claire") is None


def test_avec_cle_jeton_porte_lutilisateur_et_une_signature(monkeypatch):
    monkeypatch.setenv("JEU_FACTIONS_KEY", "cle-coeur-jeu-factions")
    jeton = jfj.emettre("claire")
    assert jeton is not None
    utilisateur, expire, signature = jeton.split(":")
    assert utilisateur == "claire"
    assert expire.isdigit()
    assert len(signature) == 64  # hex sha256


def test_deux_personnes_jetons_distincts(monkeypatch):
    monkeypatch.setenv("JEU_FACTIONS_KEY", "cle-coeur-jeu-factions")
    assert jfj.emettre("claire") != jfj.emettre("marina")
```

Append to `core/test_dashboard.py`'s `test_urls_briques_injectees`:

```python
def test_urls_briques_injectees():
    """Les placeholders __STUDIO_UI_URL__ / __PERSONNAGES_UI_URL__ doivent être remplacés."""
    html = client.get("/dashboard").text
    assert "__STUDIO_UI_URL__" not in html
    assert "__PERSONNAGES_UI_URL__" not in html
    assert "__ATELIER_IMAGES_VIDEO_UI_URL__" not in html
    assert "__JEU_FACTIONS_UI_URL__" not in html
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd core && python -m pytest test_jeu_factions_jeton.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'jeu_factions_jeton'`

Run: `cd core && python -m pytest test_dashboard.py -v -k test_urls_briques_injectees`
Expected: PASS already (this specific assertion doesn't fail — `__JEU_FACTIONS_UI_URL__` is already absent from the rendered HTML today, since `dashboard.py` already replaces it with the raw `u("JEU_FACTIONS")` URL; this assertion is added for completeness/regression coverage, not because it's red)

- [ ] **Step 3: Create `core/jeu_factions_jeton.py`**

```python
"""Jeton signé Cœur→jeu-factions (S217) : dit à la brique jeu-factions QUI ouvre la tuile du
dashboard, sans jamais exposer `JEU_FACTIONS_KEY` au navigateur. Miroir exact de
`core/memoire_jeton.py` (S186) — même motif HMAC, même rôle.

HMAC, pas de chiffrement : l'identité (un id d'utilisateur) n'est pas confidentielle, seule
l'INTÉGRITÉ compte — empêche un utilisateur connecté de fabriquer le jeton d'un autre en
modifiant l'URL. Vérification dupliquée côté brique (`briques/jeu-factions/jeton.py`, process
séparé) : seul le secret `JEU_FACTIONS_KEY` est partagé.

Sans `JEU_FACTIONS_KEY` configurée : `emettre` renvoie ``None`` — le dashboard laisse l'URL de
la tuile telle quelle. CONTRAIREMENT à Mémoire, la brique jeu-factions n'a PAS de repli
mono-tenant dans ce cas (spec S217, Non-objectifs) : la tuile devient simplement inutilisable
tant que la clé n'est pas posée.
"""
import hashlib
import hmac
import os
import time

TTL_DEFAUT = 120  # secondes : juste assez pour charger la page, la brique pose ensuite un cookie


def _secret() -> bytes:
    return (os.environ.get("JEU_FACTIONS_KEY") or "").encode()


def emettre(utilisateur: str, ttl: int = TTL_DEFAUT) -> str | None:
    """Jeton `utilisateur:expiration:signature`, ou ``None`` si JEU_FACTIONS_KEY n'est pas posée."""
    secret = _secret()
    if not secret:
        return None
    expire = int(time.time()) + ttl
    message = f"{utilisateur}:{expire}"
    signature = hmac.new(secret, message.encode(), hashlib.sha256).hexdigest()
    return f"{message}:{signature}"
```

- [ ] **Step 4: Wire it into `dashboard.py`**

Add the import, right after `import memoire_jeton`:

```python
import auth
import memoire_jeton
```

becomes:

```python
import auth
import jeu_factions_jeton
import memoire_jeton
```

Add the `jeu_factions_ui` construction right after the existing `memoire_ui` block (currently ending with `memoire_ui = f"{memoire_ui}{sep}m={jeton_memoire}"`), and change the final `.replace(...)` call to use it:

```python
    memoire_ui = u("MEMOIRE")
    jeton_memoire = memoire_jeton.emettre(auth.sub_session_optionnel(request) or "perso")
    if jeton_memoire:
        sep = "&" if "?" in memoire_ui else "?"
        memoire_ui = f"{memoire_ui}{sep}m={jeton_memoire}"
    # Jeu-factions (S217) : même motif jeton signé que Mémoire. Contrairement à Mémoire, PAS
    # de repli mono-tenant si JEU_FACTIONS_KEY est absente — la brique refuse tout sans jeton
    # valide (spec S217, Non-objectifs), donc la tuile reste simplement inutilisable.
    jeu_factions_ui = u("JEU_FACTIONS")
    jeton_jf = jeu_factions_jeton.emettre(auth.sub_session_optionnel(request) or "perso")
    if jeton_jf:
        sep = "&" if "?" in jeu_factions_ui else "?"
        jeu_factions_ui = f"{jeu_factions_ui}{sep}j={jeton_jf}"
    return HTMLResponse(content=_GABARIT
        .replace("__FORGE_UI_URL__", u("FORGE"))
        .replace("__STUDIO_UI_URL__", studio_ui)
        .replace("__ATELIER_IMAGES_VIDEO_UI_URL__", atelier_images_video_ui)
        .replace("__PERSONNAGES_UI_URL__", personnages_ui)
        .replace("__TRANSCRIPTION_UI_URL__", u("TRANSCRIPTION"))
        .replace("__RESTAURANT_UI_URL__", u("RESTAURANT"))
        .replace("__MAIL_UI_URL__", u("MAIL"))
        .replace("__AGENDA_UI_URL__", u("AGENDA"))
        .replace("__GEO_UI_URL__", geo_ui)
        .replace("__ATELIER_VEILLE_UI_URL__", "/atelier-veille-app/atelier")
        .replace("__SYNOPSIS_UI_URL__", u("SYNOPSIS"))
        .replace("__VOIX_UI_URL__", u("VOIX"))
        .replace("__MEMOIRE_UI_URL__", memoire_ui)
        .replace("__DEV_IDE_URL__", u("DEV_IDE"))
        .replace("__GENERATEUR_BUNDLES_URL__", u("GENERATEUR"))
        .replace("__GATEWAY_UI_URL__", u("GATEWAY"))
        .replace("__JEU_FACTIONS_UI_URL__", jeu_factions_ui))
```

- [ ] **Step 5: Add the `.env.example` block**

In `.env.example`, right after the existing `MEMOIRE_KEY=` line (in the "Brique « memoire »" section), add:

```
# ── Brique « jeu-factions » (factions & territoire PvE, port 6210) ────────────
# Clé partagée Cœur↔brique pour le jeton signé de la tuile du dashboard (S217, même motif que
# MEMOIRE_KEY ci-dessus). CONTRAIREMENT à MEMOIRE_KEY : pas de repli mono-tenant si elle est
# vide — la brique refuse tout accès sans jeton valide (spec S217, Non-objectifs), donc la
# tuile est INUTILISABLE tant que cette clé n'est pas posée. Génère une clé :
# `openssl rand -hex 32`.
JEU_FACTIONS_KEY=
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd core && python -m pytest test_jeu_factions_jeton.py test_dashboard.py -v`
Expected: PASS (all tests)

- [ ] **Step 7: Run the full Cœur suite to check for regressions**

Run: `cd core && python -m pytest -q`
Expected: PASS, no new failures

- [ ] **Step 8: Commit**

```bash
git add core/jeu_factions_jeton.py core/test_jeu_factions_jeton.py core/routers/dashboard.py \
        core/test_dashboard.py .env.example
git commit -m "feat(jeu-factions): Cœur — jeton signé pour la tuile du dashboard (S217)"
```
