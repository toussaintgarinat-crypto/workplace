# S248 partie 3a — Paquets chiffrés, stockage SeaweedFS, export + vérification — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal :** Que l'assistant puisse, pour UN utilisateur d'une app à contrat (Studio), exporter ses données en paquet chiffré stocké dans SeaweedFS (rétention 14 jours) puis PROUVER que ce paquet est restaurable — sans jamais lire le contenu.

**Architecture :** `livraison` orchestre : il appelle les routes `/support/*` de l'app, chiffre le paquet (AES-256-GCM, clé locale hors dépôt) et le dépose via l'exécuteur de restauration (VM 100), seul détenteur du secret S3, sur un préfixe réservé `contrat/`. Un registre local des paquets (`paquets.json`) porte les métadonnées (jamais le contenu) ; un journal d'accès JSONL trace chaque opération ; une purge supprime les paquets expirés. Un registre d'apps à contrat (`contrats.json`, tenu par l'exploitant comme `inventaire.json`) dit où joindre chaque app et quelle variable porte sa clé de support. Le Cœur n'est PAS modifié ici (voir 3b) : les outils exposés sont `livraison_donnees_exporter` et `livraison_donnees_verifier`, sans prérequis.

**Tech Stack :** Python 3.12, FastAPI + httpx (livraison), `cryptography` (nouvelle dépendance, AES-GCM), stdlib seule pour l'exécuteur et le Studio, pytest.

**Hors de ce plan (3b) :** reset/restitution (`livraison_donnees_reinitialiser`, `livraison_donnees_restituer`), prérequis `paquet_verifie` à clé composite dans le Cœur, `fournit_preuve` sur le vérificateur, preuve LIVE.

## Global Constraints

- L'assistant ne voit JAMAIS `donnees.json` : les routes de livraison ne renvoient que `paquet_id`, `empreinte`, `comptages`, `version_schema`, `expire_a`, verdict. Aucun `utilisateur` n'est renvoyé ni journalisé en clair (on utilise `h = sha256(utilisateur)[:16]`, même convention que les comptes du Studio).
- Le secret S3 ne quitte JAMAIS la VM 100 : `livraison` n'a aucune variable S3. Le chiffrement se fait dans `livraison` ; l'exécuteur ne voit que des octets chiffrés.
- Clé de chiffrement : `LIVRAISON_CHIFFREMENT_CLE` (base64 de 32 octets), dans `briques/livraison/.env` local (0600), JAMAIS le `.env` racine. Absente → 503, jamais de repli en clair.
- Clé de support d'une app : variable désignée par le registre, dont le nom doit finir par `_SUPPORT_KEY` (fullmatch `[A-Z][A-Z0-9_]{0,60}_SUPPORT_KEY`) : le registre ne peut pas faire lire `DOKPLOY_API_KEY` ou `EXECUTEUR_KEY`.
- Rétention : 14 jours (`RETENTION_S = 14 * 86400`), purge automatique ; un échec de suppression S3 laisse l'entrée du registre pour un nouvel essai.
- Objets S3 : uniquement `contrat/<app>/<h>/<id>.bin` (fullmatch `contrat/[a-z0-9_-]{1,40}/[0-9a-f]{16}/[0-9a-f]{32}\.bin`), taille max 80 Mio.
- Erreurs : messages fixes, jamais de donnée de l'utilisateur ni de clé ; verdicts de vérification en échec = `ok: True, verdict: "invalide"` (convention S247 « fail closed »).
- Routes d'écriture de livraison : `cle_api_fermee` (403 sans `LIVRAISON_API_KEYS`).
- Tests purs, aucun réseau. Commits en français, un par tâche, terminés par les lignes d'attribution du système.

## Structure des fichiers

| Fichier | Rôle |
|---|---|
| `shared/contrat_donnees.py` (modifier) | `valider_bloc_contrat` durci (`%2e`, `.`, `\`, `//`) |
| `briques/studio/contrat_donnees.py` (copie) | Resynchronisée par `outils/sync_socle.sh` |
| `briques/livraison/contrat_donnees.py` (copie) | Nouvelle copie (CONTRAT_BRIQUES += livraison) |
| `briques/studio/main.py` (modifier) | Plafond de corps 413 sur `/support/*` ; refus d'identité = clé secrète |
| `briques/studio/support.py` (modifier) | Normalisation du `cree_par` legacy à l'export |
| `outils/executeur-restauration/executeur.py` (modifier) | Routes `PUT/GET/DELETE /objets/<clé>` |
| `briques/livraison/client_executeur.py` (modifier) | `deposer` / `lire` / `supprimer` d'un objet |
| `briques/livraison/chiffrement.py` (créer) | AES-GCM, contexte = clé d'objet |
| `briques/livraison/contrats.py` (créer) | Registre des apps à contrat + client `/support/*` |
| `briques/livraison/paquets.py` (créer) | Registre des paquets, journal d'accès, rétention |
| `briques/livraison/main.py` (modifier) | Routes `/contrats/{app}/exporter`, `/verifier`, purge |
| `briques/livraison/manifest.json` (modifier) | Capacités `livraison_donnees_exporter` / `_verifier` |
| `briques/livraison/contrats.exemple.json` (créer) | Registre du Studio (copie du bloc du manifeste) |

---

### Task 1 : Durcir `valider_bloc_contrat` et propager la copie

**Files :**
- Modify : `shared/contrat_donnees.py` (fonction `valider_bloc_contrat`, ~l.137-160)
- Modify : `shared/test_contrat_donnees.py`
- Modify : `outils/sync_socle.sh:23` (`CONTRAT_BRIQUES=(studio livraison)`)

**Interfaces :**
- Produces : `chemin_support_sur(chemin) -> bool` (publique, réutilisée par `livraison/contrats.py`).

- [ ] **Step 1 : Écrire les tests qui échouent** (ajouter à la fin de `shared/test_contrat_donnees.py`)

```python
import pytest

BLOC_OK = {"version_schema": "1",
           "exporter": {"methode": "POST", "chemin": "/support/exporter"},
           "reinitialiser": {"methode": "POST", "chemin": "/support/reinitialiser"},
           "importer": {"methode": "POST", "chemin": "/support/importer"}}


@pytest.mark.parametrize("chemin", [
    "/support/%2e%2e/x", "/support/%2E%2E/x", "/support/./x", "/support//x",
    "/support/a\\b", "/support/exporter/", "/support/a b", "/support/a?x=1", "/support/é",
    "/support/", "/supportx/exporter"])
def test_chemin_dangereux_refuse(chemin):
    import contrat_donnees as C
    assert C.chemin_support_sur(chemin) is False
    bloc = dict(BLOC_OK, exporter={"methode": "POST", "chemin": chemin})
    assert C.valider_bloc_contrat(bloc)


def test_chemins_sains_acceptes():
    import contrat_donnees as C
    for ch in ("/support/exporter", "/support/v1/exporter", "/support/a-b_c.d~e"):
        assert C.chemin_support_sur(ch) is True
    assert C.valider_bloc_contrat(BLOC_OK) == []
```

(Si le fichier importe déjà `contrat_donnees as C` en tête, supprimer les imports locaux et utiliser l'alias existant.)

- [ ] **Step 2 : Lancer, vérifier l'échec**

Run : `cd shared && python3 -m pytest test_contrat_donnees.py -q -p no:cacheprovider`
Expected : FAIL (`AttributeError: ... chemin_support_sur`).

- [ ] **Step 3 : Implémenter** — dans `shared/contrat_donnees.py`, ajouter sous `_CHIFFRES_ASCII` :

```python
_CHEMIN_SUR = re.compile(r"/support/[A-Za-z0-9._~/-]+")


def chemin_support_sur(chemin) -> bool:
    """Chemin interne `/support/...` : alphabet restreint (donc ni `%`, ni `\\`, ni espace, ni `?`),
    aucun segment vide, `.` ou `..`, pas de `/` final."""
    if not (isinstance(chemin, str) and _CHEMIN_SUR.fullmatch(chemin)):
        return False
    return all(seg not in ("", ".", "..") for seg in chemin.split("/")[1:])
```

et remplacer, dans `valider_bloc_contrat`, la condition du chemin par :

```python
        if not chemin_support_sur(a.get("chemin")):
            erreurs.append(f"{action}.chemin doit commencer par /support/ et rester sûr")
```
(supprimer la variable locale `chemin` devenue inutile).

- [ ] **Step 4 : Propager et vérifier**

Éditer `outils/sync_socle.sh` : `CONTRAT_BRIQUES=(studio livraison)`. Puis :
Run : `bash outils/sync_socle.sh && cd shared && python3 -m pytest test_contrat_donnees.py -q -p no:cacheprovider && cd ../briques/studio && python3 -m pytest test_support_routes.py -q -p no:cacheprovider`
Expected : tout PASS ; `briques/livraison/contrat_donnees.py` existe ; `git diff --stat` montre la copie Studio mise à jour (le test `test_copie_de_la_bibliotheque_a_jour` du Studio passe).

- [ ] **Step 5 : Commit**

```bash
git add shared outils/sync_socle.sh briques/studio/contrat_donnees.py briques/livraison/contrat_donnees.py
git commit -m "fix(s248): valider_bloc_contrat refuse %2e, ., antislash, // ; copie dans livraison"
```

---

### Task 2 : Studio — plafond de corps 413 sur `/support/*`

**Files :**
- Modify : `briques/studio/main.py` (bloc « Contrat de données », ~l.1556-1625)
- Test : `briques/studio/test_support_routes.py`

**Interfaces :**
- Produces : `CORPS_SUPPORT_MAX: int` (module `main`) ; `async def _corps_borne(request) -> bytes` (413 `trop_gros`).

- [ ] **Step 1 : Test qui échoue** (ajouter à `test_support_routes.py`)

```python
def test_corps_trop_gros_413_sur_verifier_et_importer(monkeypatch):
    monkeypatch.setattr(main, "CORPS_SUPPORT_MAX", 100)
    for route in ("verifier", "importer"):
        r = client.post(f"/support/{route}?utilisateur=claire", content=b"x" * 200, headers=H)
        assert r.status_code == 413, route
        assert r.json()["detail"] == "trop_gros"


def test_corps_borne_ne_masque_pas_le_401():
    r = client.post("/support/verifier?utilisateur=claire", content=b"x" * 10)
    assert r.status_code == 401
```

- [ ] **Step 2 :** `cd briques/studio && python3 -m pytest test_support_routes.py -q -p no:cacheprovider -k corps` → FAIL.

- [ ] **Step 3 : Implémenter** — dans `main.py`, juste avant `class CibleSupport`, ajouter :

```python
CORPS_SUPPORT_MAX = C.TAILLE_MAX + 1024 * 1024   # le paquet est borné par la bibliothèque (64 Mio)


async def _corps_borne(request: Request) -> bytes:
    """Lit le corps EN FLUX avec plafond : refuse (413) dès le dépassement, que le client annonce
    ou non un Content-Length. La clé de support est déjà vérifiée (dépendance) avant d'arriver ici."""
    try:
        annonce = int(request.headers.get("content-length", "0") or 0)
    except ValueError:
        raise HTTPException(400, "content-length invalide")
    if annonce > CORPS_SUPPORT_MAX:
        raise HTTPException(413, "trop_gros")
    morceaux, total = [], 0
    async for m in request.stream():
        total += len(m)
        if total > CORPS_SUPPORT_MAX:
            raise HTTPException(413, "trop_gros")
        morceaux.append(m)
    return b"".join(morceaux)
```
Puis remplacer `await request.body()` par `await _corps_borne(request)` dans `support_verifier` ET `support_importer` (2 occurrences).

- [ ] **Step 4 :** relancer tout le fichier : `python3 -m pytest test_support_routes.py test_support.py -q -p no:cacheprovider` → PASS.

- [ ] **Step 5 : Commit** `git commit -am "fix(s248): plafond de corps 413 sur les routes /support du Studio"`

---

### Task 3 : Studio — plus de secret dans le paquet (cree_par legacy, identité = clé)

**Files :**
- Modify : `briques/studio/support.py` (`exporter`, ~l.99-125)
- Modify : `briques/studio/main.py` (`_cible`, ~l.1569)
- Test : `briques/studio/test_support.py`, `briques/studio/test_support_routes.py`

**Interfaces :**
- Consumes : `S.identite_effective(objet) -> str` (existante).
- Produces : l'export ne contient plus jamais la valeur brute de `STUDIO_KEY` ; `_cible` refuse (422 `identite_interdite`) un `utilisateur` égal à `STUDIO_KEY` ou à un élément de `API_KEYS`.

- [ ] **Step 1 : Tests qui échouent**

Dans `test_support.py` (réutiliser le helper de peuplement existant du fichier ; sinon `S._save` comme dans `peupler` de `test_support_routes.py`) :

```python
def test_export_ne_contient_pas_la_studio_key_legacy(monkeypatch, volume_jetable_ou_equivalent):
    monkeypatch.setenv("STUDIO_KEY", "cle-brute-secrete")
    S._save({"id": "s-legacy", "titre": "Ancienne", "cree_par": "cle-brute-secrete", "episodes": []})
    objets = SUP.exporter("perso")
    assert [s["id"] for s in objets["series"]] == ["s-legacy"]
    assert "cle-brute-secrete" not in json.dumps(objets)
    assert objets["series"][0]["cree_par"] == "perso"
```
(Le nom de la fixture de volume jetable est celui déjà utilisé dans `test_support.py` — l'ouvrir et reprendre exactement le même.)

Dans `test_support_routes.py` :

```python
@pytest.mark.parametrize("secret_env", ["STUDIO_KEY", "API_KEYS"])
def test_identite_egale_a_une_cle_secrete_refusee(monkeypatch, secret_env):
    monkeypatch.setenv(secret_env, "autre-cle-xyz, cle-secrete-123")
    cible = "cle-secrete-123" if secret_env == "API_KEYS" else "autre-cle-xyz, cle-secrete-123"
    r = client.post("/support/exporter", json={"utilisateur": cible}, headers=H)
    assert r.status_code == 422 and r.json()["detail"] == "identite_interdite"
```

- [ ] **Step 2 :** lancer les deux fichiers → FAIL.

- [ ] **Step 3 : Implémenter**

`support.py`, dans `exporter`, après le calcul de `series` :

```python
    # Jamais de secret dans un paquet qui peut quitter le volume : une série dont `cree_par` est
    # l'ancienne STUDIO_KEY brute est exportée sous l'identité normalisée (copie, fichier intact).
    series = [dict(s, cree_par=S.identite_effective(s)) if s.get("cree_par") != S.identite_effective(s)
              else s for s in series]
```

`main.py`, dans `_cible`, après le test des espaces :

```python
    secrets_ = {k.strip() for var in ("STUDIO_KEY", "API_KEYS")
                for k in os.environ.get(var, "").split(",") if k.strip()}
    if utilisateur in secrets_:
        raise HTTPException(422, "identite_interdite")  # identité BYO = clé API : jamais dans un paquet
```

- [ ] **Step 4 :** `python3 -m pytest test_support.py test_support_routes.py -q -p no:cacheprovider` → PASS (le test de conformité round-trip doit rester vert : export normalisé = import = ré-export).

- [ ] **Step 5 : Commit** `git commit -am "fix(s248): aucun secret dans le paquet (cree_par legacy normalisé, identité=clé refusée)"`

---

### Task 4 : Exécuteur — dépôt, lecture, suppression d'objets `contrat/…`

**Files :**
- Modify : `outils/executeur-restauration/executeur.py`
- Create : `outils/executeur-restauration/test_executeur_objets.py`

**Interfaces :**
- Produces : `RE_CLE_OBJET`, `MAX_OBJET`, `cle_objet(chemin) -> str`, `deposer_objet(runner, cfg, cle, source: Path) -> None`, `lire_objet(runner, cfg, cle, dest: Path) -> None`, `supprimer_objet(runner, cfg, cle) -> None` (toutes lèvent `ErreurExecuteur` 400/502) ; routes HTTP `PUT|GET|DELETE /objets/<clé>` (même clé `X-API-Key`).

- [ ] **Step 1 : Tests qui échouent** — `test_executeur_objets.py` :

```python
import hashlib
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

import executeur
from executeur import ErreurExecuteur

SECRET = "s3cr3t-tres-long-et-unique"
CFG = {"KEY": "cle-exec", "S3_ENDPOINT": "http://s3.test:9106", "S3_BUCKET": "dokploy-backups",
       "S3_KEY": "AKIATEST", "S3_SECRET": SECRET, "S3_REGION": "us-east-1"}
CLE = "contrat/studio/0123456789abcdef/" + "a" * 32 + ".bin"


class FauxS3:
    def __init__(self, echec=0):
        self.objets, self.appels, self.echec = {}, [], echec

    def run(self, argv, stdin=None, timeout=300):
        self.appels.append((list(argv), stdin))
        if self.echec:
            return self.echec, b"", b""
        url = argv[-1]
        if "-T" in argv:
            self.objets[url] = Path(argv[argv.index("-T") + 1]).read_bytes()
        elif "DELETE" in argv:
            self.objets.pop(url, None)
        else:
            Path(argv[argv.index("-o") + 1]).write_bytes(self.objets[url])
        return 0, b"", b""


def test_cle_objet_valide_et_refus():
    assert executeur.cle_objet("/objets/" + CLE) == CLE
    for mauvais in ("/objets/../x", "/objets/contrat/../../x.bin", "/objets/autre/x.bin",
                    "/objets/contrat/Studio/0123456789abcdef/" + "a" * 32 + ".bin",
                    "/objets/" + CLE + "\n", "/objets/"):
        with pytest.raises(ErreurExecuteur) as e:
            executeur.cle_objet(mauvais)
        assert e.value.statut == 400


def test_deposer_lire_supprimer_et_secret_hors_argv(tmp_path):
    r = FauxS3()
    src = tmp_path / "p.bin"
    src.write_bytes(b"chiffre")
    executeur.deposer_objet(r, CFG, CLE, src)
    argv, stdin = r.appels[0]
    assert SECRET not in " ".join(argv) and SECRET.encode() in stdin
    assert "x-amz-content-sha256: " + hashlib.sha256(b"chiffre").hexdigest() in argv
    dest = tmp_path / "out.bin"
    executeur.lire_objet(r, CFG, CLE, dest)
    assert dest.read_bytes() == b"chiffre"
    executeur.supprimer_objet(r, CFG, CLE)
    assert r.objets == {}


def test_echec_curl_502_message_fixe(tmp_path):
    src = tmp_path / "p.bin"
    src.write_bytes(b"x")
    with pytest.raises(ErreurExecuteur) as e:
        executeur.deposer_objet(FauxS3(echec=22), CFG, CLE, src)
    assert e.value.statut == 502 and SECRET not in e.value.message


@pytest.fixture
def serveur():
    r = FauxS3()
    srv = ThreadingHTTPServer(("127.0.0.1", 0), executeur.fabrique_handler(r, CFG))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}", r
    srv.shutdown()


def _req(base, methode, chemin, corps=None, cle="cle-exec"):
    q = urllib.request.Request(base + chemin, data=corps, method=methode,
                               headers={"X-API-Key": cle})
    try:
        with urllib.request.urlopen(q) as rep:
            return rep.status, rep.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def test_http_put_get_delete(serveur):
    base, r = serveur
    assert _req(base, "PUT", "/objets/" + CLE, b"octets-chiffres")[0] == 200
    assert _req(base, "GET", "/objets/" + CLE) == (200, b"octets-chiffres")
    assert _req(base, "DELETE", "/objets/" + CLE)[0] == 200
    assert r.objets == {}


def test_http_401_et_cle_invalide_et_corps_trop_gros(serveur, monkeypatch):
    base, _ = serveur
    assert _req(base, "PUT", "/objets/" + CLE, b"x", cle="fausse")[0] == 401
    assert _req(base, "GET", "/objets/" + CLE, cle="fausse")[0] == 401
    assert _req(base, "PUT", "/objets/autre/x.bin", b"x")[0] == 400
    monkeypatch.setattr(executeur, "MAX_OBJET", 3)
    assert _req(base, "PUT", "/objets/" + CLE, b"xxxx")[0] == 413
```

- [ ] **Step 2 :** `cd outils/executeur-restauration && python3 -m pytest test_executeur_objets.py -q -p no:cacheprovider` → FAIL.

- [ ] **Step 3 : Implémenter** — dans `executeur.py`, après `telecharger` :

```python
RE_CLE_OBJET = re.compile(r"contrat/[a-z0-9_-]{1,40}/[0-9a-f]{16}/[0-9a-f]{32}\.bin")
MAX_OBJET = 80 * 1024 * 1024
PREFIXE_OBJETS = "/objets/"


def cle_objet(chemin: str) -> str:
    cle = chemin[len(PREFIXE_OBJETS):] if chemin.startswith(PREFIXE_OBJETS) else ""
    if not RE_CLE_OBJET.fullmatch(cle):
        raise ErreurExecuteur(400, "objet invalide")
    return cle


def _curl_objet(runner, cfg: dict, cle: str, args: list, echec: str) -> None:
    url = f"{cfg['S3_ENDPOINT'].rstrip('/')}/{cfg['S3_BUCKET']}/{cle}"
    identifiants = f'user = "{cfg["S3_KEY"]}:{cfg["S3_SECRET"]}"\n'.encode()
    code, _, _ = runner.run(["curl", "-sS", "-f", "--aws-sigv4", f"aws:amz:{cfg['S3_REGION']}:s3",
                             *args, "-K", "-", url], stdin=identifiants, timeout=600)
    if code != 0:
        raise ErreurExecuteur(502, echec)


def deposer_objet(runner, cfg: dict, cle: str, source: Path) -> None:
    sha = hashlib.sha256(source.read_bytes()).hexdigest()   # signé explicitement (pas d'UNSIGNED-PAYLOAD)
    _curl_objet(runner, cfg, cle, ["-X", "PUT", "-H", f"x-amz-content-sha256: {sha}",
                                   "-T", str(source)], "dépôt de l'objet impossible")


def lire_objet(runner, cfg: dict, cle: str, dest: Path) -> None:
    _curl_objet(runner, cfg, cle, ["--max-filesize", str(MAX_OBJET), "-o", str(dest)],
                "lecture de l'objet impossible")


def supprimer_objet(runner, cfg: dict, cle: str) -> None:
    _curl_objet(runner, cfg, cle, ["-X", "DELETE"], "suppression de l'objet impossible")
```
(ajouter `import hashlib` en tête.) Dans `fabrique_handler`, ajouter à `Handler` :

```python
        def _authentifie(self) -> bool:
            presentee = self.headers.get("X-API-Key", "")
            if hmac.compare_digest(presentee.encode(), cfg["KEY"].encode()):
                return True
            self._rep(401, {"erreur": "clé invalide"})
            return False

        def _objet(self, methode: str):
            if not self.path.startswith(PREFIXE_OBJETS):
                return self._rep(404, {"erreur": "introuvable"})
            if not self._authentifie():
                return
            try:
                cle = cle_objet(self.path)
                with tempfile.TemporaryDirectory() as tmp:
                    f = Path(tmp) / "objet.bin"
                    if methode == "PUT":
                        taille = int(self.headers.get("Content-Length", "0") or 0)
                        if taille <= 0:
                            raise ErreurExecuteur(400, "corps invalide")
                        if taille > MAX_OBJET:
                            raise ErreurExecuteur(413, "objet trop gros")
                        restant = taille
                        with open(f, "wb") as out:
                            while restant:
                                morceau = self.rfile.read(min(restant, 1 << 20))
                                if not morceau:
                                    raise ErreurExecuteur(400, "corps incomplet")
                                out.write(morceau)
                                restant -= len(morceau)
                        deposer_objet(runner, cfg, cle, f)
                        return self._rep(200, {"ok": True})
                    if methode == "DELETE":
                        supprimer_objet(runner, cfg, cle)
                        return self._rep(200, {"ok": True})
                    lire_objet(runner, cfg, cle, f)
                    octets = f.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(len(octets)))
                self.end_headers()
                self.wfile.write(octets)
            except ErreurExecuteur as e:
                self._rep(e.statut, {"erreur": e.message})
            except Exception:   # jamais de détail ni de trace vers le client
                self._rep(500, {"erreur": "erreur interne de l'exécuteur"})

        def do_PUT(self):
            self._objet("PUT")

        def do_DELETE(self):
            self._objet("DELETE")
```
Remplacer le corps de `do_GET` par : si `self.path.startswith(PREFIXE_OBJETS)` → `return self._objet("GET")`, sinon le comportement actuel (`/sante`, 404). Ces routes n'utilisent PAS `VERROU` (un stockage ne doit pas attendre une restauration de 15 min).

- [ ] **Step 4 :** `python3 -m pytest -q -p no:cacheprovider` (tout le dossier) → PASS.

- [ ] **Step 5 : Commit** `git add outils/executeur-restauration && git commit -m "feat(s248): l'exécuteur dépose/lit/supprime des objets contrat/ (secret S3 inchangé)"`

---

### Task 5 : Client de l'exécuteur — objets

**Files :**
- Modify : `briques/livraison/client_executeur.py`
- Test : `briques/livraison/test_client_executeur.py`

**Interfaces :**
- Consumes : routes de la Task 4.
- Produces : `Executeur.deposer(cle: str, octets: bytes) -> None`, `Executeur.lire(cle: str) -> bytes`, `Executeur.supprimer(cle: str) -> None` ; erreurs `ExecuteurErreur` (messages fixes, jamais de corps brut).

- [ ] **Step 1 : Tests qui échouent** (ajouter ; reprendre en tête de fichier les imports déjà présents : `httpx`, `pytest`, `asyncio` ou `pytest.mark.asyncio` selon la convention du fichier — l'ouvrir et reproduire son style exact pour exécuter une coroutine)

```python
CLE_OBJ = "contrat/studio/0123456789abcdef/" + "a" * 32 + ".bin"


def _ex(handler):
    return Executeur("http://exec.test", "k", transport=httpx.MockTransport(handler))


def test_deposer_lire_supprimer():
    vu = {}

    def h(req: httpx.Request):
        vu[req.method] = (str(req.url.path), req.headers.get("x-api-key"), req.content)
        return httpx.Response(200, content=b"retour" if req.method == "GET" else b"{}")

    ex = _ex(h)
    asyncio.run(ex.deposer(CLE_OBJ, b"abc"))
    assert asyncio.run(ex.lire(CLE_OBJ)) == b"retour"
    asyncio.run(ex.supprimer(CLE_OBJ))
    assert vu["PUT"] == ("/objets/" + CLE_OBJ, "k", b"abc")
    assert set(vu) == {"PUT", "GET", "DELETE"}


@pytest.mark.parametrize("statut,attendu", [(401, "refusé la clé"), (413, "trop gros"),
                                            (502, "502"), (500, "500")])
def test_objets_erreurs_sans_corps_brut(statut, attendu):
    ex = _ex(lambda r: httpx.Response(statut, json={"erreur": "SECRET-INTERNE"}))
    with pytest.raises(ExecuteurErreur) as e:
        asyncio.run(ex.deposer(CLE_OBJ, b"x"))
    assert attendu in e.value.message and "SECRET" not in e.value.message
```

- [ ] **Step 2 :** `cd briques/livraison && python3 -m pytest test_client_executeur.py -q -p no:cacheprovider` → FAIL.

- [ ] **Step 3 : Implémenter** — dans `Executeur` :

```python
    async def _objet(self, methode: str, cle: str, contenu: Optional[bytes] = None) -> bytes:
        try:
            async with httpx.AsyncClient(base_url=self._base, transport=self._transport,
                                         timeout=DELAI_OBJET) as c:
                r = await c.request(methode, "/objets/" + cle, headers={"X-API-Key": self._cle},
                                    content=contenu)
        except (httpx.ConnectError, httpx.ConnectTimeout):
            raise ExecuteurErreur("Exécuteur de restauration injoignable.") from None
        except httpx.HTTPError:
            raise ExecuteurErreur("Échec de la communication avec l'exécuteur "
                                  "(délai dépassé ?).") from None
        if r.status_code == 401:
            raise ExecuteurErreur("L'exécuteur a refusé la clé.", 401)
        if r.status_code == 413:
            raise ExecuteurErreur("Objet trop gros pour l'exécuteur.", 413)
        if r.status_code != 200:
            raise ExecuteurErreur(f"L'exécuteur a répondu {r.status_code}.", r.status_code)
        return r.content

    async def deposer(self, cle: str, octets: bytes) -> None:
        await self._objet("PUT", cle, octets)

    async def lire(self, cle: str) -> bytes:
        return await self._objet("GET", cle)

    async def supprimer(self, cle: str) -> None:
        await self._objet("DELETE", cle)
```
et la constante `DELAI_OBJET = 300.0` sous `DELAI_CLONER`.

- [ ] **Step 4 :** relancer → PASS. **Step 5 : Commit** `git commit -am "feat(s248): client exécuteur — dépôt, lecture, suppression d'objets"`

---

### Task 6 : Chiffrement AES-GCM

**Files :**
- Create : `briques/livraison/chiffrement.py`, `briques/livraison/test_chiffrement.py`
- Modify : `briques/livraison/requirements.txt` (ajouter `cryptography==43.0.3`), `briques/livraison/.env.example`

**Interfaces :**
- Produces : `class CleAbsente(Exception)`, `class Illisible(Exception)`, `chiffrer(clair: bytes, contexte: str) -> bytes`, `dechiffrer(blob: bytes, contexte: str) -> bytes`. Le `contexte` (= clé d'objet) est authentifié (AAD) : un blob déplacé sous une autre clé est refusé.

- [ ] **Step 1 : Tests qui échouent** — `test_chiffrement.py` :

```python
import base64
import os

import pytest

import chiffrement as C


@pytest.fixture(autouse=True)
def cle(monkeypatch):
    monkeypatch.setenv("LIVRAISON_CHIFFREMENT_CLE", base64.b64encode(os.urandom(32)).decode())


def test_aller_retour_et_non_deterministe():
    a, b = C.chiffrer(b"secret", "ctx"), C.chiffrer(b"secret", "ctx")
    assert a != b and b"secret" not in a
    assert C.dechiffrer(a, "ctx") == b"secret"


def test_contexte_different_refuse():
    with pytest.raises(C.Illisible):
        C.dechiffrer(C.chiffrer(b"x", "ctx-1"), "ctx-2")


def test_blob_altere_ou_trop_court_refuse():
    blob = bytearray(C.chiffrer(b"x", "c"))
    blob[-1] ^= 1
    for mauvais in (bytes(blob), b"", b"WP1", b"XXX" + bytes(40)):
        with pytest.raises(C.Illisible):
            C.dechiffrer(mauvais, "c")


@pytest.mark.parametrize("valeur", ["", "   ", "pas-du-base64!!", base64.b64encode(b"court").decode()])
def test_cle_absente_ou_invalide(monkeypatch, valeur):
    monkeypatch.setenv("LIVRAISON_CHIFFREMENT_CLE", valeur)
    with pytest.raises(C.CleAbsente):
        C.chiffrer(b"x", "c")


def test_changer_la_cle_rend_illisible(monkeypatch):
    blob = C.chiffrer(b"x", "c")
    monkeypatch.setenv("LIVRAISON_CHIFFREMENT_CLE", base64.b64encode(os.urandom(32)).decode())
    with pytest.raises(C.Illisible):
        C.dechiffrer(blob, "c")
```

- [ ] **Step 2 :** `pip install cryptography==43.0.3` dans l'environnement de test si absent, puis `python3 -m pytest test_chiffrement.py -q -p no:cacheprovider` → FAIL (module absent).

- [ ] **Step 3 : Implémenter** — `chiffrement.py` :

```python
"""Chiffrement des paquets de données au repos (S248 3a) : AES-256-GCM, clé hors dépôt.

Format : b"WP1" + nonce (12 o) + chiffré||étiquette. Le `contexte` (la clé d'objet S3) est lié au
chiffrement (AAD) : un blob copié sous une autre clé est refusé. Changer la clé rend illisibles
les paquets déjà stockés (la rétention de 14 jours borne l'exposition ; vider avant rotation)."""
import base64
import binascii
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIE = b"WP1"
TAILLE_NONCE = 12


class CleAbsente(Exception):
    """LIVRAISON_CHIFFREMENT_CLE absente ou invalide : on refuse, jamais de repli en clair."""


class Illisible(Exception):
    """Blob altéré, mauvaise clé, mauvais contexte ou format inconnu."""


def _cle() -> bytes:
    brut = os.getenv("LIVRAISON_CHIFFREMENT_CLE", "").strip()
    try:
        cle = base64.b64decode(brut, validate=True)
    except (binascii.Error, ValueError):
        raise CleAbsente("clé de chiffrement invalide") from None
    if len(cle) != 32:
        raise CleAbsente("clé de chiffrement absente ou de mauvaise taille")
    return cle


def chiffrer(clair: bytes, contexte: str) -> bytes:
    nonce = os.urandom(TAILLE_NONCE)
    return MAGIE + nonce + AESGCM(_cle()).encrypt(nonce, clair, contexte.encode("utf-8"))


def dechiffrer(blob: bytes, contexte: str) -> bytes:
    if not blob.startswith(MAGIE) or len(blob) < len(MAGIE) + TAILLE_NONCE + 16:
        raise Illisible("format")
    nonce = blob[len(MAGIE):len(MAGIE) + TAILLE_NONCE]
    try:
        return AESGCM(_cle()).decrypt(nonce, blob[len(MAGIE) + TAILLE_NONCE:],
                                      contexte.encode("utf-8"))
    except InvalidTag:
        raise Illisible("authentification") from None
```

`.env.example` : ajouter
```
# Chiffrement au repos des paquets de données utilisateur (S248). base64 de 32 octets aléatoires :
#   python3 -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"
# À poser dans briques/livraison/.env (local, 0600), PAS dans le .env racine. Absente => 503.
# Changer cette clé rend illisibles les paquets déjà stockés.
LIVRAISON_CHIFFREMENT_CLE=
# Clés de support des apps à contrat (même valeur que celle posée côté app), une variable par app,
# nom = <APP>_SUPPORT_KEY (voir contrats.json).
STUDIO_SUPPORT_KEY=
```

- [ ] **Step 4 :** relancer → PASS. **Step 5 : Commit** `git add briques/livraison && git commit -m "feat(s248): chiffrement AES-GCM des paquets (clé hors dépôt, contexte authentifié)"`

---

### Task 7 : Registre des apps à contrat + client `/support/*`

**Files :**
- Create : `briques/livraison/contrats.py`, `briques/livraison/contrats.exemple.json`, `briques/livraison/test_contrats.py`

**Interfaces :**
- Consumes : `contrat_donnees.valider_bloc_contrat`, `contrat_donnees.chemin_support_sur` (copie Task 1).
- Produces :
  - `lire(nom_app: str) -> dict | None` → `{"url": str, "cle_env": str, "bloc": dict}` ou `None` (absent/invalide : fail closed).
  - `class ContratErreur(Exception)` : `.message`, `.statut: int | None`, `.raison: str`.
  - `class AppContrat(nom: str, entree: dict, transport=None, delai=120.0)` avec `async exporter(utilisateur) -> tuple[bytes, dict]` (paquet, `{"empreinte": str, "comptages": dict}`), `async verifier(utilisateur, paquet) -> dict`, `async reinitialiser(utilisateur, empreinte) -> dict`, `async importer(utilisateur, paquet) -> dict`.
  - `ouvrir(nom_app, transport=None) -> AppContrat` (lève `ContratErreur` si registre absent ou clé non configurée).

- [ ] **Step 1 : Tests qui échouent** — `test_contrats.py` :

```python
import asyncio
import json
import os
import pathlib

import httpx
import pytest

import contrats
from contrats import AppContrat, ContratErreur

BLOC = {"version_schema": "1",
        "exporter": {"methode": "POST", "chemin": "/support/exporter"},
        "reinitialiser": {"methode": "POST", "chemin": "/support/reinitialiser"},
        "importer": {"methode": "POST", "chemin": "/support/importer"}}
ENTREE = {"url": "http://studio.test:6060", "cle_env": "STUDIO_SUPPORT_KEY", "bloc": BLOC}


def _ecrire(monkeypatch, tmp_path, contenu):
    p = tmp_path / "contrats.json"
    p.write_text(json.dumps(contenu))
    monkeypatch.setenv("LIVRAISON_CONTRATS", str(p))


def test_lire_valide_et_insensible_a_la_casse(monkeypatch, tmp_path):
    _ecrire(monkeypatch, tmp_path, {"studio": ENTREE})
    assert contrats.lire(" Studio ")["url"] == "http://studio.test:6060"
    assert contrats.lire("inconnu") is None


@pytest.mark.parametrize("mut", [
    lambda e: e.update(cle_env="DOKPLOY_API_KEY"),
    lambda e: e.update(cle_env="EXECUTEUR_KEY"),
    lambda e: e.update(cle_env="studio_support_key"),
    lambda e: e.update(url="ftp://x"),
    lambda e: e.update(url="http://x/chemin"),
    lambda e: e.update(url="http://user:pw@x:1"),
    lambda e: e["bloc"].update(version_schema="un"),
    lambda e: e["bloc"]["exporter"].update(chemin="/support/%2e%2e/x"),
    lambda e: e.update(extra=1),
    lambda e: e.pop("bloc"),
])
def test_entree_invalide_refusee(monkeypatch, tmp_path, mut):
    e = json.loads(json.dumps(ENTREE))
    mut(e)
    _ecrire(monkeypatch, tmp_path, {"studio": e})
    assert contrats.lire("studio") is None


def test_registre_absent_ou_illisible(monkeypatch, tmp_path):
    monkeypatch.setenv("LIVRAISON_CONTRATS", str(tmp_path / "absent.json"))
    assert contrats.lire("studio") is None
    (tmp_path / "x.json").write_text("{pas du json")
    monkeypatch.setenv("LIVRAISON_CONTRATS", str(tmp_path / "x.json"))
    assert contrats.lire("studio") is None


def test_ouvrir_sans_cle_configuree(monkeypatch, tmp_path):
    _ecrire(monkeypatch, tmp_path, {"studio": ENTREE})
    monkeypatch.delenv("STUDIO_SUPPORT_KEY", raising=False)
    with pytest.raises(ContratErreur) as e:
        contrats.ouvrir("studio")
    assert e.value.statut == 503


def _app(handler, monkeypatch):
    monkeypatch.setenv("STUDIO_SUPPORT_KEY", "cle-support")
    return AppContrat("studio", ENTREE, transport=httpx.MockTransport(handler))


def test_exporter_renvoie_paquet_et_metadonnees(monkeypatch):
    def h(req):
        assert req.headers["x-support-key"] == "cle-support"
        assert json.loads(req.content) == {"utilisateur": "claire"}
        return httpx.Response(200, content=b"PAQUET", headers={
            "X-Empreinte": "abc", "X-Comptages": json.dumps({"series": 2})})
    paquet, meta = asyncio.run(_app(h, monkeypatch).exporter("claire"))
    assert paquet == b"PAQUET" and meta == {"empreinte": "abc", "comptages": {"series": 2}}


def test_exporter_sans_entetes_refuse(monkeypatch):
    with pytest.raises(ContratErreur):
        asyncio.run(_app(lambda r: httpx.Response(200, content=b"P"), monkeypatch).exporter("c"))


def test_verifier_envoie_les_octets_et_l_utilisateur_en_query(monkeypatch):
    def h(req):
        assert req.url.path == "/support/verifier" and req.url.params["utilisateur"] == "claire"
        assert req.content == b"PAQUET"
        return httpx.Response(200, json={"ok": True, "empreinte": "abc", "comptages": {}})
    assert asyncio.run(_app(h, monkeypatch).verifier("claire", b"PAQUET"))["empreinte"] == "abc"


@pytest.mark.parametrize("statut,raison", [(409, "empreinte"), (422, "signature"),
                                           (401, "cle_refusee"), (503, "desactive")])
def test_erreurs_ne_portent_que_la_raison(monkeypatch, statut, raison):
    corps = {"detail": raison if statut in (409, 422) else "SECRET claire@x.fr"}
    app = _app(lambda r: httpx.Response(statut, json=corps), monkeypatch)
    with pytest.raises(ContratErreur) as e:
        asyncio.run(app.reinitialiser("claire", "e"))
    assert e.value.statut == statut and e.value.raison == raison
    assert "SECRET" not in e.value.message and "claire" not in e.value.message


def test_injoignable(monkeypatch):
    def h(req):
        raise httpx.ConnectError("x")
    with pytest.raises(ContratErreur) as e:
        asyncio.run(_app(h, monkeypatch).importer("c", b"P"))
    assert e.value.statut is None and "injoignable" in e.value.message


def test_exemple_a_jour_avec_le_manifeste_du_studio():
    racine = pathlib.Path(__file__).resolve().parents[2]
    manifeste = racine / "briques" / "studio" / "manifest.json"
    if not manifeste.exists():
        pytest.skip("hors monorepo (image Docker)")
    exemple = json.loads((pathlib.Path(__file__).parent / "contrats.exemple.json").read_text())
    assert exemple["studio"]["bloc"] == json.loads(manifeste.read_text())["contrat_donnees"]
```

- [ ] **Step 2 :** lancer → FAIL (module absent).

- [ ] **Step 3 : Implémenter** — `contrats.py` :

```python
"""Registre des apps à contrat de données + client de leurs routes /support/* (S248 3a).

Fichier JSON tenu par l'exploitant (comme `inventaire.json`) : une app absente ou mal formée
n'est PAS jouée « au hasard », on refuse. Le bloc `contrat_donnees` du manifeste y est copié et
VALIDÉ ici (chemins sûrs, version numérique) : c'est le point où le bloc est exploité."""
import json
import os
import re
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

import httpx

import contrat_donnees as C

_RE_CLE_ENV = re.compile(r"[A-Z][A-Z0-9_]{0,60}_SUPPORT_KEY")
_RE_RAISON = re.compile(r"[a-z_]{1,30}")
_CHAMPS = {"url", "cle_env", "bloc"}
CHEMIN_VERIFIER = "/support/verifier"   # fixe : hors bloc (le bloc n'a que 3 actions)
DELAI_S = 120.0


class ContratErreur(Exception):
    def __init__(self, message: str, statut: Optional[int] = None, raison: str = ""):
        super().__init__(message)
        self.message, self.statut, self.raison = message, statut, raison


def _chemin() -> Path:
    explicite = os.getenv("LIVRAISON_CONTRATS")
    return Path(explicite) if explicite else Path(os.getenv("LIVRAISON_DATA", "/data")) / "contrats.json"


def _url_sure(url) -> bool:
    if not isinstance(url, str):
        return False
    p = urlsplit(url)
    return (p.scheme in ("http", "https") and bool(p.hostname) and p.path in ("", "/")
            and not (p.username or p.password or p.query or p.fragment))


def _valide(e) -> bool:
    return (isinstance(e, dict) and set(e) == _CHAMPS and _url_sure(e["url"])
            and isinstance(e["cle_env"], str) and _RE_CLE_ENV.fullmatch(e["cle_env"]) is not None
            and not C.valider_bloc_contrat(e["bloc"]))


def lire(nom_app: str) -> Optional[dict]:
    try:
        d = json.loads(_chemin().read_text())
    except (OSError, ValueError):
        return None
    e = d.get((nom_app or "").strip().lower()) if isinstance(d, dict) else None
    return json.loads(json.dumps(e)) if _valide(e) else None


def ouvrir(nom_app: str, transport: Optional[httpx.AsyncBaseTransport] = None) -> "AppContrat":
    e = lire(nom_app)
    if e is None:
        raise ContratErreur("aucun contrat de données valide pour cette application", 404, "inconnu")
    return AppContrat(nom_app.strip().lower(), e, transport)


class AppContrat:
    def __init__(self, nom: str, entree: dict, transport: Optional[httpx.AsyncBaseTransport] = None,
                 delai: float = DELAI_S):
        self.nom, self._e, self._transport, self._delai = nom, entree, transport, delai
        self._cle = os.getenv(entree["cle_env"], "").strip()
        if not self._cle:
            raise ContratErreur("clé de support de l'application non configurée", 503, "non_configure")

    @property
    def version_schema(self) -> str:
        return self._e["bloc"]["version_schema"]

    async def _appel(self, methode: str, chemin: str, **kw) -> httpx.Response:
        try:
            async with httpx.AsyncClient(base_url=self._e["url"], transport=self._transport,
                                         timeout=self._delai) as c:
                r = await c.request(methode, chemin, headers={"X-Support-Key": self._cle}, **kw)
        except (httpx.ConnectError, httpx.ConnectTimeout):
            raise ContratErreur("application injoignable", None, "injoignable") from None
        except httpx.HTTPError:
            raise ContratErreur("échec de la communication avec l'application", None,
                                "delai") from None
        if r.status_code == 200:
            return r
        raison = ""
        if r.status_code in (409, 422):
            try:
                d = r.json().get("detail")
            except (ValueError, AttributeError):
                d = None
            raison = d if isinstance(d, str) and _RE_RAISON.fullmatch(d) else "refus"
        raison = raison or {401: "cle_refusee", 503: "desactive", 413: "trop_gros"}.get(
            r.status_code, "erreur")
        raise ContratErreur(f"l'application a répondu {r.status_code} ({raison})",
                            r.status_code, raison)

    def _action(self, nom: str) -> str:
        return self._e["bloc"][nom]["chemin"]

    async def exporter(self, utilisateur: str) -> tuple:
        r = await self._appel("POST", self._action("exporter"), json={"utilisateur": utilisateur})
        try:
            emp, comptages = r.headers["X-Empreinte"], json.loads(r.headers["X-Comptages"])
        except (KeyError, ValueError):
            raise ContratErreur("export sans métadonnées exploitables", 200, "meta") from None
        if not (isinstance(emp, str) and emp and isinstance(comptages, dict)):
            raise ContratErreur("export sans métadonnées exploitables", 200, "meta")
        return r.content, {"empreinte": emp, "comptages": comptages}

    async def verifier(self, utilisateur: str, paquet: bytes) -> dict:
        r = await self._appel("POST", CHEMIN_VERIFIER, params={"utilisateur": utilisateur},
                              content=paquet)
        return r.json()

    async def reinitialiser(self, utilisateur: str, empreinte: str) -> dict:
        r = await self._appel("POST", self._action("reinitialiser"),
                              json={"utilisateur": utilisateur, "empreinte": empreinte})
        return r.json()

    async def importer(self, utilisateur: str, paquet: bytes) -> dict:
        r = await self._appel("POST", self._action("importer"),
                              params={"utilisateur": utilisateur}, content=paquet)
        return r.json()
```

`contrats.exemple.json` (le bloc doit être IDENTIQUE à `briques/studio/manifest.json` → `contrat_donnees`) :

```json
{
  "studio": {
    "url": "http://host.docker.internal:6060",
    "cle_env": "STUDIO_SUPPORT_KEY",
    "bloc": {
      "version_schema": "1",
      "exporter":      {"methode": "POST", "chemin": "/support/exporter"},
      "reinitialiser": {"methode": "POST", "chemin": "/support/reinitialiser"},
      "importer":      {"methode": "POST", "chemin": "/support/importer"}
    }
  }
}
```

- [ ] **Step 4 :** `python3 -m pytest test_contrats.py -q -p no:cacheprovider` → PASS. **Step 5 : Commit** `git add briques/livraison && git commit -m "feat(s248): registre des apps à contrat et client /support/* (bloc validé)"`

---

### Task 8 : Registre des paquets, journal d'accès, rétention

**Files :**
- Create : `briques/livraison/paquets.py`, `briques/livraison/test_paquets.py`

**Interfaces :**
- Produces :
  - `RETENTION_S = 14 * 86400`, `PREUVE_TTL_S = 6 * 3600`
  - `empreinte_utilisateur(u: str) -> str` (sha256 hex[:16])
  - `cle_objet(app: str, h: str, paquet_id: str) -> str` → `contrat/<app>/<h>/<id>.bin`
  - `nouveau_id() -> str` (32 hex)
  - `enregistrer(paquet_id, app, h, objet, empreinte, comptages, version_schema, maintenant=None) -> dict`
  - `lire(paquet_id) -> dict | None`, `marquer_verifie(paquet_id, maintenant=None) -> dict | None`
  - `expires(maintenant=None) -> list[dict]`, `retirer(paquet_id) -> None`
  - `journaliser(operation: str, app: str, h: str, paquet_id: str, ok: bool, maintenant=None) -> None`
  Un enregistrement : `{id, app, h, objet, empreinte, comptages, version_schema, cree_a, expire_a, verifie_a}` (jamais l'utilisateur en clair).

- [ ] **Step 1 : Tests qui échouent** — `test_paquets.py` :

```python
import json

import pytest

import paquets as P

H = "0123456789abcdef"


def _enreg(pid=None, t=1000.0, app="studio"):
    pid = pid or P.nouveau_id()
    return P.enregistrer(pid, app, H, P.cle_objet(app, H, pid), "emp", {"series": 1}, "1", t)


def test_empreinte_utilisateur_stable_et_sans_clair():
    assert P.empreinte_utilisateur("claire") == P.empreinte_utilisateur("claire")
    assert len(P.empreinte_utilisateur("claire")) == 16 and "claire" not in P.empreinte_utilisateur("claire")


def test_cle_objet_forme_valide():
    import re
    pid = P.nouveau_id()
    assert re.fullmatch(r"contrat/[a-z0-9_-]{1,40}/[0-9a-f]{16}/[0-9a-f]{32}\.bin",
                        P.cle_objet("studio", H, pid))


@pytest.mark.parametrize("app", ["../x", "Studio", "a/b", "", "x" * 41])
def test_cle_objet_refuse_app_dangereuse(app):
    with pytest.raises(ValueError):
        P.cle_objet(app, H, P.nouveau_id())


def test_enregistrer_lire_retention_14_jours():
    r = _enreg(t=1000.0)
    assert P.lire(r["id"])["expire_a"] == 1000.0 + 14 * 86400
    assert P.lire(r["id"])["verifie_a"] is None and "utilisateur" not in r


def test_marquer_verifie_et_inconnu():
    r = _enreg()
    assert P.marquer_verifie(r["id"], 2000.0)["verifie_a"] == 2000.0
    assert P.marquer_verifie("0" * 32) is None


def test_expires_et_retirer():
    a, b = _enreg(t=0.0), _enreg(t=10 * 86400.0)
    ids = [x["id"] for x in P.expires(maintenant=15 * 86400.0)]
    assert ids == [a["id"]]
    P.retirer(a["id"])
    assert P.lire(a["id"]) is None and P.lire(b["id"]) is not None
    P.retirer(a["id"])  # idempotent


def test_registre_illisible_se_lit_comme_vide(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "paquets.json").write_text("{pas du json")
    assert P.lire("0" * 32) is None and P.expires() == []


def test_journal_sans_donnee_perso():
    P.journaliser("exporter", "studio", H, "a" * 32, True, 5.0)
    import os
    ligne = json.loads(open(os.path.join(os.environ["LIVRAISON_DATA"], "acces.jsonl")).read().strip())
    assert ligne == {"t": 5.0, "operation": "exporter", "app": "studio", "h": H,
                     "paquet": "a" * 32, "ok": True}
```

- [ ] **Step 2 :** → FAIL. **Step 3 : Implémenter** — `paquets.py` :

```python
"""Registre des paquets de données utilisateur (S248 3a) : métadonnées seulement, JAMAIS le
contenu ni l'identité en clair (empreinte sha256[:16]). Écriture atomique ; toute erreur disque
à la lecture se lit comme « rien » (on n'agit pas sur un registre illisible). Journal d'accès
JSONL : qui/quoi/quand, jamais de contenu."""
import hashlib
import json
import os
import re
import secrets
import time
from pathlib import Path
from typing import Optional

RETENTION_S = 14 * 86400
PREUVE_TTL_S = 6 * 3600
_RE_APP = re.compile(r"[a-z0-9_-]{1,40}")
_RE_H = re.compile(r"[0-9a-f]{16}")
_RE_ID = re.compile(r"[0-9a-f]{32}")


def _dossier() -> Path:
    return Path(os.getenv("LIVRAISON_DATA", "/data"))


def _chemin() -> Path:
    return _dossier() / "paquets.json"


def empreinte_utilisateur(utilisateur: str) -> str:
    return hashlib.sha256(utilisateur.encode("utf-8")).hexdigest()[:16]


def nouveau_id() -> str:
    return secrets.token_hex(16)


def cle_objet(app: str, h: str, paquet_id: str) -> str:
    if not (_RE_APP.fullmatch(app) and _RE_H.fullmatch(h) and _RE_ID.fullmatch(paquet_id)):
        raise ValueError("composant d'objet invalide")
    return f"contrat/{app}/{h}/{paquet_id}.bin"


def _lire_tout() -> dict:
    try:
        d = json.loads(_chemin().read_text())
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _ecrire_tout(tout: dict) -> None:
    p = _chemin()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(tout))
    tmp.replace(p)


def enregistrer(paquet_id: str, app: str, h: str, objet: str, empreinte: str, comptages: dict,
                version_schema: str, maintenant: Optional[float] = None) -> dict:
    now = maintenant if maintenant is not None else time.time()
    rec = {"id": paquet_id, "app": app, "h": h, "objet": objet, "empreinte": empreinte,
           "comptages": comptages, "version_schema": version_schema,
           "cree_a": now, "expire_a": now + RETENTION_S, "verifie_a": None}
    tout = _lire_tout()
    tout[paquet_id] = rec
    _ecrire_tout(tout)
    return rec


def lire(paquet_id: str) -> Optional[dict]:
    r = _lire_tout().get(paquet_id)
    return r if isinstance(r, dict) and r.get("id") == paquet_id else None


def marquer_verifie(paquet_id: str, maintenant: Optional[float] = None) -> Optional[dict]:
    tout = _lire_tout()
    r = tout.get(paquet_id)
    if not isinstance(r, dict):
        return None
    r["verifie_a"] = maintenant if maintenant is not None else time.time()
    _ecrire_tout(tout)
    return r


def expires(maintenant: Optional[float] = None) -> list:
    now = maintenant if maintenant is not None else time.time()
    return [r for r in _lire_tout().values()
            if isinstance(r, dict) and float(r.get("expire_a", 0)) <= now]


def retirer(paquet_id: str) -> None:
    tout = _lire_tout()
    if paquet_id in tout:
        del tout[paquet_id]
        _ecrire_tout(tout)


def journaliser(operation: str, app: str, h: str, paquet_id: str, ok: bool,
                maintenant: Optional[float] = None) -> None:
    ligne = {"t": maintenant if maintenant is not None else time.time(), "operation": operation,
             "app": app, "h": h, "paquet": paquet_id, "ok": bool(ok)}
    p = _dossier() / "acces.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(ligne) + "\n")
```

- [ ] **Step 4 :** → PASS. **Step 5 : Commit** `git add briques/livraison && git commit -m "feat(s248): registre des paquets, journal d'accès et rétention 14 jours"`

---

### Task 9 : Routes `exporter` / `verifier` / purge dans livraison

**Files :**
- Modify : `briques/livraison/main.py`
- Create : `briques/livraison/donnees_utilisateur.py` (orchestration, hors de `main.py` déjà long), `briques/livraison/test_donnees_utilisateur.py`

**Interfaces :**
- Consumes : `contrats.ouvrir/ContratErreur`, `chiffrement.chiffrer/dechiffrer/CleAbsente/Illisible`, `paquets.*`, `Executeur.deposer/lire/supprimer`.
- Produces :
  - `async exporter_et_stocker(app: AppContrat, ex: Executeur, utilisateur: str) -> dict` → `{"paquet_id", "empreinte", "comptages", "version_schema", "expire_a", "h"}`. Ordre : export → chiffrement → dépôt → enregistrement (un échec de dépôt n'enregistre rien ; un échec d'enregistrement tente de supprimer l'objet déposé).
  - `async verifier_paquet(app, ex, utilisateur) -> dict` → `{"ok": True, "verdict": "valide"|"invalide", "paquet_id", "empreinte", "comptages", "raisons": [...], "expire_a"}` ; ne marque `verifie_a` que si l'app confirme la MÊME empreinte que l'export ET que le paquet relu depuis SeaweedFS puis déchiffré est octet pour octet celui exporté.
  - `async purger_expires(ex: Executeur) -> dict` → `{"supprimes": n, "restants": m}` (un échec S3 garde l'entrée).
  - Routes : `POST /contrats/{app}/exporter`, `POST /contrats/{app}/verifier` (corps `{"utilisateur": str}`, fullmatch `[A-Za-z0-9_.@-]{1,128}`), `POST /contrats/purger`.

- [ ] **Step 1 : Tests qui échouent** — `test_donnees_utilisateur.py` (faux exécuteur en mémoire + faux app) :

```python
import asyncio
import base64
import os

import pytest
from fastapi.testclient import TestClient

import chiffrement
import donnees_utilisateur as D
import main
import paquets as P
from client_executeur import ExecuteurErreur
from contrats import ContratErreur


@pytest.fixture(autouse=True)
def cle(monkeypatch):
    monkeypatch.setenv("LIVRAISON_CHIFFREMENT_CLE", base64.b64encode(os.urandom(32)).decode())


class FauxExecuteur:
    def __init__(self):
        self.objets, self.echec_depot, self.echec_suppression = {}, False, False

    async def deposer(self, cle, octets):
        if self.echec_depot:
            raise ExecuteurErreur("injoignable")
        self.objets[cle] = octets

    async def lire(self, cle):
        return self.objets[cle]

    async def supprimer(self, cle):
        if self.echec_suppression:
            raise ExecuteurErreur("injoignable")
        self.objets.pop(cle, None)


class FauxApp:
    nom, version_schema = "studio", "1"

    def __init__(self, paquet=b"PAQUET-CLAIR", empreinte="emp1", verif_emp="emp1", verif_exc=None):
        self.paquet, self.emp, self.verif_emp, self.verif_exc = paquet, empreinte, verif_emp, verif_exc
        self.recu_verif = None

    async def exporter(self, u):
        return self.paquet, {"empreinte": self.emp, "comptages": {"series": 2}}

    async def verifier(self, u, paquet):
        self.recu_verif = paquet
        if self.verif_exc:
            raise self.verif_exc
        return {"ok": True, "empreinte": self.verif_emp, "comptages": {"series": 2}}


def run(c):
    return asyncio.run(c)


def test_exporter_stocke_chiffre_et_ne_renvoie_aucune_donnee():
    ex, app = FauxExecuteur(), FauxApp()
    r = run(D.exporter_et_stocker(app, ex, "claire"))
    assert set(r) == {"paquet_id", "empreinte", "comptages", "version_schema", "expire_a", "h"}
    (cle_obj, blob), = ex.objets.items()
    assert b"PAQUET-CLAIR" not in blob and "claire" not in cle_obj
    assert chiffrement.dechiffrer(blob, cle_obj) == b"PAQUET-CLAIR"
    assert P.lire(r["paquet_id"])["objet"] == cle_obj
    assert "claire" not in str(P.lire(r["paquet_id"]))


def test_depot_en_echec_n_enregistre_rien():
    ex = FauxExecuteur()
    ex.echec_depot = True
    with pytest.raises(ExecuteurErreur):
        run(D.exporter_et_stocker(FauxApp(), ex, "claire"))
    assert not os.path.exists(os.path.join(os.environ["LIVRAISON_DATA"], "paquets.json"))


def test_verifier_valide_relit_depuis_le_stockage():
    ex, app = FauxExecuteur(), FauxApp()
    r = run(D.verifier_paquet(app, ex, "claire"))
    assert r["ok"] is True and r["verdict"] == "valide" and r["raisons"] == []
    assert app.recu_verif == b"PAQUET-CLAIR"   # l'app a vérifié le paquet RELU puis déchiffré
    assert P.lire(r["paquet_id"])["verifie_a"] is not None


def test_verifier_empreinte_differente_invalide():
    r = run(D.verifier_paquet(FauxApp(verif_emp="autre"), FauxExecuteur(), "claire"))
    assert r["verdict"] == "invalide" and P.lire(r["paquet_id"])["verifie_a"] is None


def test_verifier_refus_de_l_app_invalide_sans_exception():
    app = FauxApp(verif_exc=ContratErreur("x", 422, "signature"))
    r = run(D.verifier_paquet(app, FauxExecuteur(), "claire"))
    assert r["ok"] is True and r["verdict"] == "invalide" and "signature" in " ".join(r["raisons"])


def test_verifier_objet_altere_dans_le_stockage_invalide():
    ex, app = FauxExecuteur(), FauxApp()
    orig = ex.deposer

    async def altere(cle, octets):
        await orig(cle, octets[:-1] + bytes([octets[-1] ^ 1]))
    ex.deposer = altere
    r = run(D.verifier_paquet(app, ex, "claire"))
    assert r["verdict"] == "invalide" and app.recu_verif is None


def test_purge_supprime_les_expires_et_garde_en_cas_d_echec():
    ex = FauxExecuteur()
    vieux = run(D.exporter_et_stocker(FauxApp(), ex, "a", maintenant=0.0))
    recent = run(D.exporter_et_stocker(FauxApp(), ex, "b"))
    ex.echec_suppression = True
    assert run(D.purger_expires(ex, maintenant=20 * 86400.0)) == {"supprimes": 0, "restants": 1}
    assert P.lire(vieux["paquet_id"]) is not None
    ex.echec_suppression = False
    assert run(D.purger_expires(ex, maintenant=20 * 86400.0)) == {"supprimes": 1, "restants": 0}
    assert P.lire(vieux["paquet_id"]) is None and P.lire(recent["paquet_id"]) is not None


# ── Routes ──
c = TestClient(main.app)


def test_route_sans_cle_chiffrement_503(monkeypatch):
    monkeypatch.setenv("LIVRAISON_API_KEYS", "k")
    monkeypatch.delenv("LIVRAISON_CHIFFREMENT_CLE")
    monkeypatch.setattr(main.contrats, "ouvrir", lambda nom: FauxApp())
    monkeypatch.setattr(main, "executeur", lambda: FauxExecuteur())
    r = c.post("/contrats/studio/exporter", json={"utilisateur": "claire"}, headers={"X-API-Key": "k"})
    assert r.status_code == 503


def test_route_fail_closed_sans_cles_api(monkeypatch):
    monkeypatch.setenv("LIVRAISON_API_KEYS", "")
    assert c.post("/contrats/studio/exporter", json={"utilisateur": "claire"}).status_code == 403


@pytest.mark.parametrize("u", ["", "a b", "../x", "x" * 129, "a\nb"])
def test_route_utilisateur_invalide_422(monkeypatch, u):
    monkeypatch.setenv("LIVRAISON_API_KEYS", "k")
    r = c.post("/contrats/studio/exporter", json={"utilisateur": u}, headers={"X-API-Key": "k"})
    assert r.status_code == 422


def test_route_exporter_nominale(monkeypatch):
    monkeypatch.setenv("LIVRAISON_API_KEYS", "k")
    monkeypatch.setattr(main.contrats, "ouvrir", lambda nom: FauxApp())
    ex = FauxExecuteur()
    monkeypatch.setattr(main, "executeur", lambda: ex)
    r = c.post("/contrats/studio/exporter", json={"utilisateur": "claire"}, headers={"X-API-Key": "k"})
    assert r.status_code == 200 and r.json()["ok"] is True
    assert "claire" not in r.text and "PAQUET" not in r.text


def test_route_app_inconnue_404(monkeypatch):
    monkeypatch.setenv("LIVRAISON_API_KEYS", "k")
    r = c.post("/contrats/inconnue/exporter", json={"utilisateur": "claire"}, headers={"X-API-Key": "k"})
    assert r.status_code == 404
```
(`D.exporter_et_stocker` et `purger_expires` acceptent un paramètre nommé `maintenant: float | None = None`, transmis à `paquets.*`.)

- [ ] **Step 2 :** → FAIL.

- [ ] **Step 3 : Implémenter** — `donnees_utilisateur.py` :

```python
"""Orchestration des paquets de données utilisateur (S248 3a) : export → chiffrement → dépôt
SeaweedFS (via l'exécuteur) → registre ; vérification par RELECTURE du stockage. Jamais le contenu
en retour, jamais l'identité en clair."""
import time
from typing import Optional

import chiffrement
import paquets
from client_executeur import ExecuteurErreur


async def exporter_et_stocker(app, ex, utilisateur: str, maintenant: Optional[float] = None) -> dict:
    h = paquets.empreinte_utilisateur(utilisateur)
    paquet, meta = await app.exporter(utilisateur)
    pid = paquets.nouveau_id()
    objet = paquets.cle_objet(app.nom, h, pid)
    await ex.deposer(objet, chiffrement.chiffrer(paquet, objet))
    try:
        rec = paquets.enregistrer(pid, app.nom, h, objet, meta["empreinte"], meta["comptages"],
                                  app.version_schema, maintenant)
    except OSError:
        try:
            await ex.supprimer(objet)     # pas d'objet orphelin hors registre
        except ExecuteurErreur:
            pass
        raise
    paquets.journaliser("exporter", app.nom, h, pid, True, maintenant)
    return {"paquet_id": pid, "empreinte": rec["empreinte"], "comptages": rec["comptages"],
            "version_schema": rec["version_schema"], "expire_a": rec["expire_a"], "h": h}


async def verifier_paquet(app, ex, utilisateur: str, maintenant: Optional[float] = None) -> dict:
    """Exporte à neuf, stocke, RELIT depuis le stockage, déchiffre, et fait vérifier CE paquet par
    l'app (import dans un dossier jetable + ré-export + même empreinte). Toute défaillance donne un
    verdict `invalide` avec `ok: True` (fail closed, convention S247)."""
    from contrats import ContratErreur
    r = await exporter_et_stocker(app, ex, utilisateur, maintenant)
    pid, raisons = r["paquet_id"], []
    rec = paquets.lire(pid)
    try:
        blob = await ex.lire(rec["objet"])
        clair = chiffrement.dechiffrer(blob, rec["objet"])
        retour = await app.verifier(utilisateur, clair)
        if retour.get("ok") is not True or retour.get("empreinte") != rec["empreinte"]:
            raisons.append("l'application ne confirme pas l'empreinte exportée")
    except chiffrement.Illisible:
        raisons.append("paquet relu illisible (altéré ou mauvaise clé)")
    except ContratErreur as e:
        raisons.append(f"refus de l'application : {e.raison or 'erreur'}")
    except ExecuteurErreur as e:
        raisons.append(f"stockage : {e.message}")
    verdict = "valide" if not raisons else "invalide"
    if verdict == "valide":
        paquets.marquer_verifie(pid, maintenant)
    paquets.journaliser("verifier", app.nom, r["h"], pid, verdict == "valide", maintenant)
    now = maintenant if maintenant is not None else time.time()
    return {"ok": True, "verdict": verdict, "paquet_id": pid, "empreinte": rec["empreinte"],
            "comptages": rec["comptages"], "raisons": raisons,
            "expire_a": min(now + paquets.PREUVE_TTL_S, rec["expire_a"])}


async def purger_expires(ex, maintenant: Optional[float] = None) -> dict:
    supprimes = restants = 0
    for rec in paquets.expires(maintenant):
        try:
            await ex.supprimer(rec["objet"])
        except ExecuteurErreur:
            restants += 1          # on réessaiera : l'entrée reste tant que l'objet n'est pas parti
            continue
        paquets.retirer(rec["id"])
        paquets.journaliser("purger", rec["app"], rec["h"], rec["id"], True, maintenant)
        supprimes += 1
    return {"supprimes": supprimes, "restants": restants}
```
Note : `exporter_et_stocker` appelle `app.exporter` (un `ContratErreur` / `ExecuteurErreur` remonte dans `verifier_paquet` AVANT le `try` : acceptable, les routes les traduisent en HTTP).

`main.py` : ajouter les imports (`import chiffrement`, `import contrats`, `import donnees_utilisateur as DU`, `from pydantic import BaseModel, Field`, `from client_executeur import ExecuteurErreur` si absent) et, après la section reset :

```python
# ── Données utilisateur (S248 3a) ──
class CorpsUtilisateur(BaseModel):
    utilisateur: str = Field(pattern=r"^[A-Za-z0-9_.@-]{1,128}$")   # moteur regex Rust (pydantic v2) : pas de \Z ; `$` = fin de texte stricte


def _traduire(e: Exception) -> HTTPException:
    if isinstance(e, contrats.ContratErreur):
        return HTTPException(e.statut if e.statut in (404, 409, 422, 503) else 502, e.message)
    if isinstance(e, chiffrement.CleAbsente):
        return HTTPException(503, "chiffrement des paquets non configuré (LIVRAISON_CHIFFREMENT_CLE)")
    if isinstance(e, ExecuteurErreur):
        return HTTPException(502, e.message)
    return HTTPException(500, "erreur interne")


async def _donnees(app_: str, corps: CorpsUtilisateur, fabrique):
    try:
        chiffrement._cle()                    # 503 avant tout appel à l'app (fail closed)
        app = contrats.ouvrir(app_)
        ex = executeur()
        return await fabrique(app, ex, corps.utilisateur)
    except (contrats.ContratErreur, chiffrement.CleAbsente, ExecuteurErreur, OSError) as e:
        raise _traduire(e) from None


@app.post("/contrats/{app_}/exporter")
async def exporter_donnees(app_: str, corps: CorpsUtilisateur, _: str = Depends(cle_api_fermee)):
    r = await _donnees(app_, corps, DU.exporter_et_stocker)
    r.pop("h")
    return {"ok": True, "app": app_.strip().lower(), **r}


@app.post("/contrats/{app_}/verifier")
async def verifier_donnees(app_: str, corps: CorpsUtilisateur, _: str = Depends(cle_api_fermee)):
    r = await _donnees(app_, corps, DU.verifier_paquet)
    return {"app": app_.strip().lower(), **r}


@app.post("/contrats/purger")
async def purger_contrats(_: str = Depends(cle_api_fermee)):
    try:
        return {"ok": True, **await DU.purger_expires(executeur())}
    except ExecuteurErreur as e:
        raise _traduire(e) from None
```
(Placer `/contrats/purger` AVANT les routes `{app_}` si FastAPI confond : les chemins diffèrent par nombre de segments, pas de conflit.) Ajouter, dans le handler de démarrage existant `_marquer_operations_interrompues` voisin, une boucle de purge :

```python
async def _boucle_purge():
    while True:
        try:
            await DU.purger_expires(executeur())
        except Exception:           # exécuteur non configuré/injoignable : on réessaiera
            pass
        await asyncio.sleep(3600)


@app.on_event("startup")
async def _demarrer_purge():
    t = asyncio.create_task(_boucle_purge())
    _taches_en_fond.add(t)
    t.add_done_callback(_taches_en_fond.discard)
```
Pour que `test_route_*` (TestClient sans `with`) ne lance pas la boucle, c'est déjà le cas : les handlers de démarrage ne tournent que dans `with TestClient(...)`.

- [ ] **Step 4 :** `python3 -m pytest -q -p no:cacheprovider` (tout livraison) → PASS. **Step 5 : Commit** `git add briques/livraison && git commit -m "feat(s248): routes livraison exporter/verifier des données utilisateur + purge à 14 jours"`

---

### Task 10 : Capacités du manifeste, README, journal d'accès

**Files :**
- Modify : `briques/livraison/manifest.json` (ajouter 2 capacités à la fin de `capacites`), `briques/livraison/README.md`
- Test : `briques/livraison/test_api.py` (ou le test de contrat manifeste↔route de S210 : `grep -rn "manifest" briques/livraison/test_*.py` et suivre son motif)

**Interfaces :**
- Produces : outils `livraison_donnees_exporter` (POST `/contrats/{app}/exporter`, `sensibilite: "reversible"`, `action: true`) et `livraison_donnees_verifier` (POST `/contrats/{app}/verifier`, `action: false`, SANS `fournit_preuve` : réservé à 3b, car sans la clé composite du Cœur une preuve serait enregistrée pour toute l'app).

- [ ] **Step 1 : Test qui échoue** (contrat manifeste↔route, ajouter à `test_api.py`)

```python
def test_manifeste_declare_les_outils_donnees_et_pas_de_preuve_avant_3b():
    import json, pathlib
    m = json.loads((pathlib.Path(__file__).parent / "manifest.json").read_text())
    caps = {x["nom"]: x for x in m["capacites"]}
    e, v = caps["livraison_donnees_exporter"], caps["livraison_donnees_verifier"]
    assert (e["chemin"], e["methode"], e["sensibilite"]) == ("/contrats/{app}/exporter", "POST", "reversible")
    assert (v["chemin"], v["methode"]) == ("/contrats/{app}/verifier", "POST")
    assert "fournit_preuve" not in v and "sensibilite" not in v
    for x in (e, v):
        assert set(x["params"]) == {"app", "utilisateur"} and x["relayer_erreurs"] is True
    routes = {(r.path, tuple(sorted(r.methods))) for r in main.app.routes if hasattr(r, "methods")}
    assert ("/contrats/{app_}/exporter", ("POST",)) in routes
    assert ("/contrats/{app_}/verifier", ("POST",)) in routes
```

- [ ] **Step 2 :** → FAIL.

- [ ] **Step 3 : Implémenter** — ajouter au tableau `capacites` :

```json
{
  "nom": "livraison_donnees_exporter",
  "description": "MET DE CÔTÉ les données d'UN SEUL utilisateur d'une application qui a un contrat de données (ex. le Studio) : crée un paquet chiffré conservé 14 jours. Ne modifie rien et ne lit jamais le contenu : renvoie seulement un identifiant de paquet, des comptages et une empreinte. Ce n'est PAS une sauvegarde de l'application entière (→ livraison_sauvegarder). Pour PROUVER que le paquet est restaurable → livraison_donnees_verifier. APPELLE CET OUTIL DIRECTEMENT quand l'utilisateur le demande : c'est l'appel qui crée la demande d'approbation et envoie les boutons Telegram. Ne dis JAMAIS « demande envoyée » sans avoir réellement appelé l'outil dans ce tour.",
  "methode": "POST",
  "chemin": "/contrats/{app}/exporter",
  "params": {
    "app": {"type": "string", "description": "Nom de l'application à contrat de données. Ex : « studio ».", "requis": true},
    "utilisateur": {"type": "string", "description": "Identité exacte de l'utilisateur visé dans l'application (jamais devinée : la demander).", "requis": true}
  },
  "action": true,
  "sensibilite": "reversible",
  "relayer_erreurs": true
},
{
  "nom": "livraison_donnees_verifier",
  "description": "PROUVE que les données d'UN utilisateur d'une application à contrat sont restaurables : exporte à neuf, stocke chiffré, relit le stockage, puis fait rejouer l'import dans un espace jetable et comparer l'empreinte. Renvoie un verdict valide/invalide, des comptages et une empreinte (jamais le contenu). N'affecte pas la production.",
  "methode": "POST",
  "chemin": "/contrats/{app}/verifier",
  "params": {
    "app": {"type": "string", "description": "Nom de l'application à contrat de données. Ex : « studio ».", "requis": true},
    "utilisateur": {"type": "string", "description": "Identité exacte de l'utilisateur visé (la même que pour l'export).", "requis": true}
  },
  "action": false,
  "relayer_erreurs": true
}
```
Vérifier que le JSON reste valide : `python3 -c "import json;json.load(open('manifest.json'))"`.

`README.md` : ajouter une section « Données utilisateur (S248) » : variables `LIVRAISON_CHIFFREMENT_CLE`, `STUDIO_SUPPORT_KEY` (dans `briques/livraison/.env`, 0600, même valeur que côté Studio), registre `contrats.json` (copier `contrats.exemple.json` dans le volume `/data`), rétention 14 jours + purge horaire + `POST /contrats/purger`, journal `acces.jsonl`, **piège** : changer `STUDIO_SUPPORT_KEY` OU `LIVRAISON_CHIFFREMENT_CLE` rend les paquets stockés illisibles (vider avant rotation), et exécuteur : redéployer `executeur.py` sur la VM 100 (routes `/objets/`).

- [ ] **Step 4 :** `python3 -m pytest -q -p no:cacheprovider` dans `briques/livraison`, puis `python3 -m pytest -q -p no:cacheprovider` dans `core` ne régresse pas (le Cœur charge les manifestes : `cd core && python3 -m pytest -q -p no:cacheprovider -k "manifest or capacit or outils"`) → PASS.

- [ ] **Step 5 : Commit** `git add briques/livraison && git commit -m "feat(s248): outils livraison_donnees_exporter/_verifier (sans preuve avant 3b) + README"`

---

### Task 11 : Revue finale, documentation et état

**Files :**
- Modify : `docs/GUIDE-contrat-donnees.md` (section 7 : retirer les limites soldées — `%2e%2e`, 413, secret dans le paquet — ; ajouter « stockage, chiffrement, rétention, journal : fait en 3a »), `docs/sprints/S248-contrat-app-reset-par-utilisateur.md` (statut : 3a codée)

- [ ] **Step 1 :** suite complète : `cd shared && python3 -m pytest -q -p no:cacheprovider; cd ../briques/studio && python3 -m pytest -q -p no:cacheprovider; cd ../livraison && python3 -m pytest -q -p no:cacheprovider; cd ../../outils/executeur-restauration && python3 -m pytest -q -p no:cacheprovider`. Expected : tout PASS. Noter les comptages RÉELS lus dans la sortie (ne pas se fier au compte rendu d'un sous-agent).
- [ ] **Step 2 :** lancer `/code-review high` sur la branche ; corriger les Critical/Important.
- [ ] **Step 3 :** mettre à jour les deux docs, puis commit `docs(s248): partie 3a codée — état et limites à jour`.
- [ ] **Step 4 (déploiement dormant, après accord explicite de l'utilisateur) :** construire l'image `workplace/livraison:0.2.0` et `workplace/studio:0.6.1` **sur le Mac** puis `docker save | ssh` (piège : build pip impossible sur le HP) ; poser les clés dans `briques/livraison/.env` et `STUDIO_SUPPORT_KEY` côté Studio ; copier `executeur.py` sur la VM 100 et redémarrer le service systemd. Tant que `STUDIO_SUPPORT_KEY` n'est pas posée, tout reste désactivé (503). Preuve LIVE regroupée avec 3b.

## Auto-revue (couverture de la spec)

- Chiffrement au repos, clé hors dépôt → Task 6 ; stockage SeaweedFS cloisonné par app+utilisateur (préfixe `contrat/<app>/<h>/`) → Tasks 4, 8 ; rétention 14 j + suppression + journal d'accès → Tasks 8, 9 ; l'assistant ne lit pas le contenu → Task 9 (réponses sans donnée, test explicite) ; validation du bloc exploitée → Tasks 1, 7 ; dettes d'avant-partie-3 (`%2e%2e`, 413, secret dans le paquet) → Tasks 1-3.
- Reporté à 3b : reset/restitution, prérequis composite, `fournit_preuve`, parade « comptages à zéro après reset », LIVE.
- Risque à surveiller au LIVE : signature SigV4 d'un `PUT` via curl sur SeaweedFS (on fournit `x-amz-content-sha256` explicitement ; si SeaweedFS refuse, basculer sur `--data-binary @fichier` + `-X PUT`).
