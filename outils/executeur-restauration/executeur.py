"""Exécuteur de restauration jetable (S247) — tourne sur la VM 100, sous systemd.

Dokploy n'expose aucune route de restauration et la brique `livraison` n'a ni SSH ni socket
Docker. Ce service est le seul à toucher Docker : il n'accepte qu'UN ordre, validé strictement :
« restaure cet objet S3 dans une base jetable du conteneur Postgres X et compare les comptages ».
Stdlib seule. Secrets S3 : configuration d'environnement, passés à curl par stdin (jamais argv).
"""
import gzip
import hashlib
import hmac
import json
import os
import re
import secrets
import subprocess
import tempfile
import threading
import time
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

RE_SERVICE = re.compile(r"^postgres-[a-z0-9-]{3,60}$")
RE_NOM = re.compile(r"^[a-z_][a-z0-9_]{0,40}$")
RE_TABLE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
RE_NOUVELLE = re.compile(r"^[a-z_][a-z0-9_]{0,30}_v[0-9a-f]{8}$")
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
        try:
            p = subprocess.run(argv, input=stdin, capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return 124, b"", b"timeout"
        return p.returncode, p.stdout, p.stderr


def charger_config(env=None) -> dict:
    e = os.environ if env is None else env
    cfg = {k: e.get("EXECUTEUR_" + k, "") for k in ("KEY", "S3_ENDPOINT", "S3_BUCKET", "S3_KEY",
                                                    "S3_SECRET")}
    manquants = [k for k, v in cfg.items() if not v]
    if manquants:
        raise ErreurExecuteur(500, "configuration incomplète : "
                              + ", ".join("EXECUTEUR_" + k for k in manquants))
    for k in ("S3_ENDPOINT", "S3_BUCKET", "S3_KEY", "S3_SECRET"):
        if any(c in cfg[k] for c in '"\\\r\n'):
            raise ErreurExecuteur(500, f"EXECUTEUR_{k} contient un caractère interdit")
    cfg["S3_REGION"] = e.get("EXECUTEUR_S3_REGION", "us-east-1")
    return cfg


def _valider_cible(corps) -> tuple[str, str, str]:
    if not isinstance(corps, dict):
        raise ErreurExecuteur(400, "corps JSON objet attendu")
    service, utilisateur, base = (corps.get(k) for k in ("service", "utilisateur", "base"))
    if not (isinstance(service, str) and RE_SERVICE.fullmatch(service)):
        raise ErreurExecuteur(400, "service invalide")
    if not (isinstance(utilisateur, str) and RE_NOM.fullmatch(utilisateur)):
        raise ErreurExecuteur(400, "utilisateur invalide")
    if not (isinstance(base, str) and RE_NOM.fullmatch(base)):
        raise ErreurExecuteur(400, "base invalide")
    return service, utilisateur, base


def valider(corps) -> tuple[str, str, str, str]:
    service, utilisateur, base = _valider_cible(corps)
    objet = corps.get("objet")
    if not (isinstance(objet, str) and RE_OBJET.fullmatch(objet)) or ".." in objet \
            or objet.startswith("/"):
        raise ErreurExecuteur(400, "objet invalide")
    return service, utilisateur, base, objet


def _valider_nouvelle(corps) -> str:
    nv = corps.get("nouvelle_base") if isinstance(corps, dict) else None
    if not (isinstance(nv, str) and RE_NOUVELLE.fullmatch(nv)):
        raise ErreurExecuteur(400, "nouvelle_base invalide")
    return nv


def conteneur(runner, service: str) -> str:
    code, out, _ = runner.run(["docker", "ps", "-q", "--filter", f"name=^{service}\\."])
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
        if not RE_TABLE.fullmatch(t):
            raise ErreurExecuteur(502, "nom de table inattendu")
        res[t] = int(_psql(runner, cid, utilisateur, base, f'select count(*) from "{t}"').strip())
    return res


def telecharger(runner, cfg: dict, objet: str, dest: Path) -> None:
    url = f"{cfg['S3_ENDPOINT'].rstrip('/')}/{cfg['S3_BUCKET']}/{objet}"
    identifiants = f'user = "{cfg["S3_KEY"]}:{cfg["S3_SECRET"]}"\n'.encode()
    code, _, _ = runner.run(["curl", "-sS", "-f", "--aws-sigv4", f"aws:amz:{cfg['S3_REGION']}:s3",
                             "--max-filesize", "536870912", "-K", "-", "-o", str(dest), url], stdin=identifiants, timeout=600)
    if code != 0:
        raise ErreurExecuteur(502, "téléchargement de la sauvegarde impossible")


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


def _resultat(verdict, raison, origine, restaure, debut, nettoyage="ok"):
    return {"ok": True, "verdict": verdict, "raison": raison, "comptages_origine": origine,
            "comptages_restaures": restaure, "duree_s": round(time.time() - debut, 2),
            "nettoyage": nettoyage}


def _lire_dump(runner, cfg: dict, objet: str, debut: float):
    """Télécharge, décompresse et contrôle la magie PGDMP. Retourne les octets, ou un résultat
    `invalide` déjà formé (dict)."""
    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp) / "dump.gz"
        telecharger(runner, cfg, objet, dest)
        try:
            with gzip.open(dest, "rb") as f:
                donnees = f.read(MAX_DUMP + 1)
        except (OSError, EOFError, zlib.error):
            return _resultat("invalide", "archive illisible (gzip)", {}, {}, debut)
    if len(donnees) > MAX_DUMP:
        return _resultat("invalide", "sauvegarde trop volumineuse pour la vérification", {}, {},
                         debut)
    if not donnees.startswith(MAGIE_PGDMP):
        return _resultat("invalide", "format inattendu (ce n'est pas un pg_dump -Fc)", {}, {},
                         debut)
    return donnees


