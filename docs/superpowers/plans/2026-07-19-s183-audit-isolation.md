# S183 — Audit d'isolation « chacun son espace » Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Documenter l'état d'isolation multi-tenant de toutes les briques du Workplace (cercle privé par personne + bundle client business), et corriger le seul trou identifié comme sûr à corriger immédiatement (endpoint `/jobs/{job_id}` de `synopsis` sans authentification alors que ses routes sœurs en ont une).

**Architecture:** Un audit en lecture seule (déjà mené) a produit un tableau brique→verdict. Ce plan (1) fige ce tableau dans un rapport versionné, (2) applique le fix trivial retenu en TDD, (3) met à jour la mémoire projet avec la liste priorisée pour la suite.

**Tech Stack:** FastAPI (briques Python), pytest, Markdown.

## Global Constraints

- Aucune migration de données dans ce sprint (spec `docs/superpowers/specs/2026-07-19-s183-audit-isolation-design.md`, section "Décision fix-maintenant vs report").
- Aucun changement de comportement visible pour l'usage actuel : le fix doit être invisible pour tout appelant qui respecte déjà le contrat de la brique (clé API si configurée).
- `make test-core` doit rester au vert après le sprint (ne touche pas au Cœur ici, mais vérifié par prudence).

---

### Task 1: Rapport d'audit d'isolation

**Files:**
- Create: `docs/rapport-s183-audit-isolation.md`

**Interfaces:**
- Consumes: rien (contenu factuel figé ci-dessous, issu du balayage mené pendant le brainstorming S183).
- Produces: document de référence lié depuis la mémoire (Task 3) et depuis tout futur sprint de suite (ex. futur sprint mail).

- [ ] **Step 1: Écrire le rapport**

Créer `docs/rapport-s183-audit-isolation.md` avec exactement ce contenu :

