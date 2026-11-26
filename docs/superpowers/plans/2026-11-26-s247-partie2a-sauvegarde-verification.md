# S247 partie 2a — exécuteur de restauration, vérification par restauration jetable, sauvegarde de Forgejo — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** que l'assistant puisse (1) déclencher la sauvegarde d'une app, (2) la **vérifier en la restaurant dans une base jetable et en comparant les comptages**, ce qui produit la preuve `preuve_sauvegarde` déjà câblée côté Cœur (partie 1), et (3) que Forgejo soit sauvegardé vers le S3 du HP.

**Architecture:** Dokploy 0.31.4 n'a **aucune route de restauration** (spike, `docs/s247/spike-dokploy.md`) et la brique `livraison` n'a ni SSH ni socket Docker. La restauration jetable est donc faite par un **exécuteur** (petit service Python sur la VM 100, sous systemd) qui n'accepte qu'un ordre fixe, validé, avec clé : « télécharge cet objet S3, restaure-le dans une base `restore_<hex>` du conteneur Postgres demandé, compare les comptages à l'original, supprime la base ». La brique orchestre : sauvegarde manuelle Dokploy → dernier fichier → exécuteur → verdict → `preuve.noter`. Le Cœur fait le reste (bouton « Approuver » seulement après verdict, S247 partie 1).

