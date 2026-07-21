# S193 — Prospection géo-scrapée + intégration mémoire (famille veille) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construire la 3e sous-brique de la famille `veille` — `veille-prospection` (campagnes de prospection automatisées, port 6140) — enrichir `geo` (dirigeants/effectifs/réseaux sociaux + ciblage par `zone_id`), étendre `memoire` pour qu'un espace custom nommé devienne isolable par personne, et pousser les résumés de `veille-info` et `veille-prospection` dans cet espace.

**Architecture:** 4 sous-systèmes indépendants, chacun testé isolément : (1) extension ciblée de `briques/memoire/main.py` (généralisation de `_resoudre_espace`, rétrocompatible) ; (2-3) extensions de `briques/geo/` (nouvelle fonction stockage + 2 modules domaine existants enrichis) ; (4) nouvelle brique FastAPI + SQLite `briques/veille-prospection/` sur le modèle exact de `briques/veille-info/` (isolation X-User-Id, cadence horloge via manifest, aucune dépendance de code vers les autres briques — seulement des appels HTTP) ; (5) retrofit d'un appel best-effort dans `briques/veille-info/digest.py`.

**Tech Stack:** Python 3.12, FastAPI, uvicorn, httpx, sqlite3 (stdlib), pytest, pytest-asyncio, respx (déjà utilisé par `briques/memoire`).

## Global Constraints

