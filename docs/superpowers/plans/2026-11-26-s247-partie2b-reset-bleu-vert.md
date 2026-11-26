# S247 partie 2b — Reset de l'app entière en bleu/vert, sans coupure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **La Task 11 (preuve LIVE) se fait en session avec l'utilisateur, jamais par un sous-agent.**

**Goal:** `livraison_reset_app` remet une application à neuf (code propre depuis Forgejo + données restaurées dans une base neuve) **sans coupure** et **sans effacer l'ancienne instance** ; `livraison_retour_arriere` rebascule vers elle.

**Architecture:** *Deux emplacements permanents* (A = l'app d'origine, B = son « jumeau » créé une fois par la brique). L'emplacement actif sert le domaine public ; l'inactif sert un domaine de test. Un reset travaille TOUJOURS sur l'emplacement inactif : l'exécuteur (VM 100) restaure la sauvegarde fraîche dans une **nouvelle base** du même Postgres, la brique repointe les variables de l'inactif sur cette base, le redéploie, vérifie santé + comptages, bascule la sauvegarde Dokploy, puis **échange les noms d'hôte** des deux domaines (Traefik réécrit en 0,1 s). L'ancien emplacement et son ancienne base restent intacts jusqu'au reset suivant (retour arrière = ré-échanger). Aucune suppression d'app, donc aucun droit de suppression pour la clé.

**Tech Stack:** Python 3.11 (brique FastAPI + exécuteur stdlib), httpx MockTransport (faux Dokploy), Dokploy v0.31.4, Postgres 16, systemd.

## Global Constraints