**Tech Stack:** Python 3.12 (stdlib seule pour l'exécuteur : `http.server`, `subprocess`, `gzip`), FastAPI/httpx (brique), `curl --aws-sigv4` (S3), Ansible, systemd, pytest.

## Global Constraints

- Décisions de l'utilisateur (2026-11-26) : exécuteur dédié sur la VM 100 ; `/etat` **non** durci (repère mémorisé conservé) ; **une seule clé Dokploy** pour la brique, limitée au projet `temoin` (jamais la clé owner) ; sauvegarde de Forgejo = `forgejo dump` + `curl --aws-sigv4` (pas de GoBackup) ; S3 du HP = identité administrateur d'Oria existante.
- Secrets : jamais dans le dépôt, un log, un argument de processus (`argv`), un message Telegram ni une réponse de l'API. L'exécuteur lit sa configuration dans `/etc/executeur-restauration/env` (root, 0600, **créé à la main**, jamais par Ansible). Les identifiants S3 passent à `curl` par **stdin** (`-K -`).
- L'exécuteur n'exécute que des commandes **fixes** avec des arguments validés par expression régulière : service `^postgres-[a-z0-9-]{3,60}$`, base et utilisateur `^[a-z_][a-z0-9_]{0,40}$`, objet S3 `^[A-Za-z0-9._/-]{1,200}$` sans `..` ni `/` initial. Écoute sur l'IP LAN de la VM 100 (jamais `0.0.0.0`), port **8090**, ufw : seule l'IP du HP (`192.168.1.89`).
- Une vérification à la fois (verrou, 409 sinon). La base jetable est **toujours** supprimée (`finally`).
- Verdict `valide` ⇔ comptages des tables du schéma `public` identiques entre l'original et la copie restaurée ET au moins une table. Toute autre issue (échec de sauvegarde, exécuteur injoignable, dump illisible, comptages différents) = verdict `invalide` avec `ok: true` (le Cœur révoque alors toute preuve antérieure, partie 1). Une application **sans entrée d'inventaire** : 404.
- Les volumes de fichiers sont **sauvegardés** (`volumeBackups.runManually`) mais **non vérifiés** en 2a : la réponse le dit (`volumes_non_verifies`). Le test de bout en bout se fait sur une base Postgres témoin (l'app Calendrier Familial n'a pas de base) : voir Task 11.
- Variables d'environnement de la brique : `EXECUTEUR_URL`, `EXECUTEUR_KEY`, `LIVRAISON_INVENTAIRE` (optionnelle, défaut `$LIVRAISON_DATA/inventaire.json`). Jamais `API_KEYS`. Aucun secret littéral dans un compose.
- Tests : un fichier de test par module, aucun réseau réel ni Docker réel ; comptes vérifiés via junit XML (`rtk proxy python3 -m pytest … -p no:cacheprovider --junitxml=…`). Pas de `rm -rf` (hook de sécurité) : `rm -f` fichier par fichier puis `rmdir`.
- Branche : `sprint/s247-sauvegarde-verifiee` (déjà créée). Chaque tâche : TDD (test rouge d'abord, **avant** d'écrire le code), commit.

---

### Task 6 : L'exécuteur de restauration (VM 100)

**Files:**
- Create: `outils/executeur-restauration/executeur.py`
- Test: `outils/executeur-restauration/test_executeur.py`

**Interfaces:**
- Produces : `executeur.Runner.run(argv: list[str], stdin: bytes | None = None, timeout: int = 300) -> tuple[int, bytes, bytes]` ; `executeur.ErreurExecuteur(statut: int, message: str)` (attributs `.statut`, `.message`) ; `executeur.charger_config(env: dict | None = None) -> dict` (clés `KEY, S3_ENDPOINT, S3_BUCKET, S3_KEY, S3_SECRET, S3_REGION`) ; `executeur.verifier(runner, cfg: dict, corps: dict) -> dict` ; `executeur.fabrique_handler(runner, cfg)` ; `executeur.VERROU` (threading.Lock) ; `POST /verifier` (en-tête `X-API-Key`) corps `{"service","utilisateur","base","objet"}` → `{"ok": true, "verdict": "valide"|"invalide", "raison": str|null, "comptages_origine": {table: n}, "comptages_restaures": {table: n}, "duree_s": float}`.

- [ ] **Step 1 : tests qui échouent** (`outils/executeur-restauration/test_executeur.py`)

```python
import gzip
import json
import re
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
CORPS = {"service": "postgres-abc-def", "utilisateur": "temoin", "base": "temoin",
         "objet": "postgres-abc-def/s247-pg/2026-11-26T10-00-00-000Z.sql.gz"}


class FauxRunner:
    def __init__(self, origine=None, restaure=None, dump=b"PGDMP\x01\x0f\x00donnees",
                 pg_restore=0, curl=0, ids="abc123\n"):
        self.origine = {"evenements": 42} if origine is None else origine
        self.restaure = dict(self.origine) if restaure is None else restaure
        self.dump, self.pg_restore, self.curl, self.ids = dump, pg_restore, curl, ids
        self.appels = []

    def run(self, argv, stdin=None, timeout=300):
        self.appels.append((list(argv), stdin))
        if argv[:2] == ["docker", "ps"]:
            return 0, self.ids.encode(), b""
        if argv[0] == "curl":
            if self.curl:
                return self.curl, b"", b""
            Path(argv[argv.index("-o") + 1]).write_bytes(gzip.compress(self.dump))
            return 0, b"", b""
        if argv[:2] == ["docker", "exec"]:
            if "pg_restore" in argv:
                return self.pg_restore, b"", b""
            sql, base = argv[-1], argv[argv.index("-d") + 1]
            if "create database" in sql or "drop database" in sql:
                return 0, b"", b""
            tables = self.restaure if base.startswith("restore_") else self.origine
            if "information_schema" in sql:
                return 0, "\n".join(tables).encode(), b""
            return 0, str(tables[re.search(r'from "(\w+)"', sql).group(1)]).encode(), b""
        raise AssertionError(argv)

    def commandes(self):
        return [a for a, _ in self.appels]


def _sql(r, motif):
    return [a for a in r.commandes() if a[:2] == ["docker", "exec"] and motif in a[-1]]


def test_nominal_valide_et_base_jetable_supprimee():
    r = FauxRunner()
    out = executeur.verifier(r, CFG, dict(CORPS))
    assert out["ok"] is True and out["verdict"] == "valide" and out["raison"] is None
    assert out["comptages_origine"] == out["comptages_restaures"] == {"evenements": 42}
    assert len(_sql(r, "create database restore_")) == 1
    assert len(_sql(r, "drop database if exists restore_")) == 1


def test_comptages_differents_invalide_et_base_supprimee():
    r = FauxRunner(restaure={"evenements": 41})
    out = executeur.verifier(r, CFG, dict(CORPS))
    assert out["verdict"] == "invalide" and "comptages" in out["raison"]
    assert len(_sql(r, "drop database if exists restore_")) == 1


def test_dump_qui_n_est_pas_un_pg_dump_est_refuse_sans_creer_de_base():
    r = FauxRunner(dump=b"pas un dump")
    out = executeur.verifier(r, CFG, dict(CORPS))
    assert out["verdict"] == "invalide" and "format" in out["raison"]
    assert _sql(r, "create database") == []


def test_archive_non_gzip_est_invalide():
    class R(FauxRunner):
        def run(self, argv, stdin=None, timeout=300):
            if argv[0] == "curl" and not self.curl:
                self.appels.append((list(argv), stdin))
                Path(argv[argv.index("-o") + 1]).write_bytes(b"ceci n'est pas du gzip")
                return 0, b"", b""
            return super().run(argv, stdin, timeout)
    out = executeur.verifier(R(), CFG, dict(CORPS))
    assert out["verdict"] == "invalide" and "illisible" in out["raison"]


def test_pg_restore_en_echec_invalide_et_base_supprimee():
    r = FauxRunner(pg_restore=1)
    out = executeur.verifier(r, CFG, dict(CORPS))
    assert out["verdict"] == "invalide" and "pg_restore" in out["raison"]
    assert len(_sql(r, "drop database if exists restore_")) == 1


def test_base_sans_table_ne_prouve_rien():
    out = executeur.verifier(FauxRunner(origine={}, restaure={}), CFG, dict(CORPS))
    assert out["verdict"] == "invalide" and "aucune table" in out["raison"]


@pytest.mark.parametrize("champ,valeur", [
    ("service", "postgres-x; rm"), ("service", "mysql-abc-def"), ("service", "postgres-ab"),
    ("base", "Temoin"), ("base", "a;b"), ("utilisateur", "x y"),
    ("objet", "../etc/passwd"), ("objet", "/abs/chemin"), ("objet", "a/../b"), ("objet", "a b"),
    ("objet", "")])
def test_arguments_invalides_refuses_avant_tout_appel(champ, valeur):
    r = FauxRunner()
    corps = {**CORPS, champ: valeur}
    with pytest.raises(ErreurExecuteur) as e:
        executeur.verifier(r, CFG, corps)
    assert e.value.statut == 400 and r.appels == []


def test_corps_non_objet_refuse():
    with pytest.raises(ErreurExecuteur) as e:
        executeur.verifier(FauxRunner(), CFG, ["x"])
    assert e.value.statut == 400


def test_conteneur_introuvable_ou_ambigu_404():
    for ids in ("", "a1\nb2\n"):
        with pytest.raises(ErreurExecuteur) as e:
            executeur.verifier(FauxRunner(ids=ids), CFG, dict(CORPS))
        assert e.value.statut == 404


def test_telechargement_en_echec_502():
    with pytest.raises(ErreurExecuteur) as e:
        executeur.verifier(FauxRunner(curl=22), CFG, dict(CORPS))
    assert e.value.statut == 502 and SECRET not in e.value.message


def test_le_secret_s3_ne_passe_jamais_dans_argv_seulement_par_stdin():
    r = FauxRunner()
    executeur.verifier(r, CFG, dict(CORPS))
    assert all(SECRET not in " ".join(a) for a in r.commandes())
    curl = [(a, s) for a, s in r.appels if a[0] == "curl"][0]
    assert SECRET.encode() in curl[1] and "-K" in curl[0]


def test_config_incomplete_refusee():
    with pytest.raises(ErreurExecuteur):
        executeur.charger_config({"EXECUTEUR_KEY": "k"})
    cfg = executeur.charger_config({"EXECUTEUR_KEY": "k", "EXECUTEUR_S3_ENDPOINT": "http://x",
                                    "EXECUTEUR_S3_BUCKET": "b", "EXECUTEUR_S3_KEY": "a",
                                    "EXECUTEUR_S3_SECRET": "s"})
    assert cfg["S3_REGION"] == "us-east-1"


@pytest.fixture
def serveur():
    runner = FauxRunner()
    srv = ThreadingHTTPServer(("127.0.0.1", 0), executeur.fabrique_handler(runner, CFG))
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", runner
    srv.shutdown()
    srv.server_close()


def _post(url, corps, cle=None):
    h = {"Content-Type": "application/json"}
    if cle:
        h["X-API-Key"] = cle
    req = urllib.request.Request(url + "/verifier", data=json.dumps(corps).encode(), headers=h)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def test_http_sans_cle_ou_mauvaise_cle_401_et_rien_execute(serveur):
    url, runner = serveur
    assert _post(url, CORPS)[0] == 401
    assert _post(url, CORPS, "mauvaise")[0] == 401
    assert runner.appels == []


def test_http_nominal_200(serveur):
    url, _ = serveur
    code, corps = _post(url, CORPS, "cle-exec")
    assert code == 200 and corps["verdict"] == "valide"


def test_http_validation_400(serveur):
    url, _ = serveur
    assert _post(url, {**CORPS, "objet": "../x"}, "cle-exec")[0] == 400


def test_http_une_verification_a_la_fois_409(serveur):
    url, _ = serveur
    assert executeur.VERROU.acquire(blocking=False)
    try:
        assert _post(url, CORPS, "cle-exec")[0] == 409
    finally:
        executeur.VERROU.release()


def test_http_sante_et_route_inconnue(serveur):
    url, _ = serveur
    with urllib.request.urlopen(url + "/sante", timeout=10) as r:
        assert json.loads(r.read())["ok"] is True
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(url + "/autre", timeout=10)
    assert e.value.code == 404
```

Run : `cd outils/executeur-restauration && rtk proxy python3 -m pytest test_executeur.py -q -p no:cacheprovider`
Expected : FAIL (`ModuleNotFoundError: No module named 'executeur'`).

- [ ] **Step 2 : implémenter** `outils/executeur-restauration/executeur.py`

```python
"""Exécuteur de restauration jetable (S247) — tourne sur la VM 100, sous systemd.

Dokploy n'expose aucune route de restauration et la brique `livraison` n'a ni SSH ni socket
Docker. Ce service est le seul à toucher Docker : il n'accepte qu'UN ordre, validé strictement :
« restaure cet objet S3 dans une base jetable du conteneur Postgres X et compare les comptages ».
Stdlib seule. Secrets S3 : configuration d'environnement, passés à curl par stdin (jamais argv).
"""
import gzip
import hmac
import json
import os
import re
import secrets
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

RE_SERVICE = re.compile(r"^postgres-[a-z0-9-]{3,60}$")
RE_NOM = re.compile(r"^[a-z_][a-z0-9_]{0,40}$")
RE_TABLE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
RE_OBJET = re.compile(r"^[A-Za-z0-9._/-]{1,200}$")
MAGIE_PGDMP = b"PGDMP"
MAX_DUMP = 512 * 1024 * 1024
CORPS_MAX = 65536
VERROU = threading.Lock()


class ErreurExecuteur(Exception):
    def __init__(self, statut: int, message: str):
        super().__init__(message)
        self.statut = statut
        self.message = message


class Runner:
    def run(self, argv, stdin=None, timeout=300):
        p = subprocess.run(argv, input=stdin, capture_output=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr


def charger_config(env=None) -> dict:
    e = os.environ if env is None else env
    cfg = {k: e.get("EXECUTEUR_" + k, "") for k in ("KEY", "S3_ENDPOINT", "S3_BUCKET", "S3_KEY",
                                                    "S3_SECRET")}
    manquants = [k for k, v in cfg.items() if not v]
    if manquants:
        raise ErreurExecuteur(500, "configuration incomplète : "
                              + ", ".join("EXECUTEUR_" + k for k in manquants))
    cfg["S3_REGION"] = e.get("EXECUTEUR_S3_REGION", "us-east-1")
    return cfg


def valider(corps) -> tuple[str, str, str, str]:
    if not isinstance(corps, dict):
        raise ErreurExecuteur(400, "corps JSON objet attendu")
    service, utilisateur, base, objet = (corps.get(k) for k in
                                         ("service", "utilisateur", "base", "objet"))
    if not (isinstance(service, str) and RE_SERVICE.match(service)):
        raise ErreurExecuteur(400, "service invalide")
    if not (isinstance(utilisateur, str) and RE_NOM.match(utilisateur)):
        raise ErreurExecuteur(400, "utilisateur invalide")
    if not (isinstance(base, str) and RE_NOM.match(base)):
        raise ErreurExecuteur(400, "base invalide")
    if not (isinstance(objet, str) and RE_OBJET.match(objet)) or ".." in objet \
            or objet.startswith("/"):
        raise ErreurExecuteur(400, "objet invalide")
    return service, utilisateur, base, objet


def conteneur(runner, service: str) -> str:
    code, out, _ = runner.run(["docker", "ps", "-q", "--filter", f"name=^{service}"])
    if code != 0:
        raise ErreurExecuteur(502, "docker indisponible")
    ids = out.decode().split()
    if len(ids) != 1:
        raise ErreurExecuteur(404, "conteneur introuvable ou ambigu")
    return ids[0]


def _psql(runner, cid: str, utilisateur: str, base: str, sql: str) -> str:
    code, out, _ = runner.run(["docker", "exec", cid, "psql", "-U", utilisateur, "-d", base,
                               "-Atc", sql])
    if code != 0:
        raise ErreurExecuteur(502, "requête SQL en échec")
    return out.decode()


def comptages(runner, cid: str, utilisateur: str, base: str) -> dict:
    tables = _psql(runner, cid, utilisateur, base,
                   "select table_name from information_schema.tables where "
                   "table_schema='public' and table_type='BASE TABLE' order by 1").split()
    res = {}
    for t in tables:
        if not RE_TABLE.match(t):
            raise ErreurExecuteur(502, "nom de table inattendu")
        res[t] = int(_psql(runner, cid, utilisateur, base, f'select count(*) from "{t}"').strip())
    return res


def telecharger(runner, cfg: dict, objet: str, dest: Path) -> None:
    url = f"{cfg['S3_ENDPOINT'].rstrip('/')}/{cfg['S3_BUCKET']}/{objet}"
    identifiants = f'user = "{cfg["S3_KEY"]}:{cfg["S3_SECRET"]}"\n'.encode()
    code, _, _ = runner.run(["curl", "-sS", "-f", "--aws-sigv4", f"aws:amz:{cfg['S3_REGION']}:s3",
                             "-K", "-", "-o", str(dest), url], stdin=identifiants, timeout=600)
    if code != 0:
        raise ErreurExecuteur(502, "téléchargement de la sauvegarde impossible")


def _resultat(verdict, raison, origine, restaure, debut):
    return {"ok": True, "verdict": verdict, "raison": raison, "comptages_origine": origine,
            "comptages_restaures": restaure, "duree_s": round(time.time() - debut, 2)}


def verifier(runner, cfg: dict, corps) -> dict:
    service, utilisateur, base, objet = valider(corps)
    debut = time.time()
    cid = conteneur(runner, service)
    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp) / "dump.gz"
        telecharger(runner, cfg, objet, dest)
        try:
            with gzip.open(dest, "rb") as f:
                donnees = f.read(MAX_DUMP + 1)
        except (OSError, EOFError):
            return _resultat("invalide", "archive illisible (gzip)", {}, {}, debut)
    if len(donnees) > MAX_DUMP:
        return _resultat("invalide", "sauvegarde trop volumineuse pour la vérification", {}, {},
                         debut)
    if not donnees.startswith(MAGIE_PGDMP):
        return _resultat("invalide", "format inattendu (ce n'est pas un pg_dump -Fc)", {}, {},
                         debut)
    origine = comptages(runner, cid, utilisateur, base)
    if not origine:
        return _resultat("invalide", "aucune table dans la base d'origine : rien à prouver",
                         origine, {}, debut)
    jetable = "restore_" + secrets.token_hex(4)
    restaure: dict = {}
    try:
        _psql(runner, cid, utilisateur, "postgres", f"create database {jetable}")
        code, _, _ = runner.run(["docker", "exec", "-i", cid, "pg_restore", "-U", utilisateur,
                                 "-d", jetable, "--no-owner"], stdin=donnees, timeout=900)
        if code != 0:
            return _resultat("invalide", "pg_restore a échoué", origine, restaure, debut)
        restaure = comptages(runner, cid, utilisateur, jetable)
    finally:
        try:
            _psql(runner, cid, utilisateur, "postgres", f"drop database if exists {jetable}")
        except ErreurExecuteur:
            pass
    if restaure != origine:
        return _resultat("invalide", "comptages différents entre l'original et la copie restaurée",
                         origine, restaure, debut)
    return _resultat("valide", None, origine, restaure, debut)


def fabrique_handler(runner, cfg: dict):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):   # pas de journal d'accès : jamais d'en-tête ni de corps
            pass

        def _rep(self, code, obj):
            corps = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(corps)))
            self.end_headers()
            self.wfile.write(corps)

        def do_GET(self):
            if self.path == "/sante":
                return self._rep(200, {"ok": True, "service": "executeur-restauration"})
            self._rep(404, {"erreur": "introuvable"})

        def do_POST(self):
            if self.path != "/verifier":
                return self._rep(404, {"erreur": "introuvable"})
            presentee = self.headers.get("X-API-Key", "")
            if not hmac.compare_digest(presentee.encode(), cfg["KEY"].encode()):
                return self._rep(401, {"erreur": "clé invalide"})
            try:
                taille = int(self.headers.get("Content-Length", "0") or 0)
            except ValueError:
                taille = 0
            if taille <= 0 or taille > CORPS_MAX:
                return self._rep(400, {"erreur": "corps invalide"})
            try:
                corps = json.loads(self.rfile.read(taille))
            except ValueError:
                return self._rep(400, {"erreur": "JSON invalide"})
            if not VERROU.acquire(blocking=False):
                return self._rep(409, {"erreur": "une vérification est déjà en cours"})
            try:
                self._rep(200, verifier(runner, cfg, corps))
            except ErreurExecuteur as e:
                self._rep(e.statut, {"erreur": e.message})
            finally:
                VERROU.release()
    return Handler


def main() -> None:
    cfg = charger_config()
    bind = os.environ.get("EXECUTEUR_BIND", "127.0.0.1")
    port = int(os.environ.get("EXECUTEUR_PORT", "8090"))
    ThreadingHTTPServer((bind, port), fabrique_handler(Runner(), cfg)).serve_forever()


if __name__ == "__main__":
    main()
```

- [ ] **Step 3 : tests verts** — `cd outils/executeur-restauration && rtk proxy python3 -m pytest test_executeur.py -q -p no:cacheprovider --junitxml=/private/tmp/claude-502/-Users-garinat-t-Desktop-Workplace/193dcfa4-1ddb-4efb-9c27-a49354487bc8/scratchpad/s247-t6.xml` → 0 échec (relever les comptes dans le junit).

- [ ] **Step 4 : tests de mutation** — (a) remplacer `restaure != origine` par `False` : `test_comptages_differents_invalide…` doit échouer ; (b) retirer le `finally` de suppression : `test_pg_restore_en_echec…` et `test_comptages_differents…` doivent échouer ; (c) remplacer `hmac.compare_digest(...)` par `True` : `test_http_sans_cle…` doit échouer. Restaurer après chaque mutation.

- [ ] **Step 5 : commit** — `git add outils/executeur-restauration && git commit -m "feat(s247): exécuteur de restauration jetable (VM 100)"`.

---

### Task 7 : Sauvegarde de Forgejo vers le S3 (script de la VM 100)

**Files:**
- Create: `outils/executeur-restauration/sauvegarde_forgejo.py`
- Test: `outils/executeur-restauration/test_sauvegarde_forgejo.py`

**Interfaces:**
- Consumes : `executeur.Runner`, `executeur.ErreurExecuteur`, `executeur.charger_config` (même fichier d'environnement ; `EXECUTEUR_KEY` y est exigée mais inutilisée ici).
- Produces : `sauvegarde_forgejo.sauvegarder(runner, cfg, conteneur="forgejo-forgejo-1", garder=7, maintenant=None, dossier=None) -> dict` → `{"fichier": str, "taille": int, "supprimes": list[str]}` ; lève `ErreurExecuteur` sur toute étape en échec ; **ne supprime jamais d'ancienne sauvegarde si la vérification de taille échoue**.

- [ ] **Step 1 : tests qui échouent** (`test_sauvegarde_forgejo.py`)

```python
import re
import time
from pathlib import Path

import pytest

import sauvegarde_forgejo
from executeur import ErreurExecuteur

SECRET = "s3cr3t-tres-long-et-unique"
CFG = {"KEY": "k", "S3_ENDPOINT": "http://s3.test:9106", "S3_BUCKET": "dokploy-backups",
       "S3_KEY": "AKIATEST", "S3_SECRET": SECRET, "S3_REGION": "us-east-1"}
MAINT = time.mktime((2026, 11, 26, 3, 15, 0, 0, 0, 0))


class Faux:
    def __init__(self, anciens=(), taille_s3=None, dump=0, upload=0, liste=0):
        self.anciens, self.taille_s3, self.dump, self.upload, self.liste = \
            list(anciens), taille_s3, dump, upload, liste
        self.appels, self.supprimes = [], []

    def run(self, argv, stdin=None, timeout=300):
        self.appels.append((list(argv), stdin))
        if argv[:2] == ["docker", "exec"] and "dump" in argv:
            return self.dump, b"", b""
        if argv[:2] == ["docker", "cp"]:
            Path(argv[3]).write_bytes(b"Z" * 1000)
            return 0, b"", b""
        if argv[:2] == ["docker", "exec"] and "rm" in argv:
            return 0, b"", b""
        if argv[0] == "curl":
            if "-T" in argv:
                return self.upload, b"", b""
            if "-I" in argv:
                t = 1000 if self.taille_s3 is None else self.taille_s3
                return 0, f"HTTP/1.1 200 OK\r\nContent-Length: {t}\r\n\r\n".encode(), b""
            if "DELETE" in argv:
                self.supprimes.append(argv[-1].rsplit("/", 1)[-1])
                return 0, b"", b""
            if self.liste:
                return self.liste, b"", b""
            cles = "".join(f"<Key>forgejo/{n}</Key>" for n in self.anciens)
            return 0, f"<ListBucketResult>{cles}</ListBucketResult>".encode(), b""
        raise AssertionError(argv)


def test_nominal_envoie_verifie_et_garde_les_7_dernieres(tmp_path):
    anciens = [f"forgejo-2026110{i}T031500Z.zip" for i in range(1, 9)]   # 8 anciennes
    f = Faux(anciens)
    r = sauvegarde_forgejo.sauvegarder(f, CFG, garder=7, maintenant=MAINT, dossier=tmp_path)
    assert r["fichier"] == "forgejo-20261126T031500Z.zip" and r["taille"] == 1000
    # 8 anciennes + la nouvelle (la liste du faux ne contient pas la nouvelle) : on en garde 7 en
    # tout, la nouvelle comprise => 2 supprimées parmi les 8 anciennes (les plus vieilles).
    assert f.supprimes == ["forgejo-20261101T031500Z.zip", "forgejo-20261102T031500Z.zip"]
    assert r["supprimes"] == f.supprimes


def test_ne_supprime_jamais_la_nouvelle_ni_rien_si_peu_de_sauvegardes(tmp_path):
    f = Faux(["forgejo-20261101T031500Z.zip"])
    r = sauvegarde_forgejo.sauvegarder(f, CFG, garder=7, maintenant=MAINT, dossier=tmp_path)
    assert r["supprimes"] == [] and f.supprimes == []


def test_taille_differente_sur_le_s3_leve_et_ne_supprime_rien(tmp_path):
    f = Faux([f"forgejo-2026110{i}T031500Z.zip" for i in range(1, 9)], taille_s3=999)
    with pytest.raises(ErreurExecuteur):
        sauvegarde_forgejo.sauvegarder(f, CFG, garder=7, maintenant=MAINT, dossier=tmp_path)
    assert f.supprimes == []


def test_dump_en_echec_n_envoie_rien(tmp_path):
    f = Faux(dump=1)
    with pytest.raises(ErreurExecuteur):
        sauvegarde_forgejo.sauvegarder(f, CFG, maintenant=MAINT, dossier=tmp_path)
    assert not [a for a, _ in f.appels if a[0] == "curl"]


def test_upload_en_echec_leve(tmp_path):
    with pytest.raises(ErreurExecuteur):
        sauvegarde_forgejo.sauvegarder(Faux(upload=22), CFG, maintenant=MAINT, dossier=tmp_path)


def test_liste_en_echec_ne_supprime_rien_mais_la_sauvegarde_reste_valide(tmp_path):
    f = Faux(liste=22)
    r = sauvegarde_forgejo.sauvegarder(f, CFG, maintenant=MAINT, dossier=tmp_path)
    assert r["supprimes"] == [] and f.supprimes == []


def test_le_dump_est_toujours_retire_du_conteneur(tmp_path):
    f = Faux(upload=22)
    with pytest.raises(ErreurExecuteur):
        sauvegarde_forgejo.sauvegarder(f, CFG, maintenant=MAINT, dossier=tmp_path)
    assert any(a[:2] == ["docker", "exec"] and "rm" in a for a, _ in f.appels)


def test_secret_jamais_dans_argv(tmp_path):
    f = Faux()
    sauvegarde_forgejo.sauvegarder(f, CFG, maintenant=MAINT, dossier=tmp_path)
    assert all(SECRET not in " ".join(a) for a, _ in f.appels)
    assert any(s and SECRET.encode() in s for a, s in f.appels if a[0] == "curl")


def test_nom_de_fichier_horodate_trie_chronologiquement():
    assert re.fullmatch(r"forgejo-\d{8}T\d{6}Z\.zip", sauvegarde_forgejo.nom_fichier(MAINT))
```

Run : `cd outils/executeur-restauration && rtk proxy python3 -m pytest test_sauvegarde_forgejo.py -q -p no:cacheprovider` → FAIL (`ModuleNotFoundError: sauvegarde_forgejo`).

- [ ] **Step 2 : implémenter** `sauvegarde_forgejo.py`

```python
"""Sauvegarde de Forgejo vers le S3 du HP (S247) : forgejo dump -> envoi -> vérification de
taille -> rétention. Lancé par un timer systemd sur la VM 100. Même fichier d'environnement que
l'exécuteur. Code de sortie non nul à la moindre étape en échec (systemd le montre)."""
import json
import re
import sys
import tempfile
import time
from pathlib import Path

from executeur import ErreurExecuteur, Runner, charger_config

PREFIXE = "forgejo/"


def nom_fichier(maintenant: float) -> str:
    return time.strftime("forgejo-%Y%m%dT%H%M%SZ.zip", time.gmtime(maintenant))


def _curl(runner, cfg, args, url, timeout=600):
    ident = f'user = "{cfg["S3_KEY"]}:{cfg["S3_SECRET"]}"\n'.encode()
    return runner.run(["curl", "-sS", "-f", "--aws-sigv4", f"aws:amz:{cfg['S3_REGION']}:s3",
                       "-K", "-", *args, url], stdin=ident, timeout=timeout)


def sauvegarder(runner, cfg, conteneur="forgejo-forgejo-1", garder=7, maintenant=None,
                dossier=None) -> dict:
    now = time.time() if maintenant is None else maintenant
    nom = nom_fichier(now)
    base = f"{cfg['S3_ENDPOINT'].rstrip('/')}/{cfg['S3_BUCKET']}"
    with tempfile.TemporaryDirectory(dir=dossier) as tmp:
        local = Path(tmp) / nom
        try:
            code, _, _ = runner.run(["docker", "exec", "-u", "git", conteneur, "forgejo", "dump",
                                     "-f", f"/tmp/{nom}", "--type", "zip"], timeout=900)
            if code != 0:
                raise ErreurExecuteur(502, "forgejo dump a échoué")
            code, _, _ = runner.run(["docker", "cp", f"{conteneur}:/tmp/{nom}", str(local)])
            if code != 0 or not local.exists() or local.stat().st_size == 0:
                raise ErreurExecuteur(502, "récupération du dump impossible ou vide")
            taille = local.stat().st_size
            code, _, _ = _curl(runner, cfg, ["-X", "PUT", "-T", str(local)],
                               f"{base}/{PREFIXE}{nom}")
            if code != 0:
                raise ErreurExecuteur(502, "envoi vers le S3 impossible")
            code, out, _ = _curl(runner, cfg, ["-I"], f"{base}/{PREFIXE}{nom}")
            m = re.search(r"(?im)^content-length:\s*(\d+)", out.decode(errors="replace"))
            if code != 0 or not m or int(m.group(1)) != taille:
                raise ErreurExecuteur(502, "taille de l'objet S3 différente du dump local")
        finally:
            runner.run(["docker", "exec", conteneur, "rm", "-f", f"/tmp/{nom}"])
    supprimes: list[str] = []
    code, out, _ = _curl(runner, cfg, [], f"{base}?list-type=2&prefix={PREFIXE}", timeout=60)
    if code == 0:
        noms = sorted(set(re.findall(r"<Key>" + PREFIXE + r"([^<]+)</Key>", out.decode())) | {nom})
        for ancien in noms[:-garder] if garder > 0 else []:
            if ancien == nom:
                continue
            c, _, _ = _curl(runner, cfg, ["-X", "DELETE"], f"{base}/{PREFIXE}{ancien}", timeout=60)
            if c == 0:
                supprimes.append(ancien)
    return {"fichier": nom, "taille": taille, "supprimes": supprimes}


def main() -> int:
    try:
        print(json.dumps(sauvegarder(Runner(), charger_config())))
        return 0
    except ErreurExecuteur as e:
        print(json.dumps({"ok": False, "erreur": e.message}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3 : tests verts** (junit dans le scratchpad, `s247-t7.xml`). Attention au test nominal : la liste du faux contient 8 anciennes ; `noms` = 8 anciennes + la nouvelle = 9, `noms[:-7]` = les 2 plus vieilles → 2 suppressions. 
- [ ] **Step 4 : mutation** — retirer le test `int(m.group(1)) != taille` : `test_taille_differente…` doit échouer ; changer `noms[:-garder]` en `noms[:garder]` : le test nominal doit échouer. Restaurer.
- [ ] **Step 5 : commit** — `git add outils/executeur-restauration && git commit -m "feat(s247): sauvegarde de Forgejo vers le S3 (dump, envoi, vérification, rétention)"`.

---

### Task 8 : Rôle Ansible `executeur_restauration` (VM 100)

**Files:**
- Create: `infra/ansible/roles/executeur_restauration/defaults/main.yml`
- Create: `infra/ansible/roles/executeur_restauration/tasks/main.yml`
- Create: `infra/ansible/roles/executeur_restauration/templates/executeur-restauration.service.j2`
- Create: `infra/ansible/roles/executeur_restauration/templates/forgejo-sauvegarde.service.j2`
- Create: `infra/ansible/roles/executeur_restauration/templates/forgejo-sauvegarde.timer.j2`
- Modify: `infra/ansible/playbooks/livraison.yml` (ajouter le rôle)
- Modify: `infra/ansible/tests/test_roles_livraison.py`

**Interfaces:**
- Consumes : `outils/executeur-restauration/{executeur.py,sauvegarde_forgejo.py}`.
- Produces : service `executeur-restauration` (écoute `{{ executeur_bind }}:{{ executeur_port }}`), timer `forgejo-sauvegarde.timer` (03:15 chaque jour), fichier d'environnement attendu `/etc/executeur-restauration/env` (créé à la main).

- [ ] **Step 1 : tests qui échouent** — dans `infra/ansible/tests/test_roles_livraison.py`, ajouter `"executeur_restauration"` à la liste des rôles de `FILES` (ligne `for r in ("dokploy", "forgejo", "docker_user_guard")`) et ces tests :

```python
def test_playbook_inclut_executeur():
    assert "executeur_restauration" in (BASE / "playbooks" / "livraison.yml").read_text()


def test_executeur_ecoute_sur_l_ip_lan_pas_sur_toutes_les_interfaces():
    t = text()
    assert "executeur_bind: \"{{ ansible_default_ipv4.address }}\"" in t
    assert "EXECUTEUR_BIND=0.0.0.0" not in t and "executeur_bind: \"0.0.0.0\"" not in t


def test_executeur_port_limite_a_l_ip_du_hp():
    t = text()
    assert "ufw allow from {{ executeur_client_ip }} to any port {{ executeur_port }}" in t
    assert "executeur_client_ip: 192.168.1.89" in t


def test_executeur_secrets_lus_dans_un_fichier_root_0600_cree_a_la_main():
    t = text()
    assert "EnvironmentFile=/etc/executeur-restauration/env" in t
    assert 'stat.mode == "0600"' in t and "ansible.builtin.stat" in t
    assert "EXECUTEUR_S3_SECRET=" not in t and "EXECUTEUR_KEY=" not in t


def test_executeur_unit_durcie():
    t = text()
    assert "NoNewPrivileges=true" in t and "ProtectHome=true" in t


def test_timer_forgejo_quotidien():
    assert "OnCalendar=*-*-* 03:15:00" in text()
```

Run : `cd infra/ansible && rtk proxy python3 -m pytest tests/test_roles_livraison.py -q -p no:cacheprovider` → FAIL (rôle absent).

- [ ] **Step 2 : implémenter**

`defaults/main.yml` :
```yaml
executeur_dir: /opt/executeur-restauration
executeur_env_file: /etc/executeur-restauration/env
executeur_port: 8090
executeur_bind: "{{ ansible_default_ipv4.address }}"
executeur_client_ip: 192.168.1.89     # le HP (seule machine autorisée à appeler l'exécuteur)
forgejo_conteneur: forgejo-forgejo-1
forgejo_sauvegardes_gardees: 7
```

`tasks/main.yml` :
```yaml
- name: Require the private environment file (created by hand, never by Ansible)
  ansible.builtin.stat: {path: "{{ executeur_env_file }}"}
  register: executeur_env
- name: Stop here when the environment file is missing or not private
  ansible.builtin.assert:
    that:
      - executeur_env.stat.exists
      - executeur_env.stat.pw_name == "root"
      - executeur_env.stat.mode == "0600"
    fail_msg: >-
      Créer {{ executeur_env_file }} (root, mode 0600) avec EXECUTEUR_KEY, EXECUTEUR_S3_ENDPOINT,
      EXECUTEUR_S3_BUCKET, EXECUTEUR_S3_KEY, EXECUTEUR_S3_SECRET ; ne jamais le mettre dans git.
- name: Directory for the scripts
  ansible.builtin.file: {path: "{{ executeur_dir }}", state: directory, owner: root, mode: "0750"}
- name: Install the scripts
  ansible.builtin.copy:
    src: "{{ playbook_dir }}/../../../outils/executeur-restauration/{{ item }}"
    dest: "{{ executeur_dir }}/{{ item }}"
    owner: root
    mode: "0750"
  loop: [executeur.py, sauvegarde_forgejo.py]
  notify: restart executeur
- name: Executor unit
  ansible.builtin.template: {src: executeur-restauration.service.j2, dest: /etc/systemd/system/executeur-restauration.service, mode: "0644"}
- name: Forgejo backup unit
  ansible.builtin.template: {src: forgejo-sauvegarde.service.j2, dest: /etc/systemd/system/forgejo-sauvegarde.service, mode: "0644"}
- name: Forgejo backup timer
  ansible.builtin.template: {src: forgejo-sauvegarde.timer.j2, dest: /etc/systemd/system/forgejo-sauvegarde.timer, mode: "0644"}
- name: Allow only the HP to call the executor
  ansible.builtin.command: ufw allow from {{ executeur_client_ip }} to any port {{ executeur_port }} proto tcp
  changed_when: true
- name: Enable and start the executor and the backup timer
  ansible.builtin.systemd:
    name: "{{ item }}"
    enabled: true
    state: restarted
    daemon_reload: true
  loop: [executeur-restauration.service, forgejo-sauvegarde.timer]
```
(Si Ansible refuse `notify` sans `handlers:`, supprimer la ligne `notify` : le redémarrage est déjà fait par la dernière tâche.)

`templates/executeur-restauration.service.j2` :
```ini
[Unit]
Description=Exécuteur de restauration jetable (S247)
After=docker.service network-online.target
Requires=docker.service

[Service]
EnvironmentFile=/etc/executeur-restauration/env
Environment=EXECUTEUR_BIND={{ executeur_bind }}
Environment=EXECUTEUR_PORT={{ executeur_port }}
ExecStart=/usr/bin/python3 {{ executeur_dir }}/executeur.py
User=root
NoNewPrivileges=true
ProtectHome=true
ProtectSystem=full
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

`templates/forgejo-sauvegarde.service.j2` :
```ini
[Unit]
Description=Sauvegarde de Forgejo vers le S3 (S247)
After=docker.service

[Service]
Type=oneshot
EnvironmentFile=/etc/executeur-restauration/env
WorkingDirectory={{ executeur_dir }}
ExecStart=/usr/bin/python3 {{ executeur_dir }}/sauvegarde_forgejo.py
NoNewPrivileges=true
ProtectHome=true
```
`templates/forgejo-sauvegarde.timer.j2` :
```ini
[Unit]
Description=Sauvegarde quotidienne de Forgejo

[Timer]
OnCalendar=*-*-* 03:15:00
Persistent=true

[Install]
WantedBy=timers.target
```

`playbooks/livraison.yml` : ajouter `    - executeur_restauration` après `forgejo`.

- [ ] **Step 3 : tests verts** (le test `test_no_floating_tags` et `test_no_literal_secret` existants doivent rester verts avec le nouveau rôle).
- [ ] **Step 4 : commit** — `git add infra/ansible outils/executeur-restauration && git commit -m "feat(s247): rôle Ansible de l'exécuteur et du timer de sauvegarde Forgejo"`.

---

### Task 9 : Inventaire, client de l'exécuteur et méthodes Dokploy (brique `livraison`)

**Files:**
- Create: `briques/livraison/inventaire.py`, `briques/livraison/client_executeur.py`
- Modify: `briques/livraison/dokploy.py` (méthodes `sauvegarder_base`, `fichiers_sauvegarde`, `sauvegarder_volume`), `briques/livraison/faux_dokploy.py`
- Test: `briques/livraison/test_inventaire.py`, `briques/livraison/test_client_executeur.py`, ajouts à `briques/livraison/test_dokploy.py`

**Interfaces:**
- Produces : `inventaire.lire(nom_app: str) -> dict | None` (clé = nom Dokploy de l'app, `strip().lower()`) au format `{"bases": [{"base","service","utilisateur","sauvegarde_id","prefixe_s3"}], "volumes": [{"volume_backup_id"}]}` — entrée **invalide ⇒ `None`** (fail closed) ; `client_executeur.ExecuteurErreur(message, statut=None)` ; `client_executeur.Executeur(base_url, cle, transport=None, delai=280.0).verifier(service, utilisateur, base, objet) -> dict` (async) ; `Dokploy.sauvegarder_base(backup_id) -> {"ok": True, "backup_id": str}` ; `Dokploy.fichiers_sauvegarde(backup_id) -> list[{"nom","taille","date"}]` (plus récent d'abord) ; `Dokploy.sauvegarder_volume(volume_backup_id) -> {"ok": True, "volume_backup_id": str}`.

- [ ] **Step 1 : tests qui échouent**

`test_inventaire.py` :
```python
import json

import inventaire

BASE = {"base": "temoin", "service": "postgres-abc-def", "utilisateur": "temoin",
        "sauvegarde_id": "B1", "prefixe_s3": "postgres-abc-def/s247-pg"}


def _ecrire(tmp_path, monkeypatch, contenu):
    p = tmp_path / "inv.json"
    p.write_text(contenu if isinstance(contenu, str) else json.dumps(contenu))
    monkeypatch.setenv("LIVRAISON_INVENTAIRE", str(p))


def test_entree_valide_insensible_a_la_casse(tmp_path, monkeypatch):
    _ecrire(tmp_path, monkeypatch, {"calendrier-familial": {"bases": [BASE], "volumes": []}})
    assert inventaire.lire("  Calendrier-Familial ")["bases"][0]["base"] == "temoin"


def test_defaut_dans_livraison_data(tmp_path, monkeypatch):
    monkeypatch.delenv("LIVRAISON_INVENTAIRE", raising=False)
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "inventaire.json").write_text(json.dumps({"a": {"bases": [BASE]}}))
    assert inventaire.lire("a")["volumes"] == []


def test_app_inconnue_fichier_absent_ou_corrompu_donnent_none(tmp_path, monkeypatch):
    _ecrire(tmp_path, monkeypatch, {"a": {"bases": [BASE]}})
    assert inventaire.lire("b") is None
    _ecrire(tmp_path, monkeypatch, "{pas du json")
    assert inventaire.lire("a") is None
    monkeypatch.setenv("LIVRAISON_INVENTAIRE", str(tmp_path / "absent.json"))
    assert inventaire.lire("a") is None


def test_entree_invalide_fail_closed(tmp_path, monkeypatch):
    for mauvais in ({"bases": [{"base": "x"}]}, {"bases": "x"}, {"bases": [BASE], "volumes": [{}]},
                    {"bases": [{**BASE, "prefixe_s3": "../x"}]}, {"bases": []}, [], "x"):
        _ecrire(tmp_path, monkeypatch, {"a": mauvais})
        assert inventaire.lire("a") is None, mauvais
```
(`{"bases": []}` sans volumes = entrée sans rien à sauvegarder → `None` ; une entrée n'est valide que si elle a au moins une base OU un volume.)

`test_client_executeur.py` :
```python
import asyncio
import json

import httpx
import pytest

from client_executeur import Executeur, ExecuteurErreur


def cli(handler, cle="k"):
    return Executeur("http://x.test", cle, transport=httpx.MockTransport(handler))


def run(c):
    return asyncio.run(c)


def test_verifier_envoie_la_cle_et_le_corps_et_renvoie_le_json():
    vus = []

    def h(req):
        vus.append((req.url.path, req.headers.get("x-api-key"), json.loads(req.content)))
        return httpx.Response(200, json={"ok": True, "verdict": "valide"})
    r = run(cli(h).verifier("postgres-a-b", "u", "b", "p/o"))
    assert r["verdict"] == "valide"
    assert vus == [("/verifier", "k", {"service": "postgres-a-b", "utilisateur": "u",
                                       "base": "b", "objet": "p/o"})]


@pytest.mark.parametrize("code,mot", [(401, "clé"), (409, "déjà en cours"), (404, "404"),
                                      (500, "500")])
def test_erreurs_http_messages_honnetes_sans_secret(code, mot):
    with pytest.raises(ExecuteurErreur) as e:
        run(cli(lambda r: httpx.Response(code, json={"erreur": "SECRET-INTERNE"})).verifier(
            "postgres-a-b", "u", "b", "o"))
    assert mot in e.value.message and "SECRET-INTERNE" not in e.value.message


def test_injoignable_et_json_illisible():
    def boom(req):
        raise httpx.ConnectError("x")
    with pytest.raises(ExecuteurErreur) as e:
        run(cli(boom).verifier("postgres-a-b", "u", "b", "o"))
    assert "injoignable" in e.value.message
    with pytest.raises(ExecuteurErreur):
        run(cli(lambda r: httpx.Response(200, content=b"pas du json")).verifier(
            "postgres-a-b", "u", "b", "o"))
```

Ajouts à `test_dokploy.py` (réutilise `etat()`, `cli()`, `run()` du fichier) :
```python
def _etat_sauvegarde():
    e = etat()
    e["fichiers"] = {"B1": [{"Name": "vieux.sql.gz", "Size": 10, "ModTime":
                             "2026-11-25T10:00:00.000000000Z", "IsDir": False}]}
    return e


def test_sauvegarder_base_appelle_la_route_et_ne_renvoie_que_ok():
    e = _etat_sauvegarde()
    r = run(cli(e).sauvegarder_base("B1"))
    assert r == {"ok": True, "backup_id": "B1"}
    a = [x for x in e["appels"] if x["chemin"] == "/api/backup.manualBackupPostgres"][0]
    assert a["methode"] == "POST" and a["corps"] == {"backupId": "B1"}


def test_fichiers_sauvegarde_liste_blanche_plus_recent_d_abord_sans_dossiers():
    e = _etat_sauvegarde()
    e["fichiers"]["B1"] += [{"Name": "dossier", "IsDir": True, "ModTime": "2026-11-27T00:00:00Z"},
                            {"Name": "recent.sql.gz", "Size": 20, "Path": "SECRET",
                             "ModTime": "2026-11-26T10:00:00.000000000Z", "IsDir": False}]
    r = run(cli(e).fichiers_sauvegarde("B1"))
    assert [f["nom"] for f in r] == ["recent.sql.gz", "vieux.sql.gz"]
    assert set(r[0]) == {"nom", "taille", "date"} and "SECRET" not in str(r)


def test_fichiers_sauvegarde_inconnue_404():
    with pytest.raises(DokployErreur) as ex:
        run(cli(_etat_sauvegarde()).fichiers_sauvegarde("ZZ"))
    assert ex.value.statut == 404


def test_sauvegarder_volume_corps_vide_est_un_succes():
    e = _etat_sauvegarde()
    assert run(cli(e).sauvegarder_volume("V1")) == {"ok": True, "volume_backup_id": "V1"}
    assert e["volumes_lances"] == ["V1"]
```

Run : `cd briques/livraison && rtk proxy python3 -m pytest test_inventaire.py test_client_executeur.py test_dokploy.py -q -p no:cacheprovider` → FAIL.

- [ ] **Step 2 : implémenter**

`inventaire.py` :
```python
"""Inventaire des sauvegardes par application (S247) : ce que contient chaque app (bases Postgres,
volumes) et où sont ses sauvegardes. Fichier JSON tenu à la main par l'exploitant (jamais deviné :
une app absente ou une entrée mal formée ne sont PAS sauvegardées « au hasard », on refuse)."""
import json
import os
import re
from pathlib import Path
from typing import Optional

_CHAMPS_BASE = ("base", "service", "utilisateur", "sauvegarde_id", "prefixe_s3")
_RE_PREFIXE = re.compile(r"^[A-Za-z0-9._/-]{1,150}$")


def _chemin() -> Path:
    explicite = os.getenv("LIVRAISON_INVENTAIRE")
    return Path(explicite) if explicite else Path(os.getenv("LIVRAISON_DATA", "/data")) / "inventaire.json"


def _valide(e) -> bool:
    if not isinstance(e, dict):
        return False
    bases, volumes = e.get("bases", []), e.get("volumes", [])
    if not isinstance(bases, list) or not isinstance(volumes, list) or not (bases or volumes):
        return False
    for b in bases:
        if not (isinstance(b, dict) and all(isinstance(b.get(c), str) and b[c] for c in _CHAMPS_BASE)):
            return False
        if not _RE_PREFIXE.match(b["prefixe_s3"]) or ".." in b["prefixe_s3"] \
                or b["prefixe_s3"].startswith("/"):
            return False
    return all(isinstance(v, dict) and isinstance(v.get("volume_backup_id"), str)
               and v["volume_backup_id"] for v in volumes)


def lire(nom_app: str) -> Optional[dict]:
    try:
        d = json.loads(_chemin().read_text())
    except (OSError, ValueError):
        return None
    e = d.get((nom_app or "").strip().lower()) if isinstance(d, dict) else None
    if not _valide(e):
        return None
    return {"bases": list(e.get("bases", [])), "volumes": list(e.get("volumes", []))}
```

`client_executeur.py` :
```python
"""Client HTTP de l'exécuteur de restauration (VM 100). Messages d'erreur honnêtes, jamais la clé
ni le corps brut de la réponse."""
from typing import Optional

import httpx


class ExecuteurErreur(Exception):
    def __init__(self, message: str, statut: Optional[int] = None):
        super().__init__(message)
        self.message = message
        self.statut = statut


class Executeur:
    def __init__(self, base_url: str, cle: str,
                 transport: Optional[httpx.AsyncBaseTransport] = None, delai: float = 280.0):
        self._base, self._cle, self._transport, self._delai = base_url.rstrip("/"), cle, transport, delai

    async def verifier(self, service: str, utilisateur: str, base: str, objet: str) -> dict:
        try:
            async with httpx.AsyncClient(base_url=self._base, transport=self._transport,
                                         timeout=self._delai) as c:
                r = await c.post("/verifier", headers={"X-API-Key": self._cle},
                                 json={"service": service, "utilisateur": utilisateur,
                                       "base": base, "objet": objet})
        except (httpx.ConnectError, httpx.ConnectTimeout):
            raise ExecuteurErreur("Exécuteur de restauration injoignable.") from None
        except httpx.HTTPError:
            raise ExecuteurErreur("Échec de la communication avec l'exécuteur "
                                  "(délai dépassé ?).") from None
        if r.status_code == 401:
            raise ExecuteurErreur("Clé de l'exécuteur refusée.", 401)
        if r.status_code == 409:
            raise ExecuteurErreur("Une vérification est déjà en cours sur l'exécuteur.", 409)
        if r.status_code != 200:
            raise ExecuteurErreur(f"L'exécuteur a répondu {r.status_code}.", r.status_code)
        try:
            d = r.json()
        except ValueError:
            raise ExecuteurErreur("Réponse illisible de l'exécuteur.") from None
        if not isinstance(d, dict):
            raise ExecuteurErreur("Réponse inattendue de l'exécuteur.")
        return d
```

`dokploy.py` — ajouter à la fin de la classe `Dokploy` :
```python
    async def sauvegarder_base(self, backup_id: str) -> dict:
        await self._requete("POST", "/api/backup.manualBackupPostgres",
                            json={"backupId": backup_id})
        return {"ok": True, "backup_id": backup_id}

    async def fichiers_sauvegarde(self, backup_id: str) -> list[dict]:
        r = await self._requete("GET", "/api/backup.listBackupFilesByBackupId",
                                params={"backupId": backup_id})
        if not isinstance(r, list):
            raise DokployErreur("Réponse de Dokploy inattendue (fichiers de sauvegarde).")
        fichiers = [{"nom": f.get("Name"), "taille": f.get("Size"), "date": f.get("ModTime")}
                    for f in r if isinstance(f, dict) and not f.get("IsDir") and f.get("Name")]
        return sorted(fichiers, key=lambda f: f["date"] or "", reverse=True)

    async def sauvegarder_volume(self, volume_backup_id: str) -> dict:
        await self._requete("POST", "/api/volumeBackups.runManually",
                            json={"volumeBackupId": volume_backup_id})
        return {"ok": True, "volume_backup_id": volume_backup_id}
```

`faux_dokploy.py` — ajouter, juste avant `return rep(404, {"message": "NOT_FOUND"})` final du handler :
```python
        if chemin == "/api/backup.manualBackupPostgres":
            fichiers = etat.get("fichiers", {}).get((corps or {}).get("backupId"))
            if fichiers is None:
                return rep(404, {"message": "NOT_FOUND"})
            if etat.get("echec_sauvegarde"):
                return rep(500, {"message": "boom"})
            if not etat.get("sauvegarde_sans_fichier"):
                maintenant = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000000000Z")
                fichiers.append({"Name": f"{maintenant}.sql.gz", "Size": 1113, "Path": "SECRET",
                                 "ModTime": maintenant, "IsDir": False})
            return rep(200, True)
        if chemin == "/api/backup.listBackupFilesByBackupId":
            fichiers = etat.get("fichiers", {}).get(req.url.params.get("backupId"))
            return rep(200, fichiers) if fichiers is not None else rep(404, {"message": "NOT_FOUND"})
        if chemin == "/api/volumeBackups.runManually":
            etat.setdefault("volumes_lances", []).append((corps or {}).get("volumeBackupId"))
            return httpx.Response(200, content=b"")   # réel : corps vide
```
et en tête de fichier : `from datetime import datetime, timezone`.

- [ ] **Step 3 : tests verts** + suite complète de la brique (`rtk proxy python3 -m pytest -q -p no:cacheprovider --junitxml=…/s247-t9.xml`) : aucune régression.
- [ ] **Step 4 : mutation** — dans `Dokploy.fichiers_sauvegarde`, retirer `reverse=True` : `test_fichiers_sauvegarde_liste_blanche…` doit échouer ; dans `inventaire._valide`, retirer le contrôle `".." in …` : le cas `prefixe_s3 "../x"` doit échouer. Restaurer.
- [ ] **Step 5 : commit** — `git add briques/livraison && git commit -m "feat(livraison): inventaire des sauvegardes, client de l'exécuteur, méthodes Dokploy de sauvegarde"`.

---

### Task 10 : Sauvegarder et vérifier (logique, routes, manifeste, Cœur)

**Files:**
- Create: `briques/livraison/sauvegarde.py`
- Modify: `briques/livraison/main.py` (fabrique `executeur()` + 2 routes), `briques/livraison/manifest.json` (2 capacités), `briques/livraison/.env.example`, `briques/livraison/docker-compose.yml` (commentaire des variables)
- Modify: `core/outils_communs.py` (table des routes lentes)
- Test: `briques/livraison/test_sauvegarde.py`, `core/test_outils_dynamiques_lentes.py` (nouveau)

**Interfaces:**
- Consumes : `Dokploy.sauvegarder_base|fichiers_sauvegarde|sauvegarder_volume`, `client_executeur.Executeur.verifier`, `inventaire.lire`, `preuve.noter`, `main._resoudre`, `main.fournisseur`, `main.cle_api_fermee`.
- Produces : `sauvegarde.sauvegarder(d, entree) -> {"bases": list[str], "volumes": int}` ; `sauvegarde.verifier(d, ex, entree, app_id, horloge=time.time) -> {"ok": True, "verdict": "valide"|"invalide", "preuve_id": str, "raisons": list[str], "comptages": {base: {table: n}}, "expire_a": float, "volumes_non_verifies": int}` ; routes `POST /apps/{app}/sauvegarder` → `{"ok": True, "app", "bases", "volumes"}` et `POST /apps/{app}/sauvegardes/verifier` → le dict de `verifier` + `"app"` et `"app_id"` (les 3 clés que le Cœur enregistre, partie 1) ; 404 si l'app n'a pas d'inventaire ; capacités de manifeste `livraison_sauvegarder` (`sensibilite: reversible`) et `livraison_verifier_sauvegarde` (`action: false`, `fournit_preuve: "preuve_sauvegarde"`).

- [ ] **Step 1 : tests qui échouent** (`briques/livraison/test_sauvegarde.py`)

```python
import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

import inventaire
import main
import preuve
import sauvegarde
from client_executeur import Executeur
from dokploy import Dokploy
from faux_dokploy import fabrique_transport
from test_api import _etat

c = TestClient(main.app)
CLE = "cle-test"
H = {"X-API-Key": CLE}
BASE = {"base": "temoin", "service": "postgres-abc-def", "utilisateur": "temoin",
        "sauvegarde_id": "B1", "prefixe_s3": "postgres-abc-def/s247-pg"}
ANCIEN = {"Name": "vieux.sql.gz", "Size": 10, "ModTime": "2020-01-01T00:00:00.000000000Z",
          "IsDir": False}


def _executeur(reponse, appels):
    def h(req):
        appels.append(json.loads(req.content))
        return httpx.Response(200, json=reponse)
    return Executeur("http://exec.test", "k", transport=httpx.MockTransport(h))


@pytest.fixture
def e(monkeypatch, tmp_path):
    etat = _etat()
    etat["fichiers"] = {"B1": [dict(ANCIEN)]}
    monkeypatch.setattr(main, "fournisseur",
                        lambda: Dokploy("http://d.test", "k", transport=fabrique_transport(etat)))
    inv = tmp_path / "inv.json"
    inv.write_text(json.dumps({"calendrier": {"bases": [BASE], "volumes": [
        {"volume_backup_id": "V1"}]}}))
    monkeypatch.setenv("LIVRAISON_INVENTAIRE", str(inv))
    monkeypatch.setenv("LIVRAISON_API_KEYS", CLE)   # les actions sont fermées sans clé (403)
    return etat


def _entree():
    return inventaire.lire("calendrier")


def _dok(etat):
    return Dokploy("http://d.test", "k", transport=fabrique_transport(etat))


def run(co):
    return asyncio.run(co)


OK = {"ok": True, "verdict": "valide", "raison": None,
      "comptages_origine": {"evenements": 42}, "comptages_restaures": {"evenements": 42}}


def test_sauvegarder_lance_base_et_volumes(e):
    r = run(sauvegarde.sauvegarder(_dok(e), _entree()))
    assert r == {"bases": ["temoin"], "volumes": 1} and e["volumes_lances"] == ["V1"]
    assert len(e["fichiers"]["B1"]) == 2


def test_verifier_valide_ecrit_la_preuve_et_envoie_l_objet_le_plus_recent(e):
    appels = []
    r = run(sauvegarde.verifier(_dok(e), _executeur(OK, appels), _entree(), "A1"))
    assert r["verdict"] == "valide" and r["raisons"] == [] and r["ok"] is True
    assert r["comptages"] == {"temoin": {"evenements": 42}} and r["volumes_non_verifies"] == 1
    assert appels[0]["objet"].startswith("postgres-abc-def/s247-pg/20") \
        and appels[0]["objet"].endswith(".sql.gz") and "vieux" not in appels[0]["objet"]
    assert preuve.valide("A1")["preuve_id"] == r["preuve_id"]


def test_verifier_comptages_differents_invalide_et_annule_la_preuve_precedente(e):
    preuve.noter("A1", "ANCIENNE", "valide", {})
    bad = {**OK, "verdict": "invalide", "raison": "comptages différents"}
    r = run(sauvegarde.verifier(_dok(e), _executeur(bad, []), _entree(), "A1"))
    assert r["verdict"] == "invalide" and "comptages différents" in r["raisons"][0]
    assert preuve.valide("A1") is None


def test_verifier_sauvegarde_non_recente_invalide_sans_appeler_l_executeur(e):
    e["sauvegarde_sans_fichier"] = True
    appels = []
    r = run(sauvegarde.verifier(_dok(e), _executeur(OK, appels), _entree(), "A1"))
    assert r["verdict"] == "invalide" and "récente" in r["raisons"][0] and appels == []


def test_verifier_echec_de_la_sauvegarde_dokploy_invalide(e):
    e["echec_sauvegarde"] = True
    r = run(sauvegarde.verifier(_dok(e), _executeur(OK, []), _entree(), "A1"))
    assert r["verdict"] == "invalide" and r["raisons"]


def test_verifier_sans_base_invalide(e):
    r = run(sauvegarde.verifier(_dok(e), _executeur(OK, []), {"bases": [], "volumes": [
        {"volume_backup_id": "V1"}]}, "A1"))
    assert r["verdict"] == "invalide" and "aucune base" in r["raisons"][0]


def test_route_verifier_renvoie_les_cles_que_le_coeur_enregistre(e, monkeypatch):
    monkeypatch.setattr(main, "executeur", lambda: _executeur(OK, []))
    r = c.post("/apps/Calendrier/sauvegardes/verifier", headers=H)
    assert r.status_code == 200
    d = r.json()
    assert d["verdict"] == "valide" and d["app"] == "calendrier" and d["app_id"] == "A1"
    assert d["preuve_id"] and isinstance(d["expire_a"], float)


def test_route_executeur_injoignable_donne_verdict_invalide_pas_une_erreur(e, monkeypatch):
    def boom(req):
        raise httpx.ConnectError("x")
    monkeypatch.setattr(main, "executeur", lambda: Executeur(
        "http://x.test", "k", transport=httpx.MockTransport(boom)))
    d = c.post("/apps/calendrier/sauvegardes/verifier", headers=H).json()
    assert d["ok"] is True and d["verdict"] == "invalide" and "injoignable" in d["raisons"][0]


def test_route_sans_inventaire_404(e, monkeypatch, tmp_path):
    monkeypatch.setenv("LIVRAISON_INVENTAIRE", str(tmp_path / "absent.json"))
    assert c.post("/apps/calendrier/sauvegarder", headers=H).status_code == 404
    assert c.post("/apps/calendrier/sauvegardes/verifier", headers=H).status_code == 404


def test_route_sauvegarder(e):
    r = c.post("/apps/calendrier/sauvegarder", headers=H)
    assert r.status_code == 200 and r.json() == {"ok": True, "app": "calendrier",
                                                 "bases": ["temoin"], "volumes": 1}


@pytest.mark.parametrize("chemin", ["/apps/calendrier/sauvegarder",
                                    "/apps/calendrier/sauvegardes/verifier"])
@pytest.mark.parametrize("valeur", ["", None])
def test_actions_sans_cle_configuree_403_sans_appel_dokploy(e, monkeypatch, chemin, valeur):
    if valeur is None:
        monkeypatch.delenv("LIVRAISON_API_KEYS", raising=False)
    else:
        monkeypatch.setenv("LIVRAISON_API_KEYS", valeur)
    assert c.post(chemin).status_code == 403
    assert e["appels"] == []


def test_actions_mauvaise_cle_401(e):
    assert c.post("/apps/calendrier/sauvegarder", headers={"X-API-Key": "mauvaise"}).status_code == 401
```
Core, `core/test_outils_dynamiques_lentes.py` :
```python
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault("GATEWAY_KEY", "sk-test-local")

import outils_communs  # noqa: E402


def _cap(chemin):
    return {"nom": "x", "chemin": chemin, "methode": "POST"}


def test_routes_de_sauvegarde_ont_un_timeout_long():
    assert outils_communs._timeout_dynamique(_cap("/apps/{app}/sauvegarder")) \
        >= outils_communs.TIMEOUT_MUTATION_LONGUE
    assert outils_communs._timeout_dynamique(_cap("/apps/{app}/sauvegardes/verifier")) \
        > outils_communs.TIMEOUT_MUTATION_LONGUE


def test_route_quelconque_garde_le_timeout_du_client():
    assert outils_communs._timeout_dynamique(_cap("/apps/{app}/etat")) is None
```

Run : tests brique + core → FAIL.

- [ ] **Step 2 : implémenter**

`sauvegarde.py` :
```python
"""Sauvegarde et vérification par restauration jetable (S247)."""
import secrets
import time
from datetime import datetime, timezone
from typing import Callable, Optional

import preuve
from client_executeur import Executeur, ExecuteurErreur
from dokploy import Dokploy, DokployErreur

# Tolérance d'horloge entre le HP (qui mesure `debut`) et la VM 100 (qui date le fichier).
TOLERANCE_HORLOGE_S = 120


def _epoch(iso: Optional[str]) -> float:
    try:
        return datetime.strptime((iso or "")[:19], "%Y-%m-%dT%H:%M:%S").replace(
            tzinfo=timezone.utc).timestamp()
    except ValueError:
        return 0.0


async def sauvegarder(d: Dokploy, entree: dict) -> dict:
    bases = []
    for b in entree.get("bases", []):
        await d.sauvegarder_base(b["sauvegarde_id"])
        bases.append(b["base"])
    for v in entree.get("volumes", []):
        await d.sauvegarder_volume(v["volume_backup_id"])
    return {"bases": bases, "volumes": len(entree.get("volumes", []))}


async def verifier(d: Dokploy, ex: Executeur, entree: dict, app_id: str,
                   horloge: Callable[[], float] = time.time) -> dict:
    """Sauvegarde FRAÎCHE de chaque base, restauration jetable (exécuteur), comparaison des
    comptages. Toute défaillance (Dokploy, exécuteur, comptages) donne un verdict `invalide` avec
    `ok: True` : le Cœur révoque alors toute preuve antérieure (fail closed)."""
    debut = horloge()
    raisons: list[str] = []
    comptages: dict = {}
    bases = entree.get("bases", [])
    if not bases:
        raisons.append("aucune base déclarée à l'inventaire : rien à vérifier")
    for b in bases:
        nom = b["base"]
        try:
            await d.sauvegarder_base(b["sauvegarde_id"])
            fichiers = await d.fichiers_sauvegarde(b["sauvegarde_id"])
            if not fichiers or _epoch(fichiers[0]["date"]) < debut - TOLERANCE_HORLOGE_S:
                raisons.append(f"{nom} : aucune sauvegarde récente")
                continue
            r = await ex.verifier(b["service"], b["utilisateur"], b["base"],
                                  f"{b['prefixe_s3']}/{fichiers[0]['nom']}")
        except (DokployErreur, ExecuteurErreur) as e:
            raisons.append(f"{nom} : {e.message}")
            continue
        comptages[nom] = r.get("comptages_restaures") or {}
        if r.get("verdict") != "valide":
            raisons.append(f"{nom} : {r.get('raison') or 'restauration non conforme'}")
    verdict = "valide" if not raisons else "invalide"
    preuve_id = secrets.token_hex(8)
    rec = preuve.noter(app_id, preuve_id, verdict, comptages)
    return {"ok": True, "verdict": verdict, "preuve_id": preuve_id, "raisons": raisons,
            "comptages": comptages, "expire_a": rec["expire_a"],
            "volumes_non_verifies": len(entree.get("volumes", []))}
```

`main.py` — importer `import inventaire, sauvegarde` et `from client_executeur import Executeur` à côté des autres imports, puis :
```python
def executeur() -> Executeur:
    url, cle = os.getenv("EXECUTEUR_URL"), os.getenv("EXECUTEUR_KEY")
    if not url or not cle:
        raise HTTPException(503, "Exécuteur de restauration non configuré "
                                 "(EXECUTEUR_URL / EXECUTEUR_KEY).")
    return Executeur(url, cle)


def _entree_inventaire(nom_app: str) -> dict:
    e = inventaire.lire(nom_app)
    if not e:
        raise HTTPException(404, "aucun inventaire de sauvegarde valide pour cette application")
    return e


@app.post("/apps/{app_}/sauvegarder")
async def sauvegarder_app(app_: str, _: str = Depends(cle_api_fermee)):
    d = fournisseur()
    try:
        a = await _resoudre(d, app_)
        r = await sauvegarde.sauvegarder(d, _entree_inventaire(a["nom"]))
    except DokployErreur as e:
        raise _erreur(e)
    return {"ok": True, "app": a["nom"], **r}


@app.post("/apps/{app_}/sauvegardes/verifier")
async def verifier_sauvegarde(app_: str, _: str = Depends(cle_api_fermee)):
    d = fournisseur()
    try:
        a = await _resoudre(d, app_)
    except DokployErreur as e:
        raise _erreur(e)
    r = await sauvegarde.verifier(d, executeur(), _entree_inventaire(a["nom"]), a["id"])
    return {"app": a["nom"], "app_id": a["id"], **r}
```
(`executeur()` est appelée **après** la résolution de l'app et de l'inventaire pour qu'un 404 prime sur un 503 ; dans la route, l'ordre des arguments évalue `_entree_inventaire` avant l'appel : ne pas changer cet ordre.)

`core/outils_communs.py` — compléter la table :
```python
TIMEOUT_VERIFICATION = 300.0
_ROUTES_DYNAMIQUES_LENTES = (("/redemarrer", TIMEOUT_MUTATION_LONGUE),
                             ("/rollback", TIMEOUT_MUTATION_LONGUE),
                             ("/deployer", TIMEOUT_MUTATION_LONGUE),
                             ("/sauvegarder", TIMEOUT_MUTATION_LONGUE),
                             ("/sauvegardes/verifier", TIMEOUT_VERIFICATION))
```
(le délai de l'exécuteur côté brique, 280 s, reste inférieur à 300 s : le Cœur ne coupe jamais avant la brique.)

`manifest.json` — ajouter dans `capacites` :
```json
    {
      "nom": "livraison_sauvegarder",
      "description": "Lance une sauvegarde de l'application (bases et volumes déclarés à l'inventaire) vers le stockage S3. Aucun effet sur la production. À utiliser quand l'utilisateur demande de sauvegarder / mettre de côté les données. Pour PROUVER que la sauvegarde est restaurable, utiliser livraison_verifier_sauvegarde. L'exécution attend l'approbation de l'utilisateur sur Telegram.",
      "methode": "POST",
      "chemin": "/apps/{app}/sauvegarder",
      "params": {"app": {"type": "string", "description": "Nom ou id de l'application (voir livraison_apps). Ex : « calendrier ».", "requis": true}},
      "action": true,
      "sensibilite": "reversible",
      "relayer_erreurs": true
    },
    {
      "nom": "livraison_verifier_sauvegarde",
      "description": "PROUVE que la sauvegarde d'une application est restaurable : fait une sauvegarde fraîche, la restaure dans une base jetable et compare les comptages de chaque table avec l'original. Renvoie un verdict valide/invalide. Une action destructrice sur les données (remise à zéro) ne pourra être approuvée sur Telegram qu'après un verdict VALIDE sur la MÊME application : réutilise exactement le nom d'application donné par livraison_apps. N'affecte pas la production.",
      "methode": "POST",
      "chemin": "/apps/{app}/sauvegardes/verifier",
      "params": {"app": {"type": "string", "description": "Nom de l'application (voir livraison_apps), identique à celui de l'action à approuver.", "requis": true}},
      "action": false,
      "fournit_preuve": "preuve_sauvegarde",
      "relayer_erreurs": true
    }
```
`.env.example` — ajouter :
```
# Exécuteur de restauration (VM 100, S247) : URL et clé. La clé est celle de EXECUTEUR_KEY dans
# /etc/executeur-restauration/env sur la VM 100. Jamais de secret S3 ici (il ne quitte pas la VM 100).
EXECUTEUR_URL=
EXECUTEUR_KEY=
# Inventaire des sauvegardes par application (défaut : $LIVRAISON_DATA/inventaire.json).
LIVRAISON_INVENTAIRE=
```
`docker-compose.yml` — mettre à jour le commentaire `env_file` pour citer `EXECUTEUR_URL, EXECUTEUR_KEY` (les valeurs restent dans le `.env` racine, jamais littérales).

- [ ] **Step 3 : tests verts** — `briques/livraison` complet, puis `core/test_outils_dynamiques_lentes.py core/test_approbations_preuves_garde.py core/test_catalogue*.py` (non-régression) ; junit `s247-t10.xml`.
- [ ] **Step 4 : mutation** — dans `verifier`, remplacer `_epoch(...) < debut - TOLERANCE` par `False` : `test_verifier_sauvegarde_non_recente…` doit échouer ; remplacer `verdict = "valide" if not raisons else "invalide"` par `"valide"` : `test_verifier_comptages_differents…` doit échouer. Restaurer.
- [ ] **Step 5 : commit** — `git add briques/livraison core/outils_communs.py core/test_outils_dynamiques_lentes.py && git commit -m "feat(livraison): sauvegarder et vérifier une sauvegarde par restauration jetable (preuve pour le Cœur)"`.

---

### Task 11 : Preuve LIVE groupée (SLIVE) — VM 100 et HP

**Files:**
- Create: `docs/s247/preuve-sauvegarde-verifiee.md`
- Modify (non committé, sur le HP et la VM 100) : `/etc/executeur-restauration/env` (VM 100), `briques/livraison/.env` (HP, fichier **local à la brique**, 0600, pas le `.env` racine), `inventaire.json` du volume `livraison_data`

Cette tâche **touche la production du HP et la VM 100** : à exécuter **en session avec l'utilisateur**, une étape à la fois, jamais par un sous-agent, avec sauvegarde de ce qui est modifié (`.env.avant-s247`, image `workplace/livraison:avant-s247`, image `core-core:avant-s247`). Ne PAS toucher aux clés d'approbation du HP. Jamais afficher un secret (lire les fichiers de secrets sans `cat`).

- [ ] **Step 0 : vérifications préalables (hors production)** — `ansible-playbook --syntax-check` puis `--check --diff` du playbook `livraison.yml` (installer Ansible dans un venv du Mac si absent). Sur la VM 100 : `curl --version` ≥ 7.75 (nécessaire à `--aws-sigv4`), `python3 --version`.
- [ ] **Step 1 : préparer la VM 100 (accord de l'utilisateur sur chaque secret)** — créer à la main `/etc/executeur-restauration/env` (root, 0600) avec `EXECUTEUR_KEY` (`openssl rand -hex 32`), `EXECUTEUR_S3_ENDPOINT=http://192.168.1.89:9106`, `EXECUTEUR_S3_BUCKET=dokploy-backups`, `EXECUTEUR_S3_KEY`/`EXECUTEUR_S3_SECRET` = identité administrateur d'Oria (lue sur le HP dans `oria-stack/oria/.env`, **jamais affichée**, aucune valeur contenant `"`, `\` ni saut de ligne). Créer le bucket `dokploy-backups` (`curl -X PUT --aws-sigv4 … -K -`). Appliquer le playbook (jamais pendant une vérification : il redémarre l'exécuteur). Vérifier : `GET /sante` depuis le HP = 200 ; depuis le Mac (autre IP) = refus ufw ; sans clé = 401. **Vérifications explicites** : (a) `PUT`, `HEAD` et liste signés (`list-type=2&prefix=forgejo/`) acceptés par le SeaweedFS de production ; (b) l'utilisateur Postgres de Dokploy a `CREATEDB` ; (c) `docker ps -q --filter "name=^<appName>\."` renvoie exactement un identifiant.
- [ ] **Step 2 : base témoin (pièges de nommage)** — dans le projet `temoin`, créer un service Postgres permanent via `postgres.create`. **Ne pas imposer d'`appName` personnalisé** : le nom généré par Dokploy (`postgres-<mots>-<6 lettres>`) passe l'expression `^postgres-[a-z0-9-]{3,60}$` de l'exécuteur ; relire l'`appName` réel avec `postgres.one` et vérifier qu'il la respecte. Nom de base et d'utilisateur : `^[a-z_][a-z0-9_]{0,40}$` (pas de tiret). Y insérer 42 lignes de test. Créer sa destination S3 (`destination.create`, endpoint `http://192.168.1.89:9106`, région `us-east-1`) et son `backup.create` ; ouvrir le pare-feu de la VM 100 vers le port 9106 du HP si nécessaire. Écrire `inventaire.json` (clé `calendrier-familial`, en minuscules) : `service` = `appName`, `utilisateur`, `base`, `sauvegarde_id`, `prefixe_s3` = `<appName>/<prefix>`. Tester que la clé unique de la brique (limitée à `temoin`) accepte `backup.manualBackupPostgres`, `backup.listBackupFilesByBackupId` et `volumeBackups.runManually` (**sinon** : lui accorder ces droits dans l'utilisateur Dokploy `livraison@…`).
- [ ] **Step 3 : déployer sur le HP (SLIVE groupé)** — **reconstruire** le Cœur ET la brique : `docker compose up -d --build` pour les deux (le code du Cœur est dans son image, sans montage de sources : un simple recreate laisserait l'ancien code, donc l'ancien délai de 30 s et pas de prérequis). Taguer d'abord les images d'origine (`avant-s247`). Poser `EXECUTEUR_URL` / `EXECUTEUR_KEY` dans `briques/livraison/.env` (0600) et **non** dans le `.env` racine. Vérifier santé verte, que `livraison_verifier_sauvegarde` apparaît dans le catalogue, et que le Cœur porte bien `TIMEOUT_VERIFICATION = 600` (lire la valeur dans le conteneur).
- [ ] **Step 4 : cas nominal** — demander dans le chat « vérifie la sauvegarde de calendrier-familial » : verdict `valide`, comptages 42 = 42, `nettoyage: ok`, preuve enregistrée (`GET /apps/calendrier-familial/preuve` → `valide: true`). Consigner la durée totale. Puis demander une action `donnees` factice (une capacité de test déclarant `prerequis: ["preuve_sauvegarde"]`, ou la future `livraison_reset_app`) : la demande Telegram doit porter le bouton « Approuver ». Sans preuve : pas de bouton.
- [ ] **Step 5 : sabotages réalisables** (la vérification fait toujours une sauvegarde FRAÎCHE puis restaure la plus récente : corrompre un ancien objet ne prouve rien). Trois cas, chacun doit donner un verdict `invalide`, faire passer `/preuve` à `valide: false` et **révoquer la preuve côté Cœur** (le bouton Telegram disparaît pour une nouvelle demande) : (a) `prefixe_s3` erroné dans l'inventaire (téléchargement impossible) ; (b) `systemctl stop executeur-restauration` sur la VM 100 (« injoignable ») ; (c) mauvaise `EXECUTEUR_KEY` côté brique (401). Remettre l'état nominal après chaque cas. Le cas « comptages différents » reste couvert par les tests unitaires seulement : le dire.
- [ ] **Step 6 : Forgejo** — `systemctl start forgejo-sauvegarde.service` sur la VM 100 ; vérifier `journalctl` (JSON `{"fichier", "taille", "supprimes", "retention"}`, code de sortie 0), l'objet dans `s3://dokploy-backups/forgejo/`, puis restaurer **un** dépôt à partir du zip dans un Forgejo jetable (ou, à défaut, `unzip -t` + lecture du dump SQLite) ; consigner. **Rétention** : le test unitaire ne suffit pas à la prouver en réel ; relancer le service 8 fois de suite (ou abaisser temporairement `garder` à 2 et le restaurer) pour constater qu'au plus `garder` fichiers restent.
- [ ] **Step 7 : documenter et committer** `docs/s247/preuve-sauvegarde-verifiee.md` (tableau action / résultat constaté, écarts, durées, pièges), mettre à jour la fiche S247 et la mémoire de l'utilisateur, puis `git commit -m "docs(s247): preuve LIVE de la sauvegarde vérifiée (exécuteur, Forgejo)"`.

---

## Partie 2b (à écrire après la preuve de 2a)

`livraison_reset_app` (`sensibilite: donnees`, `prerequis: ["preuve_sauvegarde"]`, `exiger_preuve` en tête de route), clone bleu/vert (`project.duplicate` + `domain.update`) **avec restauration des données dans la base du clone** et réécriture de la variable de connexion de l'app (à concevoir après 2a), `livraison_basculer`, `livraison_retour_arriere`, rétention de la bleue (7 jours proposés), nettoyage des images de rollback du registre Forgejo (le spike de l'API `packages` de Forgejo reste à faire), diagnostic préalable (code/config/données), page « maintenance ». Risques notés par la revue finale de 2a (à traiter en 2b) : l'exécuteur restaure avec `pg_restore` en **superutilisateur** dans un conteneur de production — une clé d'exécuteur + l'écriture dans le bucket permettent de faire exécuter du SQL arbitraire (`DROP DATABASE`, `COPY … TO PROGRAM`) : restaurer avec un rôle non super-utilisateur propriétaire de la base jetable, et isoler la restauration jetable du volume de production ; une tentative en échec HTTP (404/503/502/500) ou annulée ne révoque pas la preuve précédente (6 h) — la brique doit révoquer elle-même et `exiger_preuve` rester la barrière ; verrou de l'exécuteur tenu jusqu'à 25 min après un abandon du client (délais internes 600/900 s contre 280 s côté brique). Points hérités à régler : ordre des vérifications dans `consommer_id` (revue finale partie 1), app recréée sous le même nom qui hérite d'une preuve côté Cœur (clé de preuve par nom).

---

## Self-Review

- **Couverture** : décisions 1-5 de l'utilisateur → exécuteur (T6/T8), `/etat` inchangé, clé unique testée (T11 step 2), `forgejo dump`+`curl` (T7/T8), identité admin du S3 (T11 step 1) ; spec S247 « sauvegarde + vérification » → T9/T10 ; « bouton seulement après preuve » → déjà fourni par la partie 1, branché par `fournit_preuve` (T10 manifeste) ; reset/bascule/rétention/nettoyage registre → 2b (annoncé, non codé).
- **Placeholders** : aucun « TBD ». Les routes d'action sont fermées sans `LIVRAISON_API_KEYS` (403, `cle_api_fermee`) : les tests de T10 posent la clé et l'en-tête `X-API-Key`.
- **Cohérence des types** : `Runner.run -> (code, out, err)` utilisé à l'identique en T6/T7 ; `verifier(runner, cfg, corps)` (T6) ↔ `Executeur.verifier(service, utilisateur, base, objet)` (T9) ↔ `sauvegarde.verifier` (T10) : champs `service/utilisateur/base/objet` partout ; entrée d'inventaire `base/service/utilisateur/sauvegarde_id/prefixe_s3` identique en T9, T10 et T11 ; clés du verdict `ok/verdict/preuve_id/app/app_id/expire_a` conformes à `_enregistrer_preuve_eventuelle` (partie 1).
- **Risques connus** : exécuteur = démon root (limité par validation stricte, clé, IP du HP, durcissement systemd) ; comptages de l'original lus en direct (une écriture concurrente entre la sauvegarde et la lecture donne un verdict `invalide` à refaire, documenté) ; la clé unique Dokploy peut manquer de droits sur `backup/volumeBackups` (testé en T11).
