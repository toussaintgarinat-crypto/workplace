# Comparatif de modèles d'image — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permettre de choisir/comparer plusieurs modèles d'image (via la Gateway/OpenRouter déjà configurée) directement dans l'Atelier Images & Vidéo, avec une liste de modèles tenue à jour dynamiquement.

**Architecture:** `briques/images` (moteur) apprend à lister en direct les modèles image d'OpenRouter et à accepter un `modele` en override pour le fournisseur `gateway` ; `briques/atelier-images-video` relaie ces deux capacités (même motif de proxy que l'existant) ; `front.html` gagne un onglet **Comparatif** qui orchestre côté client N appels parallèles à l'endpoint `/images/generer` existant (un par modèle coché).

**Tech Stack:** Python 3.12 / FastAPI / httpx (backend), JS vanilla + Fetch API (front), pytest + TestClient (tests). Aucune nouvelle dépendance.

## Global Constraints

- Commentaires et libellés UI en français, cohérents avec le reste du dépôt.
- Aucune nouvelle dépendance Python ou JS.
- Suivre les conventions déjà en place dans chaque fichier touché (style de mock HTTP dans les tests, `esc()`/`jsonAttr()` côté front, motif de proxy `_relayer` côté atelier).
- Le fournisseur `gateway` uniquement gagne la capacité de `modele` en override — ne pas généraliser aux autres fournisseurs (nanobanana/fal/replicate/openai/pruna), qui ne sont de toute façon pas configurés en prod (YAGNI, cf. spec).
- Jamais de liste de modèles figée en dur en repli : si OpenRouter est injoignable et qu'aucun cache n'existe, l'erreur est propagée telle quelle.

---

### Task 1: `fournisseurs.py` — le fournisseur `gateway` accepte un modèle en override

**Files:**
- Modify: `briques/images/fournisseurs.py:130-153` (classe `Gateway`)
- Modify: `briques/images/fournisseurs.py:110-127` (classe `_HTTP`, base commune)
- Modify: `briques/images/fournisseurs.py:156-243` (signatures `_requete` de NanoBanana, Fal, Replicate, OpenAI, Pruna — ajout du paramètre, non utilisé)
- Test: `briques/images/test_fournisseurs.py`

**Interfaces:**
- Consomme : rien de nouveau (fichier existant).
- Produit : `_HTTP.generer(self, prompt, negatif, largeur, hauteur, seed, modele=None)` et
  `<Fournisseur>._requete(self, prompt, negatif, largeur, hauteur, seed, modele=None)` — la
  Task 3 (moteur.py) appellera `fournisseurs.REGISTRE[nom].generer(prompt, negatif, largeur, hauteur, seed, modele)` **positionnellement** (pas en kwarg), pour rester compatible avec les mocks existants de `test_moteur.py` qui déclarent `async def generer(self, *a)`.

- [ ] **Step 1: Write the failing test**

Ajouter à la fin de `briques/images/test_fournisseurs.py` (après `test_gateway_modele_surchargeable`, qui teste déjà la surcharge par variable d'env — celle-ci teste la surcharge PAR REQUÊTE, prioritaire sur l'env) :

```python
def test_gateway_modele_override_par_requete_prioritaire_sur_lenv(monkeypatch):
    monkeypatch.setenv("GATEWAY_KEY", "k")
    monkeypatch.setenv("IMAGE_GATEWAY_MODEL", "google/gemini-2.5-flash-image")
    _, _, body = F.Gateway()._requete("x", "", 1024, 1024, None, "openai/gpt-5-image")
    assert body["model"] == "openai/gpt-5-image"


def test_gateway_sans_override_retombe_sur_lenv(monkeypatch):
    monkeypatch.setenv("GATEWAY_KEY", "k")
    monkeypatch.setenv("IMAGE_GATEWAY_MODEL", "google/gemini-2.5-flash-image")
    _, _, body = F.Gateway()._requete("x", "", 1024, 1024, None)
    assert body["model"] == "google/gemini-2.5-flash-image"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd briques/images && python3 -m pytest test_fournisseurs.py::test_gateway_modele_override_par_requete_prioritaire_sur_lenv -v`
Expected: FAIL avec `TypeError: _requete() takes from 6 to 6 positional arguments but 7 were given` (la signature actuelle ne connaît pas ce 6e argument).

- [ ] **Step 3: Write minimal implementation**

Dans `briques/images/fournisseurs.py`, remplacer la classe `_HTTP` (lignes 110-127) :

