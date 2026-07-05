# Sprint S148 — Isoler `.dev-ateliers/` du tooling de développement

> **But du sprint** : éliminer le bruit de développement causé par les 1 344 fichiers
> Python dupliqués dans `.dev-ateliers/`, sans toucher au fonctionnement de la brique dev.

- **Sprint** : S148
- **Catégorie** : DX (Developer Experience) / Infrastructure
- **Statut** : PLANIFIÉ
- **Date de planification** : 2026-07-04
- **Briques concernées** : `.dev-ateliers/`, `.gitignore`, `.dockerignore`, `pytest.ini`
- **Prérequis** : aucun

---

## Contexte

La brique dev (5955) crée des snapshots de travail dans `.dev-ateliers/` pour chaque
chantier en cours. Ces snapshots sont des copies complètes du workspace (briques, core,
oria-stack).

**Impact mesuré** :
- `.dev-ateliers/` contient **1 344 fichiers Python** vs 859 pour le vrai workspace
- Tout `grep -r` sur le projet retourne **3× les résultats** (vrai + 2 snapshots)
- `find . -name "test_*.py"` remonte 3× les fichiers de test → comptages faux
- `wc -l` sur les tests inclut les copies → statistiques erronées
- Git status / git add `.` peuvent accidentellement inclure des artefacts

Pytest est protégé (`testpaths = tests` dans `pytest.ini`).
Le reste du tooling — grep, find, wc, LSP — n'est pas protégé.

---

## Chantiers

### C0 — Vérifier ce que contient `.dev-ateliers/` actuellement

```bash
ls .dev-ateliers/
du -sh .dev-ateliers/
```

S'assurer qu'il n'y a pas de travail en cours non commité à préserver.

### C1 — Ajouter `.dev-ateliers/` au `.gitignore`

```
# Snapshots de la brique dev (artefacts éphémères, jamais commités)
.dev-ateliers/
```

Vérifier que `.dev-ateliers/` n'est pas déjà suivi par git :
```bash
git ls-files .dev-ateliers/ | head -5
```
Si des fichiers sont tracés → les désindexer avec `git rm -r --cached .dev-ateliers/`.

### C2 — Ajouter `.dev-ateliers/` au `.dockerignore`

```
.dev-ateliers/
```

Le `.dockerignore` racine protège les builds Docker de la brique noyau / core
qui montent le workspace.

### C3 — Exclure du `grep` par convention de documentation

Ajouter une note dans `GUIDE-ajouter-une-brique.md` ou `WORKPLACE.md` :

```markdown
## Recherches dans le code

Les snapshots de la brique dev vivent dans `.dev-ateliers/` (artefacts éphémères).
Pour exclure le bruit des recherches :

    grep -r "terme" . --exclude-dir=.dev-ateliers
    find . -path "./.dev-ateliers" -prune -o -name "*.py" -print
```

### C4 — Option : déplacer les ateliers hors du workspace

Si la brique dev `5955` peut être configurée pour écrire dans `/tmp/dev-ateliers/`
au lieu de `.dev-ateliers/`, c'est la solution propre à terme.

Vérifier dans `briques/dev/` comment le chemin est configuré :

```bash
grep -rn "dev-ateliers\|ATELIERS_DIR\|workdir\|workspace" briques/dev/ | grep -v .venv
```

Si c'est une constante → la rendre configurable via env `ATELIERS_DIR`.
Si c'est déjà configurable → documenter la variable dans `.env.example`.

---

## Critère d'acceptation

- `.dev-ateliers/` dans `.gitignore` (ou confirmation qu'il y est déjà)
- `.dev-ateliers/` dans `.dockerignore`
- `git status` ne propose plus d'ajouter les fichiers des ateliers
- `grep -r "TODO" .` réduit d'environ 60% le bruit
- Note de documentation dans `WORKPLACE.md` ou le guide approprié

---

## Effort estimé

**< 30 min**
- C0 (vérification) : 5 min
- C1 (gitignore) : 5 min
- C2 (dockerignore) : 5 min
- C3 (doc) : 10 min
- C4 (option env) : optionnel, 15 min si trivial

## Valeur

Toutes les recherches grep/find redeviennent exploitables au premier coup. Les
statistiques de couverture de tests (`find -name "test_*.py"`) redeviennent exactes.