def verifier(runner, cfg: dict, corps) -> dict:
    service, utilisateur, base, objet = valider(corps)
    debut = time.time()
    cid = conteneur(runner, service)
    donnees = _lire_dump(runner, cfg, objet, debut)
    if isinstance(donnees, dict):
        return donnees
    origine = comptages(runner, cid, utilisateur, base)
    if not origine:
        return _resultat("invalide", "aucune table dans la base d'origine : rien à prouver",
                         origine, {}, debut)
    # Le contenu de la sauvegarde n'est pas digne de confiance : il est restauré et relu avec un
    # rôle jetable SANS privilège (ni superutilisateur, ni création de rôle/base), propriétaire
    # de la seule base jetable. Le superutilisateur ne sert qu'à créer/supprimer ces deux objets.
    jetable = "restore_" + secrets.token_hex(4)
    restaure: dict = {}
    nettoyage = "ok"
    verdict, raison = "valide", None
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
                verdict = "invalide"
                raison = "comptages différents entre l'original et la copie restaurée"
    finally:
        for sql in (f"drop database if exists {jetable} with (force)",
                    f"drop role if exists {jetable}"):
            try:
                _psql(runner, cid, utilisateur, "postgres", sql)
            except ErreurExecuteur:
                nettoyage = "echec"
    return _resultat(verdict, raison, origine, restaure, debut, nettoyage)


def cloner(runner, cfg: dict, corps) -> dict:
    nouvelle = _valider_nouvelle(corps)
    service, utilisateur, base, objet = valider(corps)
    if nouvelle == base:
        raise ErreurExecuteur(400, "nouvelle_base invalide")
    debut = time.time()
    cid = conteneur(runner, service)
    donnees = _lire_dump(runner, cfg, objet, debut)
    if isinstance(donnees, dict):
        return {**donnees, "nouvelle_base": None}
    origine = comptages(runner, cid, utilisateur, base)
    if not origine:
        return {**_resultat("invalide", "aucune table dans la base d'origine : rien à cloner",
                            origine, {}, debut), "nouvelle_base": None}
    jetable = "restore_" + secrets.token_hex(4)
    restaure: dict = {}
    nettoyage = "ok"
    verdict, raison = "valide", None
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
                verdict = "invalide"
                raison = "comptages différents entre l'original et la copie restaurée"
        if verdict == "valide":
            # Le rôle jetable possède tout : on réattribue au compte de l'application puis on
            # renomme. REASSIGN OWNED agit dans la base COURANTE : s'y connecter explicitement.
            _psql(runner, cid, utilisateur, jetable, f"reassign owned by {jetable} to {utilisateur}")
            _psql(runner, cid, utilisateur, "postgres",
                  f"alter database {jetable} owner to {utilisateur}")
            _psql(runner, cid, utilisateur, "postgres",
                  f"alter database {jetable} rename to {nouvelle}")
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
    if not final:
        verdict = "invalide"
    r = _resultat(verdict, raison, origine, restaure, debut, nettoyage)
    r["nouvelle_base"] = nouvelle if final else None
    return r


def lire_comptages(runner, cfg: dict, corps) -> dict:
    service, utilisateur, base = _valider_cible(corps)
    cid = conteneur(runner, service)
    return {"ok": True, "comptages": comptages(runner, cid, utilisateur, base)}


def supprimer_base(runner, cfg: dict, corps) -> dict:
    service, utilisateur, base = _valider_cible(corps)
    if not RE_NOUVELLE.fullmatch(base):   # jamais une base d'origine
        raise ErreurExecuteur(400, "base invalide")
    cid = conteneur(runner, service)
    _psql(runner, cid, utilisateur, "postgres", f"drop database if exists {base} with (force)")
    return {"ok": True}


ROUTES = {"/verifier": verifier, "/cloner": cloner, "/comptages": lire_comptages,
          "/supprimer-base": supprimer_base}


def fabrique_handler(runner, cfg: dict):
    class Handler(BaseHTTPRequestHandler):
        timeout = 30

        def log_message(self, *a):   # pas de journal d'accès : jamais d'en-tête ni de corps
            pass

        def _rep(self, code, obj):
            corps = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(corps)))
            self.end_headers()
            self.wfile.write(corps)

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

        def do_GET(self):
            if self.path.startswith(PREFIXE_OBJETS):
                return self._objet("GET")
            if self.path == "/sante":
                return self._rep(200, {"ok": True, "service": "executeur-restauration"})
            self._rep(404, {"erreur": "introuvable"})

        def do_POST(self):
            action = ROUTES.get(self.path)
            if action is None:
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
                return self._rep(409, {"erreur": "une opération est déjà en cours"})
            try:
                self._rep(200, action(runner, cfg, corps))
            except ErreurExecuteur as e:
                self._rep(e.statut, {"erreur": e.message})
            except Exception:   # jamais de détail ni de trace vers le client
                self._rep(500, {"erreur": "erreur interne de l'exécuteur"})
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