```python
class _HTTP:
    """Base commune : un POST JSON suffit. On ne spécialise que `_requete` et `disponible`."""
    nom = ""
    timeout = 120

    def disponible(self) -> bool:
        raise NotImplementedError

    def _requete(self, prompt, negatif, largeur, hauteur, seed, modele=None):
        """→ (url, headers, json_body). À spécialiser par fournisseur.

        `modele` (optionnel) : override ponctuel, prioritaire sur la variable d'env du
        fournisseur — SEULE la classe Gateway l'utilise réellement (comparatif de
        modèles OpenRouter) ; les autres l'acceptent pour une signature uniforme mais
        l'ignorent (YAGNI : ils ne sont pas configurés en prod)."""
        raise NotImplementedError

    async def generer(self, prompt, negatif, largeur, hauteur, seed, modele=None) -> Optional[bytes]:
        url, headers, body = self._requete(prompt, negatif, largeur, hauteur, seed, modele)
        async with httpx.AsyncClient(timeout=self.timeout) as c:
            r = await c.post(url, headers=headers, json=body)
            r.raise_for_status()
            return await _resoudre(c, _cherche_image(r.json()))
```

Remplacer la classe `Gateway` (lignes 130-153) :

```python
class Gateway(_HTTP):
    """Passe par la GATEWAY Workplace (LiteLLM → OpenRouter) — déjà utilisée par l'assistant
    pour le texte. AUCUNE clé d'image à configurer : on réutilise la clé OpenRouter déjà
    posée dans l'env de la Gateway. On demande l'image via /chat/completions (modalité image)
    avec un modèle d'image OpenRouter — Nano Banana par défaut, paramétrable par env OU par
    requête (le `modele` explicite gagne toujours sur `IMAGE_GATEWAY_MODEL`, cf. comparatif
    de modèles dans l'Atelier Images & Vidéo).

    Réponse OpenRouter : l'image arrive dans choices[].message.images[].image_url.url
    (data URI base64), gérée par `_cherche_image`."""
    nom = "gateway"

    def _url(self):
        return os.getenv("GATEWAY_URL", "http://host.docker.internal:4001").rstrip("/")

    def disponible(self):
        # la clé OpenRouter vit côté Gateway ; ici il suffit de savoir joindre la Gateway.
        return bool(os.getenv("GATEWAY_KEY"))

    def _requete(self, prompt, negatif, largeur, hauteur, seed, modele=None):
        modele = modele or os.getenv("IMAGE_GATEWAY_MODEL", "google/gemini-2.5-flash-image")
        texte = prompt if not negatif else f"{prompt}\n\nÀ éviter : {negatif}"
        body = {"model": modele, "modalities": ["image", "text"],
                "messages": [{"role": "user", "content": texte}]}
        return (f"{self._url()}/v1/chat/completions",
                {"Authorization": f"Bearer {os.getenv('GATEWAY_KEY')}"}, body)
```

Puis ajouter `, modele=None` au paramètre de `_requete` des 5 autres classes (signature seulement,
corps inchangé) :

- `NanoBanana._requete(self, prompt, negatif, largeur, hauteur, seed, modele=None):`
- `Fal._requete(self, prompt, negatif, largeur, hauteur, seed, modele=None):`
- `Replicate._requete(self, prompt, negatif, largeur, hauteur, seed, modele=None):`
- `OpenAI._requete(self, prompt, negatif, largeur, hauteur, seed, modele=None):`
- `Pruna._requete(self, prompt, negatif, largeur, hauteur, seed, modele=None):`

Et à `ComfyUI.generer` (classe séparée, ne dérive pas de `_HTTP`) :

```python
    async def generer(self, prompt, negatif, largeur, hauteur, seed, modele=None) -> Optional[bytes]:
```

