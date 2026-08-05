# Prospection B2C — forge : CRM logements (adresse, jamais de nom) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `POST /crm/import-lot` (adapter `briques/forge/main.py`) sait importer des
prospects « logement » (adresse + grade DPE, jamais de nom de personne) au même
titre que des prospects entreprise, avec un dédoublonnage par adresse.

**Architecture:** Extension additive de trois fonctions existantes
(`_signatures`, `_prospect_vers_lead`, la garde « rien pour nommer le prospect » de
`crm_importer_lot`) — aucun changement de schéma côté `forge` core (`CrmLeads.statut`
est déjà une string libre, `CrmLeads` n'a pas besoin d'une colonne `adresse` : elle
va dans `notes`, comme le site/NAF/commune le font déjà pour les entreprises).

**Tech Stack:** FastAPI (adapter mince, pas le monolithe `forge/core`).

## Global Constraints

- Aucun nom de personne ne doit jamais être écrit dans un lead créé depuis un
  prospect « logement » — ni dans `nom`, ni dans `notes` (cf. contrainte légale
  MAJIC, `docs/superpowers/specs/2026-08-05-prospection-b2c-signal-identite-design.md`).
- Le comportement existant pour les prospects « entreprise » (dédoublonnage
  email/nom, contenu des notes) reste identique bit-à-bit — extension additive
  uniquement, aucune branche `if type ==` n'est nécessaire : la détection se fait
  sur la PRÉSENCE du champ `adresse` (un prospect entreprise n'en a jamais).
- Le champ `id` du lead créé (déjà exposé par `_resume_lead`, vérifié dans le code
  actuel — **pas un changement à faire**) sert de `lead_id` pour le plan mail
  (capture de réponse → `PATCH /crm/{lead_id}`, plan séparé).

---

### Task 1: Dédoublonnage par adresse (`_signatures`)

**Files:**
- Modify: `briques/forge/main.py:620-630` (`_signatures`)
- Test: `briques/forge/test_crm_import_lot.py`

**Interfaces:**
- Produces: `_signatures(lead: dict) -> set[str]` gagne une signature `"adr:" +
  norm(adresse)` quand `lead.get("adresse")` est présent — consommé par
  `crm_importer_lot` (inchangé, Task 3).

- [ ] **Step 1: Écrire le test**

Ajouter à `briques/forge/test_crm_import_lot.py` :

```python
def test_import_lot_dedoublonne_logements_par_adresse(monkeypatch):
    _install_faux_core(monkeypatch, [])
    d = client.post("/crm/import-lot", json={"prospects": [
        {"adresse": "12 Rue des Lilas, Castres", "grade_dpe": "F"},
        {"adresse": "12 Rue des Lilas, Castres", "grade_dpe": "F"},  # même adresse
        {"adresse": "4 Impasse du Moulin, Castres", "grade_dpe": "G"},
    ]}).json()
    assert d["crees"] == 2 and d["doublons"] == 1
```

- [ ] **Step 2: Lancer le test pour vérifier qu'il échoue**

Run: `cd briques/forge && python3 -m pytest test_crm_import_lot.py -k adresse -v`
Expected: FAIL — les 3 prospects sont actuellement `ignores` (aucun `nom`/`entreprise`),
donc `d["crees"] == 0`, pas `2`.

(Ce test échoue pour la MÊME raison que la Task 3 va résoudre — c'est attendu ; les
Tasks 1 à 3 sont livrées ensemble et ce test ne passera vraiment qu'après la Task 3.
On le garde en rouge pour l'instant et on avance.)

- [ ] **Step 3: Implémenter**

Dans `briques/forge/main.py`, modifier `_signatures` :

```python
def _signatures(lead: dict) -> set[str]:
    """Empreintes de dé-doublonnage d'un prospect : l'email (fort), le nom d'entreprise
    (repli B2B), ou l'adresse (repli B2C — un logement n'a ni email ni entreprise).
    Deux prospects qui partagent l'une de ces empreintes sont considérés identiques —
    l'import est ainsi ré-exécutable sans empiler des doublons."""
    sigs: set[str] = set()
    if lead.get("email"):
        sigs.add("email:" + _norm(lead["email"]))
    ent = lead.get("entreprise") or lead.get("nom")
    if ent:
        sigs.add("ent:" + _norm(ent))
    if lead.get("adresse"):
        sigs.add("adr:" + _norm(lead["adresse"]))
    return sigs
```

- [ ] **Step 4: Commit (le test reste rouge, attendu)**

```bash
git add briques/forge/main.py briques/forge/test_crm_import_lot.py
git commit -m "feat(forge): dédoublonnage CRM par adresse (prospects logement)"
```

---

### Task 2: Traduction prospect logement → lead (`_prospect_vers_lead`)

**Files:**
- Modify: `briques/forge/main.py:633-652` (`_prospect_vers_lead`)
- Test: `briques/forge/test_crm_import_lot.py`

**Interfaces:**
- Consumes: rien de nouveau.
- Produces: `_prospect_vers_lead(p, statut)` gère un prospect sans `nom`/`entreprise`
  mais avec `adresse` — `nom` devient `"Occupant — {adresse}"` (jamais un nom de
  personne), `notes` inclut adresse/commune/grade DPE/surface/période de
  construction. Consommé par `crm_importer_lot` (Task 3).

- [ ] **Step 1: Écrire le test**

Ajouter à `briques/forge/test_crm_import_lot.py` :

```python
def test_prospect_vers_lead_logement_jamais_de_nom_de_personne():
    from main import _prospect_vers_lead
    lead = _prospect_vers_lead({
        "adresse": "12 Rue des Lilas, Castres", "commune": "Castres",
        "code_postal": "81100", "grade_dpe": "F", "surface_m2": 90.0,
        "periode_construction": "avant 1948", "ref_externe": "2611E0067705R",
    }, statut="à contacter")
    assert lead["nom"] == "Occupant — 12 Rue des Lilas, Castres"
    assert lead.get("entreprise") is None
    assert lead.get("email") is None and lead.get("telephone") is None
    assert "Grade DPE : F" in lead["notes"]
    assert "Surface : 90.0 m²" in lead["notes"]
    assert "Période de construction : avant 1948" in lead["notes"]
    assert "DPE : 2611E0067705R" in lead["notes"]
    assert lead["statut"] == "à contacter"
```

- [ ] **Step 2: Lancer le test pour vérifier qu'il échoue**

Run: `cd briques/forge && python3 -m pytest test_crm_import_lot.py -k jamais_de_nom -v`
Expected: FAIL — `_prospect_vers_lead` actuel calcule `nom = p.get("nom") or ent`
où `ent = ""` (pas d'entreprise) → `lead["nom"] == ""`, pas `"Occupant — ..."`.

- [ ] **Step 3: Implémenter**

Remplacer `_prospect_vers_lead` dans `briques/forge/main.py` :

```python
def _prospect_vers_lead(p: dict, statut: str) -> dict:
    """Traduit un prospect enrichi (geo_prospecter_lot) en lead CRM. Deux formes : un
    prospect ENTREPRISE (nom/entreprise, infos site/NAF/SIREN dans les notes) ou un
    prospect LOGEMENT (adresse, jamais de nom de personne — contrainte légale, fichiers
    fonciers inaccessibles à une entreprise commerciale). Le nom d'un lead logement est
    TOUJOURS « Occupant — {adresse} », jamais un nom trouvé ailleurs."""
    adresse = (p.get("adresse") or "").strip()
    if adresse and not (p.get("entreprise") or p.get("nom")):
        notes = [f"Adresse : {adresse}"]
        if p.get("commune"):
            notes.append(f"Commune : {p['commune']}")
        if p.get("code_postal"):
            notes.append(f"Code postal : {p['code_postal']}")
        if p.get("grade_dpe"):
            notes.append(f"Grade DPE : {p['grade_dpe']}")
        if p.get("surface_m2") is not None:
            notes.append(f"Surface : {p['surface_m2']} m²")
        if p.get("periode_construction"):
            notes.append(f"Période de construction : {p['periode_construction']}")
        if p.get("ref_externe"):
            notes.append(f"DPE : {p['ref_externe']}")
        notes.append("Importé depuis la veille geo (logement)")
        if (p.get("notes") or "").strip():
            notes.append(p["notes"].strip())
        return {"nom": f"Occupant — {adresse}", "statut": statut,
                "notes": " · ".join(notes)}
    ent = (p.get("entreprise") or p.get("nom") or "").strip()
    notes = []
    if p.get("site"):
        notes.append(f"Site : {p['site']}")
    if p.get("naf"):
        notes.append(f"NAF : {p['naf']}")
    if p.get("commune"):
        notes.append(f"Commune : {p['commune']}")
    if p.get("ref_externe"):
        notes.append(f"SIREN : {p['ref_externe']}")
    notes.append("Importé depuis la veille geo")
    if (p.get("notes") or "").strip():
        notes.append(p["notes"].strip())
    charge = {"nom": (p.get("nom") or ent), "entreprise": ent,
              "email": p.get("email"), "telephone": p.get("telephone"),
              "statut": statut, "notes": " · ".join(notes)}
    return {k: v for k, v in charge.items() if v is not None}
```

(Le chemin entreprise, en dessous du `if`, est un COPIER-COLLER EXACT de l'ancien
corps de la fonction — comportement bit-à-bit inchangé pour tout prospect qui a un
`nom`/`entreprise`.)

- [ ] **Step 4: Lancer le test**

Run: `cd briques/forge && python3 -m pytest test_crm_import_lot.py -k jamais_de_nom -v`
Expected: PASS

- [ ] **Step 5: Lancer toute la suite du fichier pour vérifier la non-régression B2B**

Run: `cd briques/forge && python3 -m pytest test_crm_import_lot.py -v`
Expected: PASS pour tous les tests SAUF `test_import_lot_dedoublonne_logements_par_adresse`
(Task 1, encore rouge — attendu, résolu à la Task 3)

- [ ] **Step 6: Commit**

```bash
git add briques/forge/main.py briques/forge/test_crm_import_lot.py
git commit -m "feat(forge): traduit un prospect logement en lead sans nom de personne"
```

---

### Task 3: Accepter un prospect nommé par son adresse (`crm_importer_lot`)

La garde actuelle (« rien pour nommer le prospect ») rejette tout prospect sans
`nom` ni `entreprise` — il faut qu'un prospect avec seulement `adresse` passe.

**Files:**
- Modify: `briques/forge/main.py:678-684` (boucle de `crm_importer_lot`)
- Test: `briques/forge/test_crm_import_lot.py`

**Interfaces:**
- Consumes: `_signatures` (Task 1), `_prospect_vers_lead` (Task 2).
- Produces: `POST /crm/import-lot` accepte des prospects `{adresse, ...}` sans
  `nom`/`entreprise`.

- [ ] **Step 1: Écrire les tests**

Ajouter à `briques/forge/test_crm_import_lot.py` :

```python
def test_import_lot_accepte_prospects_logement_sans_nom(monkeypatch):
    store = _install_faux_core(monkeypatch, [])
    d = client.post("/crm/import-lot", json={"prospects": [
        {"adresse": "12 Rue des Lilas, Castres", "commune": "Castres",
         "grade_dpe": "F", "surface_m2": 90.0, "ref_externe": "2611E0067705R"},
        {"adresse": "4 Impasse du Moulin, Castres", "grade_dpe": "G"},
    ]}).json()
    assert d["crees"] == 2 and d["ignores"] == 0
    assert all(l["nom"].startswith("Occupant — ") for l in store)
    assert all(l.get("entreprise") in (None, "") for l in store)


def test_import_lot_prospects_lead_id_present_dans_la_reponse(monkeypatch):
    """Contrat requis par le futur moteur postal (mail) : chaque prospect créé doit
    porter son `id` de lead CRM dans la réponse, pour pouvoir qualifier le bon lead à
    la réception d'une réponse. Déjà vrai via `_resume_lead` — ce test le fige en
    non-régression explicite plutôt que de compter sur un effet de bord non testé."""
    _install_faux_core(monkeypatch, [])
    d = client.post("/crm/import-lot", json={"prospects": [
        {"adresse": "9 Rue Haute, Castres", "grade_dpe": "E"},
    ]}).json()
    assert d["prospects"][0]["id"]


def test_import_lot_toujours_ignore_prospect_totalement_vide(monkeypatch):
    _install_faux_core(monkeypatch, [])
    d = client.post("/crm/import-lot", json={"prospects": [
        {"email": "anonyme@x.fr"},   # ni nom, ni entreprise, ni adresse
        {"adresse": "  "},           # adresse vide après trim
    ]}).json()
    assert d["crees"] == 0 and d["ignores"] == 2
```

- [ ] **Step 2: Lancer les tests pour vérifier qu'ils échouent**

Run: `cd briques/forge && python3 -m pytest test_crm_import_lot.py -k "logement or lead_id or totalement_vide" -v`
Expected: FAIL — la garde actuelle rejette tout prospect sans `nom`/`entreprise`,
`d["ignores"]` compte les prospects logement au lieu de `d["crees"]`.

- [ ] **Step 3: Implémenter**

Dans `crm_importer_lot`, remplacer la garde :

```python
        for p in prospects:
            if not isinstance(p, dict):
                ignores += 1
                continue
            if not (p.get("nom") or p.get("entreprise") or (p.get("adresse") or "").strip()):
                ignores += 1                       # rien pour nommer le prospect
                continue
```

(Seule cette ligne `if not (...)` change ; le reste de la boucle — calcul des
signatures, appel `_appel_protege`, etc. — est déjà générique et fonctionne tel
quel avec les Tasks 1-2.)

- [ ] **Step 4: Lancer toute la suite du fichier**

Run: `cd briques/forge && python3 -m pytest test_crm_import_lot.py -v`
Expected: PASS (tous les tests, y compris celui laissé rouge à la Task 1)

- [ ] **Step 5: Lancer la suite complète de la brique forge (adapter)**

Run: `cd briques/forge && python3 -m pytest -v`
Expected: PASS (aucune régression sur les autres fichiers de test de l'adapter)

- [ ] **Step 6: Commit**

```bash
git add briques/forge/main.py briques/forge/test_crm_import_lot.py
git commit -m "feat(forge): import-lot accepte un prospect nommé par sa seule adresse"
```

---

## Self-Review

**Couverture spec** (section « Backend — forge ») : dédoublonnage par adresse ✓
(Task 1), jamais de nom de personne dans `nom`/`notes` ✓ (Task 2, testé
explicitement), `lead_id` dans la réponse ✓ (déjà vrai, figé en test Task 3) — le
point noté dans la spec comme « à vérifier/ajuster » a été vérifié : **aucun
changement de contrat n'était nécessaire**, `_resume_lead` exposait déjà `id`.

**Non-régression B2B** : chaque task relance la suite existante ; Task 2 documente
explicitement que le chemin entreprise est un copier-coller à l'identique du corps
précédent de `_prospect_vers_lead`, pas une réécriture.

**Cohérence des types** : `_prospect_vers_lead(p: dict, statut: str) -> dict` garde
exactement la même signature avant/après — aucun appelant (Task 3, ou le futur plan
mail) n'a besoin de changer sa façon de l'invoquer.