```markdown
# Audit d'isolation multi-tenant — S183 (2026-07-19)

Méthodologie : docs/superpowers/specs/2026-07-19-s183-audit-isolation-design.md
Deux modèles de tenant coexistent : (a) cercle privé par personne (Keycloak, X-User-Id,
motif établi sur l'agenda en S182) et (b) bundle client business (X-Compte-Id/ADMIN_COMPTE_ID,
épopée bundles S95-S99). L'audit couvre les deux.

## Constat central

`core/outils_communs._entetes_brique` (core/outils_communs.py:48-70) n'envoie que trois
signaux : `X-Compte-Id` (toujours, `ADMIN_COMPTE_ID`), `X-API-Key` (si `{BRIQUE}_KEY` défini),
et `X-User-Id` — **seulement pour `agenda`** (commentaire explicite : "les autres briques
ignorent cet en-tête"). `core/contexte_tenant.py` sait aussi produire `X-Org-ID` (donnees) et
`X-Forge-User-Token` (forge), mais `entetes_donnees()` n'est câblé que dans le flux de cycle de
vie de bundle (`core/cycle_de_vie.py:214`), pas dans le chemin générique d'appel d'outils LLM :
`donnees` ne reçoit donc jamais `X-Org-ID` via les outils de l'assistant et retombe sur l'org
"defaut".

La majorité des briques produit implémentent leur propre multi-tenant **par clé API**
(`tenant = sha256(X-API-Key)[:16]`, motif identique dans mail/geo/telephonie/etc.). C'est le
modèle (b). Mais le Cœur n'envoyant qu'**une seule** `{BRIQUE}_KEY` pour tout son trafic, si ce
Cœur sert un cercle privé (plusieurs proches), ces briques partagent toutes le même tenant côté
cercle privé — sauf l'agenda, seule brique ayant reçu le correctif S182.

## Tableau brique → verdict

| Brique | Port | En-têtes honorés côté serveur | Tenant en DB | Filtre appliqué | Tests d'isolation | Usage probable | Verdict |
|---|---|---|---|---|---|---|---|
| agenda | 8400 | X-User-Id (repli session cookie) | Oui — Calendar.user_id | Oui | Oui | personne | isolée-personne |
| mail | 6030 | X-API-Key/Authorization → hash tenant | Oui — tenant | Oui | Oui | personne | isolée-bundle (1 seule MAIL_KEY/Cœur = risque cercle-privé) |
| memoire | 5600 | Aucun | Non | Non | Non | personne | **TROU** |
| donnees | 5500 | X-Org-ID, Keycloak optionnel | Oui — org_id | Oui | Oui | infra-partagé | isolée-bundle (jamais reçu via outils_communs) |
| restaurant | 6010 | X-Compte-Id+X-API-Key, session Bearer | Oui — compte_id | Oui | Oui | bundle-client | isolée-bundle |
| paiements | 6020 | X-API-Key/Bearer → solution | Oui — solution/compte_id | Oui | Oui | bundle-client | isolée-bundle |
| telephonie | 6050 | X-API-Key/Bearer → solution | Oui | Oui | Oui | bundle-client | isolée-bundle |
| geo | 6110 | X-API-Key/Bearer → tenant hash | Oui — tenant | Oui | Oui | bundle-client | isolée-bundle |
| personnages | 5900 | X-API-Key/Bearer | Oui — cle_api | Oui | Non | bundle-client | isolée-bundle |
| studio | 6060 | X-API-Key/STUDIO_KEY | Non (cree_par capturé, jamais filtré) | Non | Non | bundle-client (visé) | **TROU** |
| calcul | 5990 | X-API-Key/Bearer | Non (parc partagé) | N/A | Oui (hors tenant) | infra-partagé | partagée-à-raison |
| forge | 5700 | X-Forge-User-Token (ContextVar) | Non (propagation identité) | N/A | Oui | infra-partagé | partagée-à-raison |
| connexion | 5870 | X-API-Key, X-Telegram-Init-Data | Oui-partiel — mapping interlocuteur→utilisateur | Oui | Non | personne | isolée-personne (non testée) |
| voix | 5985 | X-API-Key/Bearer | Non (bibliothèque de clones globale) | Non | Non | personne (biométrie vocale) | partagée-à-raison (voulu, sensible) |
| images | 5950 | X-API-Key/Bearer | Non (stateless) | N/A | Non | bundle-client | partagée-à-raison |
| video | 5970 | X-API-Key/Bearer | Non (stateless) | N/A | Non | bundle-client | partagée-à-raison |
| transcription | 5980 | X-API-Key/Bearer | Non (stateless) | N/A | Non | bundle-client | partagée-à-raison |
| vision | 5960 | X-API-Key/Bearer | Non (stateless) | N/A | Non | bundle-client | partagée-à-raison |
| recherche | 6040 | X-API-Key/Bearer | Non (cache global) | N/A | Non | bundle-client | partagée-à-raison |
| peertube | 6100 | X-API-Key | Non | N/A | Non | bundle-client | partagée-à-raison |
| synopsis | 6090 | X-API-Key/Bearer sur /resumer* — **absent sur /jobs/{id}** | Non | Non | Non | bundle-client | **TROU (poll job non authentifié) — FIXÉ CE SPRINT (Task 2)** |
| oria | 6085 | Aucun | Non | N/A | Non | infra-partagé/collaboration | partagée-à-raison |
| audit | 5300 | Aucun | Non | N/A | Oui (hors isolation) | infra-partagé | partagée-à-raison |
| etl | 5200 | Aucun | Non | N/A | Oui (hors isolation) | infra-partagé | partagée-à-raison |
| generateur | 5400 | Aucun | Non | N/A | Non | infra-partagé | partagée-à-raison |
| gateway | 4001 | N/A (proxy LiteLLM) | Non | N/A | Non | infra-partagé | partagée-à-raison |
| dev | 5955 | X-API-Key=DEV_KEY unique | Non | N/A | Non | infra-partagé | partagée-à-raison |
| app-builder | — | pas de code serveur | — | — | — | — | (ignorée) |
| noyau | — | pas de code serveur | — | — | — | — | (ignorée) |

## Trous : action retenue

- **synopsis `/jobs/{job_id}`** : FIX CE SPRINT (Task 2) — motif déjà établi dans le même
  fichier (`Depends(cle_api)` sur les routes sœurs), zéro migration, zéro changement de
  comportement pour un appelant qui respecte déjà le contrat de la brique.
- **memoire** : REPORTÉ — aucune auth du tout aujourd'hui ; corriger exige de concevoir un
  modèle de tenant complet (colonne, filtre sur toutes les routes), pas un fix d'1-2 lignes.
  Candidat prioritaire pour un sprint dédié (donnée éminemment personnelle).
- **studio** : REPORTÉ — `cree_par` est déjà capturé mais jamais filtré (aveu explicite en
  commentaire, socle S51 non fait) ; l'activer maintenant changerait le comportement pour
  toute donnée déjà créée sous des clés différentes. Sprint dédié.
- **mail** (1 seule `MAIL_KEY` par Cœur) : REPORTÉ — aligner sur le motif X-User-Id
  (comme l'agenda) est un changement de comportement, pas un trou à boucher au sens strict.
  Cité dans la mémoire S182/S183 comme candidat mûr pour un sprint dédié.
- **`donnees` (X-Org-ID jamais forwardé via `outils_communs`)** : REPORTÉ — nécessite de
  décider si les outils LLM doivent porter une organisation, hors périmètre "chacun son espace
  par personne".

## Hors périmètre confirmé

Briques stateless ou sans notion de tenant pertinente (images, video, transcription, vision,
recherche, peertube, calcul, forge, gateway, dev, audit, etl, generateur, oria, voix) : verdict
"partagée à raison", aucune action.
```