(corps de la méthode inchangé — `modele` accepté mais ignoré, ComfyUI n'a pas cette notion.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd briques/images && python3 -m pytest test_fournisseurs.py -v`
Expected: tous PASS, y compris les 2 nouveaux tests et tous les tests existants (aucune régression : les appels existants `_requete(prompt, negatif, largeur, hauteur, seed)` à 5 arguments restent valides grâce au défaut `modele=None`).

- [ ] **Step 5: Commit**

```bash
git add briques/images/fournisseurs.py briques/images/test_fournisseurs.py
git commit -m "feat(images): le fournisseur gateway accepte un modèle en override par requête"
```

---

### Task 2: `fournisseurs.py` — liste dynamique des modèles image OpenRouter (avec cache)

**Files:**
- Modify: `briques/images/fournisseurs.py` (ajout en fin de fichier, après le registre)
- Test: `briques/images/test_fournisseurs.py`

**Interfaces:**
- Produit : `async def modeles_image_openrouter() -> list[dict]` — chaque dict a la forme
  `{"id": str, "prix_image": str | None}`, trié par `id`. Lève l'exception d'origine si
  aucun cache n'est disponible et qu'OpenRouter est injoignable. Consommé par la Task 4
  (`main.py` de la brique images).

- [ ] **Step 1: Write the failing test**

Ajouter en tête de `briques/images/test_fournisseurs.py` l'import `pytest` (absent
aujourd'hui) et `asyncio` reste déjà importé :

```python
import pytest
```

Puis, à la fin du fichier :

```python
# ── Liste dynamique des modèles image OpenRouter (comparatif) ──────────────
def _client_openrouter(payload):
    class _Reponse:
        def raise_for_status(self):
            pass
        def json(self):
            return payload

    class _Client:
        def __init__(self, *a, **k):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False
        async def get(self, url):
            _Client.appels += 1
            return _Reponse()
    _Client.appels = 0
    return _Client


def test_modeles_image_filtre_output_modalities_et_exclut_auto(monkeypatch):
    F._cache = {"ts": 0.0, "modeles": []}
    payload = {"data": [
        {"id": "google/gemini-2.5-flash-image",
         "architecture": {"output_modalities": ["image"]}, "pricing": {"image": "0.0000003"}},
        {"id": "openrouter/auto",
         "architecture": {"output_modalities": ["image"]}, "pricing": {}},
        {"id": "google/gemini-3-pro-image",
         "architecture": {"output_modalities": ["image"]}, "pricing": {"image": "0.000002"}},
        {"id": "text-only/model",
         "architecture": {"output_modalities": ["text"]}, "pricing": {}},
    ]}
    monkeypatch.setattr(F.httpx, "AsyncClient", _client_openrouter(payload))
    modeles = asyncio.run(F.modeles_image_openrouter())
    assert [m["id"] for m in modeles] == [
        "google/gemini-2.5-flash-image", "google/gemini-3-pro-image"]
    assert modeles[0]["prix_image"] == "0.0000003"


def test_modeles_image_cache_evite_le_second_appel_http(monkeypatch):
    F._cache = {"ts": 0.0, "modeles": []}
    payload = {"data": [{"id": "a/b", "architecture": {"output_modalities": ["image"]},
                         "pricing": {}}]}
    Client = _client_openrouter(payload)
    monkeypatch.setattr(F.httpx, "AsyncClient", Client)
    asyncio.run(F.modeles_image_openrouter())
    asyncio.run(F.modeles_image_openrouter())
    assert Client.appels == 1


def test_modeles_image_cache_perime_relance_un_appel(monkeypatch):
    F._cache = {"ts": 0.0, "modeles": [{"id": "vieux/modele", "prix_image": None}]}
    payload = {"data": [{"id": "nouveau/modele",
                         "architecture": {"output_modalities": ["image"]}, "pricing": {}}]}
    Client = _client_openrouter(payload)
    monkeypatch.setattr(F.httpx, "AsyncClient", Client)
    modeles = asyncio.run(F.modeles_image_openrouter())
    assert Client.appels == 1
    assert [m["id"] for m in modeles] == ["nouveau/modele"]


def test_modeles_image_sert_le_cache_perime_si_openrouter_tombe(monkeypatch):
    F._cache = {"ts": 0.0, "modeles": [{"id": "cache/modele", "prix_image": None}]}

    class _Boom:
        def __init__(self, *a, **k):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False
        async def get(self, url):
            raise RuntimeError("timeout")

    monkeypatch.setattr(F.httpx, "AsyncClient", _Boom)
    modeles = asyncio.run(F.modeles_image_openrouter())
    assert modeles == [{"id": "cache/modele", "prix_image": None}]


def test_modeles_image_leve_si_cache_vide_et_openrouter_tombe(monkeypatch):
    F._cache = {"ts": 0.0, "modeles": []}

    class _Boom:
        def __init__(self, *a, **k):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False
        async def get(self, url):
            raise RuntimeError("timeout")

    monkeypatch.setattr(F.httpx, "AsyncClient", _Boom)
    with pytest.raises(RuntimeError):
        asyncio.run(F.modeles_image_openrouter())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd briques/images && python3 -m pytest test_fournisseurs.py -k modeles_image -v`
Expected: FAIL avec `AttributeError: module 'fournisseurs' has no attribute '_cache'` (ou
`modeles_image_openrouter`) — rien n'existe encore.

- [ ] **Step 3: Write minimal implementation**

Ajouter en tête de `briques/images/fournisseurs.py`, dans le bloc d'imports (après `import httpx`) :

```python
import time
```

Puis, tout en bas du fichier, après la définition de `disponibles()` :

```python
# ── Modèles image OpenRouter (comparatif, Atelier Images & Vidéo) ──────────
# Endpoint PUBLIC (pas de clé requise pour lister). Cache mémoire 1h : évite de re-frapper
# OpenRouter à chaque ouverture de l'onglet Comparatif. Jamais de liste inventée : si
# l'appel échoue et qu'un cache existe encore (même périmé), on le sert plutôt que de
# casser l'UI ; si le cache est vide, l'erreur est propagée telle quelle.
_CACHE_TTL_S = 3600
_cache: dict = {"ts": 0.0, "modeles": []}


async def modeles_image_openrouter() -> list:
    """Modèles OpenRouter capables de générer une image (architecture.output_modalities
    contient "image"), routeurs auto (openrouter/auto*) exclus — ils choisissent eux-mêmes
    le modèle sous le capot, ce qui fausserait un comparatif."""
    maintenant = time.time()
    if _cache["modeles"] and maintenant - _cache["ts"] < _CACHE_TTL_S:
        return _cache["modeles"]
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get("https://openrouter.ai/api/v1/models")
            r.raise_for_status()
            data = r.json()
    except Exception:
        if _cache["modeles"]:
            return _cache["modeles"]
        raise
    modeles = sorted(
        (
            {"id": m["id"], "prix_image": (m.get("pricing") or {}).get("image")}
            for m in data.get("data", [])
            if "image" in ((m.get("architecture") or {}).get("output_modalities") or [])
            and not m["id"].startswith("openrouter/auto")
        ),
        key=lambda m: m["id"],
    )
    _cache["modeles"], _cache["ts"] = modeles, maintenant
    return modeles
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd briques/images && python3 -m pytest test_fournisseurs.py -v`
Expected: tous PASS (le fichier complet, pas seulement les nouveaux tests).

- [ ] **Step 5: Commit**

```bash
git add briques/images/fournisseurs.py briques/images/test_fournisseurs.py
git commit -m "feat(images): liste dynamique des modèles image OpenRouter, cache 1h"
```

---

### Task 3: `moteur.py` — transmettre et restituer le modèle utilisé

**Files:**
- Modify: `briques/images/moteur.py:76-111` (fonction `generer`)
- Test: `briques/images/test_moteur.py`

**Interfaces:**
- Consomme : `fournisseurs.REGISTRE[nom].generer(prompt, negatif, largeur, hauteur, seed, modele)` (Task 1).
- Produit : `moteur.generer(prompt, negatif="", largeur=1024, hauteur=1024, seed=None, fournisseur=None, modele=None) -> dict`, la réponse succès inclut désormais `"modele"` (la valeur passée si le fournisseur retenu est `gateway`, sinon `None`). Consommé par la Task 4.

- [ ] **Step 1: Write the failing test**

Ajouter à la fin de `briques/images/test_moteur.py` :

```python
def test_modele_restitue_quand_fournisseur_gateway(monkeypatch):
    class OK:
        async def generer(self, *a):
            return PNG
    monkeypatch.setattr(fournisseurs, "REGISTRE", {"gateway": OK()})
    res = asyncio.run(moteur.generer("x", fournisseur="gateway", modele="openai/gpt-5-image"))
    assert res["modele"] == "openai/gpt-5-image"


def test_modele_absent_hors_gateway(monkeypatch):
    class OK:
        async def generer(self, *a):
            return PNG
    monkeypatch.setattr(fournisseurs, "REGISTRE", {"fal": OK()})
    res = asyncio.run(moteur.generer("x", fournisseur="fal", modele="ignore-moi"))
    assert res["modele"] is None


def test_modele_absent_par_defaut():
    res = asyncio.run(moteur.generer("x"))  # aucun fournisseur configuré → placeholder
    assert "modele" not in res or res.get("modele") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd briques/images && python3 -m pytest test_moteur.py -k modele -v`
Expected: FAIL avec `KeyError: 'modele'` sur les deux premiers tests (le champ n'existe pas
encore dans la réponse).

- [ ] **Step 3: Write minimal implementation**

Dans `briques/images/moteur.py`, remplacer la fonction `generer` (lignes 76-111) :

```python
async def generer(prompt: str, negatif: str = "", largeur: int = 1024, hauteur: int = 1024,
                  seed=None, fournisseur: Optional[str] = None,
                  modele: Optional[str] = None) -> dict:
    """Rend {url, backend, place_holder, modele}. `url` est servie par CETTE brique
    (/fichiers/…).

    `fournisseur` (optionnel) force un moteur précis ; sinon on suit l'ordre de préférence.
    `modele` (optionnel) : override ponctuel, honoré SEULEMENT par le fournisseur `gateway`
    (comparatif de modèles OpenRouter, cf. Atelier Images & Vidéo) — la réponse le restitue
    tel quel dans ce cas, `None` sinon (on ne sait pas quel modèle un autre fournisseur a
    lu depuis SA propre variable d'env sans le lui redemander explicitement).
    """
    largeur, hauteur = int(largeur or 1024), int(hauteur or 1024)

    if fournisseur:                                   # forçage explicite d'un moteur
        f = fournisseurs.REGISTRE.get(fournisseur.lower())
        candidats = [fournisseur.lower()] if (f and f.disponible()) else []
    else:
        candidats = fournisseurs.disponibles()

    if not candidats:
        note = (f"Fournisseur « {fournisseur} » indisponible" if fournisseur
                else "Aucun moteur d'images configuré")
        return {"url": _placeholder(prompt, largeur, hauteur, note), "prompt": prompt,
                "backend": "placeholder", "place_holder": True, "fournisseurs": candidats}

    erreurs = {}
    for nom in candidats:
        try:
            data = await fournisseurs.REGISTRE[nom].generer(
                prompt, negatif, largeur, hauteur, seed, modele)
            if data:
                fichier = f"img-{uuid.uuid4().hex[:12]}.{_ext(data)}"
                return {"url": _enregistrer(fichier, data), "prompt": prompt,
                        "backend": nom, "place_holder": False,
                        "modele": modele if (nom == "gateway" and modele) else None}
            erreurs[nom] = "aucune image renvoyée"
        except Exception as e:  # noqa: BLE001
            erreurs[nom] = str(e)[:160]

    return {"url": _placeholder(prompt, largeur, hauteur,
                                "Moteurs essayés sans succès : " + ", ".join(candidats)),
            "prompt": prompt, "backend": "placeholder", "place_holder": True,
            "erreurs": erreurs}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd briques/images && python3 -m pytest test_moteur.py -v`
Expected: tous PASS.

- [ ] **Step 5: Commit**

```bash
git add briques/images/moteur.py briques/images/test_moteur.py
git commit -m "feat(images): moteur.generer transmet et restitue le modèle utilisé (gateway)"
```

---

### Task 4: `main.py` (brique images) — champ `modele` + endpoint `GET /modeles`

**Files:**
- Modify: `briques/images/main.py:46-52` (classe `Generer`)
- Modify: `briques/images/main.py:101-106` (endpoint `POST /generer`)
- Modify: `briques/images/main.py` (nouvel endpoint, après `GET /fournisseurs`)
- Test: `briques/images/test_api.py`

**Interfaces:**
- Consomme : `moteur.generer(..., modele=...)` (Task 3), `fournisseurs.modeles_image_openrouter()` (Task 2).
- Produit : `GET /modeles` → `{"modeles": [...]}`. Consommé par la Task 5 (proxy atelier).

- [ ] **Step 1: Write the failing test**

Ajouter en tête de `briques/images/test_api.py` l'import `fournisseurs` (absent aujourd'hui) :

