# Sprint S149 — Briques ETL et Audit : couverture de tests minimale

> **But du sprint** : écrire les tests de base pour `briques/etl/` (502 lignes, 0 tests)
> et `briques/audit/` (393 lignes, 0 tests), afin qu'une régression dans ces deux
> briques soit détectable avant déploiement.

- **Sprint** : S149
- **Catégorie** : Qualité / Tests / Briques
- **Statut** : CODE-COMPLET
- **Date de planification** : 2026-07-04
- **Date de livraison** : 2026-07-04
- **Briques concernées** : `briques/etl/`, `briques/audit/`
- **Prérequis** : aucun (tests offline avec client HTTP de test)

---

## Contexte

### Brique ETL (`briques/etl/`)

Extraction, transformation et chargement de données structurées.
Fichiers : `main.py`, `extraction.py`, `stockage.py`.
**0 test** sur 502 lignes de code de production.

### Brique Audit (`briques/audit/`)

Analyse qualité de documents/contenus via LLM.
Fichiers : `main.py`, `analyse.py`, `prompts.py`, `gateway.py`.
**0 test** sur 393 lignes de code de production.

Ces deux briques ont des manifests et des endpoints actifs câblés au Cœur.
Une régression (endpoint cassé, import manquant, erreur de schéma) ne serait
pas détectée avant `docker logs` sur le HP.

---

## Chantiers

### Brique ETL

#### C0 — Lire les endpoints de `briques/etl/main.py`

```bash
grep -n "@app\.\|@router\." briques/etl/main.py
```

Identifier les 3-5 endpoints principaux à couvrir.

#### C1 — Créer `briques/etl/test_etl.py`

Structure de base :

```python
import pytest
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_sante():
    """L'endpoint de santé répond 200."""
    resp = client.get("/sante")
    assert resp.status_code == 200

def test_manifest():
    """Le manifest est valide et expose des capacités."""
    resp = client.get("/manifest")
    assert resp.status_code == 200
    data = resp.json()
    assert "capacites" in data
    assert len(data["capacites"]) > 0

def test_extraction_champ_manquant_retourne_422():
    """Un appel sans le champ requis retourne 422, pas 500."""
    resp = client.post("/extraire", json={})
    assert resp.status_code in (400, 422)

def test_extraction_source_valide():
    """Extraction avec une source valide retourne un résultat structuré."""
    resp = client.post("/extraire", json={"source": "texte de test", "format": "json"})
    # Accepter 200 (succès) ou 422 (validation) — jamais 500
    assert resp.status_code != 500

def test_stockage_liste():
    """Lister les extractions stockées ne crashe pas."""
    resp = client.get("/extractions")
    assert resp.status_code in (200, 404)
    assert resp.status_code != 500
```

Adapter les noms d'endpoints après lecture de `main.py`.

### Brique Audit

#### C2 — Lire les endpoints de `briques/audit/main.py`

```bash
grep -n "@app\.\|@router\." briques/audit/main.py
```

#### C3 — Créer `briques/audit/test_audit.py`

```python
import pytest
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_sante():
    resp = client.get("/sante")
    assert resp.status_code == 200

def test_manifest():
    resp = client.get("/manifest")
    assert resp.status_code == 200
    data = resp.json()
    assert "capacites" in data

def test_analyser_champ_manquant():
    """Corps vide → 422, pas 500."""
    resp = client.post("/analyser", json={})
    assert resp.status_code in (400, 422)

def test_analyser_texte_court(monkeypatch):
    """Analyser un texte court : le LLM est mocké, pas d'appel réseau."""
    # Mocker l'appel au gateway LLM
    import analyse
    monkeypatch.setattr(analyse, "appeler_llm",
        lambda *a, **kw: {"score": 0.8, "remarques": ["ok"]})
    resp = client.post("/analyser", json={"contenu": "Test contenu."})
    assert resp.status_code in (200, 422)
    assert resp.status_code != 500

def test_prompts_disponibles():
    """Les prompts d'audit sont chargés et non vides."""
    from prompts import PROMPTS
    assert isinstance(PROMPTS, dict)
    assert len(PROMPTS) > 0
```

#### C4 — Vérifier les imports et dépendances offline

S'assurer que les tests peuvent tourner sans le gateway LLM ni d'autres services
(monkeypatch ou repli mock intégré à la brique si présent).

---

## Critère d'acceptation

- `briques/etl/test_etl.py` : ≥ 5 tests verts
- `briques/audit/test_audit.py` : ≥ 5 tests verts
- Aucun test ne nécessite un LLM réel ou Docker (mock ou repli)
- Les deux suites passent avec `pytest briques/etl/` et `pytest briques/audit/`
- Zéro 500 dans les scénarios testés

---

## Effort estimé

**Demi-journée (3-4h)**
- C0+C1 (ETL) : 1h30 — lire le code + écrire les tests + ajuster
- C2+C3 (Audit) : 1h30 — idem
- C4 (isolation offline) : 1h — identifier et mocker les dépendances réseau

## Valeur

Deux briques précédemment invisibles au CI deviennent testables. Un import cassé,
une signature d'endpoint modifiée, ou un schéma Pydantic mal défini sont désormais
détectés avant `docker compose up`.
