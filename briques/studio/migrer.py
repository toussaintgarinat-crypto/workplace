"""S54 — migration des séries de l'atelier Oria vers la brique studio.

Les séries écrites par l'ancien `atelier_router` d'Oria sont des fichiers JSON
(`{id}.json`) rangés dans le volume `uploads_data` d'Oria, sous `/app/uploads/ateliers`.
La brique studio range les siennes dans son propre volume (`STUDIO_DIR`, défaut
`/data/ateliers`) avec un schéma **identique** (même lignée de code, cf. README S51).

Migrer = recopier ces JSON dans `STUDIO_DIR` en les passant par `_normaliser` (qui
crée Cycle 1 / Tome 1 et rattache les chapitres orphelins des vieilles séries). C'est
**idempotent** et **non destructif** : une série déjà présente dans la brique est
ignorée (sauf `--ecraser`), pour ne jamais piétiner par accident le travail déjà fait
dans la brique. Aucune suppression côté source.

Procédure conteneur (le volume Oria monté en lecture seule dans la brique) :

    docker run --rm \
      -v oria_uploads_data:/oria-uploads:ro \
      -v studio_data:/data \
      briques-studio python migrer.py /oria-uploads/ateliers

Usage direct :

    python migrer.py <dossier_source> [--ecraser]
"""
from __future__ import annotations

import json
import os
import sys

import studio as S


def importer_depuis(source_dir: str, dest_dir: str | None = None, ecraser: bool = False) -> dict:
    """Importe toutes les séries `*.json` de `source_dir` vers `dest_dir` (défaut STUDIO_DIR).

    Renvoie un rapport honnête : ce qui a été importé, ignoré (déjà présent) et en erreur.
    """
    dest_dir = dest_dir or S.ATELIERS_DIR
    rapport = {
        "source": source_dir,
        "dest": dest_dir,
        "importees": [],
        "ignorees": [],
        "erreurs": [],
    }

    if not os.path.isdir(source_dir):
        rapport["erreurs"].append({"fichier": source_dir, "raison": "dossier source introuvable"})
        return rapport

    os.makedirs(dest_dir, exist_ok=True)

    for fn in sorted(os.listdir(source_dir)):
        if not fn.endswith(".json"):
            continue
        chemin = os.path.join(source_dir, fn)
        try:
            with open(chemin, encoding="utf-8") as f:
                serie = json.load(f)
        except Exception as e:  # JSON cassé, fichier illisible…
            rapport["erreurs"].append({"fichier": fn, "raison": f"lecture/JSON : {e}"})
            continue

        sid = serie.get("id")
        if not isinstance(sid, str) or not sid.strip():
            rapport["erreurs"].append({"fichier": fn, "raison": "série sans id exploitable"})
            continue

        dest = os.path.join(dest_dir, f"{sid}.json")
        if os.path.exists(dest) and not ecraser:
            rapport["ignorees"].append(sid)
            continue

        S._normaliser(serie)   # rétrocompat : hiérarchie cycles/tomes, canon, etc.
        with open(dest, "w", encoding="utf-8") as f:
            json.dump(serie, f, ensure_ascii=False, indent=2)
        rapport["importees"].append(sid)

    return rapport


def _afficher(r: dict) -> None:
    print(f"Migration {r['source']} → {r['dest']}")
    print(f"  ✅ importées : {len(r['importees'])}  {r['importees']}")
    print(f"  ⏭  ignorées (déjà présentes) : {len(r['ignorees'])}  {r['ignorees']}")
    if r["erreurs"]:
        print(f"  ⚠ erreurs : {len(r['erreurs'])}")
        for e in r["erreurs"]:
            print(f"     - {e['fichier']} : {e['raison']}")


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    ecraser = "--ecraser" in args
    positionnels = [a for a in args if not a.startswith("--")]
    if not positionnels:
        print(__doc__)
        return 2
    rapport = importer_depuis(positionnels[0], ecraser=ecraser)
    _afficher(rapport)
    return 1 if rapport["erreurs"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