```python
import fournisseurs
```

Puis, à la fin du fichier :

```python
def test_generer_transmet_le_modele(monkeypatch):
    captes = {}

    async def _faux_generer(prompt, negatif, largeur, hauteur, seed=None,
                            fournisseur=None, modele=None):
        captes["modele"] = modele
        return {"url": "/fichiers/x.png", "prompt": prompt, "backend": "gateway",
                "place_holder": False, "modele": modele}

    monkeypatch.setattr(main.moteur, "generer", _faux_generer)
    r = c.post("/generer", json={"prompt": "un chat", "fournisseur": "gateway",
                                 "modele": "openai/gpt-5-image"})
    assert r.status_code == 200
    assert captes["modele"] == "openai/gpt-5-image"
    assert r.json()["modele"] == "openai/gpt-5-image"


def test_modeles_liste_le_catalogue_openrouter(monkeypatch):
    async def _faux_modeles():
        return [{"id": "google/gemini-2.5-flash-image", "prix_image": "0.0000003"}]

    monkeypatch.setattr(fournisseurs, "modeles_image_openrouter", _faux_modeles)
    r = c.get("/modeles")
    assert r.status_code == 200
    assert r.json()["modeles"] == [
        {"id": "google/gemini-2.5-flash-image", "prix_image": "0.0000003"}]


def test_modeles_openrouter_injoignable_renvoie_502(monkeypatch):
    async def _boom():
        raise RuntimeError("timeout OpenRouter")

    monkeypatch.setattr(fournisseurs, "modeles_image_openrouter", _boom)
    r = c.get("/modeles")
    assert r.status_code == 502
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd briques/images && python3 -m pytest test_api.py -k "modele or modeles" -v`
Expected: FAIL — `test_generer_transmet_le_modele` échoue car `Generer` n'a pas de champ
`modele` (Pydantic l'ignorerait silencieusement, donc `captes["modele"]` resterait `None`
même si on l'envoie... en fait ça se traduira par une assertion ratée sur
`captes["modele"] == "openai/gpt-5-image"`) ; les deux tests `test_modeles_*` échouent avec
404 (route `/modeles` inexistante).

