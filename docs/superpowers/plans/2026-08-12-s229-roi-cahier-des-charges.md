# S229 — ROI chiffré + cahier des charges exportable — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ajouter une 5e couche `roi` à `briques/audit` (chiffrage euros/heures des problèmes du Pareto, hypothèse LLM ou coût fourni par le client, toujours marqué comme tel) puis un cahier des charges formel généré par `briques/generateur` (12 sections + section ROI déterministe), exportable en PDF (et bonus PPTX) via `briques/export`.

**Architecture:** `briques/audit` gagne un module `chiffrage.py` (prompt LLM + statut par pôle décidé en Python) et `POST /audits/{id}/chiffrer`. `briques/generateur` gagne un module `cdc.py` (assemblage markdown : 12 sections LLM + section ROI injectée par du code, jamais par le LLM) et 4 endpoints (`POST`/`GET /cahier-des-charges`, `GET .../pdf`, `POST .../pptx`). `prompt_plan_app` (génération d'app) devient traçable au cahier des charges quand il existe, avec repli identique au comportement actuel si aucun CDC n'a été généré pour l'audit.

**Tech Stack:** FastAPI + SQLite (audit, generateur), `shared/llm_client.py` (Gateway LLM déjà mutualisé), `briques/export` (WeasyPrint/python-pptx, déjà en prod).

## Global Constraints

- Les deux nouveaux endpoints qui appellent le LLM (`POST /audits/{id}/chiffrer`, `POST /audits/{id}/cahier-des-charges`) sont **synchrones** (pas de `background_tasks` + 202), contrairement à `/auditer`/`/generer` : ce sont CHACUN un seul appel LLM (borné par le timeout `shared/llm_client.py` de 180s), pas un pipeline séquentiel à 4 couches ni une génération d'app avec provisioning. Ajouter une infra de polling pour un seul appel serait hors-sujet pour ce sprint (cf. `PUT /apps/{app_id}/partage-forge` dans `briques/generateur/main.py:336-350`, déjà synchrone sur un appel réseau).
- L'avertissement (`"Estimation à valider avec le client — non contractuelle."`) est un **littéral Python**, jamais dans un prompt LLM, jamais retourné par le LLM — décision actée dans le design, reprise à l'identique dans `briques/audit/chiffrage.py` ET `briques/generateur/cdc.py` (duplication intentionnelle : deux briques/déploiements séparés, pas de package partagé pour ce domaine, même logique que `langues.py` dupliqué entre `audit` et `generateur`).
- Le statut `"fourni_client"` / `"hypothese_llm"` est décidé **en Python après l'appel LLM**, jamais par le LLM lui-même — il compare le `pole` renvoyé par le LLM à `cout_horaire` reçu du client. Le LLM ne doit jamais avoir le dernier mot sur cette distinction.
- `briques/export` peut être fermée par `API_KEYS` (cf. `briques/export/main.py:25-35`) — `briques/generateur` doit présenter une clé si `EXPORT_KEY` est définie, comme `briques/audit` le fait déjà pour `INGESTION_KEY` (`briques/audit/main.py:16-22`). Piège « env shadow » documenté dans `briques/audit/docker-compose.yml:20-22` : ne JAMAIS déclarer `EXPORT_KEY=${EXPORT_KEY:-}` dans le nouveau bloc `environment:` de `briques/generateur/docker-compose.yml` — laisser la clé venir uniquement du `.env` racine via `env_file`.
- Chaque capacité manifest ajoutée doit pointer vers une route qui existe réellement dans le code de CETTE tâche (leçon S228 : 3 Critical trouvés en revue finale, dont des routes manifest inexistantes) — vérifier `chemin`/`methode` contre le décorateur FastAPI au moment d'écrire le manifest, pas de mémoire.
- `prompt_plan_app` (génération d'app, `briques/generateur/prompts.py`) : le cahier des charges remplace l'assemblage informel SWOT/TOC/OKRs/MoSCoW **uniquement quand un CDC existe déjà** pour l'audit — sinon comportement strictement inchangé (aucune régression pour les audits/apps déjà en usage, aucune dépendance dure ajoutée au chemin critique de `/generer`). Le vocabulaire (`glossaire_metier`/`agregats`/`bounded_contexts`) reste puisé directement dans `territoire` dans LES DEUX branches — c'est la RÈGLE la plus importante du prompt, elle ne doit jamais dépendre de la présence d'un CDC.
- Tests offline uniquement (mock `appeler_llm` au niveau du module qui l'importe, `TestClient` avec `DB_PATH` redirigé vers `tmp_path`) — même conventions que `briques/audit/test_audit.py` et `briques/generateur/test_revue.py`.

---

## File Structure

**`briques/audit/`** :
- `prompts.py` — ajoute `prompt_roi(...)`
- `chiffrage.py` — NOUVEAU : appel LLM + statut/avertissement déterministes
- `main.py` — colonne `roi`, `POST /audits/{id}/chiffrer`, `importer_audit` porte `roi`
- `manifest.json` — capacité `audit_chiffrer`
- `test_audit.py` — tests colonne `roi` + endpoint `/chiffrer`

**`shared/schemas/`** :
- `audit.py` — champ `roi: dict | None`
- `tests/test_shared_schema_audit.py` — test du nouveau champ

**`briques/generateur/`** :
- `prompts.py` — ajoute `prompt_cahier_des_charges(...)`, refactor `prompt_plan_app(...)`
- `cdc.py` — NOUVEAU : assemblage markdown (12 sections LLM + ROI déterministe) + diapositives PPTX
- `generateur.py` — `generer_app_complete(...)` prend `cahier_des_charges` optionnel
- `main.py` — table `cahiers_des_charges`, 4 endpoints CDC, wiring `EXPORT_URL`/`EXPORT_KEY`, `generer()`/`_generer_en_background` propagent le CDC stocké
- `manifest.json` — 4 capacités + `depends_on`/`besoin` mis à jour
- `docker-compose.yml` — `EXPORT_URL` (env)
- `test_cdc.py` — NOUVEAU : tests `cdc.py` + endpoints CDC
- `test_generateur.py` — NOUVEAU : non-régression `prompt_plan_app` (avec/sans CDC)

---

## Task 1 : `briques/audit` — colonne `roi` (schéma + import/lecture)

**Files:**
- Modify: `briques/audit/main.py`
- Test: `briques/audit/test_audit.py`

**Interfaces:**
- Produces: colonne `audits.roi` (TEXT JSON, nullable), `_audit_vers_dict` parse `roi`, `POST /audits/import` accepte `roi`.

- [ ] **Step 1: Write the failing test**

Ajouter à la fin de `briques/audit/test_audit.py` :

```python
def test_audit_roi_serialise_puis_relu_en_json(client):
    resp = client.post("/audits/import", json={
        "nom_entreprise": "ROI SA",
        "statut": "termine",
        "roi": {"problemes": [{"probleme": "Relances manuelles", "statut": "hypothese_llm"}]},
    })
    assert resp.status_code == 200
    audit_id = resp.json()["id"]

    resp2 = client.get(f"/audits/{audit_id}")
    assert resp2.json()["roi"] == {
        "problemes": [{"probleme": "Relances manuelles", "statut": "hypothese_llm"}]
    }


def test_audit_sans_roi_retourne_champ_absent_ou_null(client):
    resp = client.post("/audits/import", json={"nom_entreprise": "SansROI SA", "statut": "termine"})
    audit_id = resp.json()["id"]
    resp2 = client.get(f"/audits/{audit_id}")
    assert resp2.json().get("roi") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd briques/audit && python3 -m pytest test_audit.py -k test_audit_roi -v`
Expected: FAIL — `test_importer_audit` insère sans erreur `roi` (colonne ignorée silencieusement par le dict Pydantic-less `dict` body) mais `roi` n'est jamais lu au retour (`_audit_vers_dict` ne le connaît pas), donc `resp2.json()["roi"]` lève `KeyError`/renvoie absent avec un contenu incorrect si testé avec valeur non-null.

- [ ] **Step 3: Add the column, the migration and the read/write paths**

Dans `briques/audit/main.py`, modifie `_init_db` :

```python
def _init_db():
    with _connexion() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS audits (
                id             TEXT PRIMARY KEY,
                date_audit     TEXT NOT NULL,
                nom_entreprise TEXT,
                docs_sources   TEXT,
                territoire     TEXT,
                flux           TEXT,
                problemes      TEXT,
                priorites      TEXT,
                statut         TEXT DEFAULT 'en_cours'
            )
        """)
        # Migration S229 : colonne roi (5e couche, calculée à la demande via /chiffrer).
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(audits)").fetchall()}
        if "roi" not in cols:
            conn.execute("ALTER TABLE audits ADD COLUMN roi TEXT")
        conn.commit()
```

Modifie `_audit_vers_dict` :

```python
def _audit_vers_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    for champ in ("docs_sources", "territoire", "flux", "problemes", "priorites", "roi"):
        if d.get(champ):
            try:
                d[champ] = json.loads(d[champ])
            except Exception:
                pass
    return d
```

Modifie `importer_audit` :

```python
@app.post("/audits/import")
def importer_audit(audit: dict):
    """Réinsère un audit complet (id préservé) — reprise d'un dossier décroché (S6)."""
    def _ser(v):
        if v is None or isinstance(v, str):
            return v
        return json.dumps(v, ensure_ascii=False)

    audit_id = audit.get("id") or str(uuid.uuid4())
    with _connexion() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO audits
               (id, date_audit, nom_entreprise, docs_sources, territoire, flux,
                problemes, priorites, roi, statut)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                audit_id,
                audit.get("date_audit") or datetime.now(timezone.utc).isoformat(),
                audit.get("nom_entreprise"),
                _ser(audit.get("docs_sources")),
                _ser(audit.get("territoire")),
                _ser(audit.get("flux")),
                _ser(audit.get("problemes")),
                _ser(audit.get("priorites")),
                _ser(audit.get("roi")),
                audit.get("statut") or "termine",
            ),
        )
        conn.commit()
    return {"id": audit_id, "statut": "termine"}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd briques/audit && python3 -m pytest test_audit.py -v`
Expected: PASS (tous les tests, y compris les 2 nouveaux et les préexistants inchangés)

- [ ] **Step 5: Commit**

```bash
git add briques/audit/main.py briques/audit/test_audit.py
git commit -m "feat(audit): S229 colonne roi (5e couche, import/lecture)"
```

---

## Task 2 : `briques/audit` — prompt ROI + module `chiffrage.py`

**Files:**
- Modify: `briques/audit/prompts.py`
- Create: `briques/audit/chiffrage.py`
- Test: `briques/audit/test_audit.py` (nouveau bloc de tests dédiés au module)

**Interfaces:**
- Consumes: `gateway.appeler_llm` (existant, `briques/audit/gateway.py:16`)
- Produces: `chiffrage.AVERTISSEMENT` (str), `async chiffrage.chiffrer(territoire, problemes, priorites, cout_horaire) -> dict | None`

- [ ] **Step 1: Write the failing test**

Ajouter à `briques/audit/test_audit.py` (nouvel import en tête de fichier : `import chiffrage`) :

```python
import chiffrage


def test_chiffrer_cout_horaire_fourni_marque_fourni_client_et_efface_la_fourchette(monkeypatch):
    async def faux_llm(prompt):
        return {"problemes": [{
            "probleme": "Relances manuelles", "pole": "commercial",
            "temps_mensuel_heures": 20,
            "cout_horaire_estime": {"bas": 30, "moyen": 40, "haut": 50},
            "cout_actuel_estime": {"bas": 500, "haut": 700},
            "gain_potentiel_estime": {"bas": 300, "haut": 400},
        }], "synthese": "Gain notable sur les relances."}
    monkeypatch.setattr(chiffrage, "appeler_llm", faux_llm)

    import asyncio
    resultat = asyncio.run(chiffrage.chiffrer({}, {}, {}, {"commercial": 45}))

    entree = resultat["problemes"][0]
    assert entree["statut"] == "fourni_client"
    assert entree["avertissement"] == chiffrage.AVERTISSEMENT
    assert entree["cout_horaire_estime"] is None  # le client a fourni son coût, pas besoin d'hypothèse


def test_chiffrer_sans_cout_horaire_marque_hypothese_llm(monkeypatch):
    async def faux_llm(prompt):
        return {"problemes": [{
            "probleme": "Saisie manuelle", "pole": "administratif",
            "temps_mensuel_heures": 10,
            "cout_horaire_estime": {"bas": 25, "moyen": 30, "haut": 35},
            "cout_actuel_estime": {"bas": 250, "haut": 350},
            "gain_potentiel_estime": {"bas": 150, "haut": 200},
        }]}
    monkeypatch.setattr(chiffrage, "appeler_llm", faux_llm)

    import asyncio
    resultat = asyncio.run(chiffrage.chiffrer({}, {}, {}, None))

    entree = resultat["problemes"][0]
    assert entree["statut"] == "hypothese_llm"
    assert entree["avertissement"] == chiffrage.AVERTISSEMENT
    assert entree["cout_horaire_estime"] == {"bas": 25, "moyen": 30, "haut": 35}


def test_chiffrer_llm_echoue_retourne_none(monkeypatch):
    async def llm_ko(prompt):
        raise RuntimeError("Gateway indisponible")
    monkeypatch.setattr(chiffrage, "appeler_llm", llm_ko)

    import asyncio
    assert asyncio.run(chiffrage.chiffrer({}, {}, {}, None)) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd briques/audit && python3 -m pytest test_audit.py -k test_chiffrer -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'chiffrage'`

- [ ] **Step 3: Write `prompt_roi` and `chiffrage.py`**

Ajouter à la fin de `briques/audit/prompts.py` :

```python
def prompt_roi(territoire_json: str, problemes_json: str, priorites_json: str,
               cout_horaire_json: str) -> str:
    return f"""Territoire (dont repartition_ca[].temps_pct) : {territoire_json}
Problèmes (dont pareto : impact %, fréquence %) : {problemes_json}
Priorités (dont moscow, chemin_critique) : {priorites_json}

Coût horaire connu du client par pôle (peut être vide) : {cout_horaire_json}

Pour CHAQUE problème listé dans pareto, chiffre son coût actuel et son gain potentiel après
automatisation. Combine sa fréquence (pareto) avec le temps_pct de l'activité concernée
(repartition_ca) pour estimer un temps mensuel en heures. Le coût après automatisation
s'appuie sur la complexité de la solution proposée dans moscow/chemin_critique.

Retourne un JSON avec exactement ces clés :
- "problemes" : liste d'objets, un par problème du pareto, chacun avec :
    - "probleme" : le libellé du problème (repris du pareto)
    - "pole" : "commercial" | "production" | "administratif" — le pôle métier concerné
    - "temps_mensuel_heures" : NOMBRE d'heures/mois estimées consommées par ce problème
    - "cout_horaire_estime" : SI le pôle n'est PAS dans le coût horaire connu du client,
      une fourchette {{"bas":NOMBRE,"moyen":NOMBRE,"haut":NOMBRE}} en euros/heure plausible
      pour ce type de poste ; sinon null (le coût horaire du client sera utilisé tel quel)
    - "cout_actuel_estime" : {{"bas":NOMBRE,"haut":NOMBRE}} en euros/mois (fourchette basse/haute)
    - "gain_potentiel_estime" : {{"bas":NOMBRE,"haut":NOMBRE}} en euros/mois après automatisation
- "synthese" : 1-2 phrases résumant le chiffrage global (ordre de grandeur, pas de total garanti)

N'invente jamais un coût horaire fourni par le client — utilise UNIQUEMENT ceux listés
ci-dessus ; pour les autres pôles, propose une fourchette réaliste et dis-le."""
```

Créer `briques/audit/chiffrage.py` :

```python
"""Chiffrage ROI (S229) — 5e couche de l'audit, calculée à la demande via POST /chiffrer.

Le statut ('fourni_client' vs 'hypothese_llm') est décidé ICI, en Python, PAS par le LLM,
pour ne jamais dépendre de sa discipline. Idem pour l'avertissement : un littéral fixe,
jamais généré, ajouté après coup à chaque entrée.
"""
import json
import logging

from gateway import appeler_llm
from prompts import prompt_roi

logger = logging.getLogger(__name__)

AVERTISSEMENT = "Estimation à valider avec le client — non contractuelle."


async def chiffrer(territoire: dict, problemes: dict, priorites: dict,
                   cout_horaire: dict | None) -> dict | None:
    """Retourne le JSON de chiffrage, ou None si le LLM échoue après 1 retry."""
    cout_horaire = cout_horaire or {}
    prompt = prompt_roi(
        json.dumps(territoire or {}, ensure_ascii=False),
        json.dumps(problemes or {}, ensure_ascii=False),
        json.dumps(priorites or {}, ensure_ascii=False),
        json.dumps(cout_horaire, ensure_ascii=False),
    )

    resultat = None
    for tentative in range(2):
        try:
            resultat = await appeler_llm(prompt)
            break
        except Exception as e:
            logger.warning(f"Chiffrage ROI tentative {tentative + 1} échouée : {e}")

    if not resultat or not isinstance(resultat.get("problemes"), list):
        return None

    for entree in resultat["problemes"]:
        if not isinstance(entree, dict):
            continue
        pole = entree.get("pole")
        entree["statut"] = "fourni_client" if pole in cout_horaire else "hypothese_llm"
        entree["avertissement"] = AVERTISSEMENT
        if entree["statut"] == "fourni_client":
            entree["cout_horaire_estime"] = None
    return resultat
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd briques/audit && python3 -m pytest test_audit.py -k test_chiffrer -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add briques/audit/prompts.py briques/audit/chiffrage.py briques/audit/test_audit.py
git commit -m "feat(audit): S229 module chiffrage.py — ROI par pôle, statut/avertissement déterministes"
```

---

## Task 3 : `briques/audit` — endpoint `POST /audits/{id}/chiffrer`

**Files:**
- Modify: `briques/audit/main.py`
- Test: `briques/audit/test_audit.py`

**Interfaces:**
- Consumes: `chiffrage.chiffrer` (Task 2)
- Produces: `POST /audits/{audit_id}/chiffrer` → `{"id", "roi", "statut_roi"}`

- [ ] **Step 1: Write the failing test**

Ajouter à `briques/audit/test_audit.py` :

```python
def test_chiffrer_audit_inexistant_retourne_404(client):
    resp = client.post("/audits/audit-inexistant-xyz/chiffrer")
    assert resp.status_code == 404


def test_chiffrer_audit_non_termine_retourne_400(client):
    resp = client.post("/audits/import", json={"nom_entreprise": "EnCours SA", "statut": "en_cours"})
    audit_id = resp.json()["id"]
    resp2 = client.post(f"/audits/{audit_id}/chiffrer")
    assert resp2.status_code == 400


def test_chiffrer_endpoint_bout_en_bout_persiste_le_roi(client, monkeypatch):
    resp = client.post("/audits/import", json={
        "nom_entreprise": "Chiffrage SA", "statut": "termine",
        "territoire": {"repartition_ca": [{"libelle": "SAV", "temps_pct": 40}]},
        "problemes": {"pareto": [{"probleme": "Relances manuelles"}]},
        "priorites": {"moscow": {"must": ["Automatiser les relances"]}},
    })
    audit_id = resp.json()["id"]

    async def faux_llm(prompt):
        return {"problemes": [{"probleme": "Relances manuelles", "pole": "commercial",
                                "cout_actuel_estime": {"bas": 500, "haut": 700},
                                "gain_potentiel_estime": {"bas": 300, "haut": 400}}],
                "synthese": "Gain notable."}
    monkeypatch.setattr(chiffrage, "appeler_llm", faux_llm)

    resp2 = client.post(f"/audits/{audit_id}/chiffrer", json={"cout_horaire": {"commercial": 45}})
    assert resp2.status_code == 200
    data = resp2.json()
    assert data["statut_roi"] == "termine"
    assert data["roi"]["problemes"][0]["statut"] == "fourni_client"

    resp3 = client.get(f"/audits/{audit_id}")
    assert resp3.json()["roi"]["problemes"][0]["statut"] == "fourni_client"


def test_chiffrer_echec_llm_roi_indisponible_audit_reste_termine(client, monkeypatch):
    resp = client.post("/audits/import", json={"nom_entreprise": "KO SA", "statut": "termine"})
    audit_id = resp.json()["id"]

    async def llm_ko(prompt):
        raise RuntimeError("Gateway indisponible")
    monkeypatch.setattr(chiffrage, "appeler_llm", llm_ko)

    resp2 = client.post(f"/audits/{audit_id}/chiffrer")
    assert resp2.status_code == 200
    assert resp2.json()["statut_roi"] == "roi_indisponible"
    assert resp2.json()["roi"] is None

    resp3 = client.get(f"/audits/{audit_id}")
    assert resp3.json()["statut"] == "termine"  # jamais remis en cause
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd briques/audit && python3 -m pytest test_audit.py -k test_chiffrer_endpoint -v`
Expected: FAIL with 404 (route inexistante)

- [ ] **Step 3: Add the endpoint**

Dans `briques/audit/main.py`, ajoute l'import et le modèle en haut du fichier (à côté de `RequeteAudit`) :

```python
from chiffrage import chiffrer
```

Ajoute après `RequeteAudit` :

```python
class RequeteChiffrer(BaseModel):
    cout_horaire: dict[str, float] | None = None
```

Ajoute l'endpoint (après `lire_audit`, avant `supprimer_audit`) :

```python
@app.post("/audits/{audit_id}/chiffrer")
async def chiffrer_audit(audit_id: str, req: RequeteChiffrer | None = None):
    req = req or RequeteChiffrer()
    with _connexion() as conn:
        row = conn.execute(
            "SELECT territoire, flux, problemes, priorites, statut FROM audits WHERE id=?",
            (audit_id,),
        ).fetchone()
    if not row:
        raise HTTPException(404, "Audit introuvable")
    if row["statut"] != "termine":
        raise HTTPException(400, f"L'audit n'est pas terminé (statut : {row['statut']})")

    territoire = json.loads(row["territoire"]) if row["territoire"] else {}
    problemes = json.loads(row["problemes"]) if row["problemes"] else {}
    priorites = json.loads(row["priorites"]) if row["priorites"] else {}

    resultat = await chiffrer(territoire, problemes, priorites, req.cout_horaire)
    with _connexion() as conn:
        conn.execute(
            "UPDATE audits SET roi=? WHERE id=?",
            (json.dumps(resultat, ensure_ascii=False) if resultat else None, audit_id),
        )
        conn.commit()
    return {"id": audit_id, "roi": resultat,
            "statut_roi": "termine" if resultat else "roi_indisponible"}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd briques/audit && python3 -m pytest test_audit.py -v`
Expected: PASS (tous les tests du fichier)

- [ ] **Step 5: Commit**

```bash
git add briques/audit/main.py briques/audit/test_audit.py
git commit -m "feat(audit): S229 POST /audits/{id}/chiffrer"
```

---

## Task 4 : `briques/audit` — manifest.json (capacité `audit_chiffrer`)

**Files:**
- Modify: `briques/audit/manifest.json`

**Interfaces:**
- Produces: capacité manifest `audit_chiffrer` pointant sur la route réelle de la Task 3.

- [ ] **Step 1: Update the manifest**

Dans `briques/audit/manifest.json`, remplace la ligne `"description"` (ligne 5) :

```json
  "description": "Audit d'entreprise IA — 5 couches : Territoire (DDD/Canvas/Stakeholders), Flux (VSM/SIPOC/EventStorming), Problèmes (Ishikawa/Pareto/TOC/5Pourquoi), Priorités (CPM/PERT/SWOT/OKRs/MoSCoW), ROI (chiffrage euros/heures des problèmes, à la demande)",
```

Remplace le bloc `"version"` (ligne 4) :

```json
  "version": "0.2.0",
```

Remplace le bloc `"offre"` (lignes 16-22) :

```json
  "offre": [
    "audit_entreprise",
    "fiche_territoire",
    "fiche_flux",
    "fiche_problemes",
    "fiche_priorites",
    "chiffrage_roi"
  ],
```

Dans le tableau `capacites`, la capacité `audit_tout` (dernière du tableau) se termine ainsi (lignes 67-75, INCHANGÉES) :

```json
    {
      "nom": "audit_tout",
      "description": "Lance un audit sur TOUS les documents ingérés disponibles (pas de sélection). ACTION (travail LLM très long et coûteux) : confirme=true requis.",
      "methode": "POST",
      "chemin": "/auditer/tout",
      "params": {},
      "action": true,
      "niveau": 1
    }
  ]
```

Remplace ces 10 lignes (de `    {` à `  ]`, la fermeture du tableau `capacites`) par :

```json
    {
      "nom": "audit_tout",
      "description": "Lance un audit sur TOUS les documents ingérés disponibles (pas de sélection). ACTION (travail LLM très long et coûteux) : confirme=true requis.",
      "methode": "POST",
      "chemin": "/auditer/tout",
      "params": {},
      "action": true,
      "niveau": 1
    },
    {
      "nom": "audit_chiffrer",
      "description": "Chiffre en euros/heures les problèmes identifiés par le Pareto de l'audit (5e couche ROI) : combine fréquence, part de temps de travail et coût horaire (fourni par le client par pôle, ou hypothèse LLM sinon — toujours marqué comme tel avec un avertissement de non-garantie). ACTION (appel LLM) : confirme=true requis.",
      "methode": "POST",
      "chemin": "/audits/{audit_id}/chiffrer",
      "params": {
        "audit_id": {
          "type": "string",
          "description": "Identifiant de l'audit à chiffrer (voir audits_lister). L'audit doit être 'termine'.",
          "requis": true
        },
        "cout_horaire": {
          "type": "object",
          "description": "Coût horaire connu du client par pôle, ex: {\"commercial\": 45, \"production\": 38}. Optionnel — les pôles absents reçoivent une fourchette hypothèse LLM, jamais bloquant."
        }
      },
      "action": true,
      "niveau": 1
    }
  ]
}
```

`capacites` est la dernière propriété du manifest (pas de `"taches"` dans `briques/audit/manifest.json`, contrairement à `briques/generateur/manifest.json`) — le `}` final ci-dessus ferme l'objet racine. Les capacités `audits_lister`, `audit_lire`, `audit_lancer` (lignes 27-66) ne sont touchées par aucune de ces 3 opérations d'édition — elles restent telles quelles.

- [ ] **Step 2: Validate the JSON**

Run: `cd briques/audit && python3 -c "import json; json.load(open('manifest.json'))" && echo OK`
Expected: `OK`

- [ ] **Step 3: Cross-check route vs manifest**

Run: `cd briques/audit && grep -n 'audits/{audit_id}/chiffrer' main.py manifest.json`
Expected: 2 lignes (une dans chaque fichier), même chemin exact.

- [ ] **Step 4: Commit**

```bash
git add briques/audit/manifest.json
git commit -m "docs(audit): S229 capacité manifest audit_chiffrer"
```

---

## Task 5 : `shared/schemas/audit.py` — champ `roi` sur le contrat

**Files:**
- Modify: `shared/schemas/audit.py`
- Test: `tests/test_shared_schema_audit.py`

**Interfaces:**
- Produces: `Audit.roi: dict[str, Any] | None`

- [ ] **Step 1: Write the failing test**

Ajouter à `tests/test_shared_schema_audit.py` :

```python
def test_audit_roi_optionnel_et_type_dict():
    a = Audit.model_validate({
        "id": "x1", "statut": "termine",
        "roi": {"problemes": [{"probleme": "x", "statut": "hypothese_llm"}]},
    })
    assert a.roi == {"problemes": [{"probleme": "x", "statut": "hypothese_llm"}]}


def test_audit_sans_roi_vaut_none():
    a = Audit(id="x2")
    assert a.roi is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/garinat_t/Desktop/Workplace && python3 -m pytest tests/test_shared_schema_audit.py -k roi -v`
Expected: FAIL — `roi` n'existe pas sur le modèle mais passe quand même (extra="allow") ; le test échoue seulement si l'assertion porte sur `a.roi` explicitement typé (AttributeError avant l'ajout du champ n'aurait PAS lieu grâce à `extra=allow`, donc ce test seul ne suffit pas à prouver l'absence — vérifie plutôt avec `"roi" in Audit.model_fields`).

Remplace le premier test par une assertion sur le schéma :

```python
def test_audit_declare_le_champ_roi():
    assert "roi" in Audit.model_fields
```

Re-run — Expected: FAIL avec `AssertionError` avant l'ajout du champ.

- [ ] **Step 3: Add the field**

Dans `shared/schemas/audit.py`, modifie le docstring (ligne 3) et ajoute le champ après `priorites` :

```python
"""Contrat de l'audit (S119) — brique `audit` (productrice) → brique `generateur`.

L'audit est une enveloppe (identité + statut + entreprise) portant 5 couches d'analyse
produites par le LLM (territoire, flux, problèmes, priorités, roi). Chaque couche est du
JSON de forme libre (sortie modèle), donc typée `dict | None` ; l'enveloppe, elle, est
figée. `extra="allow"` : on tolère des champs additionnels pour ne pas casser à la moindre
évolution (le contrat fixe le NOYAU, pas un mur).
"""
```

```python
    territoire: dict[str, Any] | None = None
    flux: dict[str, Any] | None = None
    problemes: dict[str, Any] | None = None
    priorites: dict[str, Any] | None = None
    # S229 : 5e couche, calculée à la demande via `POST /audits/{id}/chiffrer` (absente tant
    # qu'elle n'a jamais été demandée, ou après un échec LLM — jamais bloquant).
    roi: dict[str, Any] | None = None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/garinat_t/Desktop/Workplace && python3 -m pytest tests/test_shared_schema_audit.py -v`
Expected: PASS (tous les tests)

- [ ] **Step 5: Commit**

```bash
git add shared/schemas/audit.py tests/test_shared_schema_audit.py
git commit -m "feat(shared): S229 champ roi sur le contrat Audit"
```

---

## Task 6 : `briques/generateur` — table `cahiers_des_charges`

**Files:**
- Modify: `briques/generateur/main.py`
- Test: `briques/generateur/test_cdc.py` (NOUVEAU)

**Interfaces:**
- Produces: table `cahiers_des_charges (id, audit_id, markdown, pdf_chemin, pptx_chemin, statut, created_at)`, helper `_dernier_cdc(audit_id) -> dict | None`

- [ ] **Step 1: Write the failing test**

Créer `briques/generateur/test_cdc.py` :

```python
"""Tests S229 : table cahiers_des_charges + endpoints cahier des charges."""
import os
import tempfile

os.environ.setdefault("GATEWAY_KEY", "test-offline")
os.environ.setdefault("DB_PATH", os.path.join(tempfile.gettempdir(), "test_generateur_cdc.db"))

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    import main as gen_main
    monkeypatch.setattr(gen_main, "DB_PATH", str(tmp_path / "apps.db"))
    with TestClient(gen_main.app) as c:
        yield c


def test_table_cahiers_des_charges_existe(client):
    import main as gen_main
    with gen_main._connexion() as conn:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(cahiers_des_charges)").fetchall()}
    assert cols == {"id", "audit_id", "markdown", "pdf_chemin", "pptx_chemin", "statut", "created_at"}


def test_dernier_cdc_absent_retourne_none(client):
    import main as gen_main
    assert gen_main._dernier_cdc("audit-inexistant") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd briques/generateur && python3 -m pytest test_cdc.py -v`
Expected: FAIL — table absente (colonnes vide) et `AttributeError: module 'main' has no attribute '_dernier_cdc'`

- [ ] **Step 3: Add the table and the helper**

Dans `briques/generateur/main.py`, modifie `_init_db` (ajoute après le bloc `if "langue" not in cols:`) :

```python
        if "langue" not in cols:
            conn.execute("ALTER TABLE apps ADD COLUMN langue TEXT DEFAULT 'fr'")

        # S229 : cahiers des charges (table neuve, pas de migration de colonnes nécessaire).
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cahiers_des_charges (
                id          TEXT PRIMARY KEY,
                audit_id    TEXT NOT NULL,
                markdown    TEXT NOT NULL,
                pdf_chemin  TEXT,
                pptx_chemin TEXT,
                statut      TEXT NOT NULL DEFAULT 'genere',
                created_at  TEXT NOT NULL
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_cdc_audit ON cahiers_des_charges(audit_id)"
        )
        conn.commit()
```

Ajoute le helper après `_charger_audit` (autour de la ligne 396) :

```python
def _dernier_cdc(audit_id: str) -> dict | None:
    with _connexion() as conn:
        row = conn.execute(
            "SELECT id, audit_id, markdown, pdf_chemin, pptx_chemin, statut, created_at "
            "FROM cahiers_des_charges WHERE audit_id=? ORDER BY created_at DESC LIMIT 1",
            (audit_id,),
        ).fetchone()
    return dict(row) if row else None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd briques/generateur && python3 -m pytest test_cdc.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add briques/generateur/main.py briques/generateur/test_cdc.py
git commit -m "feat(generateur): S229 table cahiers_des_charges + helper _dernier_cdc"
```

---

## Task 7 : `briques/generateur` — prompt CDC + module `cdc.py`

**Files:**
- Modify: `briques/generateur/prompts.py`
- Create: `briques/generateur/cdc.py`
- Test: `briques/generateur/test_cdc.py`

**Interfaces:**
- Consumes: `gateway.appeler_llm(user, langue)` (existant, `briques/generateur/gateway.py:18`)
- Produces: `cdc.AVERTISSEMENT`, `async cdc.generer_cahier_des_charges(audit, langue) -> str`, `cdc.construire_diapositives(audit) -> list[dict]`

- [ ] **Step 1: Write the failing test**

Ajouter à `briques/generateur/test_cdc.py` :

```python
import asyncio

import cdc


def test_section_roi_absente_dit_chiffrage_non_disponible():
    markdown = cdc._section_roi_markdown(None)
    assert "relancer" in markdown.lower()


def test_section_roi_presente_contient_avertissement_mot_pour_mot():
    roi = {"synthese": "Gain notable.", "problemes": [{
        "probleme": "Relances manuelles", "pole": "commercial",
        "cout_actuel_estime": {"bas": 500, "haut": 700},
        "gain_potentiel_estime": {"bas": 300, "haut": 400},
        "statut": "hypothese_llm", "avertissement": cdc.AVERTISSEMENT,
    }]}
    markdown = cdc._section_roi_markdown(roi)
    assert cdc.AVERTISSEMENT in markdown
    assert "Relances manuelles" in markdown


def test_generer_cahier_des_charges_assemble_12_sections_llm_plus_roi(monkeypatch):
    async def faux_llm(prompt, langue="fr"):
        return {cle: f"Contenu {cle}" for cle, _ in cdc._SECTIONS_CDC}
    monkeypatch.setattr(cdc, "appeler_llm", faux_llm)

    audit = {"nom_entreprise": "Test SA", "roi": None}
    markdown = asyncio.run(cdc.generer_cahier_des_charges(audit, "fr"))

    for _, titre in cdc._SECTIONS_CDC:
        assert f"## {titre}" in markdown
    assert "## ROI" in markdown
    assert "relancer" in markdown.lower()


def test_generer_cahier_des_charges_repli_si_llm_echoue(monkeypatch):
    async def llm_ko(prompt, langue="fr"):
        raise RuntimeError("Gateway indisponible")
    monkeypatch.setattr(cdc, "appeler_llm", llm_ko)

    markdown = asyncio.run(cdc.generer_cahier_des_charges({"nom_entreprise": "KO SA"}, "fr"))
    assert "Non disponible" in markdown  # aucune section n'a de contenu, mais le doc existe


def test_construire_diapositives_5_a_8_slides_avec_avertissement_dans_roi():
    audit = {
        "nom_entreprise": "Slides SA",
        "problemes": {"pareto": [{"probleme": "Relances manuelles"}]},
        "priorites": {"moscow": {"must": ["Automatiser"]}, "chemin_critique": [{"id": "T1", "duree_jours": 5}]},
        "roi": {"synthese": "Gain notable."},
    }
    diapos = cdc.construire_diapositives(audit)
    assert 5 <= len(diapos) <= 8
    roi_slide = next(d for d in diapos if d["titre"] == "ROI estimé")
    assert roi_slide["notes"] == cdc.AVERTISSEMENT
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd briques/generateur && python3 -m pytest test_cdc.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'cdc'`

- [ ] **Step 3: Write `prompt_cahier_des_charges` and `cdc.py`**

Ajoute à `briques/generateur/prompts.py`, avant `prompt_plan_app` :

```python
_SECTIONS_CDC = [
    ("objectifs", "Objectifs"),
    ("utilisateurs", "Utilisateurs"),
    ("fonctionnalites", "Fonctionnalités"),
    ("regles_metier", "Règles métier"),
    ("architecture", "Architecture"),
    ("api", "API"),
    ("base_de_donnees", "Base de données"),
    ("interfaces", "Interfaces"),
    ("integrations", "Intégrations"),
    ("securite", "Sécurité"),
    ("tests", "Tests"),
    ("criteres_acceptation", "Critères d'acceptation"),
]


def prompt_cahier_des_charges(audit: dict, langue: str = "fr") -> str:
    nom = audit.get("nom_entreprise", "Entreprise inconnue")
    territoire = audit.get("territoire") or {}
    flux = audit.get("flux") or {}
    problemes = audit.get("problemes") or {}
    priorites = audit.get("priorites") or {}

    contexte = json.dumps({
        "nom_entreprise": nom,
        "business_model_canvas": territoire.get("business_model_canvas"),
        "ddd": territoire.get("ddd"),
        "glossaire_metier": territoire.get("glossaire_metier"),
        "value_stream_map": flux.get("value_stream_map"),
        "processus_cles": flux.get("processus_cles"),
        "ishikawa": problemes.get("ishikawa"),
        "theory_of_constraints": problemes.get("theory_of_constraints"),
        "moscow": priorites.get("moscow"),
        "chemin_critique": priorites.get("chemin_critique"),
        "swot": priorites.get("swot"),
        "okrs_proposes": priorites.get("okrs_proposes"),
    }, ensure_ascii=False, indent=2)

    cles = "\n".join(f'- "{cle}" : section "{titre}"' for cle, titre in _SECTIONS_CDC)

    return f"""Voici l'audit complet de l'entreprise "{nom}" :
{contexte}

Rédige un cahier des charges formel pour l'application sur-mesure à livrer à cette
entreprise. Utilise le vocabulaire de l'entreprise (glossaire_metier, ddd) partout où
c'est pertinent. Base les fonctionnalités sur le moscow (Must/Should/Could/Won't).

Retourne un JSON avec exactement ces clés, chacune un TEXTE markdown (pas un objet) :
{cles}

Chaque section doit être un texte markdown autonome et lisible (pas de titre ## à
l'intérieur, il est ajouté automatiquement), 2 à 6 paragraphes ou listes selon la section.
Ne mentionne PAS de chiffrage ROI — cette section est ajoutée séparément.{consigne_langue(langue)}"""
```

Crée `briques/generateur/cdc.py` :

```python
"""Cahier des charges (S229) — assemble un document markdown à partir d'un audit complet.

La section ROI est un littéral CODE, jamais généré par le LLM (même logique que
`briques/audit/chiffrage.py`) — le LLM ne produit QUE les 12 sections qualitatives.
"""
import logging

from gateway import appeler_llm
from prompts import prompt_cahier_des_charges, _SECTIONS_CDC

logger = logging.getLogger(__name__)

AVERTISSEMENT = "Estimation à valider avec le client — non contractuelle."


def _section_roi_markdown(roi: dict | None) -> str:
    if not roi or not isinstance(roi.get("problemes"), list) or not roi["problemes"]:
        return "_Chiffrage non disponible — relancer `POST /audits/{id}/chiffrer`._"
    lignes = [roi.get("synthese", "")]
    for p in roi["problemes"]:
        cout = p.get("cout_actuel_estime") or {}
        gain = p.get("gain_potentiel_estime") or {}
        lignes.append(
            f"- **{p.get('probleme', '—')}** ({p.get('pole', '—')}) — "
            f"coût actuel estimé {cout.get('bas', '?')}–{cout.get('haut', '?')} €/mois, "
            f"gain potentiel {gain.get('bas', '?')}–{gain.get('haut', '?')} €/mois "
            f"[{p.get('statut', 'hypothese_llm')}]. {p.get('avertissement', AVERTISSEMENT)}"
        )
    return "\n\n".join(lignes)


async def generer_cahier_des_charges(audit: dict, langue: str = "fr") -> str:
    """Retourne le markdown complet (12 sections LLM + section ROI déterministe)."""
    prompt = prompt_cahier_des_charges(audit, langue)
    sections: dict = {}
    for tentative in range(2):
        try:
            sections = await appeler_llm(prompt, langue)
            break
        except Exception as e:
            logger.warning(f"Cahier des charges tentative {tentative + 1} échouée : {e}")

    corps = "\n\n".join(
        f"## {titre}\n\n{sections.get(cle) or '_Non disponible._'}"
        for cle, titre in _SECTIONS_CDC
    )
    roi_md = f"## ROI\n\n{_section_roi_markdown(audit.get('roi'))}"
    return f"{corps}\n\n{roi_md}"


def construire_diapositives(audit: dict) -> list[dict]:
    """5-8 diapositives 'points clés' à partir de l'audit déjà chiffré — AUCUN appel LLM
    supplémentaire (réutilise problemes/priorites/roi déjà en base, coût marginal nul)."""
    nom = audit.get("nom_entreprise") or "Entreprise"
    problemes = audit.get("problemes") or {}
    priorites = audit.get("priorites") or {}
    roi = audit.get("roi") or {}
    pareto = (problemes.get("pareto") or [])[:5]
    must = ((priorites.get("moscow") or {}).get("must") or [])[:5]
    chemin_critique = (priorites.get("chemin_critique") or [])[:5]

    return [
        {"titre": nom, "points": ["Cahier des charges — points clés"]},
        {"titre": "Problèmes majeurs",
         "points": [p.get("probleme", "—") for p in pareto] or ["Aucun problème majeur identifié."]},
        {"titre": "ROI estimé",
         "points": [roi.get("synthese")] if roi.get("synthese")
                   else ["Chiffrage non disponible — relancer POST /audits/{id}/chiffrer."],
         "notes": AVERTISSEMENT},
        {"titre": "Solution proposée", "points": must or ["À définir."]},
        {"titre": "Priorités",
         "points": [f"{t.get('id', '?')} — {t.get('duree_jours', '?')}j" for t in chemin_critique]
                   or ["Aucune priorité chiffrée."]},
    ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd briques/generateur && python3 -m pytest test_cdc.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add briques/generateur/prompts.py briques/generateur/cdc.py briques/generateur/test_cdc.py
git commit -m "feat(generateur): S229 module cdc.py — markdown 12 sections + ROI déterministe + diapositives"
```

---

## Task 8 : `briques/generateur` — endpoints `POST`/`GET /audits/{id}/cahier-des-charges`

**Files:**
- Modify: `briques/generateur/main.py`
- Test: `briques/generateur/test_cdc.py`

**Interfaces:**
- Consumes: `cdc.generer_cahier_des_charges` (Task 7), `_charger_audit` (existant, `main.py:385`), `_dernier_cdc` (Task 6)
- Produces: `POST /audits/{audit_id}/cahier-des-charges`, `GET /audits/{audit_id}/cahier-des-charges`

- [ ] **Step 1: Write the failing test**

Ajouter à `briques/generateur/test_cdc.py` :

```python
def test_generer_cdc_audit_inexistant_retourne_404(client, monkeypatch):
    import main as gen_main

    async def audit_ko(audit_id):
        return {}
    monkeypatch.setattr(gen_main, "_charger_audit", audit_ko)

    resp = client.post("/audits/audit-inexistant/cahier-des-charges")
    assert resp.status_code == 404


def test_generer_cdc_audit_non_termine_retourne_400(client, monkeypatch):
    import main as gen_main

    async def audit_en_cours(audit_id):
        return {"statut": "en_cours"}
    monkeypatch.setattr(gen_main, "_charger_audit", audit_en_cours)

    resp = client.post("/audits/audit-en-cours/cahier-des-charges")
    assert resp.status_code == 400


def test_generer_cdc_bout_en_bout_puis_le_lire(client, monkeypatch):
    import main as gen_main
    import cdc

    async def audit_termine(audit_id):
        return {"statut": "termine", "nom_entreprise": "CDC SA"}
    monkeypatch.setattr(gen_main, "_charger_audit", audit_termine)

    async def faux_llm(prompt, langue="fr"):
        return {cle: f"Contenu {cle}" for cle, _ in cdc._SECTIONS_CDC}
    monkeypatch.setattr(cdc, "appeler_llm", faux_llm)

    resp = client.post("/audits/cdc-audit-1/cahier-des-charges")
    assert resp.status_code == 200
    assert "## Objectifs" in resp.json()["markdown"]
    assert resp.json()["pdf_chemin"] is None

    resp2 = client.get("/audits/cdc-audit-1/cahier-des-charges")
    assert resp2.status_code == 200
    assert resp2.json()["markdown"] == resp.json()["markdown"]


def test_lire_cdc_sans_generation_prealable_retourne_404(client):
    resp = client.get("/audits/jamais-genere/cahier-des-charges")
    assert resp.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd briques/generateur && python3 -m pytest test_cdc.py -k "generer_cdc or lire_cdc" -v`
Expected: FAIL with 404 (routes inexistantes)

- [ ] **Step 3: Add the endpoints**

Dans `briques/generateur/main.py`, ajoute l'import en tête de fichier (à côté des autres imports de modules locaux) :

```python
import cdc
```

Ajoute après `_dernier_cdc` (Task 6) :

```python
class DemandeCdc(BaseModel):
    langue: str = "fr"


@app.post("/audits/{audit_id}/cahier-des-charges")
async def generer_cdc_endpoint(audit_id: str, corps: DemandeCdc | None = None):
    corps = corps or DemandeCdc()
    audit = await _charger_audit(audit_id)
    if not audit:
        raise HTTPException(404, f"Audit introuvable ou brique Audit inaccessible : {audit_id}")
    if audit.get("statut") != "termine":
        raise HTTPException(400, f"L'audit n'est pas terminé (statut : {audit.get('statut')})")

    langue = normaliser_langue(corps.langue)
    markdown = await cdc.generer_cahier_des_charges(audit, langue)

    cdc_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    with _connexion() as conn:
        conn.execute(
            "INSERT INTO cahiers_des_charges (id, audit_id, markdown, statut, created_at) "
            "VALUES (?,?,?,?,?)",
            (cdc_id, audit_id, markdown, "genere", now),
        )
        conn.commit()
    return {"id": cdc_id, "audit_id": audit_id, "markdown": markdown,
            "pdf_chemin": None, "pptx_chemin": None, "statut": "genere"}


@app.get("/audits/{audit_id}/cahier-des-charges")
def lire_cdc(audit_id: str):
    row = _dernier_cdc(audit_id)
    if not row:
        raise HTTPException(404, "Aucun cahier des charges — lance d'abord POST /cahier-des-charges")
    return row
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd briques/generateur && python3 -m pytest test_cdc.py -v`
Expected: PASS (11 tests)

- [ ] **Step 5: Commit**

```bash
git add briques/generateur/main.py briques/generateur/test_cdc.py
git commit -m "feat(generateur): S229 POST/GET /audits/{id}/cahier-des-charges"
```

---

## Task 9 : `briques/generateur` — export PDF (`EXPORT_URL`/`EXPORT_KEY` + `GET .../pdf`)

**Files:**
- Modify: `briques/generateur/main.py`
- Modify: `briques/generateur/docker-compose.yml`
- Test: `briques/generateur/test_cdc.py`

**Interfaces:**
- Produces: `GET /audits/{audit_id}/cahier-des-charges/pdf` → `{"id", "audit_id", "pdf_url"}`

- [ ] **Step 1: Write the failing test**

Ajouter à `briques/generateur/test_cdc.py` :

```python
def test_pdf_sans_cdc_retourne_404(client):
    resp = client.get("/audits/jamais-genere/cahier-des-charges/pdf")
    assert resp.status_code == 404


def test_pdf_genere_via_export_puis_reutilise_le_lien_stocke(client, monkeypatch):
    import main as gen_main
    import cdc
    import httpx

    async def audit_termine(audit_id):
        return {"statut": "termine", "nom_entreprise": "PDF SA"}
    monkeypatch.setattr(gen_main, "_charger_audit", audit_termine)

    async def faux_llm(prompt, langue="fr"):
        return {cle: f"Contenu {cle}" for cle, _ in cdc._SECTIONS_CDC}
    monkeypatch.setattr(cdc, "appeler_llm", faux_llm)

    client.post("/audits/pdf-audit-1/cahier-des-charges")

    appels = {"n": 0}
    _VRAI_CLIENT = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        appels["n"] += 1
        return httpx.Response(200, json={"url": "/fichiers/export-abc123.pdf", "fichier": "export-abc123.pdf"})

    def faux_async_client(*a, **k):
        k.pop("timeout", None)
        return _VRAI_CLIENT(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(gen_main.httpx, "AsyncClient", faux_async_client)

    resp = client.get("/audits/pdf-audit-1/cahier-des-charges/pdf")
    assert resp.status_code == 200
    assert resp.json()["pdf_url"] == "/fichiers/export-abc123.pdf"
    assert appels["n"] == 1

    resp2 = client.get("/audits/pdf-audit-1/cahier-des-charges/pdf")
    assert resp2.json()["pdf_url"] == "/fichiers/export-abc123.pdf"
    assert appels["n"] == 1  # pas de second appel réseau : déjà stocké


def test_pdf_export_injoignable_retourne_502(client, monkeypatch):
    import main as gen_main
    import cdc
    import httpx

    async def audit_termine(audit_id):
        return {"statut": "termine", "nom_entreprise": "PDF KO SA"}
    monkeypatch.setattr(gen_main, "_charger_audit", audit_termine)

    async def faux_llm(prompt, langue="fr"):
        return {cle: f"Contenu {cle}" for cle, _ in cdc._SECTIONS_CDC}
    monkeypatch.setattr(cdc, "appeler_llm", faux_llm)

    client.post("/audits/pdf-audit-ko/cahier-des-charges")

    _VRAI_CLIENT = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("export down")

    def faux_async_client(*a, **k):
        k.pop("timeout", None)
        return _VRAI_CLIENT(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(gen_main.httpx, "AsyncClient", faux_async_client)

    resp = client.get("/audits/pdf-audit-ko/cahier-des-charges/pdf")
    assert resp.status_code == 502

    # Le markdown reste consultable malgré l'échec d'export.
    resp2 = client.get("/audits/pdf-audit-ko/cahier-des-charges")
    assert resp2.status_code == 200
    assert resp2.json()["pdf_chemin"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd briques/generateur && python3 -m pytest test_cdc.py -k test_pdf -v`
Expected: FAIL with 404 (route inexistante)

- [ ] **Step 3: Add EXPORT_URL wiring and the endpoint**

Dans `briques/generateur/main.py`, ajoute avec les autres constantes d'URL (à côté de `AUDIT_URL`, ligne 26) :

```python
# Brique « export » (S229) : rendu PDF/PPTX déterministe (aucune IA, aucun coût).
# Peut être fermée par API_KEYS (S211, même motif que INGESTION_KEY côté audit) — présenter
# la clé si elle existe. NE JAMAIS déclarer `EXPORT_KEY=${EXPORT_KEY:-}` dans docker-compose
# (piège « env shadow » : chaîne vide qui écraserait la vraie valeur du .env racine).
EXPORT_URL = os.getenv("EXPORT_URL", "http://host.docker.internal:6150")
_EXPORT_CLE = os.getenv("EXPORT_KEY")
EXPORT_ENTETES = {"X-API-Key": _EXPORT_CLE} if _EXPORT_CLE else {}
```

Ajoute l'endpoint après `lire_cdc` (Task 8) :

```python
@app.get("/audits/{audit_id}/cahier-des-charges/pdf")
async def cdc_pdf(audit_id: str):
    row = _dernier_cdc(audit_id)
    if not row:
        raise HTTPException(404, "Aucun cahier des charges — lance d'abord POST /cahier-des-charges")
    if row.get("pdf_chemin"):
        return {"id": row["id"], "audit_id": audit_id, "pdf_url": row["pdf_chemin"]}

    audit = await _charger_audit(audit_id)
    nom = audit.get("nom_entreprise") or "Entreprise"
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(f"{EXPORT_URL}/pdf", headers=EXPORT_ENTETES, json={
                "titre": f"Cahier des charges — {nom}",
                "markdown": row["markdown"],
                "theme": "rapport",
            })
            r.raise_for_status()
            pdf_url = r.json()["url"]
    except Exception as e:
        raise HTTPException(502, f"Brique export inaccessible ou en échec : {e}")

    with _connexion() as conn:
        conn.execute("UPDATE cahiers_des_charges SET pdf_chemin=? WHERE id=?", (pdf_url, row["id"]))
        conn.commit()
    return {"id": row["id"], "audit_id": audit_id, "pdf_url": pdf_url}
```

Dans `briques/generateur/docker-compose.yml`, ajoute sous la ligne `- DONNEES_SRC=/briques_src/donnees` :

```yaml
      # Export PDF/PPTX du cahier des charges (S229). EXPORT_KEY (si la brique export est
      # fermée par API_KEYS) vient du .env racine via env_file — jamais redéclarée ici.
      - EXPORT_URL=http://host.docker.internal:6150
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd briques/generateur && python3 -m pytest test_cdc.py -v`
Expected: PASS (14 tests)

- [ ] **Step 5: Commit**

```bash
git add briques/generateur/main.py briques/generateur/docker-compose.yml briques/generateur/test_cdc.py
git commit -m "feat(generateur): S229 GET /audits/{id}/cahier-des-charges/pdf via briques/export"
```

---

## Task 10 : `briques/generateur` — bonus PPTX

**Files:**
- Modify: `briques/generateur/main.py`
- Test: `briques/generateur/test_cdc.py`

**Interfaces:**
- Consumes: `cdc.construire_diapositives` (Task 7)
- Produces: `POST /audits/{audit_id}/cahier-des-charges/pptx` → `{"id", "audit_id", "pptx_url"}`

- [ ] **Step 1: Write the failing test**

Ajouter à `briques/generateur/test_cdc.py` :

```python
def test_pptx_sans_cdc_retourne_404(client):
    resp = client.post("/audits/jamais-genere/cahier-des-charges/pptx")
    assert resp.status_code == 404


def test_pptx_genere_via_export(client, monkeypatch):
    import main as gen_main
    import cdc
    import httpx

    async def audit_termine(audit_id):
        return {"statut": "termine", "nom_entreprise": "PPTX SA",
                "problemes": {"pareto": []}, "priorites": {"moscow": {"must": []}}, "roi": None}
    monkeypatch.setattr(gen_main, "_charger_audit", audit_termine)

    async def faux_llm(prompt, langue="fr"):
        return {cle: f"Contenu {cle}" for cle, _ in cdc._SECTIONS_CDC}
    monkeypatch.setattr(cdc, "appeler_llm", faux_llm)

    client.post("/audits/pptx-audit-1/cahier-des-charges")

    _VRAI_CLIENT = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"url": "/fichiers/export-xyz789.pptx", "fichier": "export-xyz789.pptx"})

    def faux_async_client(*a, **k):
        k.pop("timeout", None)
        return _VRAI_CLIENT(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(gen_main.httpx, "AsyncClient", faux_async_client)

    resp = client.post("/audits/pptx-audit-1/cahier-des-charges/pptx")
    assert resp.status_code == 200
    assert resp.json()["pptx_url"] == "/fichiers/export-xyz789.pptx"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd briques/generateur && python3 -m pytest test_cdc.py -k test_pptx -v`
Expected: FAIL with 404 (route inexistante)

- [ ] **Step 3: Add the endpoint**

Ajoute après `cdc_pdf` (Task 9) :

```python
@app.post("/audits/{audit_id}/cahier-des-charges/pptx")
async def cdc_pptx(audit_id: str):
    row = _dernier_cdc(audit_id)
    if not row:
        raise HTTPException(404, "Aucun cahier des charges — lance d'abord POST /cahier-des-charges")
    if row.get("pptx_chemin"):
        return {"id": row["id"], "audit_id": audit_id, "pptx_url": row["pptx_chemin"]}

    audit = await _charger_audit(audit_id)
    nom = audit.get("nom_entreprise") or "Entreprise"
    diapositives = cdc.construire_diapositives(audit)
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(f"{EXPORT_URL}/pptx", headers=EXPORT_ENTETES, json={
                "titre": f"Cahier des charges — {nom}",
                "diapositives": diapositives,
                "theme": "sobre",
            })
            r.raise_for_status()
            pptx_url = r.json()["url"]
    except Exception as e:
        raise HTTPException(502, f"Brique export inaccessible ou en échec : {e}")

    with _connexion() as conn:
        conn.execute("UPDATE cahiers_des_charges SET pptx_chemin=? WHERE id=?", (pptx_url, row["id"]))
        conn.commit()
    return {"id": row["id"], "audit_id": audit_id, "pptx_url": pptx_url}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd briques/generateur && python3 -m pytest test_cdc.py -v`
Expected: PASS (16 tests)

- [ ] **Step 5: Commit**

```bash
git add briques/generateur/main.py briques/generateur/test_cdc.py
git commit -m "feat(generateur): S229 bonus POST /audits/{id}/cahier-des-charges/pptx"
```

---

## Task 11 : `briques/generateur` — manifest.json (4 capacités)

**Files:**
- Modify: `briques/generateur/manifest.json`

**Interfaces:**
- Produces: capacités `generateur_cahier_des_charges_generer/lire/pdf/pptx` pointant sur les routes réelles des Tasks 8-10.

- [ ] **Step 1: Update the manifest**

Dans `briques/generateur/manifest.json`, remplace le bloc `depends_on` (lignes 12-16) :

```json
  "depends_on": [
    "audit",
    "gateway",
    "donnees",
    "export"
  ],
```

Remplace le bloc `offre` (lignes 17-22) :

```json
  "offre": [
    "generation_app",
    "export_html",
    "dashboard_entreprise",
    "packaging_deploiement",
    "cahier_des_charges"
  ],
```

Remplace le bloc `besoin` (lignes 23-27) :

```json
  "besoin": [
    "audit_entreprise",
    "llm_chat",
    "persistance_crud",
    "rendu_pdf"
  ],
```

La capacité `generateur_app_apercu` (dernière du tableau `capacites`) se termine ainsi (lignes 88-101, INCHANGÉES) :

```json
    {
      "nom": "generateur_app_apercu",
      "description": "Retourne l'URL d'aperçu d'une app générée pour la prévisualiser. L'app doit avoir le statut 'généré'.",
      "methode": "GET",
      "chemin": "/apps/{app_id}/apercu",
      "params": {
        "app_id": {
          "type": "string",
          "description": "Identifiant de l'app générée.",
          "requis": true
        }
      },
      "action": false
    }
  ]
```

Remplace ces 15 lignes (de `    {` à `  ]`, la fermeture du tableau `capacites`) par :

```json
    {
      "nom": "generateur_app_apercu",
      "description": "Retourne l'URL d'aperçu d'une app générée pour la prévisualiser. L'app doit avoir le statut 'généré'.",
      "methode": "GET",
      "chemin": "/apps/{app_id}/apercu",
      "params": {
        "app_id": {
          "type": "string",
          "description": "Identifiant de l'app générée.",
          "requis": true
        }
      },
      "action": false
    },
    {
      "nom": "generateur_cahier_des_charges_generer",
  "description": "Génère (ou régénère) le cahier des charges formel d'un audit terminé : 12 sections structurées (objectifs, utilisateurs, fonctionnalités MoSCoW, règles métier, architecture, API, base de données, interfaces, intégrations, sécurité, tests, critères d'acceptation) + une section ROI reprenant le chiffrage de l'audit (voir audit_chiffrer) avec son avertissement de non-garantie. ACTION (appel LLM) : confirme=true requis.",
  "methode": "POST",
  "chemin": "/audits/{audit_id}/cahier-des-charges",
  "params": {
    "audit_id": {
      "type": "string",
      "description": "Identifiant de l'audit source, terminé (voir audit_lire).",
      "requis": true
    },
    "langue": {
      "type": "string",
      "description": "Langue du document généré (défaut 'fr')."
    }
  },
  "action": true,
  "niveau": 1
},
{
  "nom": "generateur_cahier_des_charges_lire",
  "description": "Lit le dernier cahier des charges généré pour un audit (markdown + statut + lien PDF/PPTX si déjà exportés). Lecture seule.",
  "methode": "GET",
  "chemin": "/audits/{audit_id}/cahier-des-charges",
  "params": {
    "audit_id": {
      "type": "string",
      "description": "Identifiant de l'audit source.",
      "requis": true
    }
  },
  "action": false,
  "niveau": 0
},
{
  "nom": "generateur_cahier_des_charges_pdf",
  "description": "Exporte le dernier cahier des charges en PDF (thème 'rapport', via la brique export) et renvoie son URL de téléchargement. Réutilise le PDF déjà produit si disponible (pas de re-génération LLM). ACTION (écrit un fichier) : confirme=true requis.",
  "methode": "GET",
  "chemin": "/audits/{audit_id}/cahier-des-charges/pdf",
  "params": {
    "audit_id": {
      "type": "string",
      "description": "Identifiant de l'audit source.",
      "requis": true
    }
  },
  "action": true,
  "niveau": 1
},
{
  "nom": "generateur_cahier_des_charges_pptx",
  "description": "Exporte une version 'points clés' (5-8 diapositives : problèmes majeurs, ROI, solution proposée, priorités) du cahier des charges en PPTX via la brique export. Réutilise le PPTX déjà produit si disponible. ACTION (écrit un fichier) : confirme=true requis.",
  "methode": "POST",
  "chemin": "/audits/{audit_id}/cahier-des-charges/pptx",
  "params": {
    "audit_id": {
      "type": "string",
      "description": "Identifiant de l'audit source.",
      "requis": true
    }
  },
  "action": true,
  "niveau": 1
}
  ]
}
```

Cette dernière capacité `generateur_cahier_des_charges_pptx` ferme le tableau `capacites` (`]`) puis l'objet racine du manifest (`}`) — vérifie qu'aucune virgule finale ne traîne et que `"taches": []` (lignes 28-38 du fichier original) reste inchangé et placé AVANT `"capacites"` comme dans le fichier d'origine.

- [ ] **Step 2: Validate the JSON**

Run: `cd briques/generateur && python3 -c "import json; json.load(open('manifest.json'))" && echo OK`
Expected: `OK`

- [ ] **Step 3: Cross-check routes vs manifest**

Run: `cd briques/generateur && for r in "audits/{audit_id}/cahier-des-charges\"" "audits/{audit_id}/cahier-des-charges/pdf" "audits/{audit_id}/cahier-des-charges/pptx"; do grep -c "$r" main.py manifest.json; done`
Expected : chaque route apparaît au moins une fois dans `main.py` (décorateur) et une fois dans `manifest.json` (`"chemin"`).

- [ ] **Step 4: Commit**

```bash
git add briques/generateur/manifest.json
git commit -m "docs(generateur): S229 4 capacités manifest cahier_des_charges"
```

---

## Task 12 : `briques/generateur` — traçabilité : `generer()` réutilise le CDC stocké

**Files:**
- Modify: `briques/generateur/prompts.py`
- Modify: `briques/generateur/generateur.py`
- Modify: `briques/generateur/main.py`
- Test: `briques/generateur/test_generateur.py` (NOUVEAU)

**Interfaces:**
- Consumes: `_dernier_cdc` (Task 6)
- Produces: `prompt_plan_app(audit, langue, cahier_des_charges=None)`, `generer_app_complete(..., cahier_des_charges=None)`

- [ ] **Step 1: Write the failing test**

Créer `briques/generateur/test_generateur.py` :

```python
"""Non-régression S229 : prompt_plan_app avec/sans cahier des charges."""
import os
import tempfile

os.environ.setdefault("GATEWAY_KEY", "test-offline")
os.environ.setdefault("DB_PATH", os.path.join(tempfile.gettempdir(), "test_generateur_plan.db"))

from prompts import prompt_plan_app

AUDIT = {
    "nom_entreprise": "Atelier Fleurs",
    "territoire": {
        "ddd": {"bounded_contexts": [{"nom": "Atelier"}], "agregats": ["Composition"]},
        "glossaire_metier": [{"terme_generique": "produit", "terme_entreprise": "composition"}],
        "business_model_canvas": {"proposition_valeur": "Fleurs sur-mesure"},
    },
    "flux": {"value_stream_map": {"efficacite_flux_pct": 60}},
    "problemes": {"theory_of_constraints": {"goulot_principal": "Atelier"}},
    "priorites": {
        "swot": {"forces": ["Savoir-faire"]},
        "moscow": {"must": ["Devis rapides"]},
        "okrs_proposes": [{"objectif": "Réduire les délais"}],
    },
}


def test_sans_cdc_utilise_l_assemblage_informel_existant():
    prompt = prompt_plan_app(AUDIT, "fr")
    assert "Fleurs sur-mesure" in prompt  # proposition_valeur du canvas, toujours présent en repli
    assert "Devis rapides" in prompt      # must_have du moscow
    assert "CAHIER DES CHARGES" not in prompt


def test_avec_cdc_utilise_le_document_et_garde_le_vocabulaire():
    cdc_markdown = "## Objectifs\n\nAugmenter le CA de 20%.\n\n## Fonctionnalités\n\nGestion des devis."
    prompt = prompt_plan_app(AUDIT, "fr", cahier_des_charges=cdc_markdown)
    assert cdc_markdown in prompt
    assert "composition" in prompt.lower()  # glossaire_metier toujours injecté
    assert "Composition" in prompt  # agregats toujours injecté
    assert "RÈGLE DE VOCABULAIRE" in prompt


def test_les_deux_branches_contiennent_le_meme_schema_json():
    sans_cdc = prompt_plan_app(AUDIT, "fr")
    avec_cdc = prompt_plan_app(AUDIT, "fr", cahier_des_charges="## Objectifs\n\nX")
    for cle in ('"nom_app"', '"navigation"', '"entites"', '"kpis"', '"actions_immediates"'):
        assert cle in sans_cdc
        assert cle in avec_cdc
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd briques/generateur && python3 -m pytest test_generateur.py -v`
Expected: FAIL with `TypeError: prompt_plan_app() got an unexpected keyword argument 'cahier_des_charges'`

- [ ] **Step 3: Refactor `prompt_plan_app` and wire the CDC through**

Dans `briques/generateur/prompts.py`, remplace ENTIÈREMENT la fonction `prompt_plan_app` existante par :

```python
def _schema_json_plan_app() -> str:
    return """Génère un JSON avec EXACTEMENT ces clés pour configurer son tableau de bord applicatif :

- "nom_app" : nom court et percutant pour l'application (ex: "AlphaOps", "VentesPilot")
- "sous_titre" : slogan ou description en une ligne (max 80 caractères)
- "secteur" : secteur d'activité détecté (ex: "Commerce B2B", "Services RH", "Industrie")
- "couleur_principale" : code hex correspondant au secteur (ex: "#1D4ED8" pour finance, "#059669" pour commerce)
- "couleur_secondaire" : couleur complémentaire en hex
- "resume_executif" : 3 phrases résumant la situation de l'entreprise, ses défis principaux et la valeur de cette app
- "navigation" : liste de 3 à 6 sections opérationnelles de l'app, NOMMÉES d'après les bounded_contexts/le vocabulaire de l'entreprise. Chaque section avec :
    - "id" : identifiant court en minuscules sans espaces (ex: "atelier", "commandes")
    - "label" : le libellé affiché, dans les mots de l'entreprise (ex: "Atelier floral", "Réservations")
    - "icone" : nom d'icône Bootstrap Icons (ex: "bi-flower1", "bi-calendar-check")
- "entites" : liste des 2 à 5 objets métier manipulés par l'app, repris des "agregats". Ce sont de VRAIS modules opérationnels (on doit pouvoir créer/lister des enregistrements). Chaque entité avec :
    - "id" : identifiant court en minuscules sans espaces ni accents (ex: "devis", "client", "chantier")
    - "nom" : le terme EXACT de l'entreprise au singulier (ex: "Composition florale", "Adhérent", "Devis")
    - "description" : à quoi sert cette entité dans l'entreprise (1 phrase)
    - "icone" : nom d'icône Bootstrap Icons
    - "champs" : liste de 3 à 6 attributs, chacun un OBJET avec :
        - "cle" : identifiant court sans espaces ni accents (ex: "client", "montant", "date_pose", "statut")
        - "label" : le libellé affiché, dans le vocabulaire de l'entreprise (ex: "Nom du client", "Montant TTC")
        - "type" : un parmi "texte" | "nombre" | "montant" | "date" | "statut"
        - "options" : UNIQUEMENT si type = "statut", liste de 2 à 5 valeurs possibles (ex: ["Brouillon","Envoyé","Accepté","Refusé"])
    - "exemples" : 2 à 3 enregistrements d'exemple réalistes et cohérents avec l'entreprise, chacun un objet {cle: valeur} reprenant les "cle" des champs ci-dessus
- "glossaire" : reprends le glossaire_metier ci-dessus (liste de {"terme_generique","terme_entreprise","definition"}), corrigé/complété si besoin. Sert à expliquer le vocabulaire de l'app.
- "kpis" : liste de 4 à 6 indicateurs clés détectés dans l'audit, libellés avec le vocabulaire de l'entreprise, chacun avec :
    - "nom" : libellé court
    - "valeur" : valeur estimée ou constatée (string)
    - "unite" : unité (%, jours, €, etc.)
    - "icone" : nom d'icône Bootstrap Icons (ex: "bi-graph-up-arrow", "bi-clock", "bi-people")
    - "tendance" : "hausse" | "baisse" | "stable" | "alerte"
- "actions_immediates" : liste de 3 actions prioritaires à lancer, chacune avec :
    - "titre" : titre court de l'action
    - "description" : explication en 1 phrase
    - "priorite" : "critique" | "haute" | "normale"
    - "icone" : nom d'icône Bootstrap Icons
- "message_introduction" : phrase d'accueil personnalisée affichée en haut du dashboard (max 120 caractères)"""


def prompt_plan_app(audit: dict, langue: str = "fr", cahier_des_charges: str | None = None) -> str:
    nom = audit.get("nom_entreprise", "Entreprise inconnue")
    territoire = audit.get("territoire") or {}
    ddd = territoire.get("ddd") or {}
    glossaire = territoire.get("glossaire_metier") or []

    regle_vocabulaire = """RÈGLE DE VOCABULAIRE — la plus importante : cette application doit parler la langue de l'entreprise.
Utilise SYSTÉMATIQUEMENT les "terme_entreprise" du glossaire_metier et les noms des "agregats"/"bounded_contexts"
ci-dessus dans TOUS les libellés que tu génères (navigation, entités, KPIs, actions, titres). N'invente pas de
termes génériques ("Items", "Produits", "Module 1") si l'entreprise a son propre mot."""

    if cahier_des_charges:
        # S229 : le cahier des charges (déjà validé, synthèse structurée des 4 couches de
        # l'audit) remplace l'assemblage informel SWOT/TOC/OKRs/MoSCoW ci-dessous — traçable
        # à un document réel et relisable. Le vocabulaire (glossaire/agrégats) reste puisé
        # directement dans `territoire` : structurellement fiable, il conditionne TOUTES les
        # sorties, pas seulement une section du CDC.
        vocabulaire = json.dumps({
            "nom_entreprise": nom,
            "bounded_contexts": ddd.get("bounded_contexts"),
            "agregats": ddd.get("agregats"),
            "glossaire_metier": glossaire,
        }, ensure_ascii=False, indent=2)
        return f"""Voici le CAHIER DES CHARGES validé de "{nom}" — base-toi dessus en priorité pour l'analyse (il est plus complet et plus fiable qu'un audit brut) :
{cahier_des_charges}

Vocabulaire de l'entreprise (à respecter dans TOUS les libellés) :
{vocabulaire}

{regle_vocabulaire}

{_schema_json_plan_app()}
{consigne_langue(langue)}"""

    # Repli : aucun cahier des charges généré pour cet audit — comportement inchangé.
    canvas = territoire.get("business_model_canvas") or {}
    flux = audit.get("flux") or {}
    problemes = audit.get("problemes") or {}
    priorites = audit.get("priorites") or {}
    swot = priorites.get("swot") or {}
    moscow = priorites.get("moscow") or {}
    vsm = flux.get("value_stream_map") or {}
    toc = problemes.get("theory_of_constraints") or {}
    okrs = priorites.get("okrs_proposes") or []

    contexte = json.dumps({
        "nom_entreprise": nom,
        "proposition_valeur": canvas.get("proposition_valeur"),
        "segments_clients": canvas.get("segments_clients"),
        "forces": swot.get("forces"),
        "faiblesses": swot.get("faiblesses"),
        "opportunites": swot.get("opportunites"),
        "menaces": swot.get("menaces"),
        "goulot_principal": toc.get("goulot_principal"),
        "efficacite_flux_pct": vsm.get("efficacite_flux_pct"),
        "must_have": moscow.get("must"),
        "objectifs_okr": [o.get("objectif") for o in okrs[:3]],
        "bounded_contexts": ddd.get("bounded_contexts"),
        "agregats": ddd.get("agregats"),
        "glossaire_metier": glossaire,
    }, ensure_ascii=False, indent=2)

    return f"""Voici l'analyse stratégique de l'entreprise "{nom}" :
{contexte}

{regle_vocabulaire}

{_schema_json_plan_app()}
{consigne_langue(langue)}"""
```

Dans `briques/generateur/generateur.py`, modifie `generer_app_complete` :

```python
async def generer_app_complete(audit: dict, app_id: str = "", api_base: str = "",
                               oria: dict | None = None, langue: str = "fr",
                               cahier_des_charges: str | None = None) -> tuple[dict, str]:
    """Retourne (plan, html) à partir d'un audit complet.

    Si `app_id` + `api_base` sont fournis → app en mode hébergé (persistance serveur) ;
    sinon → mode autonome (localStorage). `oria` (optionnel) = config de la messagerie
    interne (espace + salons) à embarquer dans l'app. `langue` = langue de l'app livrée
    (contenu LLM + châssis) ; défaut/repli `fr`. `cahier_des_charges` (S229, optionnel) =
    markdown du CDC déjà généré pour cet audit — remplace l'assemblage informel si présent."""
    langue = normaliser_langue(langue)
    try:
        prompt = prompt_plan_app(audit, langue, cahier_des_charges)
        plan = await appeler_llm(prompt, langue)
    except Exception:
        plan = _PLAN_FALLBACK.copy()
        plan["nom_app"] = f"Dashboard {audit.get('nom_entreprise', 'Entreprise')}"

    html = generer_html(audit, plan, app_id=app_id, api_base=api_base, oria=oria, langue=langue)
    return plan, html
```

Dans `briques/generateur/main.py`, modifie `_generer_en_background` (signature + appel) :

```python
async def _generer_en_background(app_id: str, audit: dict, mode: str, messagerie: bool,
                                 email_client: str | None = None,
                                 contact_client: str | None = None,
                                 langue: str = "fr",
                                 cahier_des_charges: str | None = None):
    try:
        hebergee = mode == "hebergee"
        api_base = DONNEES_URL_PUBLIQUE if hebergee else ""

        oria_cfg = None
        if hebergee and messagerie:
            import anyio
            oria_cfg = await anyio.to_thread.run_sync(_provisionner_messagerie, audit)

        plan, html = await generer_app_complete(
            audit, app_id=(app_id if hebergee else ""), api_base=api_base, oria=oria_cfg,
            langue=langue, cahier_des_charges=cahier_des_charges,
        )
```

(le reste de `_generer_en_background` est inchangé)

Modifie `generer()` pour charger et propager le CDC stocké (juste avant `background_tasks.add_task`) :

```python
    with _connexion() as conn:
        conn.execute(
            "INSERT INTO apps (id, date_creation, audit_id, nom_entreprise, statut, mode, langue) "
            "VALUES (?,?,?,?,?,?,?)",
            (app_id, now, demande.audit_id, nom, "en_cours", mode, langue),
        )
        conn.commit()

    cdc_existant = _dernier_cdc(demande.audit_id)
    cahier_des_charges = cdc_existant["markdown"] if cdc_existant else None
    background_tasks.add_task(_generer_en_background, app_id, audit, mode,
                              demande.messagerie, demande.email_client,
                              demande.contact_client, langue, cahier_des_charges)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd briques/generateur && python3 -m pytest test_generateur.py test_cdc.py -v`
Expected: PASS (tous les tests, aucune régression sur les tests existants du fichier)

Run aussi : `cd briques/generateur && python3 -m pytest -v` (suite complète de la brique)
Expected: PASS — aucune régression sur `test_appliquer.py`, `test_balayage.py`, `test_bundle.py`, `test_bundle_studio.py`, `test_client_provisioning.py`, `test_langues.py`, `test_pont_crm.py`, `test_revue.py`.

- [ ] **Step 5: Commit**

```bash
git add briques/generateur/prompts.py briques/generateur/generateur.py briques/generateur/main.py briques/generateur/test_generateur.py
git commit -m "feat(generateur): S229 generer() traçable au cahier des charges quand il existe (repli inchangé sinon)"
```

---

## Task 13 : garde-fou transverse — l'avertissement survit mot pour mot partout

**Files:**
- Modify: `briques/audit/test_audit.py`
- Modify: `briques/generateur/test_cdc.py`

**Interfaces:**
- Consumes: `chiffrage.AVERTISSEMENT`, `cdc.AVERTISSEMENT` (doivent rester des littéraux identiques — la vision insiste sur ce point)

- [ ] **Step 1: Write the failing test**

Ajouter à `briques/audit/test_audit.py` :

```python
def test_avertissement_est_le_litteral_exact_de_la_vision():
    """Garde-fou permanent : une régression qui changerait ce texte (ou le ferait générer
    par le LLM) doit casser CE test explicitement, pas être découverte en prod."""
    assert chiffrage.AVERTISSEMENT == "Estimation à valider avec le client — non contractuelle."


def test_toute_sortie_chiffrer_avec_hypothese_contient_l_avertissement_mot_pour_mot(client, monkeypatch):
    resp = client.post("/audits/import", json={"nom_entreprise": "Garde SA", "statut": "termine"})
    audit_id = resp.json()["id"]

    async def faux_llm(prompt):
        return {"problemes": [{"probleme": "X", "pole": "commercial",
                                "cout_actuel_estime": {"bas": 1, "haut": 2},
                                "gain_potentiel_estime": {"bas": 1, "haut": 2}}]}
    monkeypatch.setattr(chiffrage, "appeler_llm", faux_llm)

    resp2 = client.post(f"/audits/{audit_id}/chiffrer")
    assert chiffrage.AVERTISSEMENT in str(resp2.json())
```

Ajouter à `briques/generateur/test_cdc.py` :

```python
def test_cdc_avertissement_est_le_meme_litteral_que_l_audit():
    """Duplication intentionnelle entre briques (cf. Global Constraints) — mais le TEXTE
    doit rester identique, sinon le client voit deux formulations différentes du même
    avertissement selon qu'il lit le JSON de l'audit ou le markdown du CDC."""
    assert cdc.AVERTISSEMENT == "Estimation à valider avec le client — non contractuelle."


def test_markdown_cdc_avec_roi_contient_l_avertissement_mot_pour_mot(monkeypatch):
    async def faux_llm(prompt, langue="fr"):
        return {cle: f"Contenu {cle}" for cle, _ in cdc._SECTIONS_CDC}
    monkeypatch.setattr(cdc, "appeler_llm", faux_llm)

    audit = {"nom_entreprise": "Garde SA", "roi": {
        "synthese": "Gain notable.",
        "problemes": [{"probleme": "X", "pole": "commercial",
                       "cout_actuel_estime": {"bas": 1, "haut": 2},
                       "gain_potentiel_estime": {"bas": 1, "haut": 2},
                       "statut": "hypothese_llm", "avertissement": cdc.AVERTISSEMENT}],
    }}
    markdown = asyncio.run(cdc.generer_cahier_des_charges(audit, "fr"))
    assert cdc.AVERTISSEMENT in markdown


def test_diapositive_roi_contient_l_avertissement_mot_pour_mot():
    audit = {"nom_entreprise": "Garde SA", "roi": {"synthese": "Gain notable."}}
    diapos = cdc.construire_diapositives(audit)
    roi_slide = next(d for d in diapos if d["titre"] == "ROI estimé")
    assert roi_slide["notes"] == cdc.AVERTISSEMENT
```

- [ ] **Step 2: Run tests to verify they pass immediately**

Ces tests ne dépendent d'aucun code nouveau (tout a été écrit dans les Tasks 2, 7, 9-10) — ils doivent PASSER dès l'écriture, pas échouer d'abord. C'est le comportement attendu pour un garde-fou permanent : il documente et verrouille un invariant déjà vrai.

Run: `cd briques/audit && python3 -m pytest test_audit.py -k avertissement -v`
Run: `cd briques/generateur && python3 -m pytest test_cdc.py -k "avertissement or diapositive_roi" -v`
Expected: PASS (les deux commandes)

- [ ] **Step 3: Run the full test suites of both briques one last time**

Run: `cd briques/audit && python3 -m pytest -v`
Run: `cd briques/generateur && python3 -m pytest -v`
Expected: PASS intégral, aucune régression.

- [ ] **Step 4: Commit**

```bash
git add briques/audit/test_audit.py briques/generateur/test_cdc.py
git commit -m "test(audit,generateur): S229 garde-fou permanent — l'avertissement ROI survit mot pour mot (JSON+markdown+PPTX)"
```

---

## Hors périmètre (rappel, cf. spec)

- Saisie du coût horaire dans l'entretien guidé (S228) — `cout_horaire` reste un appel manuel/API.
- Mesure du ROI réel post-déploiement (`briques/generateur/revue.py`) — non touchée par ce plan.
- UI de visualisation du CDC/ROI — capacités API + export PDF/PPTX seulement.
- Validation/signature du CDC par le client — hors Workplace.