- Design de référence : `docs/superpowers/specs/2026-07-21-s193-veille-prospection-design.md`.
- Aucune modification de `briques/forge/` ni `briques/voix/` — réutilisés tels quels.
- Isolation par personne (motif `mail` S185 / `veille-info`) pour `veille-prospection` : `X-User-Id` + `VEILLE_PROSPECTION_KEY`, fail-closed si `API_KEYS` défini.
- L'extension `memoire` doit être 100% rétrocompatible : aucun appelant actuel (Forge `forge-org-*`, `transcription`) ne transmet `X-User-Id` aujourd'hui — leur comportement (espace partagé, compte de service) ne doit pas changer d'un octet. Vérifié par test dédié.
- `veille-prospection` NE duplique PAS la définition de zone : une campagne référence un `zone_id` `geo` existant. La création/gestion de zones reste exclusivement dans `geo`.
- Tout appel vers `geo`/`forge`/`memoire` depuis `veille-prospection` ou `veille-info` est **best-effort au-delà du premier appel critique** : un échec `forge` ou `memoire` ne doit jamais faire perdre les prospects déjà trouvés côté `geo`, ni faire planter le pipeline. Seul l'appel `geo` initial (sans lui, rien à faire) peut arrêter le traitement d'UNE campagne — jamais des autres.
- Le push `memoire` (`veille-prospection` et `veille-info`) n'a lieu que s'il y a quelque chose à raconter (au moins un prospect trouvé, ou un digest créé) — pas de résumé vide quotidien qui polluerait l'espace `veille`.
- Espace `memoire` : littéralement `"veille"` (minuscule, cohérent avec l'énum existant `"solution"`/`"perso"`), wings `"veille-info"` et `"veille-prospection"`.
- Tests sans réseau réel partout (mocks `httpx`/`respx`).
- Cette version n'ajoute AUCUNE UI (ni atelier-veille, ni autre front) — capacités assistant + API seulement, cf. Hors périmètre du design.

---

### Task 1: Extension `memoire` — espace custom isolable par personne

**Files:**
- Modify: `briques/memoire/main.py:205-221` (fonction `_resoudre_espace`)
- Modify: `briques/memoire/manifest.json` (5 occurrences de l'énum `espace`)
- Test: `briques/memoire/test_espace_custom_personne.py` (nouveau)

**Interfaces:**
- Consumes : `_espace_id(client, nom)`, `_token(client)`, `_token_personne(client, utilisateur)`, `_espace_id_personne(client, jeton_personne, utilisateur, nom)`, `_normaliser_espace(espace_brut)`, `UTILISATEUR_DEFAUT` — tous déjà existants dans `briques/memoire/main.py`, signatures inchangées.
- Produces (consommé par les Tasks 6 et 9, via un simple appel HTTP `POST /retenir {espace: "veille", wing: ..., ...}` avec un header `X-User-Id` réel) : `_resoudre_espace` renvoie désormais un espace **personnellement isolé** (`{nom}-{utilisateur}`, jeton personnel) pour tout espace custom nommé (ni `None`/`"solution"`, ni `"perso"`) dès qu'un `utilisateur` réel (≠ `UTILISATEUR_DEFAUT`) est résolu par `_identite_service`.

- [ ] **Step 1: Write the failing tests**

Créer `briques/memoire/test_espace_custom_personne.py` :

```python
"""Extension S193 : un espace memoire CUSTOM (ni 'perso', ni 'solution'/None) devient
personnellement isolé quand un vrai X-User-Id est transmis — même mécanique que 'perso'
(S186) mais générique, pour que veille-prospection/veille-info stockent leurs résumés dans
un espace "veille" séparé PAR PERSONNE.

Vérifie aussi la NON-régression : les appelants qui ne transmettent JAMAIS X-User-Id
aujourd'hui (Forge memory_palace.py, briques/transcription/main.py) doivent rester sur un
espace partagé, exactement comme avant cette extension.
"""
import json as _json

import httpx
import pytest
import respx

import main

API = main.MEMORY_API
VEILLE_ALICE_ID = "44444444-4444-4444-4444-444444444444"
VEILLE_BOB_ID = "55555555-5555-5555-5555-555555555555"
VEILLE_PARTAGE_ID = "66666666-6666-6666-6666-666666666666"
FORGE_ORG_ID = "77777777-7777-7777-7777-777777777777"
SOLUTION_ID = "88888888-8888-8888-8888-888888888888"


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    main._session["token"] = None
    main._espaces.clear()
    main._sessions_personne.clear()
    main._espaces_personne.clear()
    monkeypatch.setenv("MEMOIRE_KEY", "cle-coeur-memoire")
    yield
    main._session["token"] = None
    main._espaces.clear()
    main._sessions_personne.clear()
    main._espaces_personne.clear()


async def _appel(method: str, url: str, **kw):
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://brique") as c:
        return await c.request(method, url, **kw)


def _entetes(utilisateur: str | None = None) -> dict:
    e = {"X-API-Key": "cle-coeur-memoire"}
    if utilisateur:
        e["X-User-Id"] = utilisateur
    return e


def _cablage(rsx: respx.MockRouter):
    rsx.post(f"{API}/api/v1/auth/register").mock(return_value=httpx.Response(200, json={}))

    def _login(request):
        corps = _json.loads(request.content)
        email = corps["email"]
        if email == main.EMAIL:
            return httpx.Response(200, json={"access_token": "jwt-service"})
        utilisateur = email.split("@")[0]
        return httpx.Response(200, json={"access_token": f"jwt-{utilisateur}"})

    rsx.post(f"{API}/api/v1/auth/login").mock(side_effect=_login)

    espaces_personnels = {
        ("alice", "veille-alice"): VEILLE_ALICE_ID,
        ("bob", "veille-bob"): VEILLE_BOB_ID,
    }

    def _list_spaces(request):
        jwt = request.headers["authorization"].removeprefix("Bearer ")
        if jwt == "jwt-service":
            return httpx.Response(200, json=[
                {"id": VEILLE_PARTAGE_ID, "name": "veille"},
                {"id": FORGE_ORG_ID, "name": "forge-org-o1"},
                {"id": SOLUTION_ID, "name": "Workplace"},
            ])
        utilisateur = jwt.removeprefix("jwt-")
        connus = [(u, n) for (u, n) in espaces_personnels if u == utilisateur]
        return httpx.Response(200, json=[
            {"id": espaces_personnels[(u, n)], "name": n} for (u, n) in connus
        ])

    rsx.get(f"{API}/api/v1/spaces").mock(side_effect=_list_spaces)
    rsx.post(f"{API}/api/v1/spaces/{VEILLE_PARTAGE_ID}/invite").mock(
        return_value=httpx.Response(200, json={"detail": "invited"}))


@pytest.mark.asyncio
@respx.mock
async def test_espace_custom_avec_x_user_id_devient_personnel():
    _cablage(respx.mock)
    route = respx.post(f"{API}/api/v1/spaces/{VEILLE_ALICE_ID}/nodes").mock(
        return_value=httpx.Response(201, json={"id": "n1", "title": "t", "type": "input"}))
    r = await _appel("POST", "/retenir",
                     json={"contenu": "digest du jour", "espace": "veille",
                          "wing": "veille-info"},
                     headers=_entetes("alice"))
    assert r.status_code == 200
    assert route.called


@pytest.mark.asyncio
@respx.mock
async def test_deux_personnes_espaces_veille_distincts():
    _cablage(respx.mock)
    route_alice = respx.post(f"{API}/api/v1/spaces/{VEILLE_ALICE_ID}/nodes").mock(
        return_value=httpx.Response(201, json={"id": "n1", "title": "t", "type": "input"}))
    route_bob = respx.post(f"{API}/api/v1/spaces/{VEILLE_BOB_ID}/nodes").mock(
        return_value=httpx.Response(201, json={"id": "n2", "title": "t", "type": "input"}))
    await _appel("POST", "/retenir", json={"contenu": "x", "espace": "veille"},
                headers=_entetes("alice"))
    await _appel("POST", "/retenir", json={"contenu": "y", "espace": "veille"},
                headers=_entetes("bob"))
    assert route_alice.called and route_bob.called
    assert route_alice.calls.call_count == 1
    assert route_bob.calls.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_espace_custom_sans_x_user_id_reste_partage():
    """Motif Forge (memory_palace.py) : espace custom nommé, jamais de X-User-Id — doit
    rester EXACTEMENT comme avant cette extension (compte de service, espace partagé)."""
    _cablage(respx.mock)
    route = respx.post(f"{API}/api/v1/spaces/{FORGE_ORG_ID}/nodes").mock(
        return_value=httpx.Response(201, json={"id": "n3", "title": "t", "type": "input"}))
    r = await _appel("POST", "/retenir",
                     json={"contenu": "note projet", "espace": "forge-org-o1"},
                     headers=_entetes(None))
    assert r.status_code == 200
    assert route.called
    # Régression à éviter : un register/login personnel déclenché pour un appelant qui ne
    # transmet jamais X-User-Id.
    assert main._sessions_personne == {}


@pytest.mark.asyncio
@respx.mock
async def test_espace_solution_reste_partage_meme_avec_x_user_id():
    """L'espace solution (None/'solution') ne devient JAMAIS personnel, même avec un vrai
    X-User-Id — seul un espace CUSTOM nommé peut s'isoler par personne."""
    _cablage(respx.mock)
    route = respx.post(f"{API}/api/v1/spaces/{SOLUTION_ID}/nodes").mock(
        return_value=httpx.Response(201, json={"id": "n4", "title": "t", "type": "input"}))
    r = await _appel("POST", "/retenir", json={"contenu": "note", "espace": "solution"},
                     headers=_entetes("alice"))
    assert r.status_code == 200
    assert route.called
    assert main._sessions_personne == {}


@pytest.mark.asyncio
@respx.mock
async def test_perso_garde_son_comportement_historique_inchange():
    """Le mot-clé 'perso' (S186) suit TOUJOURS sa branche dédiée — cette extension ne doit
    rien y changer (nom d'espace 'Perso-<utilisateur>', pas 'perso-<utilisateur>')."""
    _cablage(respx.mock)
    perso_alice_id = "99999999-9999-9999-9999-999999999999"
    espaces_personnels_perso = {"alice": perso_alice_id}

    def _list_spaces_perso(request):
        jwt = request.headers["authorization"].removeprefix("Bearer ")
        if jwt == "jwt-service":
            return httpx.Response(200, json=[{"id": VEILLE_PARTAGE_ID, "name": "veille"}])
        utilisateur = jwt.removeprefix("jwt-")
        if utilisateur in espaces_personnels_perso:
            return httpx.Response(200, json=[
                {"id": espaces_personnels_perso[utilisateur], "name": f"Perso-{utilisateur}"}])
        return httpx.Response(200, json=[])

    respx.get(f"{API}/api/v1/spaces").mock(side_effect=_list_spaces_perso)
    route = respx.post(f"{API}/api/v1/spaces/{perso_alice_id}/nodes").mock(
        return_value=httpx.Response(201, json={"id": "n5", "title": "t", "type": "input"}))
    r = await _appel("POST", "/retenir", json={"contenu": "préfère le bleu", "espace": "perso"},
                     headers=_entetes("alice"))
    assert r.status_code == 200
    assert route.called
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd briques/memoire && python3 -m pytest test_espace_custom_personne.py -v`
Expected: `test_espace_custom_avec_x_user_id_devient_personnel`,
`test_deux_personnes_espaces_veille_distincts` et
`test_espace_solution_reste_partage_meme_avec_x_user_id` ÉCHOUENT (le code actuel résout
TOUJOURS un espace custom en partagé — `route.called` est `False`, ou une erreur respx
« no matching route » puisque le test n'a pas mocké l'endpoint `/nodes` du VRAI espace
appelé). `test_espace_custom_sans_x_user_id_reste_partage` et
`test_perso_garde_son_comportement_historique_inchange` PASSENT déjà (comportement actuel).

- [ ] **Step 3: Write the implementation**

Dans `briques/memoire/main.py`, remplacer la fonction `_resoudre_espace` (lignes 205-221) :

```python
async def _resoudre_espace(client: httpx.AsyncClient, espace_brut: str | None,
                           utilisateur: str) -> tuple[str, str]:
    """Résout `(espace_id, jwt à utiliser)` pour un appel de `utilisateur`.

    Le mot-clé ``perso`` garde sa branche dédiée EXACTE (S186, inchangée) : nom d'espace
    ``Perso-<utilisateur>``, casse figée.

    Tout AUTRE nom custom (ni ``None``/``"solution"``, ni ``"perso"``) devient lui aussi
    personnellement isolé (S193) dès qu'un ``utilisateur`` RÉEL est résolu (≠
    ``UTILISATEUR_DEFAUT`` — c'est-à-dire qu'un vrai ``X-User-Id`` a été transmis) : espace
    ``<nom>-<utilisateur>``, compte de LA personne. Généralisation du motif « perso », pour
    que veille-prospection/veille-info isolent leur espace "veille" par personne sans
    dupliquer la mécanique.

    Sans ``utilisateur`` réel (mode service/mono-user, ex. Forge ``forge-org-*``,
    ``transcription``) : comportement INCHANGÉ, espace partagé sous le compte de service —
    aucun appelant actuel ne transmet ``X-User-Id`` pour un espace custom, donc ce
    changement est rétrocompatible par construction (vérifié par test)."""
    if (espace_brut or "").strip().lower() == "perso":
        if utilisateur == UTILISATEUR_DEFAUT:
            return await _espace_id(client, "Perso"), await _token(client)
        jeton_personne = await _token_personne(client, utilisateur)
        nom = f"Perso-{utilisateur}"
        return await _espace_id_personne(client, jeton_personne, utilisateur, nom), jeton_personne
    nom = _normaliser_espace(espace_brut)
    if nom is not None and utilisateur != UTILISATEUR_DEFAUT:
        jeton_personne = await _token_personne(client, utilisateur)
        nom_personne = f"{nom}-{utilisateur}"
        return (await _espace_id_personne(client, jeton_personne, utilisateur, nom_personne),
                jeton_personne)
    return await _espace_id(client, nom), await _token(client)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd briques/memoire && python3 -m pytest test_espace_custom_personne.py -v`
Expected: `5 passed`

- [ ] **Step 5: Ajouter `"veille"` à l'énumération `espace` du manifest**

Dans `briques/memoire/manifest.json`, les 5 occurrences de :

```json
        "espace": {
          "type": "string",
          "enum": [
            "solution",
            "perso"
          ],
```

deviennent (ajout de `"veille"`, ordre alphabétique après `perso`) :

```json
        "espace": {
          "type": "string",
          "enum": [
            "solution",
            "perso",
            "veille"
          ],
```

Les 5 capacités concernées : `memoire_rappeler` (ligne ~38), `memoire_lister_souvenirs`
(~63), `memoire_taxonomy` (~80), `memoire_retenir` (~111), `memoire_oublier` (~133) — même
bloc de 6 lignes à chaque fois, seule la ligne `"description"` qui suit diffère (sert de
contexte pour distinguer les occurrences si l'édition se fait bloc par bloc).

- [ ] **Step 6: Verify manifest**

Run: `python3 -c "
import json
d = json.load(open('briques/memoire/manifest.json'))
for cap in d['capacites']:
    assert 'veille' in cap['params']['espace']['enum'], cap['nom']
print('manifest OK')
"`
Expected: `manifest OK`

Puis lancer toute la suite de la brique pour confirmer l'absence de régression :

Run: `cd briques/memoire && python3 -m pytest -v`
Expected: tous les tests passent (existants + les 5 nouveaux), aucune régression sur
`test_isolation_personne.py`, `test_memoire.py`, `test_spa_personne.py`.

- [ ] **Step 7: Commit**

```bash
git add briques/memoire/main.py briques/memoire/manifest.json \
       briques/memoire/test_espace_custom_personne.py
git commit -m "feat(memoire): espace custom isolable par personne (S193)"
```

---

### Task 2: `geo` — cibler `enrichir-lot` par `zone_id`

**Files:**
- Modify: `briques/geo/stockage.py` (nouvelle fonction, après `supprimer_zone` ligne ~302)
- Modify: `briques/geo/main.py:220-263` (`ProspecterLotEntree`, `enrichir_lot`)
- Test: `briques/geo/test_prospection.py` (ajout de tests)

**Interfaces:**
- Consumes : `stockage._zone_dict` (interne, déjà existant), `stockage.chercher_bbox` (déjà
  existant, signature inchangée).
- Produces (consommé par Task 6, `veille-prospection`) :
  - `stockage.lire_zone(tenant: str, zone_id: str) -> dict | None`
  - `POST /prospection/enrichir-lot` accepte désormais `{zone_id: str}` EN PLUS de
    `{bbox: str}` (l'un des deux requis, `zone_id` prioritaire si les deux sont fournis) —
    réponse strictement identique par ailleurs.

- [ ] **Step 1: Write the failing tests**

Ajouter à la fin de `briques/geo/test_prospection.py` :

```python


def test_prospecter_lot_via_zone_id(monkeypatch):
    monkeypatch.setattr(enrichissement.httpx, "Client", _FauxRecherche())
    cle = {"X-API-Key": "lot-zone"}
    zone = client.post("/zones", headers=cle, json={"nom": "Castres", "bbox": BBOX}).json()
    _objet(cle, "Prospect De La Zone")
    r = client.post("/prospection/enrichir-lot", headers=cle,
                    json={"zone_id": zone["id"], "limite": 10})
    assert r.status_code == 200
    assert r.json()["traites"] == 1


def test_prospecter_lot_zone_id_introuvable_404():
    cle = {"X-API-Key": "lot-zone-404"}
    r = client.post("/prospection/enrichir-lot", headers=cle,
                    json={"zone_id": "zone-inexistante", "limite": 10})
    assert r.status_code == 404


def test_prospecter_lot_zone_id_cloisonne_par_tenant(monkeypatch):
    monkeypatch.setattr(enrichissement.httpx, "Client", _FauxRecherche())
    zone = client.post("/zones", headers={"X-API-Key": "lot-zone-prop"},
                       json={"nom": "Castres", "bbox": BBOX}).json()
    r = client.post("/prospection/enrichir-lot", headers={"X-API-Key": "lot-zone-voisin"},
                    json={"zone_id": zone["id"], "limite": 10})
    assert r.status_code == 404   # zone d'un autre tenant : invisible, pas 403 (cloisonnement)


def test_prospecter_lot_sans_bbox_ni_zone_id_400():
    r = client.post("/prospection/enrichir-lot", headers={"X-API-Key": "lot-sans-cible"},
                    json={"limite": 10})
    assert r.status_code == 400
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd briques/geo && python3 -m pytest test_prospection.py -v -k zone_id`
Expected: FAIL (`ProspecterLotEntree` n'a pas de champ `zone_id` → 422 au lieu de 200/404/400
selon les tests, `AttributeError`/`ValidationError` visibles dans la réponse JSON).

- [ ] **Step 3: Write the implementation**

Dans `briques/geo/stockage.py`, ajouter après `supprimer_zone` (après la ligne 302) :

```python
def lire_zone(tenant: str, zone_id: str) -> dict | None:
    with _conn() as c:
        r = c.execute("SELECT * FROM geo_zones WHERE tenant = ? AND id = ?",
                      (tenant, zone_id)).fetchone()
    return _zone_dict(r) if r else None
```

Dans `briques/geo/main.py`, remplacer la classe `ProspecterLotEntree` (lignes 220-225) :

```python
class ProspecterLotEntree(BaseModel):
    bbox: Optional[str] = None             # zone « lat_min,lon_min,lat_max,lon_max »…
    zone_id: Optional[str] = None          # …OU une zone geo déjà créée (prioritaire)
    type: str = "entreprise"
    naf: Optional[str] = None              # préfixe d'activité pour cibler la prospection
    limite: int = 8                        # petit par défaut (enrichissement web = lent)
    force: bool = False                    # ré-enrichir même les objets déjà enrichis
```

Puis remplacer le début de `enrichir_lot` (lignes 228-241, jusqu'à la ligne
`res = stockage.chercher_bbox(...)`) :

```python
@app.post("/prospection/enrichir-lot")
def enrichir_lot(corps: ProspecterLotEntree, tenant: str = Depends(tenant_actuel)):
    """Enrichit EN LOT (borné) les objets d'une zone — le socle de la PROSPECTION : pour
    chaque objet, trouve le site officiel + les coordonnées publiques (même moteur que
    l'unitaire, mêmes garde-fous : uniquement ce que l'entité affiche, chaque tentative
    journalisée). Cible une zone géo déjà créée (`zone_id`, S193 — couvre aussi les zones
    définies par communes, leur bbox étant toujours résolu à la création) OU une bbox brute.
    Assouplissement ASSUMÉ du « une à la fois » pour du démarchage B2B, gardé BORNÉ (plafond
    GEO_ENRICHIR_LOT_MAX). Synchrone et lent (lectures web réelles) → garde les lots petits.
    Renvoie un décompte honnête + les prospects prêts pour le CRM."""
    type_, naf = corps.type, corps.naf
    if corps.zone_id:
        zone = stockage.lire_zone(tenant, corps.zone_id)
        if not zone:
            raise HTTPException(404, "Zone introuvable.")   # cloisonnement : rien révélé
        boite = (zone["lat_min"], zone["lon_min"], zone["lat_max"], zone["lon_max"])
        type_, naf = zone["type"], zone["naf"]
    elif corps.bbox:
        try:
            boite = domaine.valider_bbox(corps.bbox)
        except ValueError as e:
            raise HTTPException(400, str(e))
    else:
        raise HTTPException(400, "Fournir soit « zone_id », soit « bbox ».")
    plafond = max(1, min(corps.limite, PLAFOND_ENRICHIR_LOT))
    res = stockage.chercher_bbox(tenant, boite, type_=type_, naf=naf, limite=plafond)
```

Le reste de la fonction (à partir de `objets = res["objets"]`) est **inchangé** — attention à
bien remplacer les usages restants de `corps.type`/`corps.naf` s'il y en avait (il n'y en a
pas dans le corps de boucle existant : seul l'appel à `chercher_bbox` les utilisait).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd briques/geo && python3 -m pytest test_prospection.py -v`
Expected: tous les tests passent (les 6 existants + les 4 nouveaux = 10 passed).

Run: `cd briques/geo && python3 -m pytest -v`
Expected: aucune régression sur le reste de la suite (`test_objets.py`, `test_ingestion.py`,
`test_communes.py`, `test_enrichissement.py`, `test_domaine.py`, `test_fournisseurs.py`,
`test_isolation.py`, `test_front.py`).

- [ ] **Step 5: Commit**

```bash
git add briques/geo/stockage.py briques/geo/main.py briques/geo/test_prospection.py
git commit -m "feat(geo): cibler l'enrichissement en lot par zone_id (S193)"
```

---

### Task 3: `geo` — dirigeants + effectifs (zéro appel réseau supplémentaire)

**Files:**
- Modify: `briques/geo/domaine.py:140-176` (`normaliser_entreprise`)
- Test: `briques/geo/test_fournisseurs.py` (ajout de tests, réutilise `PAYLOAD_SIRENE`)

**Interfaces:**
- Consumes : rien de nouveau (payload brut déjà reçu par la fonction).
- Produces (consommé par Task 4, `_prospect_crm`) : `normaliser_entreprise(...)["metadata"]`
  gagne deux clés OPTIONNELLES (absentes si la donnée source ne les fournit pas) :
  - `dirigeants: list[{"nom": str, "prenom": str, "qualite": str}]` (au plus 5)
  - `effectifs: str` (tranche brute Sirene, ex. `"22"`)

Payload réel vérifié (`curl https://recherche-entreprises.api.gouv.fr/search?q=...`, live
2026-07-21) : `dirigeants` est une liste AU NIVEAU RACINE du payload (pas dans
`matching_etablissements`/`siege`), avec deux formes selon `type_dirigeant` :
- personne physique : `{"nom", "prenoms", "qualite", "type_dirigeant": "personne physique", ...}`
- personne morale : `{"denomination", "siren", "qualite", "type_dirigeant": "personne morale"}`
  (PAS de `nom`/`prenoms`).

`tranche_effectif_salarie` est un champ de l'ÉTABLISSEMENT (`matching_etablissements[0]` ou
`siege`, comme les autres champs déjà lus par cette fonction) — pas du payload racine.

- [ ] **Step 1: Write the failing tests**

Ajouter à `briques/geo/test_fournisseurs.py`, après
`test_normaliser_prend_l_etablissement_local_pas_le_siege` :

```python


def test_normaliser_extrait_dirigeants_et_effectifs_si_presents():
    payload = {**PAYLOAD_SIRENE,
              "dirigeants": [
                  {"nom": "BLACHERE", "prenoms": "BERNARD", "qualite": "Président de SAS",
                   "type_dirigeant": "personne physique"},
                  {"siren": "378159818", "denomination": "HOLDING BLACHERE",
                   "qualite": "Président de SAS", "type_dirigeant": "personne morale"},
              ],
              "matching_etablissements": [
                  {**PAYLOAD_SIRENE["matching_etablissements"][0],
                   "tranche_effectif_salarie": "22"},
              ]}
    objet = domaine.normaliser_entreprise(payload)
    assert objet["metadata"]["dirigeants"] == [
        {"nom": "BLACHERE", "prenom": "BERNARD", "qualite": "Président de SAS"},
        {"nom": "HOLDING BLACHERE", "prenom": "", "qualite": "Président de SAS"},
    ]
    assert objet["metadata"]["effectifs"] == "22"


def test_normaliser_sans_dirigeants_ni_effectifs_absents_du_metadata():
    objet = domaine.normaliser_entreprise(PAYLOAD_SIRENE)
    assert "dirigeants" not in objet["metadata"]
    assert "effectifs" not in objet["metadata"]


def test_normaliser_dirigeants_tronque_a_cinq():
    payload = {**PAYLOAD_SIRENE,
              "dirigeants": [{"nom": f"Dirigeant {i}", "qualite": "Gérant"} for i in range(8)]}
    objet = domaine.normaliser_entreprise(payload)
    assert len(objet["metadata"]["dirigeants"]) == 5
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd briques/geo && python3 -m pytest test_fournisseurs.py -v -k dirigeants_et_effectifs`
Expected: FAIL (`KeyError: 'dirigeants'` — la clé n'existe pas encore dans `metadata`).

- [ ] **Step 3: Write the implementation**

Dans `briques/geo/domaine.py`, remplacer `normaliser_entreprise` (lignes 140-176) :

```python
def _dirigeant_dict(d: dict) -> dict:
    """Un dirigeant Sirene, personne physique OU morale — normalisé au même schéma
    ({nom, prenom, qualite}) pour que la vue prospect (geo/main.py::_prospect_crm) n'ait
    jamais à distinguer les deux formes."""
    return {"nom": d.get("nom") or d.get("denomination") or "",
            "prenom": d.get("prenoms") or "", "qualite": d.get("qualite") or ""}


def normaliser_entreprise(brute: dict, type_: str = "entreprise") -> dict | None:
    """Payload brut recherche-entreprises.api.gouv.fr → objet `geo_objects`, ou None si
    inexploitable. PIÈGE vérifié LIVE : l'API apparie les ÉTABLISSEMENTS proches
    (`matching_etablissements`) — c'est LUI qu'on géolocalise et date, pas le siège
    (le bureau de poste de Castres appartient à un siège… parisien). On écarte les
    établissements FERMÉS (etat_administratif ≠ A) et les coordonnées protégées
    (« [NON-DIFFUSIBLE] », vu LIVE sur des associations). Coordonnées en CHAÎNES.
    L'identité d'upsert = SIRET de l'établissement (le SIREN en repli).
    `type_` : « entreprise » ou « association » (même payload Sirene).

    S193 : `dirigeants` (payload RACINE, personnes physiques ET morales, tronqué à 5) et
    `effectifs` (tranche Sirene, champ de l'ÉTABLISSEMENT) sont extraits si présents —
    zéro appel réseau supplémentaire (même payload déjà reçu). Absents du metadata si la
    donnée source ne les fournit pas (payload figé de test, ou API sans ces champs)."""
    etab = (brute.get("matching_etablissements") or [{}])[0]
    if not etab:
        etab = brute.get("siege") or {}
    if (etab.get("etat_administratif") or "A") != "A":
        return None
    try:
        latitude = float(etab.get("latitude"))
        longitude = float(etab.get("longitude"))
        valider_point(latitude, longitude)
    except (TypeError, ValueError):
        return None
    nom = (etab.get("nom_commercial") or brute.get("nom_complet")
           or brute.get("nom_raison_sociale") or "")
    metadata = {
        "nom": nom,
        "naf": etab.get("activite_principale") or brute.get("activite_principale") or "",
        "adresse": etab.get("adresse") or "",
        "commune": etab.get("libelle_commune") or "",
        "siren": brute.get("siren") or "",
    }
    dirigeants = [_dirigeant_dict(d) for d in (brute.get("dirigeants") or [])[:5]
                 if (d.get("nom") or d.get("denomination"))]
    if dirigeants:
        metadata["dirigeants"] = dirigeants
    effectifs = etab.get("tranche_effectif_salarie")
    if effectifs:
        metadata["effectifs"] = effectifs
    return {
        "type": type_,
        "latitude": latitude,
        "longitude": longitude,
        "date_reference": etab.get("date_creation") or brute.get("date_creation"),
        "ref_externe": etab.get("siret") or brute.get("siren"),
        "source": "recherche-entreprises",
        "metadata": metadata,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd briques/geo && python3 -m pytest test_fournisseurs.py -v`
Expected: tous les tests passent (existants + 3 nouveaux). Vérifier en particulier que
`test_normaliser_prend_l_etablissement_local_pas_le_siege` (assertion `==` stricte sur tout
le dict) passe TOUJOURS sans modification — `PAYLOAD_SIRENE` n'a ni `dirigeants` ni
`tranche_effectif_salarie`, donc ces clés restent absentes de `metadata`.

Run: `cd briques/geo && python3 -m pytest -v`
Expected: aucune régression sur le reste de la suite.

- [ ] **Step 5: Commit**

```bash
git add briques/geo/domaine.py briques/geo/test_fournisseurs.py
git commit -m "feat(geo): extraire dirigeants + effectifs du payload Sirene (S193)"
```

---

### Task 4: `geo` — réseaux sociaux (liens du site officiel) + vue prospect enrichie

**Files:**
- Modify: `briques/geo/enrichissement.py` (nouvelle constante + fonction, appel dans `enrichir`)
- Modify: `briques/geo/main.py` (`_enrichir_et_enregistrer`, `_prospect_crm`)
- Test: `briques/geo/test_enrichissement.py` (ajout de tests)
- Test: `briques/geo/test_prospection.py` (ajout d'un test)

**Interfaces:**
- Consumes : `_domaine(url)` (déjà existant dans `enrichissement.py`).
- Produces (consommé par Task 6 via `_prospect_crm`, indirectement) :
  - `enrichissement.extraire_reseaux_sociaux(liens: list) -> list[str]`
  - `enrichissement.enrichir(objet)["reseaux_sociaux"] -> list[str]` (nouvelle clé du rapport)
  - `_prospect_crm(objet)` expose désormais aussi `dirigeants`, `effectifs`,
    `reseaux_sociaux` (lus depuis `objet["metadata"]`, `None`/absents si jamais renseignés).

- [ ] **Step 1: Write the failing tests**

Ajouter à `briques/geo/test_enrichissement.py`, après les tests d'heuristiques pures (après
`test_trouver_lien_contact_dicts_et_chaines`, avant la section « Faux client HTTP ») :

```python


def test_extraire_reseaux_sociaux_filtre_et_deduplique():
    liens = [
        {"url": "https://www.facebook.com/x"}, {"url": "https://www.facebook.com/x"},
        {"url": "https://linkedin.com/company/x"}, {"url": "https://autre-site.fr/"},
        "https://x.com/handle",
    ]
    assert enrichissement.extraire_reseaux_sociaux(liens) == [
        "https://www.facebook.com/x", "https://linkedin.com/company/x",
        "https://x.com/handle"]


def test_extraire_reseaux_sociaux_vide_sans_liens():
    assert enrichissement.extraire_reseaux_sociaux([]) == []
    assert enrichissement.extraire_reseaux_sociaux(None) == []
```

Puis ajouter, après `test_enrichir_email_sur_la_page_contact` :

```python


def test_enrichir_extrait_reseaux_sociaux_de_la_page_officielle(monkeypatch):
    pages = {"https://boulangerie-test.fr/":
             {"texte": "Bienvenue ! bonjour@boulangerie-test.fr",
              "liens": [{"url": "https://www.facebook.com/boulangerietest", "texte": "FB"},
                       {"url": "https://www.instagram.com/boulangerietest", "texte": "IG"},
                       {"url": "https://boulangerie-test.fr/menu", "texte": "Menu"}]}}
    monkeypatch.setattr(enrichissement.httpx, "Client", _FauxHTTP(RESULTATS, pages))
    r = client.post(f"/objets/{_objet()}/enrichir", headers=CLE)
    meta = r.json()["objet"]["metadata"]
    assert meta["reseaux_sociaux"] == ["https://www.facebook.com/boulangerietest",
                                       "https://www.instagram.com/boulangerietest"]


def test_enrichir_sans_reseaux_sociaux_absent_du_metadata(monkeypatch):
    pages = {"https://boulangerie-test.fr/":
             {"texte": "bonjour@boulangerie-test.fr", "liens": []}}
    monkeypatch.setattr(enrichissement.httpx, "Client", _FauxHTTP(RESULTATS, pages))
    r = client.post(f"/objets/{_objet()}/enrichir", headers=CLE)
    assert "reseaux_sociaux" not in r.json()["objet"]["metadata"]
```

Et à `briques/geo/test_prospection.py`, à la fin :

```python


def test_prospect_crm_expose_dirigeants_et_effectifs(monkeypatch):
    monkeypatch.setattr(enrichissement.httpx, "Client", _FauxRecherche())
    cle = {"X-API-Key": "lot-profond"}
    _objet(cle, "Societe Profonde", metadata={
        "dirigeants": [{"nom": "Dupont", "prenom": "Alice", "qualite": "Gérante"}],
        "effectifs": "10 à 19 salariés",
    })
    r = client.post("/prospection/enrichir-lot", headers=cle,
                    json={"bbox": BBOX, "limite": 10}).json()
    p = r["prospects"][0]
    assert p["dirigeants"] == [{"nom": "Dupont", "prenom": "Alice", "qualite": "Gérante"}]
    assert p["effectifs"] == "10 à 19 salariés"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd briques/geo && python3 -m pytest test_enrichissement.py test_prospection.py -v -k "reseaux_sociaux or dirigeants_et_effectifs"`
Expected: FAIL (`AttributeError: module 'enrichissement' has no attribute
'extraire_reseaux_sociaux'` pour les 4 premiers ; `KeyError: 'dirigeants'` pour le dernier —
`_prospect_crm` ne renvoie pas encore ces clés).

- [ ] **Step 3: Write the implementation**

Dans `briques/geo/enrichissement.py`, ajouter après `DOMAINES_ANNUAIRES` (après la ligne 31) :

```python
# Réseaux sociaux : PAS des annuaires (on ne les choisit jamais comme « site officiel »,
# cf. DOMAINES_ANNUAIRES ci-dessus), mais un lien vers l'un d'eux TROUVÉ SUR le site
# officiel est publié par l'entreprise elle-même — cohérent avec le principe RGPD-prudent
# de ce module, contrairement aux avis tiers (hors périmètre, cf. design S193).
DOMAINES_SOCIAUX = {"facebook.com", "instagram.com", "linkedin.com", "twitter.com",
                    "x.com", "tiktok.com"}
```

Puis ajouter, après `trouver_lien_contact` (après la ligne 111, avant la section I/O) :

```python
def extraire_reseaux_sociaux(liens: list) -> list[str]:
    """Liens vers des réseaux sociaux trouvés SUR le site officiel — dédupliqués, ordre
    d'apparition. `liens` a le même format que celui déjà consommé par
    `trouver_lien_contact` (dicts {"url", "texte"} ou chaînes brutes)."""
    urls: list[str] = []
    for lien in liens or []:
        url = lien if isinstance(lien, str) else (lien.get("url") or "")
        if url and _domaine(url) in DOMAINES_SOCIAUX and url not in urls:
            urls.append(url)
    return urls
```

Dans `enrichir(objet)`, juste après `rapport = {"statut": "ok", ...}` (ligne 143-144),
initialiser la clé, puis la remplir avec les autres champs de la page (juste après le calcul
de `contacts`, ligne ~149-151) :

```python
        rapport = {"statut": "ok", "requete": requete, "site": site,
                   "emails": [], "telephones": [], "reseaux_sociaux": [], "source_url": site}
        page = client.post(f"{_base_recherche()}/lire-page",
                           json={"url": site}, headers=_entetes())
        if page.status_code < 400:
            d = page.json()
            contacts = extraire_contacts(d.get("texte") or "")
            rapport["emails"] = contacts["emails"]
            rapport["telephones"] = contacts["telephones"]
            rapport["reseaux_sociaux"] = extraire_reseaux_sociaux(d.get("liens") or [])
```

(Le reste de la fonction, à partir de `if not rapport["emails"]:`, est inchangé.)

Dans `briques/geo/main.py`, `_enrichir_et_enregistrer` (lignes 174-183), ajouter après la
ligne `meta["enrichi_source"] = rapport["source_url"]` :

```python
        if rapport.get("reseaux_sociaux"):
            meta["reseaux_sociaux"] = rapport["reseaux_sociaux"]
```

Et `_prospect_crm` (lignes 187-194), remplacer le `return` :

```python
def _prospect_crm(objet: dict) -> dict:
    """Vue « prête pour le CRM » d'un objet enrichi : ce dont la Forge a besoin pour créer
    un prospect (nom, coordonnées publiques trouvées, site, référence pour dé-doublonner),
    plus l'enrichissement profond S193 (dirigeants, effectifs, réseaux sociaux) quand
    disponible."""
    m = objet.get("metadata") or {}
    return {"objet_id": objet["id"], "nom": m.get("nom"), "entreprise": m.get("nom"),
            "email": m.get("email"), "telephone": m.get("telephone"),
            "site": m.get("site"), "naf": m.get("naf"), "commune": m.get("commune"),
            "ref_externe": objet.get("ref_externe"), "source": objet.get("source"),
            "dirigeants": m.get("dirigeants"), "effectifs": m.get("effectifs"),
            "reseaux_sociaux": m.get("reseaux_sociaux")}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd briques/geo && python3 -m pytest test_enrichissement.py test_prospection.py -v`
Expected: tous les tests passent.

Run: `cd briques/geo && python3 -m pytest -v`
Expected: `XX passed` — aucune régression (attention particulière à
`test_prospecter_lot_enrichit_plusieurs_et_rend_prospects` : le prospect a maintenant 3
clés de plus avec valeur `None`, l'assertion existante `p["nom"] and p["entreprise"] == ...`
etc. ne teste pas d'égalité stricte du dict complet donc reste verte).

- [ ] **Step 5: Commit**

```bash
git add briques/geo/enrichissement.py briques/geo/main.py \
       briques/geo/test_enrichissement.py briques/geo/test_prospection.py
git commit -m "feat(geo): réseaux sociaux du site officiel + vue prospect enrichie (S193)"
```

---

### Task 5: `veille-prospection` — stockage SQLite (campagnes, exécutions)

**Files:**
- Create: `briques/veille-prospection/stockage.py`
- Create: `briques/veille-prospection/conftest.py`
- Create: `briques/veille-prospection/test_stockage.py`

**Interfaces:**
- Consumes : rien (module racine).
- Produces (consommé par Tasks 6, 7) :
  - `stockage.creer_campagne(user_id: str, zone_id: str) -> dict` →
    `{"id", "user_id", "zone_id", "actif", "derniere_execution", "created_at"}`
  - `stockage.lister_campagnes(user_id: str, *, actives_seulement: bool = False) -> list[dict]`
  - `stockage.supprimer_campagne(user_id: str, campagne_id: int) -> bool`
  - `stockage.lister_user_ids_actifs() -> list[str]`
  - `stockage.inserer_execution(campagne_id: int, *, trouves: int, deja_connus: int, nouveaux_crm: int, erreur: str | None) -> dict`
  - `stockage.lister_executions(campagne_id: int, limite: int = 20) -> list[dict]`
  - `stockage.maj_derniere_execution(campagne_id: int) -> None`

- [ ] **Step 1: Write the failing test**

Créer `briques/veille-prospection/conftest.py` :

```python
"""Config de test : DB temporaire AVANT tout import des modules applicatifs."""
import os
import tempfile

_db = os.path.join(tempfile.gettempdir(), "veille_prospection_test.db")
os.environ["VEILLE_PROSPECTION_DB"] = _db
os.environ.pop("API_KEYS", None)
os.environ.pop("GEO_KEY", None)
os.environ.pop("FORGE_KEY", None)
os.environ.pop("MEMOIRE_KEY", None)
os.environ.pop("VEILLE_PROSPECTION_KEY", None)

if os.path.exists(_db):
    os.remove(_db)
```

Créer `briques/veille-prospection/test_stockage.py` :

```python
"""Tests de la persistance (S193). Isolation par user_id, journal d'exécutions par
campagne — motif briques/veille-info/test_stockage.py."""
import stockage


def test_creer_et_lister_campagnes():
    c = stockage.creer_campagne("alice", "zone-1")
    assert c["zone_id"] == "zone-1" and c["actif"] is True
    campagnes = stockage.lister_campagnes("alice")
    assert len(campagnes) == 1 and campagnes[0]["id"] == c["id"]


def test_lister_campagnes_isole_par_user_id():
    stockage.creer_campagne("bob", "zone-de-bob")
    assert all(c["zone_id"] != "zone-de-bob" for c in stockage.lister_campagnes("alice"))


def test_supprimer_campagne_isole_par_user_id():
    c = stockage.creer_campagne("carol", "zone-a-supprimer")
    assert stockage.supprimer_campagne("mallory", c["id"]) is False
    assert stockage.supprimer_campagne("carol", c["id"]) is True
    assert stockage.lister_campagnes("carol") == []


def test_lister_user_ids_actifs_ignore_campagnes_inactives():
    stockage.creer_campagne("dave", "zone-active")
    seule = stockage.creer_campagne("dave-seul-inactif", "zone-off")
    with stockage._conn() as c:
        c.execute("UPDATE campagnes SET actif = 0 WHERE id = ?", (seule["id"],))
    ids = stockage.lister_user_ids_actifs()
    assert "dave" in ids
    assert "dave-seul-inactif" not in ids


def test_inserer_et_lister_executions():
    c = stockage.creer_campagne("erin", "zone-erin")
    stockage.inserer_execution(c["id"], trouves=3, deja_connus=1, nouveaux_crm=2, erreur=None)
    executions = stockage.lister_executions(c["id"])
    assert len(executions) == 1
    assert executions[0]["trouves"] == 3 and executions[0]["erreur"] is None


def test_maj_derniere_execution():
    c = stockage.creer_campagne("frank", "zone-frank")
    assert c["derniere_execution"] is None
    stockage.maj_derniere_execution(c["id"])
    maj = stockage.lister_campagnes("frank")[0]
    assert maj["derniere_execution"] is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd briques/veille-prospection && python3 -m pytest test_stockage.py -v`
Expected: FAIL avec `ModuleNotFoundError: No module named 'stockage'`

- [ ] **Step 3: Write the implementation**

Créer `briques/veille-prospection/stockage.py` :

```python
"""Persistance de veille-prospection (SQLite). Cloisonné par `user_id` (motif
briques/veille-info/stockage.py). `campagnes` référence une zone `geo` EXISTANTE
(`zone_id`) — la définition de zone reste exclusivement dans `geo`, jamais dupliquée ici.
`executions` journalise chaque passage horloge, par campagne."""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone

_DB = os.getenv("VEILLE_PROSPECTION_DB", "/data/veille_prospection.db")


def _maintenant() -> str:
    return datetime.now(timezone.utc).isoformat()


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(_DB)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


_SCHEMA = """
CREATE TABLE IF NOT EXISTS campagnes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    zone_id TEXT NOT NULL,
    actif INTEGER NOT NULL DEFAULT 1,
    derniere_execution TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_campagnes_user ON campagnes(user_id);

CREATE TABLE IF NOT EXISTS executions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campagne_id INTEGER NOT NULL REFERENCES campagnes(id),
    date TEXT NOT NULL,
    trouves INTEGER NOT NULL DEFAULT 0,
    deja_connus INTEGER NOT NULL DEFAULT 0,
    nouveaux_crm INTEGER NOT NULL DEFAULT 0,
    erreur TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_executions_campagne ON executions(campagne_id);
"""


def init() -> None:
    os.makedirs(os.path.dirname(_DB) or ".", exist_ok=True)
    with _conn() as c:
        c.executescript(_SCHEMA)


init()  # schéma prêt dès l'import (robuste même sous TestClient)


def _campagne_dict(r: sqlite3.Row) -> dict:
    return {"id": r["id"], "user_id": r["user_id"], "zone_id": r["zone_id"],
            "actif": bool(r["actif"]), "derniere_execution": r["derniere_execution"],
            "created_at": r["created_at"]}


def creer_campagne(user_id: str, zone_id: str) -> dict:
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO campagnes (user_id, zone_id, actif, created_at) VALUES (?,?,1,?)",
            (user_id, zone_id, _maintenant()))
        row = c.execute("SELECT * FROM campagnes WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _campagne_dict(row)


def lister_campagnes(user_id: str, *, actives_seulement: bool = False) -> list[dict]:
    q = "SELECT * FROM campagnes WHERE user_id = ?"
    if actives_seulement:
        q += " AND actif = 1"
    q += " ORDER BY created_at DESC"
    with _conn() as c:
        rows = c.execute(q, (user_id,)).fetchall()
    return [_campagne_dict(r) for r in rows]


def supprimer_campagne(user_id: str, campagne_id: int) -> bool:
    with _conn() as c:
        cur = c.execute("DELETE FROM campagnes WHERE id = ? AND user_id = ?",
                        (campagne_id, user_id))
    return cur.rowcount > 0


def lister_user_ids_actifs() -> list[str]:
    with _conn() as c:
        rows = c.execute("SELECT DISTINCT user_id FROM campagnes WHERE actif = 1").fetchall()
    return [r["user_id"] for r in rows]


def _execution_dict(r: sqlite3.Row) -> dict:
    return {"id": r["id"], "campagne_id": r["campagne_id"], "date": r["date"],
            "trouves": r["trouves"], "deja_connus": r["deja_connus"],
            "nouveaux_crm": r["nouveaux_crm"], "erreur": r["erreur"],
            "created_at": r["created_at"]}


def inserer_execution(campagne_id: int, *, trouves: int, deja_connus: int,
                      nouveaux_crm: int, erreur: str | None) -> dict:
    date = datetime.now(timezone.utc).date().isoformat()
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO executions (campagne_id, date, trouves, deja_connus, nouveaux_crm,"
            " erreur, created_at) VALUES (?,?,?,?,?,?,?)",
            (campagne_id, date, trouves, deja_connus, nouveaux_crm, erreur, _maintenant()))
        row = c.execute("SELECT * FROM executions WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _execution_dict(row)


def lister_executions(campagne_id: int, limite: int = 20) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM executions WHERE campagne_id = ? ORDER BY created_at DESC LIMIT ?",
            (campagne_id, limite)).fetchall()
    return [_execution_dict(r) for r in rows]


def maj_derniere_execution(campagne_id: int) -> None:
    with _conn() as c:
        c.execute("UPDATE campagnes SET derniere_execution = ? WHERE id = ?",
                  (_maintenant(), campagne_id))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd briques/veille-prospection && python3 -m pytest test_stockage.py -v`
Expected: `6 passed`

- [ ] **Step 5: Commit**

```bash
git add briques/veille-prospection/stockage.py briques/veille-prospection/conftest.py \
       briques/veille-prospection/test_stockage.py
git commit -m "feat(veille-prospection): stockage SQLite campagnes/exécutions"
```

---

### Task 6: `veille-prospection` — orchestration (geo → forge → mémoire)

**Files:**
- Create: `briques/veille-prospection/orchestration.py`
- Test: `briques/veille-prospection/test_orchestration.py`

**Interfaces:**
- Consumes :
  - `stockage.lister_user_ids_actifs() -> list[str]` (Task 5)
  - `stockage.lister_campagnes(user_id, *, actives_seulement=False) -> list[dict]` (Task 5)
  - `stockage.inserer_execution(campagne_id, *, trouves, deja_connus, nouveaux_crm, erreur) -> dict` (Task 5)
  - `stockage.maj_derniere_execution(campagne_id) -> None` (Task 5)
- Produces (consommé par Task 7) :
  `orchestration.executer_campagnes(user_ids: list[str] | None = None) -> dict` →
  `{"campagnes_executees": int}`

**Note d'isolation des tests** : `executer_campagnes` accepte un paramètre optionnel
`user_ids` — motif exact `digest.executer_digest_quotidien` de `veille-info` (jamais utilisé
par la route HTTP réelle, qui traite toujours tout le monde ; sert à cibler précisément les
campagnes créées par CE test, sans toucher celles laissées par d'autres fichiers dans la
même DB SQLite partagée).

- [ ] **Step 1: Write the failing tests**

Créer `briques/veille-prospection/test_orchestration.py` :

```python
"""Tests de l'orchestration des campagnes (S193). Aucun réseau réel : geo/forge/memoire
mockés via monkeypatch sur `orchestration.httpx.post`. Chaque test utilise ses propres
identifiants (`orch-<prenom>`) pour ne jamais dépendre des campagnes laissées par d'autres
fichiers de test dans la DB SQLite partagée."""
import httpx

import orchestration
import stockage


class _Rep:
    def __init__(self, status_code, corps):
        self.status_code, self._corps = status_code, corps

    def json(self):
        return self._corps

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("erreur", request=None, response=None)


def test_campagne_sans_prospects_pas_de_crm_ni_memoire(monkeypatch):
    c = stockage.creer_campagne("orch-alice", "zone-vide")
    appels = {"forge": 0, "memoire": 0}

    def _post(url, json=None, headers=None, timeout=None):
        if url.endswith("/prospection/enrichir-lot"):
            return _Rep(200, {"prospects": [], "compte": {"deja_enrichi": 0}})
        if url.endswith("/crm/import-lot"):
            appels["forge"] += 1
            return _Rep(200, {"crees": 0})
        if url.endswith("/retenir"):
            appels["memoire"] += 1
            return _Rep(200, {"retenu": True})
        raise AssertionError(url)

    monkeypatch.setattr(orchestration.httpx, "post", _post)
    resultat = orchestration.executer_campagnes(user_ids=["orch-alice"])
    assert resultat == {"campagnes_executees": 1}
    assert appels == {"forge": 0, "memoire": 0}
    executions = stockage.lister_executions(c["id"])
    assert executions[0]["trouves"] == 0
    assert executions[0]["nouveaux_crm"] == 0
    assert executions[0]["erreur"] is None


def test_campagne_avec_prospects_pousse_crm_et_memoire(monkeypatch):
    c = stockage.creer_campagne("orch-bob", "zone-pleine")
    captes = {}

    def _post(url, json=None, headers=None, timeout=None):
        if url.endswith("/prospection/enrichir-lot"):
            assert json == {"zone_id": "zone-pleine"}
            return _Rep(200, {"prospects": [{"nom": "Prospect 1"}],
                              "compte": {"deja_enrichi": 2}})
        if url.endswith("/crm/import-lot"):
            captes["forge_json"] = json
            return _Rep(200, {"crees": 1})
        if url.endswith("/retenir"):
            captes["memoire_json"] = json
            captes["memoire_headers"] = headers
            return _Rep(200, {"retenu": True})
        raise AssertionError(url)

    monkeypatch.setattr(orchestration.httpx, "post", _post)
    resultat = orchestration.executer_campagnes(user_ids=["orch-bob"])
    assert resultat == {"campagnes_executees": 1}
    assert captes["forge_json"] == {"prospects": [{"nom": "Prospect 1"}]}
    assert captes["memoire_json"]["espace"] == "veille"
    assert captes["memoire_json"]["wing"] == "veille-prospection"
    assert captes["memoire_headers"]["X-User-Id"] == "orch-bob"
    executions = stockage.lister_executions(c["id"])
    assert executions[0]["trouves"] == 1
    assert executions[0]["deja_connus"] == 2
    assert executions[0]["nouveaux_crm"] == 1
    assert executions[0]["erreur"] is None


def test_geo_injoignable_erreur_journalisee_pas_de_crash(monkeypatch):
    c = stockage.creer_campagne("orch-carol", "zone-panne")

    def _post(url, json=None, headers=None, timeout=None):
        if url.endswith("/prospection/enrichir-lot"):
            raise httpx.ConnectError("refus de connexion")
        raise AssertionError(url)

    monkeypatch.setattr(orchestration.httpx, "post", _post)
    resultat = orchestration.executer_campagnes(user_ids=["orch-carol"])
    assert resultat == {"campagnes_executees": 1}
    executions = stockage.lister_executions(c["id"])
    assert executions[0]["trouves"] == 0
    assert executions[0]["erreur"] is not None


def test_forge_injoignable_apres_geo_ok_prospects_pas_perdus(monkeypatch):
    c = stockage.creer_campagne("orch-dave", "zone-forge-panne")

    def _post(url, json=None, headers=None, timeout=None):
        if url.endswith("/prospection/enrichir-lot"):
            return _Rep(200, {"prospects": [{"nom": "P"}], "compte": {"deja_enrichi": 0}})
        if url.endswith("/crm/import-lot"):
            raise httpx.ConnectError("forge down")
        if url.endswith("/retenir"):
            return _Rep(200, {"retenu": True})
        raise AssertionError(url)

    monkeypatch.setattr(orchestration.httpx, "post", _post)
    orchestration.executer_campagnes(user_ids=["orch-dave"])
    executions = stockage.lister_executions(c["id"])
    assert executions[0]["trouves"] == 1     # le prospect n'est pas « perdu » au décompte
    assert executions[0]["nouveaux_crm"] == 0
    assert executions[0]["erreur"] is not None


def test_memoire_injoignable_najamais_bloquant(monkeypatch):
    c = stockage.creer_campagne("orch-erin", "zone-memoire-panne")

    def _post(url, json=None, headers=None, timeout=None):
        if url.endswith("/prospection/enrichir-lot"):
            return _Rep(200, {"prospects": [{"nom": "P"}], "compte": {"deja_enrichi": 0}})
        if url.endswith("/crm/import-lot"):
            return _Rep(200, {"crees": 1})
        if url.endswith("/retenir"):
            raise httpx.ConnectError("memoire down")
        raise AssertionError(url)

    monkeypatch.setattr(orchestration.httpx, "post", _post)
    resultat = orchestration.executer_campagnes(user_ids=["orch-erin"])
    assert resultat == {"campagnes_executees": 1}
    executions = stockage.lister_executions(c["id"])
    assert executions[0]["nouveaux_crm"] == 1   # le CRM n'est pas affecté par la panne mémoire
    assert executions[0]["erreur"] is None      # best-effort : jamais remonté


def test_executer_campagnes_ignore_campagnes_inactives(monkeypatch):
    stockage.creer_campagne("orch-frank", "zone-active")
    inactive = stockage.creer_campagne("orch-frank-seul-inactif", "zone-off")
    with stockage._conn() as conn:
        conn.execute("UPDATE campagnes SET actif = 0 WHERE id = ?", (inactive["id"],))

    def _post(url, json=None, headers=None, timeout=None):
        if url.endswith("/prospection/enrichir-lot"):
            return _Rep(200, {"prospects": [], "compte": {"deja_enrichi": 0}})
        raise AssertionError(url)

    monkeypatch.setattr(orchestration.httpx, "post", _post)
    resultat = orchestration.executer_campagnes(
        user_ids=["orch-frank", "orch-frank-seul-inactif"])
    assert resultat == {"campagnes_executees": 1}


def test_executer_campagnes_user_ids_none_decouvre_via_stockage(monkeypatch):
    monkeypatch.setattr(stockage, "lister_user_ids_actifs", lambda: [])
    resultat = orchestration.executer_campagnes()
    assert resultat == {"campagnes_executees": 0}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd briques/veille-prospection && python3 -m pytest test_orchestration.py -v`
Expected: FAIL avec `ModuleNotFoundError: No module named 'orchestration'`

- [ ] **Step 3: Write the implementation**

Créer `briques/veille-prospection/orchestration.py` :

```python
"""Orchestration des campagnes de prospection (S193). À la cadence horloge (déclarée dans
manifest.json), pour chaque personne ayant au moins une campagne active : appelle `geo`
(prospects enrichis d'une zone existante) → pousse au CRM `forge` → pousse un résumé dans
`memoire` (espace "veille", wing "veille-prospection", isolé par personne).

Dégradation : `geo` injoignable ⇒ rien à faire pour cette campagne, erreur journalisée.
`forge`/`memoire` injoignables APRÈS un succès `geo` ⇒ ne font JAMAIS perdre les prospects
(déjà persistés côté `geo`) ni planter le traitement des autres campagnes — `memoire` est
strictement best-effort (jamais dans le chemin critique)."""
from __future__ import annotations

import logging
import os

import httpx

import stockage

logger = logging.getLogger(__name__)


def _url(env: str, defaut: str) -> str:
    return os.getenv(env, defaut).rstrip("/")


def _entetes(cle_env: str, user_id: str | None = None) -> dict:
    entetes: dict = {}
    cle = os.getenv(cle_env, "")
    if cle:
        entetes["X-API-Key"] = cle
    if user_id:
        entetes["X-User-Id"] = user_id
    return entetes


def _appeler_geo(zone_id: str) -> dict:
    base = _url("GEO_URL", "http://host.docker.internal:6110")
    r = httpx.post(f"{base}/prospection/enrichir-lot", json={"zone_id": zone_id},
                   headers=_entetes("GEO_KEY"), timeout=180)
    r.raise_for_status()
    return r.json()


def _appeler_forge(prospects: list[dict]) -> dict:
    base = _url("FORGE_URL", "http://host.docker.internal:5700")
    r = httpx.post(f"{base}/crm/import-lot", json={"prospects": prospects},
                   headers=_entetes("FORGE_KEY"), timeout=60)
    r.raise_for_status()
    return r.json()


def _pousser_memoire(user_id: str, contenu: str) -> None:
    """Best-effort strict : un échec ici ne remonte JAMAIS à l'appelant."""
    base = _url("MEMOIRE_URL", "http://host.docker.internal:5600")
    try:
        r = httpx.post(f"{base}/retenir",
                       json={"contenu": contenu, "titre": "Prospection", "espace": "veille",
                             "wing": "veille-prospection"},
                       headers=_entetes("MEMOIRE_KEY", user_id), timeout=30)
        r.raise_for_status()
    except Exception as e:  # noqa: BLE001 — jamais bloquant
        logger.warning("Veille-prospection push mémoire (user=%s) : %s", user_id, e)


def _executer_campagne(campagne: dict) -> dict:
    """Exécute UNE campagne. Ne lève jamais : les erreurs sont journalisées dans le
    décompte renvoyé, jamais propagées à l'appelant (une campagne en échec ne doit pas
    empêcher le traitement des autres)."""
    try:
        rapport_geo = _appeler_geo(campagne["zone_id"])
    except httpx.HTTPError as e:
        return {"trouves": 0, "deja_connus": 0, "nouveaux_crm": 0, "erreur": str(e)}

    prospects = rapport_geo.get("prospects", [])
    deja_connus = rapport_geo.get("compte", {}).get("deja_enrichi", 0)
    nouveaux_crm, erreur = 0, None
    if prospects:
        try:
            rapport_forge = _appeler_forge(prospects)
            nouveaux_crm = rapport_forge.get("crees", 0)
        except httpx.HTTPError as e:
            erreur = str(e)
        _pousser_memoire(
            campagne["user_id"],
            f"Campagne de prospection : {len(prospects)} prospect(s) trouvé(s), "
            f"{nouveaux_crm} nouveau(x) au CRM ({deja_connus} déjà connu(s)).")

    return {"trouves": len(prospects), "deja_connus": deja_connus,
            "nouveaux_crm": nouveaux_crm, "erreur": erreur}


def executer_campagnes(user_ids: list[str] | None = None) -> dict:
    """Point d'entrée horloge : traite toutes les campagnes actives de toutes les
    personnes, ou seulement `user_ids` si fourni (motif `digest.py` de `veille-info` — la
    route HTTP réelle ne le fournit JAMAIS)."""
    cibles = user_ids if user_ids is not None else stockage.lister_user_ids_actifs()
    campagnes_executees = 0
    for user_id in cibles:
        for campagne in stockage.lister_campagnes(user_id, actives_seulement=True):
            resultat = _executer_campagne(campagne)
            stockage.inserer_execution(campagne["id"], **resultat)
            stockage.maj_derniere_execution(campagne["id"])
            campagnes_executees += 1
    return {"campagnes_executees": campagnes_executees}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd briques/veille-prospection && python3 -m pytest test_orchestration.py -v`
Expected: `8 passed`

- [ ] **Step 5: Commit**

```bash
git add briques/veille-prospection/orchestration.py briques/veille-prospection/test_orchestration.py
git commit -m "feat(veille-prospection): orchestration geo → forge → mémoire"
```

---

### Task 7: `veille-prospection` — API FastAPI (main.py)

**Files:**
- Create: `briques/veille-prospection/main.py`
- Test: `briques/veille-prospection/test_main.py`

**Interfaces:**
- Consumes :
  - `stockage.creer_campagne`, `stockage.lister_campagnes`, `stockage.supprimer_campagne` (Task 5)
  - `orchestration.executer_campagnes(user_ids: list[str] | None = None) -> dict` (Task 6) —
    la route HTTP l'appelle SANS argument.
- Produces : l'app FastAPI `main.app`, montable par uvicorn (Task 8).

- [ ] **Step 1: Write the failing test**

Créer `briques/veille-prospection/test_main.py` :

```python
"""Tests API de veille-prospection : CRUD campagnes isolé par personne, gate du
déclenchement horloge. TestClient direct — motif briques/veille-info/test_main.py.

Identifiants préfixés `main-` (jamais utilisés dans test_stockage.py/test_orchestration.py).
Les tests `/campagnes/executer` mockent `main.orchestration.executer_campagnes` : ils ne
vérifient QUE le gate d'authentification, pas le pipeline (déjà couvert par
test_orchestration.py) — sans ce mock, l'appel réel traiterait toutes les campagnes de la DB
partagée, y compris celles créées par d'autres fichiers de test."""
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


def test_sante():
    r = client.get("/sante")
    assert r.status_code == 200
    assert r.json()["statut"] == "ok"


def test_creer_lister_supprimer_campagne():
    r = client.post("/campagnes", headers={"X-User-Id": "main-alice"},
                    json={"zone_id": "zone-a"})
    assert r.status_code == 201
    campagne_id = r.json()["id"]

    r = client.get("/campagnes", headers={"X-User-Id": "main-alice"})
    assert len(r.json()) == 1

    r = client.delete(f"/campagnes/{campagne_id}", headers={"X-User-Id": "main-alice"})
    assert r.status_code == 200
    assert client.get("/campagnes", headers={"X-User-Id": "main-alice"}).json() == []


def test_campagnes_isolees_par_x_user_id():
    client.post("/campagnes", headers={"X-User-Id": "main-bob"},
               json={"zone_id": "zone-de-bob"})
    r = client.get("/campagnes", headers={"X-User-Id": "main-carol"})
    assert all(c["zone_id"] != "zone-de-bob" for c in r.json())


def test_supprimer_campagne_dune_autre_personne_echoue():
    r = client.post("/campagnes", headers={"X-User-Id": "main-dave"},
                    json={"zone_id": "zone-privee"})
    campagne_id = r.json()["id"]
    r = client.delete(f"/campagnes/{campagne_id}", headers={"X-User-Id": "main-mallory"})
    assert r.status_code == 404


def test_campagnes_executer_ouvert_si_pas_de_cle_configuree(monkeypatch):
    monkeypatch.setattr(main.orchestration, "executer_campagnes",
                        lambda: {"campagnes_executees": 0})
    r = client.post("/campagnes/executer")
    assert r.status_code == 200
    assert "campagnes_executees" in r.json()


def test_campagnes_executer_gate_si_cle_configuree(monkeypatch):
    monkeypatch.setattr(main.orchestration, "executer_campagnes",
                        lambda: {"campagnes_executees": 0})
    monkeypatch.setenv("VEILLE_PROSPECTION_KEY", "secret-horloge")
    r = client.post("/campagnes/executer")
    assert r.status_code == 401
    r = client.post("/campagnes/executer",
                    headers={"Authorization": "Bearer secret-horloge"})
    assert r.status_code == 200
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd briques/veille-prospection && python3 -m pytest test_main.py -v`
Expected: FAIL avec `ModuleNotFoundError: No module named 'main'`

- [ ] **Step 3: Write the implementation**

Créer `briques/veille-prospection/main.py` :

```python
"""Brique « veille-prospection » — orchestration de campagnes de prospection géo-scrapée,
v0.1.0. Produit autonome (port 6140), isolé par personne (X-User-Id, motif mail S185/
veille-info). Référence des zones `geo` EXISTANTES (`zone_id`) — ne duplique jamais leur
définition. Cadence horloge quotidienne (manifest.json) : voir orchestration.py.
"""
from __future__ import annotations

import hashlib
import os
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import orchestration
import stockage

app = FastAPI(title="Veille-prospection — campagnes de prospection géo-scrapée",
             version="0.1.0")

_cors = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()] or ["*"]
app.add_middleware(CORSMiddleware, allow_origins=_cors, allow_methods=["*"], allow_headers=["*"])

API_KEYS = {k.strip() for k in os.getenv("API_KEYS", "").split(",") if k.strip()}


def tenant_actuel(x_api_key: Optional[str] = Header(None),
                  authorization: Optional[str] = Header(None),
                  x_user_id: Optional[str] = Header(None)) -> str:
    """Motif exact briques/veille-info/main.py (S185/veille-info) : la clé du Cœur
    (VEILLE_PROSPECTION_KEY) fait EMPRUNTER l'identité X-User-Id ; toute autre clé retombe
    sur une empreinte (tenant externe). Fail-closed si API_KEYS est défini."""
    presentee = x_api_key or (authorization or "").removeprefix("Bearer ").strip() or None
    if API_KEYS:
        if presentee not in API_KEYS:
            raise HTTPException(401, "Clé API manquante ou invalide (header X-API-Key).")
    elif not presentee:
        return "public"
    cle_coeur = os.environ.get("VEILLE_PROSPECTION_KEY")
    if cle_coeur and presentee == cle_coeur:
        return f"perso:{x_user_id or 'perso'}"
    return hashlib.sha256((presentee or "public").encode()).hexdigest()[:16]


def verifier_cle_horloge(authorization: Optional[str] = Header(None)) -> None:
    """Gate de /campagnes/executer : jeton partagé VEILLE_PROSPECTION_KEY — cette route
    traite TOUTES les personnes en un seul appel (motif horloge), pas scopée à un tenant."""
    attendu = os.environ.get("VEILLE_PROSPECTION_KEY")
    if not attendu:
        return
    presentee = (authorization or "").removeprefix("Bearer ").strip()
    if presentee != attendu:
        raise HTTPException(401, "Jeton horloge invalide (header Authorization: Bearer ...).")


@app.get("/sante", tags=["système"])
def sante():
    return {"statut": "ok", "version": "0.1.0"}


class CreerCampagne(BaseModel):
    zone_id: str = Field(min_length=1)


@app.get("/campagnes", tags=["campagnes"])
def lister_campagnes_route(tenant: str = Depends(tenant_actuel)):
    return stockage.lister_campagnes(tenant)


@app.post("/campagnes", tags=["campagnes"], status_code=201)
def creer_campagne_route(body: CreerCampagne, tenant: str = Depends(tenant_actuel)):
    return stockage.creer_campagne(tenant, body.zone_id)


@app.delete("/campagnes/{campagne_id}", tags=["campagnes"])
def supprimer_campagne_route(campagne_id: int, tenant: str = Depends(tenant_actuel)):
    ok = stockage.supprimer_campagne(tenant, campagne_id)
    if not ok:
        raise HTTPException(404, "Campagne introuvable.")
    return {"ok": True}


@app.post("/campagnes/executer", tags=["campagnes"])
def executer_campagnes_route(_: None = Depends(verifier_cle_horloge)):
    return orchestration.executer_campagnes()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd briques/veille-prospection && python3 -m pytest test_main.py -v`
Expected: `6 passed`

Puis lancer toute la suite de la brique :

Run: `cd briques/veille-prospection && python3 -m pytest -v`
Expected: `26 passed` (6 test_stockage + 8 test_orchestration + 6 test_main + les tests du
Step 2 précédemment en échec), aucune régression.

- [ ] **Step 5: Commit**

```bash
git add briques/veille-prospection/main.py briques/veille-prospection/test_main.py
git commit -m "feat(veille-prospection): API FastAPI (campagnes, déclenchement horloge)"
```

---

### Task 8: `veille-prospection` — scaffolding + isolation fleet-wide

**Files:**
- Create: `briques/veille-prospection/requirements.txt`
- Create: `briques/veille-prospection/Dockerfile`
- Create: `briques/veille-prospection/docker-compose.yml`
- Create: `briques/veille-prospection/manifest.json`
- Modify: `.env.example` (nouvelle section, après la section « geo »)
- Modify: `core/outils_communs.py:51` (`BRIQUES_PAR_PERSONNE`)
- Modify: `core/test_contexte_tenant.py:149-164` (`test_entetes_brique_par_personne_forwarde_identite`)

**Interfaces:**
- Consumes : `main:app` (Task 7, référencé par uvicorn).
- Produces : brique découvrable par le Cœur (scan automatique `briques/*/manifest.json`) et
  déployable par `docker compose` ; isolation `X-User-Id` couverte par
  `core/outils_communs.py::_entetes_brique`.

- [ ] **Step 1: Write the failing test**

Modifier `core/test_contexte_tenant.py`, dans `test_entetes_brique_par_personne_forwarde_identite`
(lignes 149-164), ajouter une ligne après `veille-info` :

```python
    assert outils_communs._entetes_brique("veille-info")["X-User-Id"] == "claire"
    assert outils_communs._entetes_brique("veille-prospection")["X-User-Id"] == "claire"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd core && python3 -m pytest test_contexte_tenant.py -v -k forwarde_identite`
Expected: FAIL (`assert 'X-User-Id' in {}` — `veille-prospection` pas encore dans
`BRIQUES_PAR_PERSONNE`).

- [ ] **Step 3: Write the implementation**

Dans `core/outils_communs.py:51`, remplacer :

```python
BRIQUES_PAR_PERSONNE = {"agenda", "ecoute", "mail", "memoire", "studio", "veille-info"}
```

par :

```python
BRIQUES_PAR_PERSONNE = {"agenda", "ecoute", "mail", "memoire", "studio", "veille-info",
                        "veille-prospection"}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd core && python3 -m pytest test_contexte_tenant.py -v`
Expected: tous les tests passent, y compris le nouveau.

- [ ] **Step 5: Créer les fichiers de scaffolding**

Créer `briques/veille-prospection/requirements.txt` :

```
# Brique veille-prospection — orchestration de campagnes de prospection géo-scrapée.
fastapi==0.115.6
uvicorn[standard]==0.34.0
httpx==0.28.1
```

Créer `briques/veille-prospection/Dockerfile` :

```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "6140"]
```

Créer `briques/veille-prospection/docker-compose.yml` :

```yaml
services:
  veille-prospection:
    build: .
    container_name: workplace_veille_prospection
    image: workplace/veille-prospection:0.1.0   # tag épinglé (pas de :latest flottant)
    env_file:
      - path: ../../.env
        required: false
    ports:
      - "6140:6140"
    environment:
      - PORT=6140
      - VEILLE_PROSPECTION_DB=/data/veille_prospection.db
      - CORS_ORIGINS=${CORS_ORIGINS:-*}
      # API_KEYS, VEILLE_PROSPECTION_KEY, GEO_KEY/FORGE_KEY/MEMOIRE_KEY : ABSENTS du
      # `environment` exprès — viennent du .env racine via env_file (piège « env shadow » :
      # ne PAS les redéclarer en `=${VAR:-}`, cf. fix-env-shadow-composes).
    volumes:
      - veille_prospection_data:/data
    extra_hosts:
      - "host.docker.internal:host-gateway"
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:6140/sante')"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 15s

volumes:
  veille_prospection_data:
```

(`extra_hosts` présent dès la création — pas d'oubli à corriger plus tard, cf. le piège déjà
rencontré 16 fois sur d'autres briques et documenté dans le projet.)

Créer `briques/veille-prospection/manifest.json` :

```json
{
  "nom": "veille-prospection",
  "famille": "veille",
  "version": "0.1.0",
  "description": "Prospection géo-scrapée : campagnes automatisées qui référencent une zone geo existante, enrichissent (site, coordonnées, dirigeants, effectifs, réseaux sociaux) et poussent au CRM Forge, avec un résumé mémorisé par personne. Isolé par personne (X-User-Id, motif mail S185/veille-info).",
  "role": "veille-prospection",
  "couche": "backend",
  "statut": "a_tester",
  "chemin_source": "~/Desktop/Workplace/briques/veille-prospection",
  "port": 6140,
  "url_sante": "http://host.docker.internal:6140/sante",
  "depends_on": [],
  "offre": [
    "campagnes_prospection_par_personne",
    "orchestration_geo_forge_memoire",
    "isolation_par_personne"
  ],
  "taches": [
    {
      "nom": "campagnes-quotidien",
      "description": "Exécute toutes les campagnes actives : enrichissement geo, push CRM forge, résumé mémoire.",
      "methode": "POST",
      "chemin": "/campagnes/executer",
      "cadence_heures": 24,
      "idempotent": true,
      "entete_token_env": "VEILLE_PROSPECTION_KEY",
      "tolere_echec": true
    }
  ],
  "capacites": [
    {
      "nom": "veille_prospection_campagnes_lister",
      "description": "Liste les campagnes de prospection de la personne connectée (zone ciblée, dernière exécution). Sert « quelles zones je prospecte », « où en est ma veille de prospects ». Lecture seule.",
      "methode": "GET",
      "chemin": "/campagnes",
      "action": false,
      "niveau": 0,
      "socle": false
    },
    {
      "nom": "veille_prospection_campagne_creer",
      "description": "Active une campagne de prospection automatisée sur une zone geo déjà créée (voir geo_zones_lister). Sert « prospecte cette zone tous les jours », « active la veille prospection sur [zone] ».",
      "methode": "POST",
      "chemin": "/campagnes",
      "params": {
        "zone_id": {"type": "string", "description": "Identifiant de la zone geo à prospecter (voir la liste des zones geo).", "requis": true}
      },
      "action": true,
      "niveau": 1,
      "socle": false
    },
    {
      "nom": "veille_prospection_campagne_supprimer",
      "description": "Désactive une campagne de prospection (arrête les exécutions futures, ne supprime pas les prospects déjà trouvés).",
      "methode": "DELETE",
      "chemin": "/campagnes/{campagne_id}",
      "params": {
        "campagne_id": {"type": "integer", "description": "Identifiant de la campagne à désactiver.", "requis": true}
      },
      "action": true,
      "niveau": 1,
      "socle": false
    }
  ]
}
```

Ajouter à `.env.example`, juste après la section « geo » (après la ligne
`GEO_NOTIF_UTILISATEUR=perso`, avant la section « atelier-veille ») :

```
# ── Brique « veille-prospection » (campagnes de prospection géo-scrapée, port 6140) ──
# Orchestre à la cadence horloge : enrichissement geo d'une zone existante (dirigeants,
# effectifs, réseaux sociaux inclus) → push CRM forge → résumé mémorisé par personne
# (espace "veille"). Réutilise GEO_KEY/FORGE_KEY/MEMOIRE_KEY déjà définis plus haut —
# aucune clé propre requise pour ces appels sortants (mono-tenant aujourd'hui : ces clés
# sont vides fleet-wide, mode ouvert). Clé que le Cœur présente (X-API-Key) à
# VEILLE-PROSPECTION elle-même : VIDE en mono-utilisateur. Définie : le Cœur emprunte
# l'identité de la personne connectée (X-User-Id) — chaque membre du foyer a SES campagnes,
# isolées des autres (motif mail S185/veille-info).
VEILLE_PROSPECTION_KEY=
```

- [ ] **Step 6: Verify**

Run: `python3 -c "
import json
d = json.load(open('briques/veille-prospection/manifest.json'))
assert d['famille'] == 'veille'
assert d['port'] == 6140
assert d['taches'][0]['chemin'] == '/campagnes/executer'
assert d['taches'][0]['cadence_heures'] == 24
print('manifest OK')
"`
Expected: `manifest OK`

Run: `docker compose -f briques/veille-prospection/docker-compose.yml config --quiet && echo "compose OK"`
Expected: `compose OK` (si `docker` indisponible dans l'environnement d'exécution, noter le
point pour vérification avant déploiement HP — régime « preuve Docker différé » du projet,
ne pas bloquer la tâche).

Run: `cd briques/veille-prospection && python3 -m pytest -v`
Expected: `26 passed` — aucune régression (cette étape n'a touché aucun fichier `.py` de la
brique).

Run: `cd core && python3 -m pytest -v`
Expected: aucune régression sur la suite `core` complète (`make test-core` si disponible).

- [ ] **Step 7: Commit**

```bash
git add briques/veille-prospection/requirements.txt briques/veille-prospection/Dockerfile \
       briques/veille-prospection/docker-compose.yml briques/veille-prospection/manifest.json \
       .env.example core/outils_communs.py core/test_contexte_tenant.py
git commit -m "feat(veille-prospection): manifest, Dockerfile, docker-compose, isolation fleet-wide"
```

---

### Task 9: `veille-info` — retrofit du push mémoire

**Files:**
- Modify: `briques/veille-info/digest.py` (`_traiter_utilisateur`)
- Test: `briques/veille-info/test_digest.py` (ajout de tests)

**Interfaces:**
- Consumes : rien de nouveau côté `stockage`/`rss`/`lib.llm_client` (inchangés).
- Produces : aucune nouvelle fonction publique — effet de bord ajouté à
  `_traiter_utilisateur` (push best-effort vers `memoire` juste après la création réussie du
  digest, dans le MÊME filet que le reste — motif de la leçon S189/audio : tout ce qui suit
  un succès reste dans le même `try/except`).

- [ ] **Step 1: Write the failing tests**

Ajouter à `briques/veille-info/test_digest.py`, à la fin :

```python


def test_digest_pousse_un_resume_dans_memoire(monkeypatch):
    stockage.creer_source("digest-frank", "Flux F", "https://f.example/rss")
    monkeypatch.setattr(digest.rss, "fetcher", lambda url: "<flux/>")
    monkeypatch.setattr(digest.rss, "parser_items", lambda texte: [
        {"titre": "Article", "url": "https://f.example/1", "published_at": ""},
    ])
    monkeypatch.setattr(digest, "llm_complete", lambda prompt, system="": "Résumé du jour.")
    captes = {}

    def _post(url, json=None, headers=None, timeout=None):
        assert url.endswith("/retenir")
        captes["json"] = json
        captes["headers"] = headers
        class _Rep:
            status_code = 200
            def raise_for_status(self):
                pass
        return _Rep()

    monkeypatch.setattr(digest.httpx, "post", _post)
    resultat = digest.executer_digest_quotidien(user_ids=["digest-frank"])
    assert resultat["digests_crees"] == 1
    assert captes["json"]["espace"] == "veille"
    assert captes["json"]["wing"] == "veille-info"
    assert captes["json"]["contenu"] == "Résumé du jour."
    assert captes["headers"]["X-User-Id"] == "digest-frank"


def test_digest_memoire_injoignable_najamais_bloquant(monkeypatch):
    stockage.creer_source("digest-grace", "Flux G", "https://g.example/rss")
    monkeypatch.setattr(digest.rss, "fetcher", lambda url: "<flux/>")
    monkeypatch.setattr(digest.rss, "parser_items", lambda texte: [
        {"titre": "Article", "url": "https://g.example/1", "published_at": ""},
    ])
    monkeypatch.setattr(digest, "llm_complete", lambda prompt, system="": "Résumé.")

    def _post(url, json=None, headers=None, timeout=None):
        raise ConnectionError("memoire down")

    monkeypatch.setattr(digest.httpx, "post", _post)
    resultat = digest.executer_digest_quotidien(user_ids=["digest-grace"])
    assert resultat["digests_crees"] == 1   # le digest texte n'est PAS affecté
    assert len(stockage.lister_digests("digest-grace")) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd briques/veille-info && python3 -m pytest test_digest.py -v -k memoire`
Expected: FAIL — `test_digest_pousse_un_resume_dans_memoire` échoue car aucun appel
`httpx.post` n'est fait par le code actuel (`captes` reste vide, `KeyError: 'json'`).
`test_digest_memoire_injoignable_najamais_bloquant` PASSE déjà accidentellement (rien
n'appelle `httpx.post` donc rien ne peut planter) — attendu, sera un test de non-régression
une fois l'implémentation faite.

- [ ] **Step 3: Write the implementation**

Dans `briques/veille-info/digest.py`, ajouter l'import `httpx` et `os` en tête (après les
imports existants `import logging`) :

```python
import logging
import os

import httpx

import rss
import stockage
from lib.llm_client import llm_complete
```

Ajouter une fonction, après `_construire_prompt` :

```python
def _pousser_memoire(user_id: str, resume: str, date: str) -> None:
    """Best-effort strict (S193) : un échec ici ne doit JAMAIS faire perdre le digest texte
    déjà créé, ni empêcher le traitement des autres personnes — même filet que l'audio
    (leçon S189 : tout ce qui suit un succès reste dans le même try/except)."""
    base = os.getenv("MEMOIRE_URL", "http://host.docker.internal:5600").rstrip("/")
    entetes = {"X-User-Id": user_id}
    cle = os.getenv("MEMOIRE_KEY", "")
    if cle:
        entetes["X-API-Key"] = cle
    try:
        r = httpx.post(f"{base}/retenir",
                       json={"contenu": resume, "titre": f"Veille du {date}",
                             "espace": "veille", "wing": "veille-info"},
                       headers=entetes, timeout=30)
        r.raise_for_status()
    except Exception as e:  # noqa: BLE001 — jamais bloquant
        logger.warning("Veille-info push mémoire (user=%s) : %s", user_id, e)
```

Puis, dans `_traiter_utilisateur`, remplacer la dernière ligne (`stockage.inserer_digest(user_id, resume, len(articles)); return True`) :

```python
    d = stockage.inserer_digest(user_id, resume, len(articles))
    _pousser_memoire(user_id, resume, d["date"])
    return True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd briques/veille-info && python3 -m pytest test_digest.py -v`
Expected: tous les tests passent (existants + audio + les 2 nouveaux memoire).

Run: `cd briques/veille-info && python3 -m pytest -v`
Expected: aucune régression sur toute la suite de la brique.

- [ ] **Step 5: Commit**

```bash
git add briques/veille-info/digest.py briques/veille-info/test_digest.py
git commit -m "feat(veille-info): push best-effort du digest vers mémoire (S193)"
```

---

## Vérification finale (après la Task 9)

- [ ] Run: `cd briques/geo && python3 -m pytest -v` — vert.
- [ ] Run: `cd briques/memoire && python3 -m pytest -v` — vert.
- [ ] Run: `cd briques/veille-info && python3 -m pytest -v` — vert.
- [ ] Run: `cd briques/veille-prospection && python3 -m pytest -v` — vert.
- [ ] Run: `cd core && python3 -m pytest -v` (ou `make test-core` si disponible à la racine) — vert.
- [ ] Vérifier que `docs/superpowers/specs/2026-07-21-s193-veille-prospection-design.md`
      reste cohérent avec ce qui a été implémenté (aucune divergence non documentée).