- [ ] **Step 3: Write minimal implementation**

Dans `briques/images/main.py`, modifier la classe `Generer` (lignes 46-52) :

```python
class Generer(BaseModel):
    prompt:      str
    negatif:     Optional[str] = None
    largeur:     int = 1024
    hauteur:     int = 1024
    seed:        Optional[int] = None
    fournisseur: Optional[str] = None   # force un moteur (sinon : ordre de préférence)
    modele:      Optional[str] = None   # override ponctuel, honoré par le fournisseur gateway
```

Modifier l'endpoint `/generer` (lignes 101-106) :

```python
@app.post("/generer", tags=["images"])
async def generer(body: Generer, _cle: str = Depends(cle_api)):
    if not (body.prompt or "").strip():
        raise HTTPException(422, "Le prompt est vide.")
    return await moteur.generer(body.prompt, body.negatif or "", body.largeur,
                                body.hauteur, body.seed, fournisseur=body.fournisseur,
                                modele=body.modele)
```

Ajouter, juste après l'endpoint `GET /fournisseurs` (après la ligne `"ordre": fournisseurs.ordre()}`) :

```python
@app.get("/modeles", tags=["système"])
async def liste_modeles():
    """Modèles d'image disponibles via la Gateway (OpenRouter), pour le comparatif de
    l'Atelier Images & Vidéo. Liste TOUJOURS interrogée en direct (avec cache côté
    fournisseurs.py) : jamais de catalogue figé en dur qui pourrait devenir obsolète."""
    try:
        modeles = await fournisseurs.modeles_image_openrouter()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"OpenRouter injoignable : {str(e)[:160]}")
    return {"modeles": modeles}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd briques/images && python3 -m pytest test_api.py -v`
