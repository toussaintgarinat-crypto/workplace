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