- [ ] **Step 2: Vérifier le rendu**

Run: `grep -c '|' docs/rapport-s183-audit-isolation.md`
Expected: la commande renvoie un nombre > 0 (le tableau est bien présent) et le fichier s'ouvre sans erreur de rendu Markdown (pas de `|` orphelin cassant l'alignement des colonnes).

- [ ] **Step 3: Commit**

```bash
git add docs/rapport-s183-audit-isolation.md
git commit -m "docs(s183): rapport d'audit isolation multi-tenant (24 briques)"
```

---

### Task 2: Fix — `synopsis` `/jobs/{job_id}` doit exiger la clé API comme ses routes sœurs

**Files:**
- Modify: `briques/synopsis/main.py:260-270`
- Test: `briques/synopsis/test_synopsis.py` (section "GET /jobs/{id}", après ligne 421)

**Interfaces:**
- Consumes: `cle_api` (dépendance FastAPI déjà définie dans le même fichier, `briques/synopsis/main.py:45-52`, signature `def cle_api(x_api_key: Optional[str] = Header(None), authorization: Optional[str] = Header(None)) -> str`).
- Produces: rien de nouveau consommé ailleurs — route existante, comportement renforcé.

- [ ] **Step 1: Écrire le test qui échoue**

Ajouter dans `briques/synopsis/test_synopsis.py`, juste après `test_jobs_endpoint_404_si_inexistant` (après la ligne 421) :

```python
def test_jobs_endpoint_401_sans_cle_si_configuree(monkeypatch, tmp_path):
    import lib.jobs as _j
    monkeypatch.setattr(_j, "JOBS_DB", str(tmp_path / "jobs.db"))
    _j.init_db()
    jid = _j.creer_job("resumer")
    monkeypatch.setenv("API_KEYS", "cle-test")
    m = importlib.reload(main)
    c = TestClient(m.app)
    r = c.get(f"/jobs/{jid}")
    assert r.status_code == 401
    monkeypatch.setenv("API_KEYS", "")
    importlib.reload(main)


def test_jobs_endpoint_200_avec_bonne_cle_si_configuree(monkeypatch, tmp_path):
    import lib.jobs as _j
    monkeypatch.setattr(_j, "JOBS_DB", str(tmp_path / "jobs.db"))
    _j.init_db()
    jid = _j.creer_job("resumer")
    monkeypatch.setenv("API_KEYS", "cle-test")
    m = importlib.reload(main)
    c = TestClient(m.app)
    r = c.get(f"/jobs/{jid}", headers={"X-API-Key": "cle-test"})
    assert r.status_code == 200
    monkeypatch.setenv("API_KEYS", "")
    importlib.reload(main)
```

- [ ] **Step 2: Lancer les tests pour vérifier qu'ils échouent**