Expected: tous PASS.

- [ ] **Step 5: Commit**

```bash
git add briques/images/main.py briques/images/test_api.py
git commit -m "feat(images): endpoint GET /modeles + champ modele sur POST /generer"
```

---

### Task 5: `atelier-images-video/main.py` — relayer `modele` et `GET /images/modeles`

**Files:**
- Modify: `briques/atelier-images-video/main.py:141-159`
- Test: `briques/atelier-images-video/test_images_video.py`

**Interfaces:**
- Consomme : `GET {IMAGES_URL}/modeles`, `POST {IMAGES_URL}/generer` avec `modele` (Task 4).
- Produit : `GET /images/modeles` (relais direct). `GenererImage.modele` transmis tel quel
  dans `body.model_dump()`. Consommé par la Task 6 (front, via `api('/images/modeles')` et
  `api('/images/generer', 'POST', {..., modele})`).

- [ ] **Step 1: Write the failing test**

Ajouter à la fin de `briques/atelier-images-video/test_images_video.py` :

```python
def test_images_generer_transmet_le_modele(monkeypatch):
    Faux = _client_json({"url": "/fichiers/img-1.png", "backend": "gateway",
                         "place_holder": False, "modele": "openai/gpt-5-image"})
    monkeypatch.setattr(M.httpx, "AsyncClient", Faux)
    client.post("/images/generer", json={"prompt": "un chat", "fournisseur": "gateway",
                                         "modele": "openai/gpt-5-image"})
    _, _, _, corps, _ = Faux.dernier_appel
    assert corps["modele"] == "openai/gpt-5-image"


def test_images_modeles_relaie_le_catalogue(monkeypatch):
    monkeypatch.setattr(M.httpx, "AsyncClient",
                        _client_json({"modeles": [{"id": "google/gemini-2.5-flash-image",
                                                    "prix_image": "0.0000003"}]}))
    r = client.get("/images/modeles")
    assert r.status_code == 200
    assert r.json()["modeles"][0]["id"] == "google/gemini-2.5-flash-image"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd briques/atelier-images-video && python3 -m pytest test_images_video.py -k modele -v`