- Règle utilisateur : « Je ne veux pas avoir à gérer le côté technique, et pas de coupure de service. » Donc : aucune préparation manuelle par app (la brique crée le jumeau et les domaines), échange de domaines (pas de redéploiement de l'actif).
- Mes vraies applications ne sont PAS migrées (elles restent sur Vercel) : tout se prouve sur l'app témoin `calendrier-familial`.
- Clé Dokploy de la brique = utilisateur **membre limité au projet `temoin`**, droits actuels + `canCreateServices` (déjà accordé le 2026-11-26). **Jamais** la clé owner, **jamais** `canDeleteServices`/`canCreateProjects`. Ne jamais afficher ni écrire dans le dépôt une clé ou un mot de passe.
- Fail closed : toute étape qui échoue AVANT l'échange de domaines laisse l'actif strictement inchangé (même base, mêmes variables, mêmes hôtes).
- `livraison_reset_app` : `sensibilite: "donnees"`, `prerequis: ["preuve_sauvegarde"]`, et la brique appelle `exiger_preuve` elle-même (défense en profondeur).
- `livraison_retour_arriere` : `sensibilite: "donnees"` SANS prérequis (les données écrites depuis la bascule restent dans la base de l'emplacement quitté ; le dire dans le résultat).
- Les fonctions de Dokploy qui *ne répondent pas en JSON* (mutations) sont un succès si 2xx (déjà géré par `_requete`).
- Écarts assumés avec la fiche S247 : (1) `livraison_basculer` n'existe pas, la bascule fait partie du reset (une seule approbation, rien à gérer) ; (2) rétention de l'ancien emplacement = « jusqu'au reset suivant » (pas de N jours) ; (3) le diagnostic préalable et la page « maintenance » sont hors 2b (inutile sans coupure).
- Environnement : `python3.11 -m pytest` (le `python3` système n'a pas pytest) ; `rm -rf` bloqué (utiliser `rm -f`) ; la sortie des outils supprime l'indentation ; `git` passe par `rtk` (utiliser `rtk proxy git diff …` pour un patch brut).

## Faits établis par le test du 2026-11-26 (clé limitée + `canCreateServices`)

| Appel | Résultat |
|---|---|
| `project.duplicate` | 401 « unauthorized to access resource project » (même avec `canCreateServices`) → **abandonné** |
| `application.create`, `application.saveGitProvider`, `application.saveBuildType`, `application.saveEnvironment` (corps avec `createEnvFile: true`), `domain.create`, `application.deploy`, `domain.update` | 200, déploiement `done` en < 1 min |
| `application.delete` | réservé à l'owner (non utilisé) |
| `application.one` (app d'origine) | `sourceType: git`, `customGitUrl`, `customGitBranch`, `customGitBuildPath`, `buildType: dockerfile`, `dockerfile`, `dockerContextPath`, `env` (vide pour le témoin), `domains: []` |
Formes de corps exactes : voir Task 3.

## Limites connues (à écrire telles quelles dans la preuve)

1. **Écritures pendant l'opération** : la nouvelle base est une copie à l'instant T de la sauvegarde. Les données écrites ensuite dans l'ancienne base ne sont pas dans la nouvelle. La brique recompte l'actif juste avant la bascule ; si les comptages ont bougé elle refait la copie (jusqu'à 3 essais) puis abandonne sans basculer (`ecritures_en_cours`).
2. **Restauration dans la base neuve** : la copie est restaurée par le rôle sans privilège, puis les objets sont réattribués au compte de l'application (`reassign owned`). Un dump piégé (fonctions `SECURITY DEFINER`) deviendrait alors puissant. Accepté en 2b : le dump est une sauvegarde faite quelques secondes avant, et écrire dans le bucket exige l'identité S3 d'administration. À durcir en 2c.
3. Le témoin `calendrier-familial` n'utilise pas sa base : la preuve de données porte sur la base et les variables (`DATABASE_URL` repointée), pas sur un écran de l'app.

---

## File Structure

| Fichier | Responsabilité |
|---|---|
| `outils/executeur-restauration/executeur.py` (modif.) | + `POST /cloner`, `POST /comptages`, `POST /supprimer-base` |
| `outils/executeur-restauration/test_executeur_cloner.py` (new) | tests des trois ordres |
| `briques/livraison/client_executeur.py` (modif.) | + `cloner`, `comptages`, `supprimer_base` |
| `briques/livraison/envreecriture.py` (new) | `reecrire_env` (pur) |
| `briques/livraison/operations.py` (new) | état persistant par app + verrou d'opération |
| `briques/livraison/inventaire.py` (modif.) | bloc facultatif `reset` validé |
| `briques/livraison/dokploy.py` + `faux_dokploy.py` (modif.) | méthodes de création/configuration/domaines/sauvegarde |
| `briques/livraison/reset.py` (new) | orchestrateur, retour arrière, sauvegarde « effective » |
| `briques/livraison/main.py`, `manifest.json` (modif.) | routes + 3 capacités |
| `core/outils_communs.py` (peut-être) | aucun délai long : l'opération est asynchrone |

---

### Task 1 : Exécuteur — `/cloner`, `/comptages`, `/supprimer-base`

**Files:**
- Modify: `outils/executeur-restauration/executeur.py`
- Create: `outils/executeur-restauration/test_executeur_cloner.py`

**Interfaces:**
- Consumes: `valider`, `conteneur`, `_psql`, `comptages`, `telecharger`, `_resultat`, `VERROU`, `FauxRunner` (dans `test_executeur.py`, à importer).
- Produces: `cloner(runner, cfg, corps) -> dict`, `lire_comptages(runner, cfg, corps) -> dict`, `supprimer_base(runner, cfg, corps) -> dict`.

Contrats (corps JSON, mêmes regex qu'existantes, `fullmatch`) :
- `/cloner` `{service, utilisateur, base, objet, nouvelle_base}` ; `nouvelle_base` doit valider `RE_NOUVELLE = ^[a-z_][a-z0-9_]{0,30}_v[0-9a-f]{8}$` et différer de `base`. Réponse 200 : `{"ok": True, "verdict": "valide"|"invalide", "raison", "nouvelle_base", "comptages_origine", "comptages_restaures", "nettoyage"}`. `verdict valide` ⇔ comptages identiques ET base renommée en `nouvelle_base` et possédée par `utilisateur`.
- `/comptages` `{service, utilisateur, base}` → `{"ok": True, "comptages": {...}}` (lecture seule, compte `public` comme `comptages`).
- `/supprimer-base` `{service, utilisateur, base}` : `base` DOIT valider `RE_NOUVELLE` (jamais une base d'origine) → `drop database if exists … with (force)` ; réponse `{"ok": True}`.

- [ ] **Step 1 : tests qui échouent** (`test_executeur_cloner.py`)

```python
import re
import pytest
import executeur
from executeur import ErreurExecuteur
from test_executeur import FauxRunner, CFG, CORPS, _sql

NOUVELLE = "temoin_v0a1b2c3d"
CLONE = {**CORPS, "nouvelle_base": NOUVELLE}


def test_cloner_nominal_renomme_et_reattribue_au_compte_de_l_application():
    r = FauxRunner()
    out = executeur.cloner(r, CFG, dict(CLONE))
    assert out["ok"] is True and out["verdict"] == "valide" and out["nouvelle_base"] == NOUVELLE
    assert out["comptages_origine"] == out["comptages_restaures"] == {"evenements": 42}
    sqls = [a[-1] for a in r.commandes() if a[:2] == ["docker", "exec"] and "pg_restore" not in a]
    assert any(re.match(r"reassign owned by restore_\w+ to temoin", s) for s in sqls)
    assert any(re.match(rf"alter database restore_\w+ rename to {NOUVELLE}", s) for s in sqls)
    assert any(s.startswith("drop role if exists restore_") for s in sqls)


def test_cloner_comptages_differents_ne_cree_pas_la_base_finale():
    r = FauxRunner(restaure={"evenements": 41})
    out = executeur.cloner(r, CFG, dict(CLONE))
    assert out["verdict"] == "invalide"
    assert not any("rename to" in a[-1] for a in r.commandes() if a[:2] == ["docker", "exec"])
    assert len(_sql(r, "drop database if exists restore_")) == 1


@pytest.mark.parametrize("nom", ["temoin", "temoin_v1", "Temoin_v0a1b2c3d", "temoin_v0a1b2c3d;x",
                                 "temoin_v0a1b2c3d\n", ""])
def test_cloner_refuse_un_nom_de_base_finale_hors_format(nom):
    r = FauxRunner()
    with pytest.raises(ErreurExecuteur) as e:
        executeur.cloner(r, CFG, {**CORPS, "nouvelle_base": nom})
    assert e.value.statut == 400 and r.appels == []


def test_supprimer_base_refuse_une_base_d_origine():
    r = FauxRunner()
    for nom in ("temoin", "postgres", "template1", "restore_0a1b2c3d"):
        with pytest.raises(ErreurExecuteur) as e:
            executeur.supprimer_base(r, CFG, {"service": CORPS["service"], "utilisateur": "temoin", "base": nom})
        assert e.value.statut == 400
    assert r.appels == []


def test_supprimer_base_generee_ok():
    r = FauxRunner()
    assert executeur.supprimer_base(r, CFG, {"service": CORPS["service"], "utilisateur": "temoin",
                                              "base": NOUVELLE}) == {"ok": True}
    assert len(_sql(r, f"drop database if exists {NOUVELLE} with (force)")) == 1


def test_comptages_lecture_seule():
    r = FauxRunner()
    out = executeur.lire_comptages(r, CFG, {"service": CORPS["service"], "utilisateur": "temoin", "base": "temoin"})
    assert out == {"ok": True, "comptages": {"evenements": 42}}
```
Étendre `FauxRunner.run` : accepter `alter database`, `reassign owned` comme les `create/drop` (retour `0, b"", b""`) ; l'écrire dans `test_executeur.py` (regex `^(create|drop|alter|reassign)`).

- [ ] **Step 2 : lancer** `python3.11 -m pytest -q outils/executeur-restauration/test_executeur_cloner.py` → FAIL (`cloner` absent).

- [ ] **Step 3 : implémenter** dans `executeur.py`

```python
RE_NOUVELLE = re.compile(r"^[a-z_][a-z0-9_]{0,30}_v[0-9a-f]{8}$")


def _valider_nouvelle(corps) -> str:
    nv = corps.get("nouvelle_base") if isinstance(corps, dict) else None
    if not (isinstance(nv, str) and RE_NOUVELLE.fullmatch(nv)):
        raise ErreurExecuteur(400, "nouvelle_base invalide")
    return nv


def cloner(runner, cfg: dict, corps) -> dict:
    nouvelle = _valider_nouvelle(corps)
    service, utilisateur, base, objet = valider(corps)
    if nouvelle == base:
        raise ErreurExecuteur(400, "nouvelle_base invalide")
    debut = time.time()
    cid = conteneur(runner, service)
    donnees = _lire_dump(runner, cfg, objet)            # factoriser le bloc télécharger/gunzip/magie de `verifier`
    if isinstance(donnees, dict):                        # verdict invalide déjà formé
        return {**donnees, "nouvelle_base": None}
    origine = comptages(runner, cid, utilisateur, base)
    if not origine:
        return {**_resultat("invalide", "aucune table dans la base d'origine", origine, {}, debut),
                "nouvelle_base": None}
    jetable = "restore_" + secrets.token_hex(4)
    restaure, nettoyage, verdict, raison = {}, "ok", "valide", None
    final = False
    try:
        _psql(runner, cid, utilisateur, "postgres",
              f"create role {jetable} login nosuperuser nocreatedb nocreaterole noinherit "
              f"noreplication nobypassrls connection limit 4")
        _psql(runner, cid, utilisateur, "postgres", f"create database {jetable} owner {jetable}")
        code, _, _ = runner.run(["docker", "exec", "-i", cid, "pg_restore", "-U", jetable,
                                 "-d", jetable, "--no-owner", "--no-privileges"],
                                stdin=donnees, timeout=900)
        if code != 0:
            verdict, raison = "invalide", "pg_restore a échoué"
        else:
            restaure = comptages(runner, cid, jetable, jetable)
            if restaure != origine:
                verdict, raison = "invalide", "comptages différents entre l'original et la copie restaurée"
        if verdict == "valide":
            # Le rôle jetable possède tout : on réattribue au compte de l'application, puis on
            # renomme. REASSIGN OWNED agit dans la base COURANTE : s'y connecter explicitement.
            _psql(runner, cid, utilisateur, jetable, f"reassign owned by {jetable} to {utilisateur}")
            _psql(runner, cid, utilisateur, "postgres", f"alter database {jetable} owner to {utilisateur}")
            _psql(runner, cid, utilisateur, "postgres", f"alter database {jetable} rename to {nouvelle}")
            final = True
    except ErreurExecuteur:
        verdict, raison = "invalide", "échec pendant la création de la copie"
    finally:
        sqls = [] if final else [f"drop database if exists {jetable} with (force)"]
        sqls.append(f"drop role if exists {jetable}")
        for sql in sqls:
            try:
                _psql(runner, cid, utilisateur, "postgres", sql)
            except ErreurExecuteur:
                nettoyage = "echec"
    r = _resultat(verdict, raison, origine, restaure, debut, nettoyage)
    r["nouvelle_base"] = nouvelle if final else None
    return r
```
`verdict valide` n'est renvoyé que si `final` est vrai : après le `except`, forcer `verdict = "invalide"` si `not final`. `lire_comptages` : `valider` partiel (service/utilisateur/base seulement : factoriser un `_valider_cible`), `comptages(...)`. `supprimer_base` : `_valider_cible` + `RE_NOUVELLE.fullmatch(base)` sinon 400 ; `_psql(..., "postgres", f"drop database if exists {base} with (force)")`.
Brancher dans `do_POST` : table `{"/verifier": verifier, "/cloner": cloner, "/comptages": lire_comptages, "/supprimer-base": supprimer_base}` ; même authentification, même `VERROU` (une opération à la fois), même `except`. **Factoriser** le bloc « télécharger → gunzip → magie » de `verifier` dans `_lire_dump(runner, cfg, objet)` (retourne les octets, ou un résultat `invalide` déjà formé) et faire utiliser `verifier` par ce même helper (les tests existants de `verifier` doivent rester verts).

- [ ] **Step 4 : tests verts** `python3.11 -m pytest -q outils/executeur-restauration` (tous, 55 existants + nouveaux).
- [ ] **Step 5 : commit** `feat(executeur): cloner une sauvegarde dans une base neuve, comptages, suppression de bases générées`

---

### Task 2 : Client de l'exécuteur

**Files:** Modify `briques/livraison/client_executeur.py`, `test_client_executeur.py`.

**Interfaces:**
- Consumes: `Executeur._post` (à extraire de `verifier`, mêmes erreurs honnêtes : injoignable, 401 « refusé la clé », 409, `erreur` fixe ≤ 120 caractères).
- Produces: `async cloner(service, utilisateur, base, objet, nouvelle_base) -> dict`, `async comptages(service, utilisateur, base) -> dict`, `async supprimer_base(service, utilisateur, base) -> dict`.

- [ ] **Step 1 : tests** (MockTransport) : chaque méthode poste sur le bon chemin avec `X-API-Key`, corps exact ; 401/409/injoignable → mêmes `ExecuteurErreur` que `verifier` ; `cloner` a un délai plus long (`delai=900`) que `verifier`.
- [ ] **Step 2 : refactorer** `verifier` pour passer par `_post(chemin, corps, delai)` et ajouter les trois méthodes. Les tests existants (69 lignes) restent verts.
- [ ] **Step 3 : commit** `feat(livraison): client de l'exécuteur — cloner, comptages, supprimer_base`

---

### Task 3 : Client Dokploy + faux serveur (création, configuration, domaines, sauvegarde)

**Files:** Modify `briques/livraison/dokploy.py`, `faux_dokploy.py`, `test_dokploy.py`.

**Interfaces — Produces** (toutes `async`, mutations → `None` sauf mention) :
- `app_complete(id_) -> dict` : `application.one` filtré sur la liste blanche `{applicationId, name, appName, applicationStatus, sourceType, customGitUrl, customGitBranch, customGitBuildPath, buildType, dockerfile, dockerContextPath, env, domains:[{domainId,host,port,path,https}]}` (**le champ `env` ne sort jamais de la brique ni dans un log**).
- `creer_app(environment_id, nom, description) -> {"id","app_name"}` : `POST application.create {name, environmentId, description}`.
- `configurer_source(id_, source: dict)` : `POST application.saveGitProvider {applicationId, customGitUrl, customGitBranch, customGitBuildPath, watchPaths: [], enableSubmodules: false}` puis `POST application.saveBuildType {applicationId, buildType, dockerfile, dockerContextPath, dockerBuildStage: "", herokuVersion: None, railpackVersion: None, publishDirectory: None, isStaticSpa: None}`.
- `ecrire_env(id_, env: str)` : `POST application.saveEnvironment {applicationId, env, buildArgs: "", buildSecrets: "", createEnvFile: true}`.
- `creer_domaine(id_, host, port) -> str` : `POST domain.create {host, path: "/", port, https: false, applicationId, certificateType: "none", domainType: "application"}` → `domainId`.
- `changer_hote(domain_id, host, port)` : `POST domain.update {domainId, host, path: "/", port, https: false, certificateType: "none", domainType: "application"}`.
- `deployer_et_attendre(id_, titre, delai_s=600, pas_s=5) -> str` : `POST application.deploy {applicationId}` puis boucle sur `app_complete(...)["applicationStatus"]` jusqu'à `done` (retourne `"done"`), `error` (→ `DokployErreur("Le déploiement de l'instance neuve a échoué.")`) ou délai (→ `DokployErreur("Délai dépassé…")`). Horloge/`sleep` injectables pour les tests.
- `rebaser_sauvegarde(backup_id, base)` : `POST backup.update {backupId, database: base, schedule, prefix, enabled, destinationId, keepLatestCount, databaseType: "postgres", backupType: "database"}` — **les champs obligatoires de `backup.update` doivent d'abord être relevés** : `GET backup.one?backupId=…` (existe en 0.31.4 ; sinon `postgres.one` → `backups[]`), recopier ses valeurs et ne changer que `database`. À vérifier en LIVE (Task 11, step 2) : si `backup.update` est refusé à la clé limitée, créer une 2ᵉ config `backup.create` pour la nouvelle base et ranger son id dans l'état (Task 4) — choisir à ce moment, le test unitaire couvre la forme « relever puis ne changer que `database` ».

- [ ] **Step 1 : tests** pour chaque méthode (forme exacte des corps, ci-dessus) + `deployer_et_attendre` (done / error / délai avec horloge factice) + `app_complete` n'expose pas `refreshToken`/`password` et garde `env` seulement dans la valeur retournée.
- [ ] **Step 2 : faux Dokploy** : état mutable `apps`, `domaines`, `backups` ; chemins ci-dessus ; `application.create` → nouvel id déterministe ; `application.deploy` passe l'app à `running` puis `done` au 2ᵉ `application.one` (paramétrable : `etat["deploy_echoue"]`) ; `domain.update` modifie l'hôte ; 401 si clé inconnue ; **le faux refuse (401) `project.duplicate` et `application.delete`** comme le vrai pour la clé limitée.
- [ ] **Step 3 : implémenter**, `python3.11 -m pytest -q briques/livraison` vert.
- [ ] **Step 4 : commit** `feat(livraison): Dokploy — créer, configurer, déployer, domaines, rebasculer la sauvegarde`

---

### Task 4 : État persistant des opérations (`operations.py`)

**Files:** Create `briques/livraison/operations.py`, `test_operations.py`.

Fichier `LIVRAISON_DATA/operations.json`, écriture atomique **avec fsync** (`tmp` + `os.fsync` + `os.replace`), verrou `threading.Lock`, **les erreurs disque ne sont PAS avalées** (une opération dont on ne peut pas persister l'état ne démarre pas). Forme :

```json
{"calendrier-familial": {
  "emplacements": {"A": {"app_id": "…", "domaine_id": "…"}, "B": {"app_id": "…", "domaine_id": "…"}},
  "actif": "A",
  "base_active": "temoin", "base_precedente": null,
  "op": {"id": "ab12…", "type": "reset", "etat": "en_cours", "etape": "clonage",
         "debut": 1795000000.0, "fin": null, "message": null, "essais": 1}}}
```

**Interfaces — Produces :**
- `lire(app) -> dict | None`
- `demarrer(app, type_) -> str` : lève `OperationEnCours` si `op.etat == "en_cours"` ; sinon écrit `op` (`etat: en_cours`) et retourne l'id.
- `etape(app, nom, **extra)` ; `terminer(app, etat, message=None)` avec `etat ∈ {"reussie","echec","interrompue"}`
- `enregistrer_emplacements(app, a: dict, b: dict, actif: str, base_active: str)` ; `basculer_etat(app, actif, base_active, base_precedente)`
- `marquer_interrompues()` : au démarrage de la brique, toute `op` restée `en_cours` devient `interrompue` (message « la brique a redémarré pendant l'opération »).

- [ ] **Step 1 : tests** : persistance après relecture ; `demarrer` deux fois → `OperationEnCours` ; `marquer_interrompues` ; écriture atomique (un `tmp` laissé n'est jamais lu) ; `OSError` propagé (patch `os.replace`) et l'état précédent intact ; fichier corrompu → `lire` renvoie `None` (et `demarrer` repart d'un état vide).
- [ ] **Step 2 : implémenter**. Brancher `marquer_interrompues()` dans le `lifespan` de `main.py`.
- [ ] **Step 3 : commit** `feat(livraison): état persistant des opérations de reset`

---

### Task 5 : Réécriture des variables + bloc `reset` de l'inventaire

**Files:** Create `briques/livraison/envreecriture.py`, `test_envreecriture.py` ; Modify `inventaire.py`, `test_inventaire.py`.

```python
# envreecriture.py
import re

def reecrire_env(env: str, variable: str, ancienne: str, nouvelle: str) -> str:
    """Remplace UNIQUEMENT le nom de base dans l'URL de `variable` ; le reste est recopié tel quel.
    Lève ValueError (sans jamais citer la valeur) si la variable manque, est ambiguë ou ne
    pointe pas sur `ancienne`."""
    lignes = (env or "").split("\n")
    motif = re.compile(r"^(" + re.escape(variable) + r"=)(.*)$")
    trouvees = [i for i, l in enumerate(lignes) if motif.match(l)]
    if len(trouvees) != 1:
        raise ValueError("variable de base introuvable ou ambiguë")
    i = trouvees[0]
    nom, valeur = motif.match(lignes[i]).groups()
    guillemet = valeur[:1] if valeur[:1] in "\"'" and valeur[-1:] == valeur[:1] else ""
    coeur = valeur[1:-1] if guillemet else valeur
    nv, n = re.subn(r"^(\w[\w+.-]*://[^/?#]*/)" + re.escape(ancienne) + r"(?=$|[?#])",
                    lambda m: m.group(1) + nouvelle, coeur)
    if n != 1:
        raise ValueError("la variable ne pointe pas sur la base attendue")
    lignes[i] = nom + guillemet + nv + guillemet
    return "\n".join(lignes)
```

Tests (obligatoires) : URL simple ; avec paramètres `?sslmode=disable` ; avec guillemets ; mot de passe contenant `/`, `@`, `:` (non touché) ; autres lignes et commentaires identiques octet pour octet ; variable absente → `ValueError` ; deux lignes identiques → `ValueError` ; base différente (`/autre`) → `ValueError` ; **le message d'erreur ne contient jamais la valeur** (assert que `str(e)` n'inclut ni le mot de passe ni l'URL) ; une base dont le nom est préfixe d'une autre (`temoin` vs `temoin2`) n'est pas modifiée.

`inventaire.py` : bloc facultatif par app `"reset"` = `{"variable_env": str, "domaine_public": str, "domaine_test": str, "port_app": int, "sante_chemin": str}` ; validations : `variable_env ^[A-Z][A-Z0-9_]{0,60}$`, domaines `^[a-z0-9]([a-z0-9.-]{0,251}[a-z0-9])$` et différents l'un de l'autre, `port_app` 1–65535, `sante_chemin ^/[A-Za-z0-9._~/-]{0,100}$` ; un bloc `reset` mal formé invalide TOUTE l'entrée (fail closed, comme aujourd'hui) ; `lire` renvoie aussi `"reset"` (ou `None`) et exige `len(bases) == 1` quand `reset` est présent (2b = une base par app). Tests : valide / chaque champ invalide / `reset` absent → entrée valide sans reset.

- [ ] **Steps :** tests d'abord → implémenter → `python3.11 -m pytest -q briques/livraison` → commit `feat(livraison): réécriture de la variable de base et bloc reset de l'inventaire`

---

### Task 6 : Orchestrateur `reset.py`

**Files:** Create `briques/livraison/reset.py`, `test_reset.py`.

**Interfaces:**
- Consumes: `Dokploy` (Task 3), `Executeur` (Task 2), `operations` (Task 4), `reecrire_env` (Task 5), `sauvegarde.sauvegarder` / `dokploy.fichiers_sauvegarde`, entrée d'inventaire (`bases[0]`, `reset`).
- Produces: `async reset(d, ex, entree, app_nom, app_id, sante=…, horloge=time.time)` — lancée en tâche de fond par la route (Task 8) ; ne lève jamais : toute issue passe par `operations.terminer`. `async retour_arriere(d, entree, app_nom)`. `base_effective(entree, etat) -> dict` (entrée d'inventaire dont `bases[0]["base"]` = `etat["base_active"]` si l'état existe).

Déroulé de `reset` (chaque étape appelle `operations.etape`) :
1. **preparation** : charger l'état. Absent → l'app d'origine est l'emplacement A, actif ; `app_complete(A)` doit avoir un domaine, sinon on lui en crée un (`domaine_public`) ; jumeau B absent → `creer_app(environment_id, f"{nom}-jumeau")` (l'`environmentId` se lit sur `project.all`), `configurer_source` recopiée depuis A, `creer_domaine(B, domaine_test)` ; `enregistrer_emplacements`. L'inactif est `B` si actif `A`, et inversement.
2. **clonage** (jusqu'à 3 essais, `essais` dans l'état) : `sauvegarder_base` ; fichier le plus récent (même règle que `verifier`, tolérance d'horloge) ; `ex.cloner(service, utilisateur, base_active, objet, nouvelle)` avec `nouvelle = f"{base_racine}_v{secrets.token_hex(4)}"` (`base_racine` = base d'origine de l'inventaire, jamais déjà suffixée). `verdict != "valide"` → échec `clonage_invalide`.
3. **configuration** : `env = app_complete(actif)["env"]` ; `reecrire_env(env, variable_env, base_active, nouvelle)` (`ValueError` → échec `env_inattendu`) ; `ecrire_env(inactif, …)` ; `configurer_source(inactif, source de l'actif)` (code propre depuis Forgejo) ; `deployer_et_attendre(inactif)`.
4. **sante** : `GET {LIVRAISON_TRAEFIK_URL}{sante_chemin}` avec en-tête `Host: domaine_test` ; 2xx/3xx attendu, 3 essais espacés de 5 s ; sinon échec `sante_ko`.
5. **recomptage** : `ex.comptages(service, utilisateur, base_active)` doit égaler `comptages_origine` du clonage ; sinon (écritures en cours) : `ex.supprimer_base(nouvelle)` puis retour à l'étape 2 (essai suivant) ; au 3ᵉ échec : échec `ecritures_en_cours`.
6. **sauvegarde** : `rebaser_sauvegarde(sauvegarde_id, nouvelle)`.
7. **bascule** : `changer_hote(domaine_inactif, domaine_public)` PUIS `changer_hote(domaine_actif, domaine_test)` (jamais de moment sans hôte public) ; `basculer_etat(app, actif=inactif, base_active=nouvelle, base_precedente=ancienne_base_active)`.
8. **nettoyage** : si `base_precedente` (avant bascule) existait, `ex.supprimer_base(base_precedente_ancienne)` (génération N-2, nom généré uniquement) ; un échec ici n'invalide pas le reset : alerte dans le message.
9. `operations.terminer(app, "reussie", message)` ; le message liste : instance maintenant active, base, comptages, et **« les données écrites dans l'ancienne instance après HH:MM:SS (heure de la sauvegarde) restent dans l'ancienne base »**.

**Compensation** (toute exception ou échec **avant** l'étape 7) : si l'étape 6 est faite → `rebaser_sauvegarde(sauvegarde_id, base_active)` ; `ex.supprimer_base(nouvelle)` si créée ; l'inactif reste tel quel (sans effet sur le trafic : il sert le seul hôte de test) ; `terminer("echec", motif)`. Échec pendant/après l'étape 7 : tenter de remettre les hôtes dans l'état d'avant (best effort), `terminer("echec", "bascule_incomplete : vérifier les domaines")` et alerte explicite. Toute `DokployErreur`/`ExecuteurErreur`/`OSError`/`ValueError` est convertie en un motif fixe court (jamais le message brut, jamais une valeur d'environnement).

`retour_arriere` : exige `etat` avec `base_precedente` et un `op` non `en_cours` ; `demarrer("retour")` ; `rebaser_sauvegarde(sauvegarde_id, base_precedente)` ; échange des hôtes (même ordre) ; `basculer_etat(actif=autre, base_active=base_precedente, base_precedente=base_active_avant)` ; message : « les données écrites depuis la bascule sont dans <emplacement quitté> / base <nom> ».

- [ ] **Step 1 : tests d'abord** (faux Dokploy + faux exécuteur à scénarios), au minimum :
  - nominal : premier reset (jumeau créé) → hôtes échangés, `actif == "B"`, `base_active` = nouvelle base, `rebaser_sauvegarde` appelé, état `reussie` ; l'**env de l'actif n'a pas changé** (assert sur `appels` : aucun `saveEnvironment` visant l'actif) ;
  - second reset : l'emplacement réutilisé est celui qui était inactif (aucun `application.create`), ancienne base N-2 supprimée ;
  - **sabotage** : clone invalide / déploiement `error` / santé KO / env inattendu / recomptage différent ×3 → AUCUN `domain.update`, `rebaser_sauvegarde` annulé si fait, base neuve supprimée, état `echec` avec le bon motif ;
  - écritures pendant l'opération : 1er recomptage différent puis égal au 2ᵉ essai → succès ; trois fois différent → `ecritures_en_cours` ;
  - échec du 2ᵉ `changer_hote` → tentative de remise en l'état, motif `bascule_incomplete` ;
  - jamais de fuite : aucun appel journalisé ni message d'état ne contient une valeur de l'env (test avec `PASSWORD=SECRETXYZ` dans l'env du faux) ;
  - verrou : un second `reset` pendant `en_cours` est refusé (`OperationEnCours`) ;
  - `retour_arriere` : hôtes ré-échangés, `base_active` = précédente ; sans `base_precedente` → refus ;
  - `base_effective` : substitue la base ; `sauvegarde.verifier` et `sauvegarder` l'utilisent (test d'intégration dans `test_sauvegarde.py`).
- [ ] **Step 2 : implémenter** `reset.py` ; faire utiliser `base_effective` par `main._entree_inventaire` (la vérification de sauvegarde et la sauvegarde suivent la base active après un reset).
- [ ] **Step 3 : `python3.11 -m pytest -q briques/livraison`** vert.
- [ ] **Step 4 : commit** `feat(livraison): reset bleu/vert, retour arrière et base effective`

---

### Task 7 : Routes, manifeste, capacités

**Files:** Modify `briques/livraison/main.py`, `manifest.json`, `test_api.py`, `docker-compose.yml`/`.env.example` (+ `LIVRAISON_TRAEFIK_URL`).

Routes (toutes `Depends(cle_api_fermee)`) :
- `POST /apps/{app}/reset` : `_resoudre` → `a` ; `_entree_inventaire` (404) ; **bloc `reset` absent → 409 « reset non configuré pour cette application »** ; `executeur()` (503) ; `exiger_preuve(a["id"])` (409) ; `operations.demarrer` (`OperationEnCours` → 409) ; lance `asyncio.create_task(reset.reset(...))` (garder une référence pour éviter le ramasse-miettes) et répond **202** `{"ok": True, "app": nom, "operation": id, "etat": "en_cours"}`. 
- `POST /apps/{app}/retour-arriere` : mêmes gardes sauf la preuve ; 202 comme ci-dessus.
- `GET /apps/{app}/operation` (lecture) : `{"app", "etat", "etape", "operation", "message", "actif", "base_active"}` ; jamais de valeur d'env ni d'identifiant de domaine.

Manifeste : `livraison_reset_app` (`sensibilite: "donnees"`, `prerequis: ["preuve_sauvegarde"]`, description « UNIQUEMENT pour remettre à neuf une application (code propre + données restaurées) ; PAS pour redémarrer, déployer ou revenir à une version ; l'opération dure plusieurs minutes et se lit avec `livraison_operation` ; ne pas dire qu'elle est terminée tant que `livraison_operation` ne répond pas `reussie` »), `livraison_retour_arriere` (`donnees`, description « revenir à l'instance précédente après un reset ; PAS pour un rollback de version »), `livraison_operation` (lecture, `reversible`/sans approbation). Ajouter au test de capacité (8 → 11).

- [ ] **Step 1 : tests API** : sans clé 401/403 ; sans preuve 409 ; sans bloc reset 409 ; sans exécuteur 503 ; nominal 202 puis `GET operation` → `reussie` (faux transport) ; second POST pendant `en_cours` → 409 ; `GET operation` ne contient jamais `env`/`password` ; ordre des erreurs (404 inventaire avant 503).
- [ ] **Step 2 : implémenter**, valider le manifeste (`python3.11 -m pytest -q briques/livraison core/test_catalogue*.py` selon les tests existants).
- [ ] **Step 3 : commit** `feat(livraison): capacités reset_app, retour_arriere et operation`

---

### Task 8 : Durcissement hérité de la partie 2a

**Files:** Modify `briques/livraison/main.py`, `sauvegarde.py`, `test_sauvegarde.py`, `test_preuve.py` ; `infra/ansible/roles/executeur_restauration/templates/executeur-restauration.service.j2`, `tests/test_roles_livraison.py`.

- [ ] **Step 1 — révocation côté brique** : toute vérification qui se termine `invalide`, ou qui échoue par exception/timeout/annulation HTTP, appelle `preuve.revoquer(app_id)` (nouvelle fonction : supprime la preuve du registre). Tests : verdict invalide → `/preuve` renvoie `valide: false` et `preuve_id: null` ; exception de l'exécuteur → idem ; une preuve valide antérieure ne survit pas à un échec.
- [ ] **Step 2 — isolation de l'exécuteur** (unit systemd) : `NoNewPrivileges=true`, `ProtectSystem=strict`, `ProtectHome=true`, `PrivateTmp=true`, `ReadWritePaths=` vide, `RestrictAddressFamilies=AF_INET AF_UNIX`, `CapabilityBoundingSet=`, `MemoryMax=1G`, `TasksMax=64`. L'exécuteur lance `docker`/`curl` : vérifier en LIVE (Task 11) que `docker exec` fonctionne encore sous ce confinement (le socket Docker doit rester accessible : sinon retirer `ProtectSystem` et le noter). Tests Ansible : le gabarit contient chaque directive.
- [ ] **Step 3 — hérités de la partie 1** (Core) : vérifier l'ordre des contrôles dans `consommer_id` (preuve contrôlée **avant** de consommer l'approbation) et l'héritage d'une preuve par une app recréée (la preuve est liée à `app_id` ET au nom : une app recréée avec le même nom ne reprend pas la preuve). Un test de non-régression par point ; si le comportement actuel est déjà correct, le test le fige.
- [ ] **Step 4 : commit** `fix(livraison): révocation de preuve à l'échec, exécuteur confiné, contrôles de preuve hérités`

---

### Task 9 : Nettoyage des images de retour arrière (Forgejo) — spike seulement

**Files:** Create `docs/s247/spike-registre-forgejo.md`.

Les redéploiements publient des versions `vN` dans le registre Forgejo (paquets conteneur) qui s'accumulent. Spike en session (clé Forgejo lue sans l'afficher) : `GET /api/v1/packages/{owner}?type=container` ; `DELETE /api/v1/packages/{owner}/container/{nom}/{version}` ; le jeton `FORGEJO_REGISTRY_TOKEN` suffit-il (portée `write:package`) ? Mesurer la place occupée. Livrable : un document qui tranche *où* faire la rétention (script de l'exécuteur sur la VM 100 avec timer, comme la sauvegarde Forgejo) et *combien garder* (proposition : les 10 dernières versions par image ET toute version référencée par un rollback Dokploy). **Pas de code en 2b** : un plan 2c l'implémentera.

- [ ] Rédiger le document, le commiter `docs(s247): spike du registre Forgejo (rétention des images de rollback)`.

---

### Task 10 : Preuve LIVE (EN SESSION AVEC L'UTILISATEUR, jamais un sous-agent)

**Préparation (sans coupure, sans secret affiché) :**
- [ ] **Step 0** : décider avec l'utilisateur les deux noms d'hôte du témoin (propositions : `calendrier.s247.test`, `calendrier-test.s247.test` ; rien ne les résout, les essais passent par l'en-tête `Host` sur `http://192.168.1.165:80`). Vérifier que le HP atteint la VM 100 en port 80 (`curl -sS -m 5 -o /dev/null -w "%{http_code}" -H "Host: x" http://192.168.1.165:80/` → 404 de Traefik attendu).
- [ ] **Step 1 : inventaire** : ajouter à `calendrier-familial` le bloc `reset` (`variable_env: DATABASE_URL`, domaines, `port_app` = port réel de l'app témoin, `sante_chemin: "/"` ou une route existante). Poser `DATABASE_URL=postgresql://temoin:<mot de passe de s247-pg>@<appName du Postgres>:5432/temoin` dans les variables de l'app d'origine **par le pipe, sans l'afficher** (le mot de passe de `s247-pg` a été généré à la création : le relire avec la clé owner, `postgres.one`, ou le réinitialiser). Écrire l'inventaire dans `/data/inventaire.json` (HP).
- [ ] **Step 2 : droits** : confirmer `backup.update` avec la clé limitée (sinon prévoir la 2ᵉ config de sauvegarde, cf. Task 3) ; confirmer que `application.create` avec la clé limitée n'a pas besoin d'un autre droit.
- [ ] **Step 3 : déploiement** : suivre la procédure de la 2a — tags `avant-s2b` du Cœur ET de la brique, construction sur le Mac (`docker build --platform linux/amd64`), `docker save | gzip | ssh … docker load`, **mettre à jour sur le HP la copie git (`git pull`) AVANT de redémarrer le Cœur** (il lit les manifestes dans `/briques`), `docker compose up -d --no-build` pour la brique puis `docker restart core-core-1`, redéployer l'exécuteur (`ansible-playbook` limité au rôle `executeur_restauration`, jamais le playbook complet) ; ajouter `LIVRAISON_TRAEFIK_URL` dans `briques/livraison/.env` du HP.
- [ ] **Step 4 : sabotages d'abord** (la base d'origine ne doit jamais bouger) : (a) corrompre le clone — pointer `variable_env` vers une variable absente → `echec env_inattendu`, hôtes inchangés ; (b) arrêter l'exécuteur en cours de reset → `echec`, aucun `domain.update` ; (c) fausse `sante_chemin` (route inexistante) → `echec sante_ko`. Pour chacun : lire `GET /operation`, constater que le domaine public répond toujours (boucle `curl` avec `Host:`) et que les comptages de `temoin` sont 42.
- [ ] **Step 5 : nominal** : lancer depuis le chat « remets calendrier-familial à neuf » ; constater la demande d'approbation Telegram (le bouton n'apparaît qu'avec une preuve valide : refaire d'abord « utilise `livraison_verifier_sauvegarde` pour calendrier-familial »), approuver, suivre `livraison_operation` jusqu'à `reussie`. **Mesure de non-coupure** : pendant tout le reset, une boucle `curl -s -o /dev/null -w "%{http_code}\n" -H "Host: calendrier.s247.test" http://192.168.1.165:80/` 10 fois par seconde ; **zéro** réponse ≠ 2xx/3xx attendue, y compris à l'instant de la bascule. Constater : emplacement actif = B, `DATABASE_URL` de B pointe sur `temoin_v…`, comptages 42 = 42, la sauvegarde Dokploy suit la nouvelle base (`backup.one` → `database`).
- [ ] **Step 6 : retour arrière** : « reviens à l'instance précédente » (approbation) → hôtes ré-échangés, base active = `temoin`, même boucle `curl` sans coupure. Puis un 2ᵉ reset nominal pour constater la réutilisation de l'emplacement et la suppression de la base N-2 (`select datname` sur le Postgres du témoin).
- [ ] **Step 7 : documenter** `docs/s247/preuve-reset-bleu-vert.md` (tableau essais/verdicts, mesure de non-coupure, limites connues 1–3, pièges rencontrés), mettre à jour la fiche S247, la mémoire `sprint-s247-sauvegarde-verifiee`, l'épopée ; commit ; **demander à l'utilisateur** avant de fusionner/pousser (finishing-a-development-branch).

---

## Self-Review

- **Couverture de la fiche** : reset sans effacement sur place (T6/T10), mise de côté + vérification (2a), nouvelle instance + contrôles (T6 étapes 3–5), bascule + bleue conservée + retour arrière (T6/T7), lien S245 prérequis (T7), secrets qui suivent sans fuite (T5/T6 tests), rétention/stockage (T6 étape 8, T9), preuve de bout en bout avec sabotage (T10). Hors 2b, explicitement : diagnostic préalable, page maintenance, nettoyage du registre (2c), miroir GitHub (autre sprint).
- **Placeholders** : aucun « TBD ». Les deux seuls points à constater en réel sont déclarés avec leur plan B : `backup.update` avec la clé limitée (T3/T10-2) et l'accès du confinement systemd à Docker (T8-2/T10).
- **Cohérence des noms** : `cloner/comptages/supprimer_base` (exécuteur T1 = client T2 = orchestrateur T6) ; `reecrire_env(env, variable, ancienne, nouvelle)` (T5 = T6) ; `base_effective`, `operations.*` (T4 = T6/T7) ; capacités `livraison_reset_app`, `livraison_retour_arriere`, `livraison_operation` (T7 = T10).