Run: `cd briques/synopsis && python3 -m pytest test_synopsis.py -k jobs_endpoint_401_sans_cle_si_configuree -v`
Expected: FAIL — `assert 200 == 401` (la route répond 200 sans clé, alors qu'on attend 401).

- [ ] **Step 3: Appliquer le fix minimal**

Dans `briques/synopsis/main.py`, remplacer :

```python
@app.get("/jobs/{job_id}")
def job_etat(job_id: str):
```

par :

```python
@app.get("/jobs/{job_id}")
def job_etat(job_id: str, _cle: str = Depends(cle_api)):
```

- [ ] **Step 4: Lancer les tests pour vérifier qu'ils passent**

Run: `cd briques/synopsis && python3 -m pytest test_synopsis.py -v`
Expected: PASS — tous les tests, y compris les 2 nouveaux et les 4 tests `/jobs/{id}` déjà existants (`test_jobs_endpoint_rend_un_job_en_cours`, `test_jobs_endpoint_rend_un_job_termine_avec_resultat`, `test_jobs_endpoint_rend_une_erreur_en_200_pas_500`, `test_jobs_endpoint_404_si_inexistant`) qui tournent sans `API_KEYS` configurée donc sans en-tête — non affectés par le fix.

- [ ] **Step 5: Commit**

```bash
git add briques/synopsis/main.py briques/synopsis/test_synopsis.py
git commit -m "fix(synopsis): /jobs/{id} exige la clé API comme /resumer* (S183)"
```

---

### Task 3: Mémoire projet — clore S183, prioriser la suite

**Files:**
- Modify: `/Users/garinat_t/.claude/projects/-Users-garinat-t-Desktop-Workplace/memory/sprint-s182-s183-multiutilisateur-espaces.md`
- Modify: `/Users/garinat_t/.claude/projects/-Users-garinat-t-Desktop-Workplace/memory/MEMORY.md`

**Interfaces:**
- Consumes: contenu du rapport `docs/rapport-s183-audit-isolation.md` (Task 1) et le commit du fix (Task 2).
- Produces: rien consommé par du code — mémoire de conversation future uniquement.

- [ ] **Step 1: Ajouter la section S183 dans le fichier mémoire existant**

Ajouter à la fin de `sprint-s182-s183-multiutilisateur-espaces.md` (après la dernière section) :

```markdown
## ✅ S183 CODE + COMMITÉ (2026-07-19) — audit d'isolation, 24 briques

Rapport complet : `docs/rapport-s183-audit-isolation.md`. Un seul fix appliqué ce sprint —
`synopsis` `/jobs/{job_id}` exigeait aucune clé API alors que ses routes sœurs (`/resumer`,
`/resumer-fichier`, `/reel`) si (motif déjà établi dans le même fichier, zéro migration).

**Trous reportés, priorisés pour la suite** :
1. **mail (6030)** — une seule `MAIL_KEY` par Cœur ⇒ tout le cercle privé partage le même
   tenant mail (le modèle par-clé-API existant n'est pas le motif X-User-Id de l'agenda).
   Candidat le plus mûr (modèle de tenant déjà là, juste pas branché sur l'identité de session).
2. **memoire (5600)** — AUCUNE auth aujourd'hui, donnée éminemment personnelle. Nécessite de
   concevoir un modèle de tenant complet, pas un fix rapide.
3. **studio (6060)** — `cree_par` capturé mais jamais filtré (aveu S51 en commentaire).
4. **`donnees` X-Org-ID jamais forwardé via `outils_communs`** — les outils LLM ne portent
   jamais d'organisation ; à trancher si pertinent hors périmètre "par personne".

Briques stateless/infra (images, video, transcription, vision, recherche, peertube, calcul,
forge, gateway, dev, audit, etl, generateur, oria, voix) : verdict "partagée à raison", zéro
action requise.
```

- [ ] **Step 2: Mettre à jour la ligne d'index MEMORY.md**

Dans `MEMORY.md`, remplacer la ligne S182+S183 existante par :

```
- [S182+S183 Chacun son espace / multi-user niveau 2](sprint-s182-s183-multiutilisateur-espaces.md) — **S182+S182b+S183 CODE+LIVE HP+MERGÉ main 2026-07-19** (agenda multi-user mergé, 457 tests ✅). S183 = audit isolation 24 briques (`docs/rapport-s183-audit-isolation.md`) + fix synopsis /jobs/{id}. RESTE priorisé : mail (1 seule clé/cercle privé), memoire (aucune auth), studio (cree_par non filtré)
```

- [ ] **Step 3: Vérifier la cohérence**

Run: `grep -n "S183" "/Users/garinat_t/.claude/projects/-Users-garinat-t-Desktop-Workplace/memory/MEMORY.md"`
Expected: une ligne trouvée, mentionnant S183 et le rapport d'audit.

(Pas de commit git ici — la mémoire vit hors du repo Workplace, dans `~/.claude/projects/...`.)