Expected: FAIL — `test_images_generer_transmet_le_modele` échoue (`corps` ne contient pas
`"modele"`, `GenererImage` n'a pas ce champ) ; `test_images_modeles_relaie_le_catalogue`
échoue en 404 (route inexistante).

- [ ] **Step 3: Write minimal implementation**

Dans `briques/atelier-images-video/main.py`, modifier la classe `GenererImage` (lignes 141-147) :

```python
class GenererImage(BaseModel):
    prompt: str
    negatif: Optional[str] = None
    largeur: int = 1024
    hauteur: int = 1024
    seed: Optional[int] = None
    fournisseur: Optional[str] = None
    modele: Optional[str] = None
```

Ajouter, juste après l'endpoint `GET /images/fournisseurs` (lignes 157-159) :

```python
@app.get("/images/modeles", tags=["images"])
async def images_modeles():
    return await _relayer("GET", f"{IMAGES_URL}/modeles", {}, "images")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd briques/atelier-images-video && python3 -m pytest test_images_video.py -v`
Expected: tous PASS.

- [ ] **Step 5: Commit**

```bash
git add briques/atelier-images-video/main.py briques/atelier-images-video/test_images_video.py
git commit -m "feat(atelier-images-video): relaie modele et GET /images/modeles"
```

---

### Task 6: `front.html` — onglet Comparatif

**Files:**
- Modify: `briques/atelier-images-video/front.html`
- Test: `briques/atelier-images-video/test_front.py`

**Interfaces:**
- Consomme : `api('/images/modeles')`, `api('/images/generer', 'POST', {prompt, fournisseur, modele})`, `mediaUrl()`, `esc()`, `jsonAttr()`, `ajouterGalerie(medium, titre, prompt, url, fournisseur, place_holder)` (tous déjà existants dans le fichier).
- Produit : onglet `comparatif` navigable comme les 4 autres ; fonctions JS
  `chargerModelesComparatif()` et `lancerComparatif()`.

- [ ] **Step 1: Write the failing test**

Ajouter à la fin de `briques/atelier-images-video/test_front.py` :

```python
def test_front_couvre_le_comparatif_de_modeles():
    html = client.get("/").text
    for marqueur in ("chargerModelesComparatif", "lancerComparatif", "/images/modeles",
                     "id=\"comparatif-modeles\"", "id=\"comparatif-grille\"",
                     "fournisseur: 'gateway'"):
        assert marqueur in html, f"marqueur absent : {marqueur}"


def test_front_comparatif_recharge_les_modeles_a_louverture_de_longlet():
    html = client.get("/").text
    assert "chargerModelesComparatif()" in html
    assert "'comparatif'" in html  # présent dans la liste des onglets de ouvrirOnglet()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd briques/atelier-images-video && python3 -m pytest test_front.py -k comparatif -v`
Expected: FAIL — aucun des marqueurs n'existe encore dans `front.html`.

- [ ] **Step 3: Write minimal implementation**

Dans `briques/atelier-images-video/front.html`, modifier la barre d'onglets (ligne 54-59) :

```html
  <nav class="onglets">
    <button id="btn-image" class="actif" onclick="ouvrirOnglet('image')">Image libre</button>
    <button id="btn-video" onclick="ouvrirOnglet('video')">Vidéo libre</button>
    <button id="btn-synergies" onclick="ouvrirOnglet('synergies')">Synergies</button>
    <button id="btn-galerie" onclick="ouvrirOnglet('galerie')">Galerie</button>
    <button id="btn-comparatif" onclick="ouvrirOnglet('comparatif')">Comparatif</button>
  </nav>
```

Ajouter, juste après la fermeture de `<div id="vue-galerie" ...>` (après la ligne
`  </div>` qui suit `<div id="galerie-grille" class="grille"></div>`, et avant la
fermeture de `<div class="wrap">`) :

```html
  <div id="vue-comparatif" class="vue panel">
    <label>Prompt</label>
    <textarea id="comparatif-prompt" placeholder="Un phare battu par la tempête, style aquarelle…"></textarea>
    <label>Modèles à comparer (via la Gateway)</label>
    <div id="comparatif-modeles">Chargement…</div>
    <button class="action" onclick="lancerComparatif()">Comparer</button>
    <div id="comparatif-erreur" class="erreur"></div>
    <div id="comparatif-grille" class="grille"></div>
  </div>
```

Modifier `ouvrirOnglet()` (lignes 127-134) :

```js
function ouvrirOnglet(nom) {
  for (const n of ['image', 'video', 'synergies', 'galerie', 'comparatif']) {
    document.getElementById('vue-' + n).classList.toggle('actif', n === nom);
    document.getElementById('btn-' + n).classList.toggle('actif', n === nom);
  }
  if (nom === 'synergies') chargerSeries();
  if (nom === 'galerie') chargerGalerie('');
  if (nom === 'comparatif') chargerModelesComparatif();
}
```

Ajouter, tout à la fin du `<script>` (juste avant `</script>`, après la fonction
`supprimerGalerie`) :

```js
// ── Comparatif de modèles (via la Gateway/OpenRouter) ──────────────────────
async function chargerModelesComparatif() {
  const zone = document.getElementById('comparatif-modeles');
  const erreur = document.getElementById('comparatif-erreur');
  erreur.textContent = ''; zone.innerHTML = 'Chargement…';
  try {
    const data = await api('/images/modeles');
    zone.innerHTML = (data.modeles || []).map(m => `
      <label style="display:flex;align-items:center;gap:6px;font-weight:normal;margin:4px 0">
        <input type="checkbox" value="${esc(m.id)}" class="comparatif-case">
        ${esc(m.id)}${m.prix_image != null ? ` <span style="color:var(--mut)">(${esc(String(m.prix_image))} $/token image)</span>` : ''}
      </label>`).join('') || '<p style="color:var(--mut)">Aucun modèle disponible.</p>';
  } catch (e) {
    zone.innerHTML = '';
    erreur.innerHTML = esc(e.message || e) +
      ' <button class="discret" onclick="chargerModelesComparatif()">Réessayer</button>';
  }
}

async function lancerComparatif() {
  const prompt = document.getElementById('comparatif-prompt').value.trim();
  const erreur = document.getElementById('comparatif-erreur');
  const grille = document.getElementById('comparatif-grille');
  erreur.textContent = ''; grille.innerHTML = '';
  if (!prompt) { erreur.textContent = 'Le prompt est vide.'; return; }
  const modeles = [...document.querySelectorAll('.comparatif-case:checked')].map(c => c.value);
  if (!modeles.length) { erreur.textContent = 'Coche au moins un modèle.'; return; }
  grille.innerHTML = modeles.map((m, i) => `<div class="carte" id="comparatif-resultat-${i}">
    <h4>${esc(m)}</h4><p style="color:var(--mut)">Génération…</p></div>`).join('');
  await Promise.allSettled(modeles.map(async (modele, i) => {
    const carte = document.getElementById('comparatif-resultat-' + i);
    try {
      const data = await api('/images/generer', 'POST', {prompt, fournisseur: 'gateway', modele});
      const avert = data.place_holder
        ? '<div class="avert">⚠️ Placeholder — aucun fournisseur réel n\'a produit ce média.</div>' : '';
      carte.innerHTML = `<h4>${esc(modele)}</h4>
        <img src="${esc(mediaUrl(data.url))}" alt="${esc(modele)}">${avert}
        <button class="discret" style="margin-top:8px" onclick='ajouterGalerie("image", ${jsonAttr(prompt.slice(0, 60) + " (" + modele + ")")}, ${jsonAttr(prompt)}, ${jsonAttr(data.url)}, ${jsonAttr(modele)}, ${!!data.place_holder})'>➕ Ajouter à la galerie</button>`;
    } catch (e) {
      carte.innerHTML = `<h4>${esc(modele)}</h4><div class="erreur">${esc(e.message || e)}</div>`;
    }
  }));
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd briques/atelier-images-video && python3 -m pytest test_front.py -v`
Expected: tous PASS (fichier complet, y compris les tests d'échappement HTML déjà présents
— vérifier en particulier que `test_front_echappe_les_autres_onclicks_synergies_contre_injection_html`
n'est pas cassé : le nouvel onclick `ajouterGalerie(...)` dans `lancerComparatif` utilise
bien `jsonAttr()` pour ses arguments dynamiques, comme `afficherResultatMedia`).

- [ ] **Step 5: Commit**

```bash
git add briques/atelier-images-video/front.html briques/atelier-images-video/test_front.py
git commit -m "feat(atelier-images-video): onglet Comparatif de modèles d'image"
```

---

### Task 7: Vérification finale — suite complète des deux briques

**Files:** aucun (vérification uniquement)

**Interfaces:** aucune (dernière étape, pas de nouveau code).

- [ ] **Step 1: Lancer la suite complète de la brique images**

Run: `cd briques/images && python3 -m pytest . -q`
Expected: tous PASS, aucune régression sur les fichiers non touchés (`test_prompts.py`, `test_workflow.py`).

- [ ] **Step 2: Lancer la suite complète de la brique atelier-images-video**

Run: `cd briques/atelier-images-video && python3 -m pytest . -q`
Expected: tous PASS, aucune régression (`test_main.py`, `test_galerie.py`, `test_synergies_studio.py`).

- [ ] **Step 3: Vérifier qu'aucun autre appelant de `fournisseurs.REGISTRE[...].generer(...)` ou de `.generer` en général n'a été oublié**

Run: `grep -rn "\.generer(" briques/images/*.py`
Expected : seuls `moteur.py` (l'appel mis à jour en Task 3) et les fichiers de tests
apparaissent — aucun autre appelant externe de cette méthode dans le dépôt.

- [ ] **Step 4: Commit final (si des ajustements ont eu lieu pendant la vérification)**

```bash
git status --short briques/images briques/atelier-images-video
```

Si tout est déjà commité (aucune modification en attente), rien à faire — les 6 commits
des tasks précédentes suffisent. Sinon, committer les ajustements restants avec un message
décrivant précisément la correction.

---

## Après l'implémentation (hors plan, rappel)

Une fois les 7 tasks vertes : pousser sur `main`, puis déployer sur le HP (git pull +
`docker compose up -d --build` dans `briques/images` ET `briques/atelier-images-video`,
même procédure que les fix précédents de cette conversation) avant de vérifier en direct
dans le navigateur.
