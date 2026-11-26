"""Rétention des images de retour arrière du registre Forgejo (S247 2c).

Lancé par un timer systemd sur la VM 100, avec le même fichier d'environnement que l'exécuteur.
Garde les N dernières versions de chaque paquet `container` dont le nom commence par un préfixe
autorisé ; ne touche JAMAIS `latest` ni un autre paquet. À blanc par défaut : tant que
EXECUTEUR_RETENTION_APPLIQUER n'est pas « 1 », il liste seulement ce qui serait supprimé.
Bibliothèque standard uniquement."""
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

GARDER_MIN = 3
PAGE = 50
PAGES_MAX = 100


class ErreurRetention(Exception):
    pass


def charger_config(env=None) -> dict:
    import os
    e = os.environ if env is None else env
    jeton = e.get("EXECUTEUR_FORGEJO_REGISTRY_TOKEN", "")
    prefixes = [p.strip() for p in e.get("EXECUTEUR_RETENTION_PREFIXES", "").split(",") if p.strip()]
    if not jeton:
        raise ErreurRetention("configuration incomplète : EXECUTEUR_FORGEJO_REGISTRY_TOKEN")
    if not prefixes:
        raise ErreurRetention("configuration incomplète : EXECUTEUR_RETENTION_PREFIXES")
    try:
        garder = int(e.get("EXECUTEUR_RETENTION_GARDER", "10"))
    except ValueError:
        raise ErreurRetention("EXECUTEUR_RETENTION_GARDER doit être un entier") from None
    return {"URL": e.get("EXECUTEUR_FORGEJO_URL", "http://127.0.0.1:3001").rstrip("/"),
            "TOKEN": jeton, "OWNER": e.get("EXECUTEUR_RETENTION_OWNER", "wp-admin"),
            "PREFIXES": prefixes, "GARDER": garder,
            "APPLIQUER": e.get("EXECUTEUR_RETENTION_APPLIQUER", "0") == "1"}


def requete_http(base: str):
    """Fabrique la fonction (méthode, chemin, jeton) -> (statut, JSON|None)."""
    def appel(methode, chemin, jeton):
        req = urllib.request.Request(base + chemin, method=methode,
                                     headers={"Authorization": "token " + jeton,
                                              "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                corps = r.read()
                return r.status, (json.loads(corps) if corps else None)
        except urllib.error.HTTPError as e:
            return e.code, None
        except (urllib.error.URLError, OSError, ValueError):
            return 0, None
    return appel


def _lister(requete, cfg) -> list[dict]:
    owner = urllib.parse.quote(cfg["OWNER"], safe="")
    tout: list[dict] = []
    for page in range(1, PAGES_MAX + 1):
        statut, corps = requete("GET", f"/api/v1/packages/{owner}?type=container"
                                       f"&limit={PAGE}&page={page}", cfg["TOKEN"])
        if statut != 200 or not isinstance(corps, list):
            raise ErreurRetention("listage des paquets impossible (aucune suppression faite)")
        if not corps:
            return tout
        tout.extend(corps)
    raise ErreurRetention("trop de pages de paquets (aucune suppression faite)")


def _autorise(nom: str, prefixes: list[str]) -> bool:
    return any(nom == p or nom.startswith(p + "-") for p in prefixes)


def appliquer_retention(requete, cfg) -> dict:
    if cfg["GARDER"] < GARDER_MIN:
        raise ErreurRetention(f"GARDER doit être ≥ {GARDER_MIN}")
    if not cfg["PREFIXES"]:
        raise ErreurRetention("aucun préfixe autorisé")
    par_paquet: dict[str, list[dict]] = {}
    for p in _lister(requete, cfg):
        nom, version = p.get("name"), p.get("version")
        if not (isinstance(nom, str) and isinstance(version, str)):
            continue
        if version == "latest" or not _autorise(nom, cfg["PREFIXES"]):
            continue
        par_paquet.setdefault(nom, []).append(p)
    cibles: list[tuple[str, str]] = []
    for nom in sorted(par_paquet):
        versions = sorted(par_paquet[nom], key=lambda p: (p.get("created_at") or "", p["version"]))
        for p in versions[:max(0, len(versions) - cfg["GARDER"])]:
            cibles.append((nom, p["version"]))
    res = {"appliquee": bool(cfg["APPLIQUER"]), "garder": cfg["GARDER"],
           "a_supprimer": [f"{n}:{v}" for n, v in cibles], "supprimees": [], "echecs": []}
    if not cfg["APPLIQUER"]:
        return res
    owner = urllib.parse.quote(cfg["OWNER"], safe="")
    for nom, version in cibles:
        chemin = (f"/api/v1/packages/{owner}/container/"
                  f"{urllib.parse.quote(nom, safe='')}/{urllib.parse.quote(version, safe='')}")
        statut, _ = requete("DELETE", chemin, cfg["TOKEN"])
        (res["supprimees"] if statut in (200, 204) else res["echecs"]).append(f"{nom}:{version}")
    return res


def main() -> int:
    try:
        cfg = charger_config()
        res = appliquer_retention(requete_http(cfg["URL"]), cfg)
        print(json.dumps(res))
        return 2 if res["echecs"] else 0
    except ErreurRetention as e:
        print(json.dumps({"ok": False, "erreur": str(e)}), file=sys.stderr)
        return 1
    except Exception:
        print(json.dumps({"ok": False, "erreur": "erreur interne"}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
