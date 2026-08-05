# Prospection B2C — pilotage assistant (catalogue + manifests) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** L'assistant peut composer une campagne B2C en conversation (« trouve-moi
des leads pour du photovoltaïque à Bordeaux ») : il découvre les critères de signal
disponibles via un nouveau catalogue en lecture, crée une campagne typée, prépare
et envoie des courriers postaux — chaque étape passant par le manifest existant
(motif déjà en place pour le pipeline B2B, S169/170), avec le même gate de
confirmation avant toute action.

**Architecture:** Une seule route de code neuve (`GET
/logements/criteres-disponibles` dans `geo`) ; le reste de ce plan est des
modifications de `manifest.json` dans 4 briques (`geo`, `forge`, `veille-prospection`,
`mail`) pour exposer les routes des 4 plans précédents. **Ce dépôt possède déjà un
filet automatisé qui valide qu'un `manifest.json` correspond exactement à la vraie
route FastAPI** (`tests/test_contrat_capacites.py`, S210) — chaque task de ce plan
s'appuie dessus au lieu d'écrire de nouveaux tests.

**Tech Stack:** JSON (manifests), FastAPI (une seule route neuve).

## Global Constraints

- Chaque `capacite` ajoutée doit passer `tests/test_contrat_capacites.py` (3
  vérifications : la route existe, aucun `param` déclaré n'est fantôme, aucun champ
  requis par la route n'est omis des `params`) — lancé à la racine du dépôt, PAS
  depuis le dossier de la brique.
- Toute action à effet réel (préparer un courrier, le déposer) reste `"action":
  true`, avec la mention explicite dans la `description` (motif déjà en place :
  « ACTION : confirme=true requis. » / « ACTION à EFFET DE BORD RÉEL »).
- Aucune capacité n'expose `/repondre/{token}` : c'est une page publique pour le
  DESTINATAIRE du courrier (un particulier), jamais un outil que l'assistant
  appelle pour le compte du tenant.
- Aucune autonomie supplémentaire de l'assistant au-delà de ce qui existe déjà
  (choix de zone, décision d'envoyer) — cf. Non-objectifs de la spec.

---

### Task 1: Catalogue des critères logement (`geo`)

**Files:**
- Modify: `briques/geo/main.py`
- Modify: `briques/geo/manifest.json`
- Test: `briques/geo/test_prospection.py` (route), `tests/test_contrat_capacites.py` (contrat)

**Interfaces:**
- Produces: route `GET /logements/criteres-disponibles` — `{"criteres": [{"id",
  "label", "valeurs_possibles", "description"}]}`.

- [ ] **Step 1: Écrire le test de la route**

Ajouter à `briques/geo/test_prospection.py` :

```python
def test_logements_criteres_disponibles_expose_le_dpe():
    r = client.get("/logements/criteres-disponibles", headers={"X-API-Key": "x"})
    assert r.status_code == 200
    criteres = r.json()["criteres"]
    dpe = next(c for c in criteres if c["id"] == "dpe")
    assert set(dpe["valeurs_possibles"]) == {"A", "B", "C", "D", "E", "F", "G"}
    assert dpe["description"]
```

- [ ] **Step 2: Lancer le test pour vérifier qu'il échoue**

Run: `cd briques/geo && python3 -m pytest test_prospection.py -k criteres_disponibles -v`
Expected: FAIL avec `404 Not Found`

- [ ] **Step 3: Implémenter la route**

Ajouter dans `briques/geo/main.py`, à la suite de `config` (juste avant la section
« Objets géolocalisés ») :

```python
@app.get("/logements/criteres-disponibles")
def logements_criteres_disponibles(_tenant: str = Depends(tenant_actuel)):
    """Catalogue des critères de détection disponibles pour les logements — sert à
    l'assistant pour composer une combinaison pertinente selon l'activité demandée
    (ex. « photovoltaïque » → DPE mauvais), en CONVERSATION avec l'utilisateur,
    plutôt qu'une table figée métier→critères en dur dans le code. Lecture seule,
    aucun gate (pas une action)."""
    return {"criteres": [
        {"id": "dpe", "label": "Diagnostic de performance énergétique",
         "valeurs_possibles": ["A", "B", "C", "D", "E", "F", "G"],
         "description": "Grade énergétique du logement (source ADEME, ouverte et "
                        "gratuite). E/F/G = « passoires thermiques » — pertinent "
                        "pour l'isolation, le chauffage, le photovoltaïque "
                        "(compenser une consommation élevée)."},
    ]}
```

- [ ] **Step 4: Lancer le test**

Run: `cd briques/geo && python3 -m pytest test_prospection.py -k criteres_disponibles -v`
Expected: PASS

- [ ] **Step 5: Ajouter la capacité au manifest**

Dans `briques/geo/manifest.json`, ajouter à la fin du tableau `capacites` (après
l'entrée `geo_zone_supprimer`, avant le `]` de fermeture — ne pas oublier la
virgule après l'accolade précédente) :

```json
    {
      "nom": "geo_logements_criteres_disponibles",
      "description": "Liste les critères de détection disponibles pour cibler des LOGEMENTS (ex. grade DPE) — sert à composer une campagne de prospection B2C en conversation (« trouve-moi des leads pour du photovoltaïque » → propose DPE E/F/G) sans table figée métier→critères. Lecture seule.",
      "methode": "GET",
      "chemin": "/logements/criteres-disponibles",
      "params": {},
      "action": false,
      "niveau": 0,
      "socle": false
    }
```

Dans la même liste, mettre à jour l'entrée `geo_zone_ajouter` existante : son
champ `params.type.description` et ajouter un nouveau param `parametres` (ajouté
par le plan geo, Task 6 de `2026-08-05-prospection-b2c-1-geo-logements.md`) :

```json
    "type": {
      "type": "string",
      "description": "« entreprise » (défaut), « association », ou « logement » (prospection B2C — voir geo_logements_criteres_disponibles pour les critères)."
    },
```

et ajouter, dans le même objet `params` de `geo_zone_ajouter`, après `"naf"` :

```json
    "parametres": {
      "type": "object",
      "description": "Réglages du type de zone. Pour « logement » : {\"grades_dpe\": [\"E\",\"F\",\"G\"]} (voir geo_logements_criteres_disponibles). Facultatif."
    }
```

- [ ] **Step 6: Vérifier le contrat manifeste↔route**

Run: `python3 -m pytest tests/test_contrat_capacites.py -k geo -v` (depuis la
RACINE du dépôt, pas depuis `briques/geo`)
Expected: PASS pour toutes les capacités `geo` (y compris les deux nouvellement
modifiées/ajoutées) — si `pyproj` n'est pas installé dans cet environnement, les
tests `geo` sont SKIP (« dépendance absente »), pas un échec : lancer alors
`cd briques/geo && pip install -r requirements.txt` puis relancer la commande
ci-dessus.

- [ ] **Step 7: Commit**

```bash
git add briques/geo/main.py briques/geo/manifest.json briques/geo/test_prospection.py
git commit -m "feat(geo): catalogue de critères logement + manifest zone logement"
```

---

### Task 2: `forge` — documenter les prospects logement dans le manifest

Pure documentation : `forge_crm_importer_lot` (route déjà modifiée par le plan
forge, `2026-08-05-prospection-b2c-2-forge-crm.md`) accepte déjà des prospects
`{adresse, ...}` — son manifest ne le dit pas encore.

**Files:**
- Modify: `briques/forge/manifest.json`
- Test: `tests/test_contrat_capacites.py`

**Interfaces:**
- Aucune (changement de texte seulement, `params.prospects` reste `type: array`,
  aucun champ requis/accepté ne change au sens du filet).

- [ ] **Step 1: Modifier la description**

Dans `briques/forge/manifest.json`, capacité `forge_crm_importer_lot`, remplacer
le champ `params.prospects.description` :

```json
    "prospects": {
      "type": "array",
      "description": "Liste d'objets prospect. Deux formes : ENTREPRISE {nom|entreprise, email?, telephone?, site?, naf?, commune?, ref_externe?, notes?} (résultat de geo_prospecter_lot type entreprise), ou LOGEMENT {adresse, commune?, code_postal?, grade_dpe?, surface_m2?, periode_construction?, ref_externe?} (résultat de geo_prospecter_lot type logement — JAMAIS de nom de personne, un logement n'a pas de propriétaire identifiable). Passe directement le champ « prospects » renvoyé par geo_prospecter_lot.",
      "requis": true
    }
```

- [ ] **Step 2: Vérifier le contrat manifeste↔route**

Run: `python3 -m pytest tests/test_contrat_capacites.py -k forge -v` (depuis la racine)
Expected: PASS (changement de texte seul, le contrat structurel est inchangé)

- [ ] **Step 3: Commit**

```bash
git add briques/forge/manifest.json
git commit -m "docs(forge): manifest documente les prospects logement sans nom"
```

---

### Task 3: `veille-prospection` — campagne typée dans le manifest

**Files:**
- Modify: `briques/veille-prospection/manifest.json`
- Test: `tests/test_contrat_capacites.py`

**Interfaces:**
- Modifie `veille_prospection_campagne_creer` pour exposer le param `type`
  (ajouté par le plan veille-prospection, Task 2 de
  `2026-08-05-prospection-b2c-3-veille-prospection.md`).

- [ ] **Step 1: Modifier la capacité**

Dans `briques/veille-prospection/manifest.json`, capacité
`veille_prospection_campagne_creer`, ajouter dans `params` (après `zone_id`) :

```json
      "type": {
        "type": "string",
        "description": "« b2b » (défaut, entreprises) ou « b2c » (particuliers/logements — la zone référencée doit être de type « logement », voir geo_zone_ajouter et geo_logements_criteres_disponibles)."
      }
```

- [ ] **Step 2: Vérifier le contrat manifeste↔route**

Run: `python3 -m pytest tests/test_contrat_capacites.py -k veille_prospection -v`
(depuis la racine)
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add briques/veille-prospection/manifest.json
git commit -m "feat(veille-prospection): manifest expose le type b2b/b2c de campagne"
```

---

### Task 4: `mail` — démarchage postal dans le manifest

**Files:**
- Modify: `briques/mail/manifest.json`
- Test: `tests/test_contrat_capacites.py`

**Interfaces:**
- Ajoute `mail_demarchage_postal_preparer` et `mail_demarchage_postal_envoyer`,
  routes ajoutées par le plan mail (`2026-08-05-prospection-b2c-4-mail-postal.md`,
  Tasks 3-4).

- [ ] **Step 1: Ajouter les deux capacités**

Dans `briques/mail/manifest.json`, ajouter à la fin du tableau `capacites` (après
l'entrée `mail_supprimer`) :

```json
    {
      "nom": "mail_demarchage_postal_preparer",
      "description": "DÉMARCHAGE POSTAL : prépare EN LOT des courriers personnalisés (JAMAIS de nom de personne — seulement adresse/commune, un logement n'a pas de propriétaire identifiable) à partir d'une liste de prospects — typiquement issue de forge_crm_lister (statut « à contacter ») ou de geo_prospecter_lot type logement. Le gabarit accepte {adresse}/{commune}. Chaque courrier reçoit un token de réponse unique (le destinataire scanne un QR pour manifester son intérêt — c'est CETTE réponse, pas le courrier envoyé, qui devient un lead vendable). Un REGISTRE de cadence/opt-out séparé de l'email est respecté. Rien n'est déposé : voir mail_demarchage_postal_envoyer. ACTION : confirme=true requis.",
      "methode": "POST",
      "chemin": "/demarchage-postal/preparer",
      "params": {
        "prospects": {
          "type": "array",
          "description": "Liste [{adresse (requis), commune?, grade_dpe?, lead_id?}]. Passe directement les prospects logement du CRM (forge_crm_lister) ou de geo_prospecter_lot.",
          "requis": true
        },
        "gabarit": {
          "type": "string",
          "description": "Corps du courrier (gabarit : {adresse}/{commune} uniquement — jamais {nom}).",
          "requis": true
        },
        "expediteur": {
          "type": "string",
          "description": "Identité de l'expéditeur affichée en bas du courrier — OBLIGATOIRE.",
          "requis": true
        },
        "cooldown_jours": {
          "type": "integer",
          "description": "Délai minimum en jours entre deux contacts d'une même adresse (défaut 90)."
        },
        "max_contacts": {
          "type": "integer",
          "description": "Nombre maximum de contacts par adresse (défaut 2)."
        }
      },
      "action": true
    },
    {
      "nom": "mail_demarchage_postal_envoyer",
      "description": "Dépose RÉELLEMENT un courrier postal préparé (id obtenu via mail_demarchage_postal_preparer) — ou, tant qu'aucun prestataire postal réel n'est branché, SIMULE honnêtement (rien n'est physiquement envoyé). ACTION à EFFET DE BORD RÉEL une fois un vrai prestataire branché : confirme=true requis, seulement après accord explicite.",
      "methode": "POST",
      "chemin": "/demarchage-postal/envoyer/{courrier_id}",
      "params": {
        "courrier_id": {
          "type": "string",
          "description": "Identifiant du courrier à déposer (obtenu via mail_demarchage_postal_preparer).",
          "requis": true
        }
      },
      "action": true
    }
```

- [ ] **Step 2: Vérifier le contrat manifeste↔route**

Run: `python3 -m pytest tests/test_contrat_capacites.py -k mail -v` (depuis la racine)
Expected: PASS pour toutes les capacités `mail`, y compris les deux nouvelles — si
`python-multipart` n'est pas installé dans cet environnement, l'import de la
brique `mail` peut échouer et SKIP ses capacités (« dépendance absente ») plutôt
que de faire échouer le test : installer alors
`cd briques/mail && pip install -r requirements.txt` puis relancer.

- [ ] **Step 3: Commit**

```bash
git add briques/mail/manifest.json
git commit -m "feat(mail): manifest expose le démarchage postal (préparer/envoyer)"
```

---

## Self-Review

**Couverture spec** (section « Pilotage assistant ») : catalogue de critères ✓
(Task 1, route + capacité), création de campagne b2c pilotable ✓ (Task 3, déjà
possible via `veille_prospection_campagne_creer` + le nouveau param `type`),
préparation/envoi des courriers pilotables ✓ (Task 4), lecture des leads qualifiés
✓ (déjà couvert par `forge_crm_lister` existant, filtre `statut` libre — vérifié
dans le plan forge, aucune capacité neuve nécessaire).

**Filet de non-régression** : chaque task s'appuie sur
`tests/test_contrat_capacites.py`, déjà présent dans ce dépôt (S210) — pas de test
maison réinventé pour vérifier qu'un manifest correspond à sa route.

**Aucune fuite d'autonomie** : aucune capacité de ce plan ne permet à l'assistant
de choisir seul une zone ou de décider seul d'un envoi réel sans un appel explicite
(le gate `confirme=true` reste porté par la convention textuelle déjà en usage
dans tout le manifeste du parc, pas réinventée ici).

**Ordre d'exécution recommandé pour toute la série** : ce plan (5) dépend
fonctionnellement des Tasks de code des plans 1 (geo), 2 (forge), 3
(veille-prospection) et 4 (mail) — à exécuter APRÈS eux, jamais avant (les routes
qu'il manifeste doivent déjà exister, sinon `test_capacite_pointe_sur_une_route_existante`
échoue).
