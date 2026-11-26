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
